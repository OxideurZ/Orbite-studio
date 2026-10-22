"""Detail retention, silhouette holes, shared preview/export and manual controls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from svgpathtools import svg2paths
from trace_image import trace,trace_settings,DEFAULT_TRACE,detection_preview
from studio_model import StudioState,PreviewBuilder
from render_social import Film,DEFAULT
from themes import ROOT


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.source=self.root/'input.png';self.svg=self.root/'trace.svg'

    def face(self):
        im=Image.new('L',(320,320),255);d=ImageDraw.Draw(im)
        d.ellipse((25,10,295,305),outline=0,width=3)
        d.arc((90,110,125,135),180,360,fill=0,width=2);d.arc((195,110,230,135),180,360,fill=0,width=2)
        d.line((150,135,150,195,170,195),fill=0,width=2);d.arc((100,195,230,260),0,180,fill=0,width=2)
        d.ellipse((106,117,110,121),fill=0);d.ellipse((210,117,214,121),fill=0)
        im.save(self.source);return im

    def test_tiny_pupils_and_short_interior_marks_survive(self):
        self.face();r=trace(self.source,self.svg,mode='auto')
        self.assertEqual(r['mode'],'lineart');self.assertGreaterEqual(r['filled_accents'],2)
        paths=svg2paths(str(self.svg))[0]
        self.assertTrue(any(100<p.start.real<120 and 110<p.start.imag<130 for p in paths))
        im=Image.new('L',(80,80),255);d=ImageDraw.Draw(im);d.line((10,15,70,15),fill=0,width=1);d.line((40,50,44,50),fill=0,width=1);im.save(self.source)
        a=trace(self.source,self.svg,mode='lineart');b=trace(self.source,self.root/'old.svg',mode='lineart',options={'min_component':16,'min_stroke':6})
        self.assertGreater(a['strokes'],b['strokes'])

    def test_checkerboard_filled_logo_uses_outlines_and_retains_hole(self):
        im=Image.new('L',(360,160),255);d=ImageDraw.Draw(im)
        for y in range(0,160,12):
            for x in range(0,360,12):
                if (x//12+y//12)%2:d.rectangle((x,y,x+11,y+11),fill=235)
        d.polygon([(10,140),(70,110),(90,30),(120,25),(135,105),(250,95),(280,10),(310,15),(340,140)],fill=0)
        d.ellipse((160,110,195,135),fill=255);im.save(self.source)
        r=trace(self.source,self.svg,mode='auto');self.assertEqual(r['mode'],'outline')
        paths=svg2paths(str(self.svg))[0];self.assertEqual(len(paths),2)
        self.assertTrue(all(p.isclosed() for p in paths))
        b=paths[0].bbox();self.assertGreater(b[1]-b[0],320);self.assertGreater(len(paths[0]),15)
        self.assertTrue(any(155<p.bbox()[0]<165 for p in paths))

    def test_explicit_threshold_and_local_threshold_restore_pale_ink(self):
        im=Image.new('L',(240,100),250);ImageDraw.Draw(im).line((20,50,220,50),fill=205,width=2);im.save(self.source)
        automatic=trace(self.source,self.svg,mode='auto');self.assertEqual(automatic['mode'],'lineart')
        self.assertGreater(automatic['threshold'],205)
        manual=trace(self.source,self.svg,mode='lineart',options={'threshold_method':'global','threshold':230});self.assertGreater(manual['strokes'],0)
        yy,xx=np.indices((120,240));g=175+70*xx/240;g[58:61,20:220]-=35;Image.fromarray(np.uint8(g)).save(self.source)
        local=trace(self.source,self.svg,mode='lineart',options={'threshold_method':'adaptive','adaptive_offset':8})
        self.assertGreater(local['strokes'],0)

    def test_small_features_are_not_silently_capped_in_photo_mode(self):
        self.face();r=trace(self.source,self.svg,mode='edges',detail='high')
        self.assertEqual(r['strokes'],r['extracted_strokes'])
        limited=trace(self.source,self.root/'limited.svg',mode='edges',detail='high',options={'max_strokes':1})
        self.assertEqual(limited['strokes'],1);self.assertTrue(limited['warnings'])

    def test_ignored_regions_are_applied_in_source_coordinates(self):
        self.face();r=trace(self.source,self.svg,mode='lineart',options={'exclude_regions':[[0,0,1,.5]]})
        self.assertTrue(all(p.bbox()[2]>=159 for p in svg2paths(str(self.svg))[0]))
        sheet=detection_preview(self.source,self.svg,r);self.assertIn('image_box',sheet.info)
        self.assertEqual(sheet.size,(360,640))

    def test_preview_export_share_options_and_raster_never_uses_svg_selector(self):
        self.face();s=StudioState.initial();s.source=str(self.source);s.config.update(path_id='old_svg_id',contours='largest')
        s.config['trace']['threshold_method']='global';s.config['trace']['threshold']=222
        builder=PreviewBuilder();self.addCleanup(builder.close)
        sheet,caption=builder.build(s,'Tracé détecté');self.assertIn('222',caption)
        builder.build(s);self.assertEqual(builder.film.c['contours'],'all');self.assertIsNone(builder.film.c['path_id'])
        self.assertGreater(builder.film.info['selected_components'],3)
        from trace_image import trace as actual
        with patch('trace_image.trace',wraps=actual) as tracer:
            s.config['trace']['threshold']=224;builder.build(s,'Tracé détecté');self.assertEqual(tracer.call_count,1)
            self.assertEqual(tracer.call_args.kwargs['options']['threshold'],224)
        s.output=str(self.root/'exports');command=s.command('stills');c=json.loads(Path(command[command.index('--config')+1]).read_text())
        self.assertEqual(c['trace'],s.config['trace'])
        s.save_project(self.root/'project.json');self.assertEqual(StudioState.load_project(self.root/'project.json').config['trace'],s.config['trace'])

    def test_compound_svg_retains_inner_holes_before_and_after_fourier(self):
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 H300 V180 H0 Z M100 40 V140 H200 V40 Z"/></svg>')
        s=StudioState.initial();s.source=str(self.svg);b=PreviewBuilder();self.addCleanup(b.close)
        im,caption=b.build(s,'Tracé détecté');self.assertIn('2/2',caption)
        self.assertLess(np.asarray(im)[318:323,122:127].min(),220)
        source,_=b.build(s,'Source');self.assertLess(np.asarray(source)[320,68].mean(),50);self.assertGreater(np.asarray(source)[320,180].mean(),250)
        b.build(s);self.assertEqual(b.film.info['selected_components'],2)
        s.config['contours']='largest';_,caption=b.build(s,'Tracé détecté');self.assertIn('1/2',caption);self.assertIn('intérieurs',caption)

    def test_two_sample_pen_run_is_visible_without_inventing_a_connector(self):
        c=deepcopy(DEFAULT);c.update(svg=str(ROOT/'examples/etoile.svg'),path_id=None,background='')
        f=Film(c,108,192)
        # Reproduce a short pen-down segment at a sampling boundary: old mask erosion erased it.
        f.pen=np.zeros(len(f.z),bool);f.pen[20:22]=True
        with patch('render_social.load_contour',return_value=(f.z,f.pen,f.info)):
            repaired=Film(c,108,192)
        self.assertEqual([ids.tolist() for ids in repaired.visible_runs],[[20,21]])

    def test_source_preview_remains_available_when_detection_finds_no_ink(self):
        Image.new('L',(200,100),255).save(self.source)
        state=StudioState.initial();state.source=str(self.source)
        builder=PreviewBuilder();self.addCleanup(builder.close)
        sheet,caption=builder.build(state,'Source');self.assertIn('avant détection',caption);self.assertIn('image_box',sheet.info)
        with self.assertRaisesRegex(ValueError,'Aucun trait'):builder.build(state,'Tracé détecté')

    def test_settings_are_validated_and_defaults_are_independent(self):
        a=trace_settings();a['exclude_regions'].append([0,0,1,1]);self.assertEqual(trace_settings()['exclude_regions'],[])
        for bad in [{'min_component':0},{'smoothing':float('nan')},{'exclude_regions':[[.8,0,.1,1]]},{'unknown':1},{'max_size':True}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):trace_settings(bad)


if __name__=='__main__':unittest.main()

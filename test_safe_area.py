"""Ensure titles, drawings and circles never overwrite reserved platform UI areas."""
from copy import deepcopy
import tempfile
import json
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
from render_social import DEFAULT,Film,Canvas
from studio_model import StudioState
from safe_area import DEFAULT_SAFE_AREA,safe_box,safe_transform,CONTENT_VIEWPORT,validate_safe_area
from themes import ROOT,load_theme,merge_configs


class SafeAreaTests(unittest.TestCase):
    def config(self,layout='classic_large'):
        c=merge_configs(DEFAULT,load_theme('cosmos'))
        c.update(svg=str(ROOT/'examples/gondor.svg'),path_id='white_tree',layout=layout,
                 samples=2048,steps=[1,5,24],durations=[1.,1.,1.])
        c['safe_area']['enabled']=True
        return c

    def assert_reserved_areas_are_background(self,film,t):
        actual=np.asarray(film.frame(float(t)));background=np.asarray(film.bg)
        mask=np.any(actual!=background,axis=2)
        x0,y0,x1,y1=safe_box(film.c['safe_area'],film.w,film.h)
        self.assertTrue(mask[y0:y1,x0:x1].any(),'Le contenu doit toujours être visible.')
        mask[y0:y1,x0:x1]=False
        self.assertFalse(mask.any(),'Les marges doivent contenir uniquement le fond.')

    def test_all_layouts_opening_drawing_and_final_transition(self):
        for layout in ['classic','classic_large','balanced','minimal']:
            film=Film(self.config(layout),270,480)
            for t in [.7,1.4,2.8,film.ends[-1]+.25,film.total-.2]:
                with self.subTest(layout=layout,t=t):self.assert_reserved_areas_are_background(film,t)

    def test_social_master_and_preview_use_proportional_margins(self):
        for w,h in [(360,640),(540,960),(1080,1920),(1440,2560)]:
            film=Film(self.config(),w,h)
            with self.subTest(size=(w,h)):self.assert_reserved_areas_are_background(film,2.6)

    def test_transform_keeps_circles_round_and_fits_content_envelope(self):
        area={**DEFAULT_SAFE_AREA,'enabled':True};scale,offset=safe_transform(area)
        cv=Canvas(Image.new('RGB',(1080,1920)),safe_area=area)
        a=cv.xy((100,100));b=cv.xy((200,100));c=cv.xy((100,200))
        self.assertAlmostEqual(b[0]-a[0],c[1]-a[1])
        x0,y0,x1,y1=CONTENT_VIEWPORT
        corners=cv.xy((x0,y0,x1,y1))
        self.assertGreaterEqual(corners[0],area['left'])
        self.assertGreaterEqual(corners[1],area['top'])
        self.assertLessEqual(corners[2],1080-area['right']+.00001)
        self.assertLessEqual(corners[3],1920-area['bottom']+.00001)
        self.assertGreater(scale,.75)

    def test_disabled_margins_restore_original_frame(self):
        c=self.config();c['safe_area']['enabled']=False
        film=Film(c,270,480)
        self.assertTrue(np.array_equal(np.asarray(film.frame(2.5)),np.asarray(film._frame_content(2.5))))
        self.assertEqual(safe_transform(c['safe_area']),(1.,(0.,0.)))

    def test_new_studio_and_builtin_themes_render_without_social_reservations(self):
        self.assertFalse(StudioState.initial().config['safe_area']['enabled'])
        for theme in ['cosmos','aurore','papier']:
            c=merge_configs(DEFAULT,load_theme(theme))
            self.assertFalse(c['safe_area']['enabled'])
            self.assertEqual(safe_transform(c['safe_area']),(1.,(0.,0.)))
            self.assertEqual(safe_box(c['safe_area'],1080,1920),(0,0,1080,1920))

    def test_partial_theme_and_legacy_project_get_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'theme.json';file.write_text(json.dumps({'safe_area':{'bottom':480}}))
            c=load_theme(file);self.assertEqual(c['safe_area']['bottom'],480)
            self.assertEqual(c['safe_area']['right'],180)
            s=StudioState.initial();file=Path(temp)/'legacy.json';s.save_project(file)
            data=json.loads(file.read_text());data['config'].pop('safe_area');file.write_text(json.dumps(data))
            self.assertEqual(StudioState.load_project(file).config['safe_area'],DEFAULT_SAFE_AREA)

    def test_invalid_margins_fail_validation(self):
        for patch in [{'top':-1},{'right':float('nan')},{'bottom':True},{'enabled':'yes'},
                      {'top':960,'bottom':100},{'left':400,'right':400},{'typo':2}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_safe_area({**DEFAULT_SAFE_AREA,**patch})

if __name__=='__main__':unittest.main()

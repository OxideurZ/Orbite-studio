"""Adaptive framing, immutable math reuse and a real spawn-based folder workflow."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from composition import value_bounds,fit_bounds,chain_bounds
from render_social import DEFAULT,Film
from studio_model import PreviewBuilder,StudioState
from themes import ROOT


class V2Tests(unittest.TestCase):
    def fixture(self,markup):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        svg=Path(temp.name)/'shape.svg';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg">'+markup+'</svg>')
        c=deepcopy(DEFAULT);c.update(svg=str(svg),path_id=None,contours='all',layout='classic_large',background='',
             samples=2048,steps=[1,5,32],durations=[1.,1.,1.],hero_scale=10.)
        return Film(c,180,320)

    def test_asymmetric_wide_tall_and_square_heroes_are_centered_without_cropping(self):
        for w,h in [(1000,10),(10,1000),(200,200)]:
            film=self.fixture(f'<path d="M -300,20 L {w-300},20 L {w-300},{h+20} L -300,{h+20} Z"/>')
            hero=film.hero_transform();b=value_bounds(film.approx[film.last],film.pen)
            b=b*hero['scale']+np.tile(hero['center'],2)
            self.assertGreaterEqual(b[0],121-1e-7);self.assertLessEqual(b[2],959+1e-7)
            self.assertGreaterEqual(b[1],536-1e-7);self.assertLessEqual(b[3],1424+1e-7)
            self.assertAlmostEqual((b[0]+b[2])/2,540);self.assertAlmostEqual((b[1]+b[3])/2,980)
            self.assertGreater(max(b[2]-b[0],b[3]-b[1]),800)

    def test_landscape_gets_full_width_and_portrait_keeps_rings_separate(self):
        for w,h in [(1000,100),(100,1000),(100,100)]:
            film=self.fixture(f'<rect width="{w}" height="{h}"/>');g=film.composition
            self.assertEqual(g['landscape'],w/h>1.35)
            box=g['drawing']['box']
            if w>h:self.assertGreater(box[2]-box[0],900)
            else:self.assertLess(g['y']['box'][2],box[0])
            self.assertLess(g['x']['box'][3],box[1])
            for a in film.approx.values():
                b=value_bounds(a,film.pen)*g['drawing']['scale']+np.tile(g['drawing']['center'],2)
                self.assertGreaterEqual(b[0],box[0]+23.9);self.assertLessEqual(b[2],box[2]-23.9)
                self.assertGreaterEqual(b[1],box[1]+23.9);self.assertLessEqual(b[3],box[3]-23.9)

    def test_prefix_bound_covers_high_frequency_tail_between_sampled_phases(self):
        rng=np.random.default_rng(123);count=180
        coeff=np.r_[.2,rng.normal(size=count)+1j*rng.normal(size=count)]
        coeff[1:]/=np.arange(1,count+1)**1.3
        for rotation in [0,np.pi/2]:
            bounds=chain_bounds(coeff,count,rotation,phases=128,explicit_terms=24)
            t=(np.arange(2048)+.37)/2048;n=np.arange(1,count+1);r=2*abs(coeff[1:])
            v=r[:,None]*np.exp(1j*(2*np.pi*n[:,None]*t+np.angle(coeff[1:,None])+rotation))
            starts=np.vstack([np.zeros((1,len(t)),complex),np.cumsum(v,axis=0)[:-1]])+coeff[0].real*np.exp(1j*rotation)
            self.assertGreaterEqual((starts.real-r[:,None]).min(),bounds[0])
            self.assertLessEqual((starts.real+r[:,None]).max(),bounds[2])
            self.assertGreaterEqual((starts.imag-r[:,None]).min(),bounds[1])
            self.assertLessEqual((starts.imag+r[:,None]).max(),bounds[3])

    def test_static_layer_reused_but_drawing_continues_to_animate(self):
        film=self.fixture('<rect width="100" height="150"/>')
        with patch.object(film,'brand',wraps=film.brand) as brand:
            a=film.frame(film.c['intro']+.25);b=film.frame(film.c['intro']+.7)
            self.assertEqual(brand.call_count,1)
        self.assertFalse(np.array_equal(np.asarray(a),np.asarray(b)))

    def test_preview_text_or_colors_do_not_repeat_svg_and_fft_preparation(self):
        state=StudioState.initial();builder=PreviewBuilder();self.addCleanup(builder.close)
        with patch('studio_model.Film',wraps=Film) as constructor:
            builder.build(state);state.config['title']='Nouveau texte';builder.build(state)
            state.config['colors']['trace']='#ffcc88';builder.build(state)
            self.assertEqual(constructor.call_count,1)

    def test_audio_only_does_not_build_visual_fourier_approximations(self):
        c=deepcopy(DEFAULT);c.update(svg=str(ROOT/'examples/etoile.svg'),path_id=None)
        with patch('render_social.adaptive_composition',side_effect=AssertionError('No visual composition')):
            film=Film(c,90,160,visual=False)
        self.assertEqual(film.approx,{});self.assertIsNone(film.bg)

    def test_parallel_folder_can_resume_skip_unchanged_and_force_regenerate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sources=root/'inputs';sources.mkdir()
            for name,w in [('a',100),('b',300)]:
                (sources/(name+'.svg')).write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><rect width="{w}" height="100"/></svg>')
            config=root/'config.json';config.write_text(json.dumps({'steps':[1,5],'durations':[.5,.5],'intro':.2,'outro':.3,'samples':512,'background':'','audio':False}))
            output=root/'result';command=[sys.executable,str(ROOT/'orbite.py'),str(sources),'--config',str(config),'--stills','--jobs','2','--output',str(output)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Traitement parallèle',result.stdout)
            report=json.loads((output/'batch_report.json').read_text());self.assertTrue(all(r['status']=='ok' for r in report))
            frames=sorted(output.rglob('*_cover.png'));self.assertEqual(len(frames),2);before=[p.stat().st_mtime_ns for p in frames]
            subprocess.run(command,check=True,capture_output=True,text=True,timeout=90)
            report=json.loads((output/'batch_report.json').read_text());self.assertTrue(all(r.get('cached') for r in report))
            self.assertEqual(before,[p.stat().st_mtime_ns for p in frames])
            # Missing products are regenerated, while the other job is still reused.
            frames[0].unlink();subprocess.run(command,check=True,capture_output=True,text=True,timeout=90)
            report=json.loads((output/'batch_report.json').read_text());self.assertEqual(sum(bool(r.get('cached')) for r in report),1)
            subprocess.run(command+['--force'],check=True,capture_output=True,text=True,timeout=90)
            report=json.loads((output/'batch_report.json').read_text());self.assertFalse(any(r.get('cached') for r in report))

if __name__=='__main__':unittest.main()

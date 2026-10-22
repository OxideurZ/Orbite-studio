"""Behavioral checks: Fourier geometry, SVG transforms, pen-up routes, and framing."""
import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from render_social import DEFAULT, Film, load_contour, svg_paths, ROOT


def config(svg, **extra):
    c=copy.deepcopy(DEFAULT)
    c.update(svg=str(svg),path_id=None,background='',**extra)
    return c


class PipelineTests(unittest.TestCase):
    def svg(self,markup):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        p=Path(d.name)/'fixture.svg'
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg">'+markup+'</svg>')
        return p

    def test_svg_group_and_element_transforms_are_applied(self):
        p=self.svg('<g transform="translate(20,30) scale(3,2)">'
                   '<rect id="r" x="0" y="0" width="10" height="10" transform="translate(2,4)"/>'
                   '</g>')
        path=svg_paths(p,'r')[0]
        self.assertTrue(np.allclose(path.bbox(),(26,56,38,58)))

    def test_disconnected_components_keep_the_pen_lifted(self):
        p=self.svg('<circle cx="0" cy="0" r="10"/>'
                   '<circle cx="100" cy="0" r="10"/>')
        z,pen,info=load_contour(config(p,contours='all'))
        self.assertEqual(info['selected_components'],2)
        self.assertTrue(np.any(~pen))
        # No drawn sample should occupy the empty space between the circles.
        middle=abs(z.real)<np.ptp(z.real)*.20
        self.assertTrue(np.any(middle))
        self.assertTrue(np.all(~pen[middle]))

    def test_open_stroke_cannot_be_silently_closed_with_a_drawn_line(self):
        p=self.svg('<polyline points="0,0 20,30 40,0"/>')
        with self.assertRaisesRegex(ValueError,'No closed contour'):
            load_contour(config(p))
        _,pen,_=load_contour(config(p,contours='all'))
        self.assertTrue(np.any(~pen))

    def test_gondor_fourier_chains_match_inverse_fft(self):
        c=config(ROOT/'examples/gondor.svg');c['path_id']='white_tree'
        film=Film(c,270,480)
        rng=np.random.default_rng(7)
        for k in c['steps']:
            ns=np.arange(1,k+1)
            for j in rng.integers(0,len(film.z),12):
                t=j/len(film.z)
                x=film.cx[0].real+np.sum(2*abs(film.cx[1:k+1])*
                    np.cos(2*np.pi*ns*t+np.angle(film.cx[1:k+1])))
                y=film.cy[0].real+np.sum(2*abs(film.cy[1:k+1])*
                    np.sin(2*np.pi*ns*t+np.angle(film.cy[1:k+1])+np.pi/2))
                self.assertLess(abs(x+1j*y-film.approx[k][j]),1e-8)
        errors=list(film.errors.values())
        self.assertTrue(all(a>b for a,b in zip(errors,errors[1:])))
        self.assertLess(errors[-1],.5)
        self.assertEqual(film.total,32)
        self.assertTrue(np.all(film.pen))

    def test_contrasting_svg_aspect_ratios_fit_the_drawing_area(self):
        for w,h in [(1000,1),(1,1000),(100,100)]:
            p=self.svg(f'<rect width="{w}" height="{h}"/>')
            z,_,_=load_contour(config(p))
            self.assertLessEqual(np.ptp(z.real),350)
            self.assertLessEqual(np.ptp(z.imag),520)

    def test_larger_portrait_keeps_circle_chains_outside_the_drawing(self):
        import json
        original=config(ROOT/'examples/portrait.svg',contours='all',samples=32768,
                        steps=[1,2,3,6,12,32,96,256,768])
        before,_,_=load_contour(original)
        c=json.loads((ROOT/'examples/portrait_grand.json').read_text())
        c['svg']=str(ROOT/'examples/portrait.svg')
        after,_,info=load_contour(c)
        self.assertGreater(np.ptp(after.real)/np.ptp(before.real),1.05)
        center=info['geometry']['center']
        top=center[1]+after.imag.min();left=center[0]+after.real.min()
        # Circumferences of every displayed prefix, tested throughout a complete rotation.
        for values,rotation,root in [(after.real,0,complex(center[0],info['geometry']['x_root_y'])),
              (after.imag,np.pi/2,complex(info['geometry']['y_root_x'],center[1]))]:
            coeff=np.fft.rfft(values)/len(values);k=max(c['steps'])
            ns=np.arange(1,k+1);r=2*abs(coeff[1:k+1])
            ts=np.linspace(0,1,1536)
            v=r[:,None]*np.exp(1j*(2*np.pi*ns[:,None]*ts+np.angle(coeff[1:k+1,None])+rotation))
            p=np.vstack([np.zeros((1,len(ts)),complex),np.cumsum(v,axis=0)[:-1]])
            p+=root+coeff[0].real*(1 if rotation==0 else 1j)
            if rotation==0:
                self.assertLess(float((p.imag+r[:,None]).max()),top-20)
            else:
                self.assertLess(float((p.real+r[:,None]).max()),left-20)


if __name__=='__main__':unittest.main()

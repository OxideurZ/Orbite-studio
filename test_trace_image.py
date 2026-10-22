"""Centerline extraction checks for the raster-image workflow."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image,ImageDraw
from svgpathtools import svg2paths
from trace_image import trace


class TraceImageTests(unittest.TestCase):
    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        return root/'input.png',root/'trace.svg'

    def test_thick_line_becomes_one_centerline(self):
        src,dst=self.fixture()
        im=Image.new('L',(220,100),255)
        ImageDraw.Draw(im).line((20,50,200,50),fill=0,width=9)
        im.save(src)
        result=trace(src,dst)
        self.assertEqual(result['strokes'],1)
        p=svg2paths(str(dst))[0][0]
        self.assertLess(abs(p.start.imag-50),1)
        self.assertLess(abs(p.end.imag-50),1)
        self.assertGreater(p.length(),165)

    def test_disconnected_lines_remain_disconnected(self):
        src,dst=self.fixture()
        im=Image.new('L',(220,100),255);d=ImageDraw.Draw(im)
        d.line((20,25,80,25),fill=0,width=5)
        d.line((140,75,200,75),fill=0,width=5)
        im.save(src)
        result=trace(src,dst)
        self.assertEqual(result['strokes'],2)
        for p in svg2paths(str(dst))[0]:
            x0,x1,_,_=p.bbox()
            self.assertTrue(x1<100 or x0>120)

    def test_compact_filled_accents_survive_thinning(self):
        src,dst=self.fixture()
        im=Image.new('L',(160,100),255);d=ImageDraw.Draw(im)
        d.ellipse((25,35,55,65),fill=0)
        d.line((90,50,145,50),fill=0,width=5)
        im.save(src)
        result=trace(src,dst)
        self.assertEqual(result['filled_accents'],1)
        self.assertGreaterEqual(result['strokes'],2)

    def test_transparent_white_logo_keeps_its_centerline(self):
        src,dst=self.fixture()
        im=Image.new('RGBA',(220,100),(0,0,0,0))
        ImageDraw.Draw(im).line((20,50,200,50),fill='white',width=9)
        im.save(src)
        result=trace(src,dst,mode='auto')
        self.assertEqual(result['mode'],'lineart')
        self.assertEqual(result['strokes'],1)

    def test_continuous_tone_image_uses_edges(self):
        src,dst=self.fixture()
        yy,xx=np.indices((180,240))
        gray=60+90*xx/240+40*yy/180
        gray[((xx-120)**2+(yy-90)**2)<40**2]*=.45
        Image.fromarray(np.uint8(gray)).save(src)
        result=trace(src,dst,mode='auto')
        self.assertEqual(result['mode'],'edges')
        self.assertGreater(result['strokes'],0)
        self.assertLessEqual(result['strokes'],180)


if __name__=='__main__':unittest.main()

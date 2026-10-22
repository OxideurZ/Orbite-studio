"""Theme and orchestration checks. Never render a frame or launch FFmpeg."""
from contextlib import redirect_stdout,redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import orbite
import render_social
from themes import (ROOT,DEFAULT_FONTS,VISUAL_DEFAULTS,load_theme,list_themes,
                    export_theme,config_fingerprint)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.tmp=Path(tmp.name)

    def theme(self,data,name='theme.json'):
        file=self.tmp/name;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(data),encoding='utf-8');return file

    def test_builtins_are_complete_and_cosmos_preserves_original_identity(self):
        self.assertEqual({t['id'] for t in list_themes()},{'cosmos','aurore','papier'})
        for name in ['cosmos','aurore','papier']:
            c=load_theme(name)
            self.assertEqual(set(c['colors']),set(VISUAL_DEFAULTS['colors']))
            self.assertEqual(set(c['fonts']),set(DEFAULT_FONTS))
        self.assertEqual(load_theme('cosmos')['colors'],render_social.DEFAULT['colors'])
        self.assertEqual(load_theme('papier')['background'],'')
        self.assertEqual(load_theme('papier')['background_dimming'],{'top':0,'bottom':0})

    def test_partial_palette_keeps_defaults_and_resolves_paths_relative_to_theme(self):
        folder=self.tmp/'identity';folder.mkdir()
        Image.new('RGB',(8,8),'purple').save(folder/'sky.png')
        serif=Path(DEFAULT_FONTS['serif'])
        file=self.theme({'brand':'TEST','colors':{'x':'#123456'},'background':'sky.png',
                         'fonts':{'sans':os.path.relpath(serif,folder)}},'identity/brand.json')
        previous=Path.cwd()
        try:
            os.chdir(self.tmp)
            c=load_theme(file)
        finally:os.chdir(previous)
        self.assertEqual(c['background'],str(folder/'sky.png'))
        self.assertEqual(c['fonts']['sans'],str(serif))
        self.assertEqual(c['colors']['x'],'#123456')
        self.assertEqual(c['colors']['y'],VISUAL_DEFAULTS['colors']['y'])
        self.assertEqual(VISUAL_DEFAULTS['colors']['x'],'#82e4ff')

    def test_invalid_theme_settings_fail_before_rendering(self):
        invalid=[{'colors':{'x':'violet'}},{'colors':{'typo':'#112233'}},
            {'background_opacity':1.2},{'background_opacity':True},
            {'background_dimming':{'top':float('nan')}},{'background':'missing.png'},
            {'fonts':{'sans':'missing.ttf'}},{'fonts':{'sans':False}},
            {'durations':[1,2]},{'brand':''},{'version':2}]
        for data in invalid:
            with self.subTest(data=data),self.assertRaises(ValueError):load_theme(self.theme(data))

    def test_exported_model_reloads_and_does_not_overwrite_user_theme(self):
        file=export_theme(self.tmp/'custom'/'brand.json','aurore')
        c=load_theme(file)
        self.assertEqual(c['colors'],load_theme('aurore')['colors'])
        self.assertEqual(c['fonts'],DEFAULT_FONTS)
        with self.assertRaisesRegex(ValueError,'existe déjà'):export_theme(file)

    def test_explicit_theme_and_cli_overrides_have_predictable_precedence(self):
        file=self.theme({'brand':'CONFIG','colors':{'x':'#123456'},'steps':[1,5],
                         'durations':[1,2],'intro':.5,'outro':1})
        no_theme=orbite.build_style(config=file)
        self.assertEqual(no_theme['brand'],'CONFIG')
        self.assertEqual(no_theme['colors']['x'],'#123456')
        c=orbite.build_style(config=file,theme='aurore',brand='FINAL',background='',opacity=.2)
        self.assertEqual(c['brand'],'FINAL')
        self.assertEqual(c['colors'],load_theme('aurore')['colors'])
        self.assertEqual(c['background'],'')
        self.assertEqual(c['background_opacity'],.2)
        self.assertEqual(c['steps'],[1,5])
        self.assertEqual(c['durations'],[1,2])

    def test_theme_changes_do_not_change_fourier_geometry_or_timing(self):
        a=orbite.build_style(theme='cosmos');b=orbite.build_style(theme='papier')
        for key in ['steps','durations','samples','layout','intro','outro']:
            self.assertEqual(a[key],b[key])
        for c in [a,b]:c.update(svg=str(ROOT/'examples/portrait.svg'),path_id=None,contours='all')
        za,pa,infoa=render_social.load_contour(a)
        zb,pb,infob=render_social.load_contour(b)
        np.testing.assert_array_equal(za,zb);np.testing.assert_array_equal(pa,pb)
        self.assertEqual(infoa,infob)

    def test_font_cache_distinguishes_theme_files_for_same_role_and_size(self):
        original=render_social.font_for(DEFAULT_FONTS,19,'sans')
        swapped={**DEFAULT_FONTS,'sans':DEFAULT_FONTS['serif']}
        other=render_social.font_for(swapped,19,'sans')
        self.assertIsNot(original,other)
        self.assertIs(other,render_social.font_for(swapped,19,'sans'))
        self.assertNotEqual(original.getname(),other.getname())

    def test_same_asset_path_with_new_contents_has_a_new_variant(self):
        bg=self.tmp/'sky.png';Image.new('RGB',(8,8),'blue').save(bg)
        c=load_theme(self.theme({'background':'sky.png'}))
        before=config_fingerprint(c)
        Image.new('RGB',(8,8),'red').save(bg)
        self.assertNotEqual(before,config_fingerprint(c))

    def test_check_validates_directory_without_outputs_or_any_render_subprocess(self):
        sources=self.tmp/'inputs';sources.mkdir()
        (sources/'star.svg').write_bytes((ROOT/'examples/etoile.svg').read_bytes())
        (sources/'portrait.jpg').write_bytes((ROOT/'examples/portrait_source.jpg').read_bytes())
        out=self.tmp/'must_not_exist';stdout=io.StringIO()
        with patch.object(sys,'argv',['orbite.py',str(sources),'--theme','papier','--check','--output',str(out)]),\
             patch('orbite.trace',side_effect=AssertionError('tracing forbidden')),\
             patch('orbite.subprocess.run',side_effect=AssertionError('subprocess forbidden')),\
             patch('render_social.Film.frame',side_effect=AssertionError('frame forbidden')),redirect_stdout(stdout):
            self.assertEqual(orbite.main(),0)
        result=json.loads(stdout.getvalue())
        self.assertTrue(result['no_render']);self.assertEqual(len(result['inputs']),2)
        self.assertEqual(result['theme'],'Papier');self.assertFalse(out.exists())

    def test_core_check_uses_custom_theme_without_frames_or_output_directory(self):
        out=self.tmp/'not_created'/'movie';stdout=io.StringIO()
        with patch.object(sys,'argv',['render_social.py','--svg',str(ROOT/'examples/etoile.svg'),
                 '--theme','aurore','--check','--output',str(out)]),\
             patch('render_social.Film',side_effect=AssertionError('Film forbidden')),\
             patch('render_social.subprocess.Popen',side_effect=AssertionError('encoder forbidden')),redirect_stdout(stdout):
            render_social.main()
        self.assertEqual(json.loads(stdout.getvalue())['theme'],'Aurore')
        self.assertFalse(out.parent.exists())

    def test_variants_share_tracing_and_real_engine_consumes_their_settings_without_rendering(self):
        out=self.tmp/'series';source=ROOT/'examples/portrait_source.jpg'
        consumed=[]
        def fake_trace(input_file,output_file,**kwargs):
            Path(output_file).write_bytes((ROOT/'examples/etoile.svg').read_bytes())
            Path(output_file).with_suffix('.trace.json').write_text(json.dumps({'mode':'lineart'}))
            return {'mode':'lineart','strokes':1}
        def preflight_engine(cmd,check):
            # Consume the actual generated episode JSON through the real engine's --check.
            config=Path(cmd[cmd.index('--config')+1])
            raw=json.loads(config.read_text());consumed.append((config,raw))
            with patch.object(sys,'argv',cmd[1:]+['--check']),redirect_stdout(io.StringIO()):
                render_social.main()
        with patch('orbite.trace',side_effect=fake_trace) as traced,\
             patch('orbite.subprocess.run',side_effect=preflight_engine),\
             patch('render_social.Film',side_effect=AssertionError('Film forbidden')):
            for name in ['cosmos','papier']:
                with patch.object(sys,'argv',['orbite.py',str(source),'--theme',name,'--stills','--output',str(out)]),\
                     redirect_stdout(io.StringIO()):self.assertEqual(orbite.main(),0)
        self.assertEqual(traced.call_count,1)
        self.assertNotEqual(consumed[0][0].parent,consumed[1][0].parent)
        vectors=[(p.parent/c['svg']).resolve() for p,c in consumed]
        self.assertEqual(vectors[0],vectors[1])
        self.assertNotEqual(consumed[0][1]['colors'],consumed[1][1]['colors'])
        self.assertEqual(consumed[1][1]['background'],'')
        self.assertFalse(list(out.rglob('*.mp4')))
        self.assertFalse(list(out.rglob('*.png')))


if __name__=='__main__':unittest.main()

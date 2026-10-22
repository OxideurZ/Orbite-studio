"""Studio persistence, complete settings, palette and cancellable job checks."""
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest

from PIL import Image
from render_social import DEFAULT
from studio_model import StudioState,TaskRunner,palette_from_image,contrast
from themes import ROOT,VISUAL_FIELDS,load_theme


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name).resolve()
        self.state=StudioState.initial();self.state.output=str(self.folder/'output')
    def tearDown(self):self.temp.cleanup()

    def test_complete_engine_and_theme_coverage(self):
        self.assertFalse((set(DEFAULT)-{'svg'})-self.state.config.keys())
        self.assertFalse(set(VISUAL_FIELDS)-self.state.config.keys())
        self.state.validate()

    def test_project_roundtrip_all_fields_and_relative_paths(self):
        s=self.state;s.source=str(ROOT/'examples/portrait.svg');s.fps=25;s.recursive=True
        s.jobs=2;s.force=True
        s.config['title']='Un autre ciel';s.config['extension_future']={'value':42}
        s.config['captions']['late']='Les détails arrivent.'
        file=self.folder/'session.json';s.save_project(file)
        self.assertFalse(Path(json.loads(file.read_text())['source']).is_absolute())
        restored=StudioState.load_project(file)
        self.assertEqual(s,restored)

    def test_switch_style_preserves_animation_and_text(self):
        s=self.state;s.config.update(title='Portrait',brand='NOVA',steps=[1,5,20],durations=[1.,2.,3.])
        s.apply_theme('papier',preserve_text=True)
        self.assertEqual(s.config['brand'],'NOVA');self.assertEqual(s.config['title'],'Portrait')
        self.assertEqual(s.config['steps'],[1,5,20]);self.assertEqual(s.theme_meta['name'],'Papier')
        s.validate()

    def test_exported_theme_is_compatible(self):
        file=self.folder/'style.json';self.state.save_theme(file)
        loaded=load_theme(str(file))
        for k in VISUAL_FIELDS:self.assertEqual(self.state.config[k],loaded[k])

    def test_import_existing_animation(self):
        self.state.import_animation(ROOT/'examples/portrait.json')
        self.state.validate();self.assertTrue(Path(self.state.source).is_file())

    def test_command_snapshot_is_immutable_and_complete(self):
        s=self.state;s.source=str(ROOT/'examples/portrait.svg');s.fps=25;s.recursive=True
        s.config['episode']='042';s.config['path_id']='portrait'
        args=s.command('check');file=Path(args[args.index('--config')+1])
        self.assertIn('--check',args);self.assertIn('--recursive',args)
        self.assertEqual(args[args.index('--fps')+1],'25')
        data=json.loads(file.read_text());self.assertEqual(data['episode'],'042')
        self.assertNotIn('title',data)
        s.config['episode']='999';self.assertEqual(json.loads(file.read_text())['episode'],'042')

    def test_invalid_settings_rejected_before_job(self):
        for key,value in [('durations',[float('inf')]*9),('steps',[True]*9),('hero_scale',float('nan')),('audio','yes')]:
            s=StudioState.initial();s.config[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):s.validate()
        with self.assertRaises(ValueError):self.state.command('check')

    def test_palette_for_dark_light_and_transparent_images(self):
        for color in ['#071f48','#f8e8dc',(150,30,230,0)]:
            file=self.folder/'bg.png';Image.new('RGBA',(64,64),color).save(file)
            colors=palette_from_image(file);self.assertEqual(set(colors),set(self.state.config['colors']))
            for key in ['ink','muted','trace']:self.assertGreaterEqual(contrast(colors[key],colors['background']),4.5)
            for key in ['x','y']:self.assertGreaterEqual(contrast(colors[key],colors['background']),3)

    def test_runner_progress_and_failures(self):
        events=queue.Queue();runner=TaskRunner(events)
        runner.start([sys.executable,'-u','-c',"print('[2/2]');print('5 / 10 s')"])
        runner.thread.join(5);self.assertFalse(runner.running)
        values=list(events.queue);self.assertIn(('done',0),values);self.assertIn(('progress',75.),values)
        runner.start([sys.executable,'-c','raise SystemExit(3)']);runner.thread.join(5)
        self.assertIn(('failed',3),list(events.queue))

    def test_runner_cancellation(self):
        events=queue.Queue();runner=TaskRunner(events)
        runner.start([sys.executable,'-u','-c',"import time;print('ready');time.sleep(30)"])
        deadline=time.monotonic()+5
        while runner.process is None and time.monotonic()<deadline:time.sleep(.01)
        runner.cancel();runner.thread.join(6)
        self.assertFalse(runner.running);self.assertIn('cancelled',[kind for kind,data in list(events.queue)])

if __name__=='__main__':unittest.main()

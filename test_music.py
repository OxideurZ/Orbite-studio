"""Composition behavior, deterministic image mapping, signal quality and real mastering."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from music import DEFAULT_MUSIC,compose,synthesize,master_audio,settings,validate_music,PENTA
from render_social import Film,DEFAULT
from themes import ROOT,merge_configs
from studio_model import StudioState


def fixture(svg='gondor.svg',**override):
    c=merge_configs(DEFAULT,{'svg':str(ROOT/'examples'/svg),'path_id':None,'contours':'all',
         'background':'','samples':2048,'steps':[1,5,32],'durations':[1.,1.5,2.],
         'intro':.5,'outro':3.,**override})
    return Film(c,90,160)


class MusicTests(unittest.TestCase):
    def test_same_geometry_reproduces_score_independently_of_brand_and_layout(self):
        f=fixture();a=compose(f.z,f.pen,f.c,f.total)
        c=deepcopy(f.c);c.update(title='Another name',brand='OTHER',colors={'x':'#ffffff'})
        b=compose(f.z*1.7,f.pen,c,f.total)
        self.assertEqual(a,b)

    def test_other_images_and_variations_change_the_melody(self):
        f=fixture();g=fixture('etoile.svg')
        a=compose(f.z,f.pen,f.c,f.total);b=compose(g.z,g.pen,g.c,g.total)
        self.assertNotEqual(a['features']['fingerprint'],b['features']['fingerprint'])
        self.assertNotEqual(a['notes'],b['notes'])
        f.c['music']['variation']=1;v=compose(f.z,f.pen,f.c,f.total)
        self.assertNotEqual(a['notes'],v['notes'])
        f.c['music']['variation']=0;self.assertEqual(a,compose(f.z,f.pen,f.c,f.total))

    def test_pitch_harmony_register_and_repetition_constraints(self):
        f=fixture(intro=1.,outro=4.,durations=[3.,3.,8.])
        for variation in range(20):
            f.c['music']['variation']=variation
            score=compose(f.z,f.pen,f.c,f.total);allowed={(score['root_midi']+x)%12 for x in PENTA}
            melody=[n for n in score['notes'] if n['kind']=='key']
            for note in score['notes']:
                self.assertIn(note['midi']%12,allowed)
                self.assertLessEqual(note['midi'],84);self.assertGreaterEqual(note['on'],0)
                self.assertLessEqual(note['on']+note['duration'],f.total+1e-6)
            for a,b in zip(melody[:-2],melody[1:-1]):self.assertLessEqual(abs(a['midi']-b['midi']),7)
            for a,b,c in zip(melody[:-3],melody[1:-2],melody[2:-1]):
                self.assertFalse(a['midi']==b['midi']==c['midi'])
            for chord in score['chords']:
                for note in chord['midi']:self.assertIn(note%12,allowed)
            self.assertEqual(melody[-1]['midi'],score['root_midi']+12)

    def test_invalid_settings_are_rejected(self):
        for bad in [{'tempo':20},{'tempo':float('nan')},{'density':2},{'space':-1},
                    {'brightness':True},{'variation':-1},{'variation':1.5},{'style':'unknown'},
                    {'mode':'unknown'},{'target_lufs':0},{'extra':True}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_music(settings(bad))

    def test_density_and_tempo_controls_affect_score(self):
        f=fixture(durations=[4.,4.,10.]);f.c['music'].update(tempo=72,density=0)
        sparse=compose(f.z,f.pen,f.c,f.total)
        f.c['music']['density']=1;dense=compose(f.z,f.pen,f.c,f.total)
        self.assertEqual(dense['bpm'],72)
        self.assertGreater(len(dense['notes']),len(sparse['notes']))

    def test_raw_signals_are_soft_faded_and_band_limited(self):
        f=fixture()
        with tempfile.TemporaryDirectory() as temp:
            for style in ['orbital','ambient','crystalline']:
                f.c['music']['style']=style
                file=Path(temp)/(style+'.wav');report=f.synthesize(file)
                with wave.open(str(file)) as wav:
                    self.assertEqual(wav.getframerate(),48000);self.assertEqual(wav.getnchannels(),2)
                    x=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').reshape(-1,2)/32768
                self.assertEqual(len(x),round(f.total*48000));self.assertGreater(np.sqrt(np.mean(x*x)),.005)
                self.assertLessEqual(np.max(abs(x)),.79)
                self.assertTrue(np.all(x[0]==0));self.assertTrue(np.all(x[-1]==0))
                self.assertLess(np.max(abs(np.diff(x,axis=0))),.08)
                freq=np.fft.rfftfreq(len(x),1/48000);power=abs(np.fft.rfft(x.mean(axis=1)))**2
                self.assertLess(power[freq>5000].sum()/power.sum(),.002)
                self.assertGreater(np.corrcoef(x.T)[0,1],.7)
                self.assertEqual(report['mode'],'generative')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_two_pass_mastering_reaches_target_and_retains_peak_headroom(self):
        f=fixture()
        with tempfile.TemporaryDirectory() as temp:
            raw=Path(temp)/'raw.wav';f.synthesize(raw)
            for level in [-18,-24]:
                m=settings({'target_lufs':level});file=Path(temp)/f'{level}.wav'
                report=master_audio(raw,file,m)
                # Independently remeasure the actual output, not the requested filter target.
                result=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-i',str(file),'-af',
                    'loudnorm=print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
                measured=json.JSONDecoder().raw_decode(result.stderr[result.stderr.rfind('{'):])[0]
                self.assertAlmostEqual(float(measured['input_i']),level,delta=.35)
                self.assertLessEqual(float(measured['input_tp']),-1.9)
                self.assertEqual(report['passes'],2)

    def test_old_projects_get_music_defaults_and_snapshot_captures_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            s=StudioState.initial();file=Path(temp)/'old.json';s.save_project(file)
            data=json.loads(file.read_text());data['config'].pop('music');file.write_text(json.dumps(data))
            restored=StudioState.load_project(file);self.assertEqual(restored.config['music'],DEFAULT_MUSIC)
            restored.source=str(ROOT/'examples/gondor.svg');restored.output=str(Path(temp)/'output')
            restored.config['music']['variation']=21
            command=restored.command('music');self.assertIn('--audio-only',command)
            config=json.loads(Path(command[command.index('--config')+1]).read_text())
            self.assertEqual(config['music']['variation'],21)

    def test_classic_mode_keeps_the_original_synthesizer(self):
        f=fixture();f.c['music']['mode']='classic'
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(f,'_synthesize_classic',wraps=f._synthesize_classic) as old:
                report=f.synthesize(Path(temp)/'classic.wav');old.assert_called_once()
                self.assertEqual(report['mode'],'classic')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_audio_only_cli_never_renders_a_frame_or_video(self):
        import render_social
        f=fixture()
        with tempfile.TemporaryDirectory() as temp:
            prefix=Path(temp)/'listen';file=Path(temp)/'config.json';file.write_text(json.dumps(f.c))
            argv=['render_social.py','--config',str(file),'--audio-only','--output',str(prefix)]
            with patch.object(sys,'argv',argv),patch.object(Film,'frame',side_effect=AssertionError('No visual frames')):
                render_social.main()
            self.assertTrue(Path(str(prefix)+'_soundtrack.mp3').exists())
            self.assertFalse(list(Path(temp).glob('*.png')));self.assertFalse(list(Path(temp).glob('*.mp4')))

if __name__=='__main__':unittest.main()

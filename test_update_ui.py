"""Real Tk tests of nonblocking checks, preferences, and session-preserving restart."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Écran graphique nécessaire')
class UpdateGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from studio import StudioApp
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.environ=patch.dict(os.environ,{'ORBITE_HOME':str(self.home),'ORBITE_DATA_DIR':str(self.home/'data')})
        self.environ.start();self.addCleanup(self.environ.stop)
        self.root=tk.Tk();self.app=StudioApp(self.root,preview_enabled=False,updates_enabled=False)
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(str(args))
        self.root.update();self.updates=self.app.updates

    def tearDown(self):
        if not self.app.closed:self.app.close()
        self.app.preview_builder.close();self.assertFalse(self.errors,self.errors)

    def pump(self,predicate):
        limit=time.monotonic()+5
        while not predicate() and time.monotonic()<limit:self.root.update();time.sleep(.02)
        self.root.update();self.assertTrue(predicate())

    def test_check_is_asynchronous_and_caches_result_and_preferences(self):
        latest={'commit':'a'*40,'version':'0.8.1','repository':'OxideurZ/Orbite-studio','branch':'main','available':True}
        self.updates.open()
        with patch('update_ui.manager.check_update',return_value=latest):
            self.updates.check();self.pump(lambda:not self.updates.pending)
        self.assertIn('disponible',self.updates.button.cget('text'))
        self.assertEqual(str(self.updates.install_button.cget('state')),'normal')
        self.updates.auto.set(False);self.updates.save_preferences()
        prefs=json.loads((self.home/'data/preferences.json').read_text());self.assertFalse(prefs['auto_check_updates'])
        self.assertEqual(prefs['latest_release']['commit'],'a'*40)

    def test_offline_failure_does_not_close_or_block_the_editor(self):
        self.updates.open()
        with patch('update_ui.manager.check_update',side_effect=RuntimeError('hors ligne')):
            self.updates.check();self.pump(lambda:not self.updates.pending)
        self.assertIn('hors ligne',self.updates.status.cget('text'))
        self.app.vars['title'].set('Toujours utilisable');self.assertEqual(self.app.collect().config['title'],'Toujours utilisable')

    def test_update_worker_command_and_failure_keep_session_and_editor(self):
        self.updates.open();self.app.vars['title'].set('Avant mise à jour')
        with patch.object(self.app.runner,'start') as start:self.updates.install()
        self.assertIn('--no-launch',start.call_args.args[0]);self.assertIn('--root',start.call_args.args[0])
        session=self.home/'data/recovery/session-update.json';self.assertTrue(session.exists())
        self.updates.finished('failed',1)
        self.assertFalse(self.app.closed);self.assertEqual(self.app.collect().config['title'],'Avant mise à jour')

    def test_restart_saves_latest_edits_and_passes_session_to_new_version(self):
        self.app.vars['title'].set('Dernière modification')
        with patch('update_ui.manager.launch') as launch:self.updates.restart()
        self.assertTrue(self.app.closed)
        session=launch.call_args.args[1];saved=json.loads(session.read_text())
        self.assertEqual(saved['config']['title'],'Dernière modification')
        self.assertEqual(saved['format'],'orbite-studio')

if __name__=='__main__':unittest.main()

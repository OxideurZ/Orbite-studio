"""Real Tk walkthrough; skipped when no graphical display is available."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Écran graphique nécessaire')
class GuiWalkthrough(unittest.TestCase):
    def test_personalize_save_reopen_and_check(self):
        import tkinter as tk
        from studio import StudioApp
        from themes import ROOT
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'ORBITE_HOME':folder,'ORBITE_DATA_DIR':str(Path(folder)/'data')}):
            root=tk.Tk();app=StudioApp(root,preview_enabled=False,updates_enabled=False);errors=[]
            root.report_callback_exception=lambda *args:errors.append(str(args))
            def pump_until(condition,seconds=10):
                limit=time.monotonic()+seconds
                while not condition() and time.monotonic()<limit:root.update();time.sleep(.02)
                root.update();self.assertTrue(condition())
            try:
                with patch('studio.messagebox.showerror',side_effect=lambda *a,**k:errors.append(str(a))):
                    root.update()
                    for size in ['1060x760','1240x930']:
                        root.geometry(size);root.update()
                        self.assertLess(app.status.winfo_rooty()+app.status.winfo_height(),root.winfo_rooty()+root.winfo_height()+1)
                        self.assertTrue(app.action_buttons['export'].winfo_viewable())
                    with patch('studio.filedialog.askopenfilename',return_value=str(ROOT/'examples/portrait.svg')):app.choose_source()
                    app.vars['title'].set('Mon portrait');app.vars['brand'].set('NOVA')
                    app.vars['base_style'].set('Papier');app.choose_base()
                    self.assertEqual(app.vars['title'].get(),'Mon portrait');self.assertEqual(app.vars['brand'].get(),'NOVA')
                    with patch('studio.filedialog.askopenfilename',return_value=str(ROOT/'assets/montagnes_orbite.png')):app.choose_background()
                    pump_until(lambda:'Palette proposée' in app.status.cget('text'))
                    app.vars['color_trace'].set('#fdc5ff');app.vars['fps'].set('25')
                    app.notebook.select(app.animation_panel);root.update()
                    self.assertFalse(app.vars['safe_enabled'].get())
                    app.vars['safe_top'].set('260');app.vars['safe_right'].set('200')
                    self.assertEqual(app.collect().config['safe_area']['top'],260)
                    app.reset_safe_area();self.assertEqual(app.collect().config['safe_area']['top'],240)
                    app.vars['safe_top'].set('260')
                    app.vars['output'].set(str(Path(folder)/'output'))
                    app.stages.selection_set(app.stages.get_children()[1]);app.select_stage()
                    app.vars['stage_n'].set('5');app.vars['stage_d'].set('1,2');app.apply_stage()
                    # 5 replaces 2 and is sorted after 3; edited row remains selected.
                    self.assertEqual(app.stages.item(app.stages.selection()[0],'values')[0],'5')
                    app.refresh_json();data=json.loads(app.json_text.get('1.0','end-1c'))
                    data['extension_future']={'enabled':True};app._replace(app.json_text,json.dumps(data));app.apply_json()
                    app.notebook.select(app.music_panel);root.update()
                    app.vars['music_style'].set('Brume · nappes aériennes')
                    app.next_music_variation();app.vars['music_tempo'].set('72')
                    self.assertEqual(app.collect().config['music']['variation'],1)
                    self.assertEqual(app.collect().config['music']['style'],'ambient')
                    expected=app.collect();project=str(Path(folder)/'project.json')
                    with patch('studio.filedialog.asksaveasfilename',return_value=project):app.save_project()
                    app.vars['title'].set('Changé')
                    with patch('studio.filedialog.askopenfilename',return_value=project):app.open_project()
                    self.assertEqual(app.collect(),expected)
                    theme=str(Path(folder)/'theme.json')
                    with patch('studio.filedialog.asksaveasfilename',return_value=theme):app.save_theme()
                    app.vars['color_trace'].set('#ffffff')
                    with patch('studio.filedialog.askopenfilename',return_value=theme):app.import_theme()
                    self.assertEqual(app.vars['color_trace'].get(),'#fdc5ff')
                    app.action_buttons['check'].invoke()
                    pump_until(lambda:'Vérification terminée' in app.status.cget('text'),20)
                    app.action_buttons['music'].invoke()
                    pump_until(lambda:'Musique prête' in app.status.cget('text'),30)
                    self.assertTrue(list(Path(folder).rglob('*.mp3')))
                    with patch('studio.subprocess.Popen') as player:
                        app.open_audio();player.assert_called_once()
                        self.assertTrue(player.call_args.args[0][-1].endswith('.mp3'))
                    self.assertFalse(list(Path(folder).rglob('*.mp4')))
                    self.assertFalse(errors,errors)
            finally:
                app.close();app.preview_builder.close()

if __name__=='__main__':unittest.main()

"""Nonblocking update checks and one-click managed installation/restart for Tk."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import install as manager
from themes import ROOT


class UpdateController:
    def __init__(self,app,enabled=True):
        self.app=app;self.enabled=enabled;self.pending=False;self.window=None;self.latest=None
        self.after=None;self.busy=False;self.message='Vérifier les nouveautés sur GitHub.'
        self.meta=manager.manifest(manager.read_json(ROOT/'app_version.json'))
        self.root=manager.install_root();self.preferences=manager.data_root()/'preferences.json'
        try:self.prefs=manager.read_json(self.preferences,{})
        except (ValueError,OSError):self.prefs={}
        if not isinstance(self.prefs,dict):self.prefs={}
        self.auto=tk.BooleanVar(app.root,value=bool(self.prefs.get('auto_check_updates',True)))
        self.button=ttk.Button(app.header,text='Mises à jour · '+self.meta['version'],command=self.open)
        self.button.pack(side='right',padx=(7,0))
        if enabled:self.after=app.root.after(1600,self.automatic_check)

    def automatic_check(self):
        self.after=None
        if not self.auto.get():return
        last=self.prefs.get('last_update_check',0)
        if not isinstance(last,(int,float)):last=0
        if time.time()-last<3600:
            latest=self.prefs.get('latest_release')
            if isinstance(latest,dict):self.receive(latest)
            return
        self.check()

    def save_preferences(self):
        self.prefs['auto_check_updates']=self.auto.get()
        manager.atomic_json(self.preferences,self.prefs)

    def check(self):
        if self.pending:return
        self.pending=True;self.set_message('Vérification sur GitHub…')
        def work():
            try:
                result=manager.check_update(self.root,self.meta['repository'],self.meta.get('branch','main'))
                self.app.events.put(('update_check',result))
            except Exception as exc:self.app.events.put(('update_check_error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def receive(self,result):
        self.latest=deepcopy(result)
        try:current=manager.read_json(self.root/'current.json',{})
        except (ValueError,OSError):current={}
        # A cached check must be compared again after an installation/restart.
        self.latest['available']=result.get('commit')!=current.get('commit')
        available=self.latest['available']
        self.button.configure(text='Mise à jour disponible' if available else 'Mises à jour · '+self.meta['version'])
        self.set_message(('Version '+result['version']+' · '+result['commit'][:8]+' disponible.' if available else 'L’application est à jour.'))
        if self.window and self.window.winfo_exists():self.install_button.configure(state='normal' if available and not self.busy else 'disabled')

    def handle(self,kind,data):
        self.pending=False
        if kind=='update_check':
            self.prefs.update(last_update_check=time.time(),latest_release=data)
            try:self.save_preferences()
            except OSError:pass
            self.receive(data)
        else:self.set_message('Vérification indisponible : '+data+'\nTu peux continuer à utiliser ORBITE.')

    def set_message(self,text):
        self.message=text
        if self.window and self.window.winfo_exists():self.status.configure(text=text)

    def open(self):
        if self.window and self.window.winfo_exists():self.window.lift();return
        w=tk.Toplevel(self.app.root);self.window=w;w.title('ORBITE · Mises à jour');w.geometry('620x420');w.minsize(580,380)
        frame=ttk.Frame(w,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Version actuelle : '+self.meta['version'],style='Section.TLabel').pack(anchor='w',pady=(0,12))
        ttk.Label(frame,text='Dépôt : '+self.meta['repository']).pack(anchor='w')
        ttk.Label(frame,text='Vérification au démarrage, au plus une fois par heure.\nLe téléchargement et l’installation demandent un clic.',style='Muted.TLabel').pack(anchor='w',pady=12)
        ttk.Checkbutton(frame,text='Chercher automatiquement les mises à jour',variable=self.auto,command=self.save_preferences).pack(anchor='w')
        self.status=ttk.Label(frame,text=self.message,wraplength=550);self.status.pack(anchor='w',pady=16)
        controls=ttk.Frame(frame);controls.pack(fill='x')
        ttk.Button(controls,text='Vérifier maintenant',command=self.check).pack(side='left',padx=(0,8))
        self.install_button=ttk.Button(controls,text='Mettre à jour et redémarrer',command=self.install,state='disabled');self.install_button.pack(side='left')
        ttk.Label(frame,text='Les versions sont installées séparément. Les projets, thèmes\npersonnels et exports sont conservés dans le dossier de données.',style='Muted.TLabel').pack(anchor='w',pady=14)
        ttk.Button(frame,text='Revenir à la version précédente',command=self.rollback).pack(anchor='w')
        if self.latest:self.receive(self.latest)
        if self.enabled:self.check()

    def install(self):
        if self.busy or self.app.runner.running:
            self.set_message('Terminer ou annuler le traitement en cours avant la mise à jour.');return
        try:
            # Validate that the current session can be restored before starting.
            self.app.collect().save_project(manager.data_root()/'recovery/session-update.json')
            self.app.current_action='update';self.busy=True
            for button in self.app.action_buttons.values():button.configure(state='disabled')
            self.app.cancel_button.configure(state='normal')
            self.app.progress.configure(mode='indeterminate',value=0);self.app.progress.start(16)
            self.install_button.configure(state='disabled')
            self.app.status.configure(text='Mise à jour en cours. Projets et exports conservés ; journal disponible.')
            self.set_message('Installation en cours. ORBITE redémarrera avec ta session.')
            self.app._append_log('\n—— Mise à jour ORBITE ——')
            argv=[sys.executable,'-u',str(ROOT/'install.py'),'--update','--no-launch','--root',str(self.root),
                  '--repo',self.meta['repository'],'--branch',self.meta.get('branch','main')]
            self.app.runner.start(argv)
        except Exception as exc:
            self.busy=False
            self.app.progress.stop()
            for button in self.app.action_buttons.values():button.configure(state='normal')
            self.app.cancel_button.configure(state='disabled')
            self.set_message(str(exc));self.app._error(exc)

    def finished(self,kind,data):
        self.busy=False
        if kind=='done':
            try:self.restart()
            except Exception as exc:
                self.set_message('Mise à jour installée. Session conservée à l’écran ; redémarrage impossible : '+str(exc))
                self.app.status.configure(text='Mise à jour installée. Corriger les champs si nécessaire, puis relancer ORBITE.')
        else:
            self.set_message('Installation annulée.' if kind=='cancelled' else 'Installation interrompue. La version précédente reste active ; détails dans le journal.')
            self.app.status.configure(text=self.message)
            if not self.app.log.winfo_manager():self.app.log.pack(fill='x',pady=(8,0))
            if self.window and self.window.winfo_exists():self.install_button.configure(state='normal')

    def restart(self):
        session=manager.data_root()/'recovery/session-update.json'
        self.app.collect().save_project(session)
        manager.launch(self.root,session)
        self.app.close()

    def rollback(self):
        if self.busy or self.app.runner.running:self.set_message('Terminer le traitement en cours.');return
        try:
            self.app.collect().save_project(manager.data_root()/'recovery/session-update.json')
            manager.rollback(self.root);self.restart()
        except Exception as exc:self.set_message(str(exc))

    def close(self):
        if self.after:
            try:self.app.root.after_cancel(self.after)
            except tk.TclError:pass

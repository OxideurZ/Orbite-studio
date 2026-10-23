#!/usr/bin/env python3
"""ORBITE Studio — local Tkinter controls for the complete video pipeline.
Run: python studio.py
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import argparse
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

try:
    import tkinter as tk
    from tkinter import ttk,filedialog,colorchooser,messagebox
except ImportError:
    raise SystemExit("Tkinter manque. Sous Linux : installer python3-tk. Sous Windows/macOS : installer Python avec Tcl/Tk.")
from PIL import ImageTk,Image,ImageDraw
from safe_area import DEFAULT_SAFE_AREA,safe_settings,safe_box

from update_ui import UpdateController
from install import data_root
from trace_image import trace_settings,TRACE_PRESETS
from music import settings as music_settings
from studio_model import StudioState,PreviewBuilder,TaskRunner,palette_from_image
from themes import ROOT,load_theme,list_themes,resolve_visual_paths,merge_configs

BG='#101624';PANEL='#172134';INK='#e9edf7';MUTED='#9aaac1';ACCENT='#84dfe6'
LAYOUTS={'Classique · grands cercles':'classic_large','Original':'classic','Épuré':'balanced','Minimal':'minimal'}
MODES={'Automatique':'auto','Dessin au trait':'lineart','Silhouette / contour des aplats':'outline','Contours photo':'edges'}
THRESHOLDS={'Automatique (Otsu)':'auto','Manuel (global)':'global','Local (papier irrégulier)':'adaptive'}
POLARITIES={'Automatique':'auto','Sombre sur fond clair':'dark','Clair sur fond sombre':'light'}
DETAILS={'Peu de détails':'low','Détails moyens':'medium','Détails fins':'high'}
QUALITIES={'Réseaux · 1080 × 1920':'social','Master · 1440 × 2560 + 1080':'master'}
COLOR_LABELS={'background':'Fond','ink':'Titres et points','muted':'Textes secondaires',
              'trace':'Tracé','x':'Axe X / cosinus','y':'Axe Y / sinus'}


class ScrollPanel(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,bg=PANEL,highlightthickness=0)
        bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
        self.body=ttk.Frame(self.canvas,padding=18)
        self.window=self.canvas.create_window(0,0,anchor='nw',window=self.body)
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.body.columnconfigure(1,weight=1)


class StudioApp:
    def __init__(self,root,preview_enabled=True,updates_enabled=True):
        self.root=root;self.state=StudioState.initial();self.preview_enabled=preview_enabled
        self.loading=True;self.closed=False;self.preview_generation=0;self.preview_after=None
        self.preview_future=None;self.events=queue.Queue();self.runner=TaskRunner(self.events)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbite-preview')
        self.preview_builder=PreviewBuilder();self.vars={};self.color_buttons={};self.action_buttons={}
        self.project_file=None;self.last_output=self.state.output
        self.root.title('ORBITE Studio');self.root.geometry('1240x930');self.root.minsize(1060,760)
        self.root.columnconfigure(0,weight=1);self.root.rowconfigure(1,weight=1)
        self.root.configure(bg=BG);self._style();self._build();self.vars['source'].trace_add('write',self.source_changed);self._populate(self.state)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.bind('<Control-o>',lambda e:self.open_project());self.root.bind('<Control-s>',lambda e:self.save_project())
        self.root.bind_all('<MouseWheel>',self._wheel,add='+')
        self.root.bind_all('<Button-4>',self._wheel,add='+');self.root.bind_all('<Button-5>',self._wheel,add='+')
        self.updates=UpdateController(self,enabled=updates_enabled)
        self.poll_after=self.root.after(80,self._poll)

    def _style(self):
        s=ttk.Style(self.root)
        try:s.theme_use('clam')
        except tk.TclError:pass
        self.root.option_add('*Font',('DejaVu Sans',10))
        self.root.option_add('*TCombobox*Listbox.background','#233149')
        self.root.option_add('*TCombobox*Listbox.foreground',INK)
        s.configure('.',background=PANEL,foreground=INK,font=('DejaVu Sans',10))
        s.configure('App.TFrame',background=BG);s.configure('TFrame',background=PANEL)
        s.configure('TLabel',background=PANEL,foreground=INK)
        s.configure('Muted.TLabel',foreground=MUTED)
        s.configure('Title.TLabel',font=('DejaVu Sans',23,'bold'),background=BG)
        s.configure('App.TLabel',background=BG,foreground=MUTED)
        s.configure('Section.TLabel',font=('DejaVu Sans',11,'bold'),foreground=ACCENT)
        s.configure('TEntry',fieldbackground='#0d1523',foreground=INK,insertcolor=INK,padding=6)
        s.configure('TCombobox',fieldbackground='#0d1523',foreground=INK,padding=5)
        s.map('TCombobox',fieldbackground=[('readonly','#0d1523')],foreground=[('readonly',INK)])
        s.configure('TButton',background='#293b54',foreground=INK,padding=(10,7))
        s.map('TButton',background=[('active','#365272')],foreground=[('disabled','#728197')])
        s.configure('Primary.TButton',background=ACCENT,foreground='#0c1c27')
        s.map('Primary.TButton',background=[('active','#a6eced'),('disabled','#38505c')])
        s.configure('TNotebook',background=BG,tabmargins=(0,5,0,0))
        s.configure('TNotebook.Tab',background='#223047',padding=(14,10))
        s.map('TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',ACCENT)])
        s.configure('Treeview',background='#0d1523',fieldbackground='#0d1523',foreground=INK,rowheight=26)
        s.configure('Treeview.Heading',background='#293b54',foreground=INK)
        s.map('Treeview',background=[('selected','#34576c')])
        s.configure('TCheckbutton',background=PANEL,foreground=INK)
        s.configure('TScale',background=PANEL,troughcolor='#293b54')
        s.configure('Horizontal.TProgressbar',background=ACCENT,troughcolor='#293b54')

    def _var(self,key,value='',kind=tk.StringVar,watch=True):
        var=kind(self.root,value=value);self.vars[key]=var
        if watch:var.trace_add('write',self._dirty)
        return var

    def _section(self,parent,title,row):
        ttk.Label(parent,text=title,style='Section.TLabel').grid(row=row,column=0,columnspan=3,sticky='w',pady=(16,9))

    def _entry(self,parent,row,label,key,hint=None,browse=None):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5)
        entry=ttk.Entry(parent,textvariable=self._var(key))
        entry.grid(row=row,column=1,sticky='ew',pady=5)
        if browse:ttk.Button(parent,text='Choisir…',command=browse).grid(row=row,column=2,padx=(7,0),pady=5)
        if hint:ttk.Label(parent,text=hint,style='Muted.TLabel',wraplength=470).grid(row=row+1,column=1,columnspan=2,sticky='w',pady=(0,5))
        return entry

    def _combo(self,parent,row,label,key,values,readonly=True):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5)
        c=ttk.Combobox(parent,textvariable=self._var(key),values=list(values),state='readonly' if readonly else 'normal')
        c.grid(row=row,column=1,columnspan=2,sticky='ew',pady=5);return c

    def _text(self,parent,row,label,key,height=2):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='nw',padx=(0,12),pady=7)
        widget=tk.Text(parent,height=height,wrap='word',bg='#0d1523',fg=INK,insertbackground=INK,
                       relief='flat',padx=8,pady=6,undo=True)
        widget.grid(row=row,column=1,columnspan=2,sticky='ew',pady=5)
        widget.bind('<KeyRelease>',self._dirty);setattr(self,key,widget);return widget

    def _slider(self,parent,row,label,key):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5)
        holder=ttk.Frame(parent);holder.grid(row=row,column=1,columnspan=2,sticky='ew');holder.columnconfigure(0,weight=1)
        var=self._var(key,0,kind=tk.DoubleVar)
        ttk.Scale(holder,from_=0,to=1,variable=var).grid(row=0,column=0,sticky='ew')
        label=ttk.Label(holder,width=5,anchor='e');label.grid(row=0,column=1)
        def update(*args):
            try:label.configure(text=f'{var.get():.0%}')
            except tk.TclError:pass
        var.trace_add('write',update);update()

    def _build(self):
        header=ttk.Frame(self.root,style='App.TFrame',padding=(22,16,22,12));header.grid(row=0,column=0,sticky='ew')
        self.header=header
        ttk.Label(header,text='ORBITE Studio',style='Title.TLabel').pack(side='left')
        for label,fn in [('Enregistrer le projet',self.save_project),('Ouvrir un projet',self.open_project)]:
            ttk.Button(header,text=label,command=fn).pack(side='right',padx=(7,0))
        main=ttk.Frame(self.root,style='App.TFrame',padding=(22,0));main.grid(row=1,column=0,sticky='nsew')
        left=ttk.Frame(main,style='App.TFrame');left.pack(side='left',fill='both',expand=True,padx=(0,18))
        self.notebook=ttk.Notebook(left);self.notebook.pack(fill='both',expand=True)
        for key,name in [('content','Contenu'),('detection','Détection'),('style','Style'),('animation','Animation'),('music','Musique'),('export','Export'),('advanced','JSON')]:
            panel=ScrollPanel(self.notebook);self.notebook.add(panel,text=name);setattr(self,key+'_panel',panel)
        self._content();self._detection();self._appearance();self._animation();self._music();self._export();self._advanced()
        right=ttk.Frame(main,padding=12,width=384);right.pack(side='right',fill='y');right.pack_propagate(False)
        ttk.Label(right,text='Source, détection et animation',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        self.view=ttk.Combobox(right,textvariable=self._var('view','Construction'),state='readonly',
                               values=['Construction','Image finale','Ouverture','Source','Tracé détecté','Comparaison source / traits']);self.view.pack(fill='x',pady=(0,8))
        inspect=ttk.Frame(right);inspect.pack(fill='x',pady=(0,8))
        for label,view in [('Source','Source'),('Traits','Tracé détecté'),('Comparer','Comparaison source / traits')]:
            ttk.Button(inspect,text=label,command=lambda v=view:self.vars['view'].set(v)).pack(side='left',expand=True,fill='x',padx=(0,4))
        ttk.Checkbutton(right,text='Voir les marges · aperçu uniquement',
                        variable=self._var('show_safe_area',True,tk.BooleanVar,False),
                        command=self._fit_preview).pack(anchor='w',pady=(0,8))
        ttk.Button(right,text='Ouvrir les résultats',command=self.open_results).pack(side='bottom',fill='x',pady=(12,0))
        self.preview_caption=ttk.Label(right,text='',style='Muted.TLabel',wraplength=350);self.preview_caption.pack(side='bottom',anchor='w',pady=(8,0))
        self.preview_label=tk.Label(right,bg='#090d20',fg=MUTED,text='Chargement de l’aperçu…',width=1,height=1)
        self.preview_label.pack(fill='both',expand=True)
        self.preview_label.bind('<Configure>',lambda e:self._fit_preview())
        self.preview_label.bind('<ButtonPress-1>',self.exclusion_start)
        self.preview_label.bind('<B1-Motion>',self.exclusion_move)
        self.preview_label.bind('<ButtonRelease-1>',self.exclusion_finish)
        footer=ttk.Frame(self.root,style='App.TFrame',padding=(22,12,22,16));footer.grid(row=2,column=0,sticky='ew')
        actions=ttk.Frame(footer,style='App.TFrame');actions.pack(fill='x')
        for action,label in [('check','Vérifier'),('stills','Images fixes'),('preview','Vidéo test'),('export','Exporter')]:
            button=ttk.Button(actions,text=label,command=lambda a=action:self.start_action(a),
                              style='Primary.TButton' if action=='export' else 'TButton')
            button.pack(side='left',padx=(0,8));self.action_buttons[action]=button
        self.cancel_button=ttk.Button(actions,text='Annuler',command=self.cancel_task,state='disabled');self.cancel_button.pack(side='left')
        ttk.Button(actions,text='Journal',command=self.toggle_log).pack(side='right')
        self.progress=ttk.Progressbar(footer,maximum=100);self.progress.pack(fill='x',pady=(11,6))
        self.status=ttk.Label(footer,text='Choisir une image, puis un style.',style='App.TLabel',wraplength=1100);self.status.pack(anchor='w')
        self.log=tk.Text(footer,height=6,bg='#090f19',fg=MUTED,insertbackground=INK,wrap='word',state='disabled')

    def _content(self):
        p=self.content_panel.body
        self._section(p,'Image ou dossier',0)
        self._entry(p,1,'Source','source',browse=self.choose_source)
        row=ttk.Frame(p);row.grid(row=2,column=1,columnspan=2,sticky='w')
        ttk.Button(row,text='Choisir un dossier…',command=self.choose_folder).pack(side='left')
        ttk.Checkbutton(row,text='Inclure les sous-dossiers',variable=self._var('recursive',False,tk.BooleanVar)).pack(side='left',padx=8)
        self._section(p,'Textes',3)
        self._entry(p,4,'Titre du sujet','title',hint='Vide : utiliser le nom de chaque fichier.')
        self._entry(p,6,'Signature / marque','brand')
        self._entry(p,7,'Sous-titre de série','tagline')
        self._entry(p,8,'Numéro d’épisode','episode',hint='Dans un lot, un numéro comme 003 devient 004, 005…')
        self._text(p,10,'Texte du plan final','final_text',2)
        self._section(p,'Petites descriptions',11)
        for row,key,label in [(12,'early','Silhouette'),(13,'middle','Structure'),(14,'late','Détails')]:self._entry(p,row,label,key)
        self._text(p,15,'Crédit / provenance','credit_text',2)

    def _appearance(self):
        p=self.style_panel.body
        self.builtins={item['name']:item['id'] for item in list_themes()}
        self._section(p,'Style de base',0)
        self.style_combo=self._combo(p,1,'Base','base_style',self.builtins)
        self.style_combo.bind('<<ComboboxSelected>>',self.choose_base)
        buttons=ttk.Frame(p);buttons.grid(row=2,column=1,columnspan=2,sticky='w')
        ttk.Button(buttons,text='Charger un thème…',command=self.import_theme).pack(side='left',padx=(0,6))
        ttk.Button(buttons,text='Enregistrer le thème…',command=self.save_theme).pack(side='left')
        self._entry(p,3,'Nom du style','theme_name')
        self._text(p,4,'Description du style','description_text',2)
        ttk.Label(p,text='Format des thèmes : version 1',style='Muted.TLabel').grid(row=5,column=1,sticky='w')
        self._section(p,'Fond',6)
        self._entry(p,7,'Image de fond','background',browse=self.choose_background)
        controls=ttk.Frame(p);controls.grid(row=8,column=1,columnspan=2,sticky='w')
        ttk.Button(controls,text='Fond uni',command=lambda:self.vars['background'].set('')).pack(side='left',padx=(0,6))
        ttk.Button(controls,text='Proposer une palette',command=self.suggest_palette).pack(side='left')
        ttk.Checkbutton(p,text='Adapter la palette quand je choisis un fond',variable=self._var('auto_palette',True,tk.BooleanVar,False)).grid(row=9,column=1,columnspan=2,sticky='w',pady=5)
        self._slider(p,10,'Opacité de l’image','opacity')
        self._slider(p,11,'Assombrir en haut','dim_top');self._slider(p,12,'Assombrir en bas','dim_bottom')
        self._section(p,'Palette — chaque couleur reste modifiable',13)
        for row,(key,label) in enumerate(COLOR_LABELS.items(),14):
            ttk.Label(p,text=label).grid(row=row,column=0,sticky='w',pady=4)
            holder=ttk.Frame(p);holder.grid(row=row,column=1,columnspan=2,sticky='ew')
            chip=tk.Button(holder,width=4,relief='flat',command=lambda k=key:self.pick_color(k))
            chip.pack(side='left',padx=(0,8));self.color_buttons[key]=chip
            ttk.Entry(holder,textvariable=self._var('color_'+key),width=13).pack(side='left')
        self._section(p,'Polices',20)
        for row,key,label in [(21,'sans','Texte courant'),(22,'bold','Titres forts'),(23,'serif','Titre du sujet')]:
            self._entry(p,row,label,'font_'+key,browse=lambda k=key:self.choose_font(k))

    def _animation(self):
        outer=self.animation_panel.body
        self._section(outer,'Zone protégée · Shorts / Reels / TikTok',0)
        ttk.Checkbutton(outer,text='Éloigner le contenu des boutons des plateformes',
                        variable=self._var('safe_enabled',False,tk.BooleanVar)).grid(row=1,column=0,columnspan=3,sticky='w',pady=5)
        for row,key,label in [(2,'top','Marge en haut'),(3,'bottom','Marge en bas'),(4,'right','Marge à droite'),(5,'left','Marge à gauche')]:
            self._entry(outer,row,label,'safe_'+key)
        ttk.Label(outer,text='Pixels dans un cadre 1080 × 1920 ; adaptation automatique\naux autres résolutions. Le fond reste sur toute la vidéo.',style='Muted.TLabel').grid(row=6,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Button(outer,text='Activer les marges recommandées',command=self.reset_safe_area).grid(row=7,column=0,columnspan=3,sticky='w')
        p=ttk.Frame(outer);p.grid(row=9,column=0,columnspan=3,sticky='ew');p.columnconfigure(1,weight=1)
        self._section(p,'Présentation et tracé',0)
        self._combo(p,1,'Disposition','layout',LAYOUTS)
        self._combo(p,2,'Contours SVG','contours',{'Tous les traits':'all','Contour fermé principal':'largest'})
        self._entry(p,3,'Identifiant SVG','path_id',hint='Facultatif. Laisser vide pour tous les éléments.')
        self._combo(p,5,'Échantillons','samples',['1024','2048','4096','8192','16384','32768','65536','131072'],False)
        self._entry(p,6,'Ouverture (s)','intro');self._entry(p,7,'Plan final (s)','outro')
        self._entry(p,8,'Zoom final maximal','hero_scale',hint='Adapté au cadre : une valeur trop grande ne coupe pas le portrait dans le mode agrandi.')
        self._section(p,'Étapes de Fourier',10)
        self.stages=ttk.Treeview(p,columns=('count','duration'),show='headings',height=7,selectmode='browse')
        self.stages.heading('count',text='Cercles / axe');self.stages.heading('duration',text='Durée (secondes)')
        self.stages.column('count',width=140,anchor='center');self.stages.column('duration',width=140,anchor='center')
        self.stages.grid(row=11,column=0,columnspan=3,sticky='ew')
        self.stages.bind('<<TreeviewSelect>>',self.select_stage)
        edit=ttk.Frame(p);edit.grid(row=12,column=0,columnspan=3,sticky='ew',pady=8)
        ttk.Label(edit,text='Cercles').pack(side='left')
        ttk.Entry(edit,textvariable=self._var('stage_n','1',watch=False),width=8).pack(side='left',padx=(6,12))
        ttk.Label(edit,text='Durée').pack(side='left')
        ttk.Entry(edit,textvariable=self._var('stage_d','1.5',watch=False),width=7).pack(side='left',padx=6)
        ttk.Button(edit,text='Appliquer',command=self.apply_stage).pack(side='left',padx=6)
        controls=ttk.Frame(p);controls.grid(row=13,column=0,columnspan=3,sticky='w')
        ttk.Button(controls,text='Ajouter',command=self.add_stage).pack(side='left',padx=(0,6))
        ttk.Button(controls,text='Supprimer',command=self.remove_stage).pack(side='left',padx=(0,6))
        ttk.Button(controls,text='Rétablir les étapes',command=self.reset_stages).pack(side='left')
        ttk.Label(p,text='Sélectionner une ligne, modifier ses valeurs, puis Appliquer.\nLes fréquences sont rangées par ordre croissant. Décimales : 1.5 ou 1,5.',
                  style='Muted.TLabel').grid(row=14,column=0,columnspan=3,sticky='w',pady=10)

    def _music(self):
        p=self.music_panel.body
        self._section(p,'Une musique propre à chaque image',0)
        ttk.Checkbutton(p,text='Inclure la musique dans les vidéos',variable=self._var('audio',True,tk.BooleanVar)).grid(row=1,column=0,columnspan=3,sticky='w',pady=5)
        self._combo(p,2,'Composition','music_mode',['Générative par image','Classique original'])
        self._combo(p,3,'Ambiance','music_style',['Orbite · arpèges doux','Brume · nappes aériennes','Cristal · notes légères'])
        self._entry(p,4,'Variation','music_variation')
        ttk.Button(p,text='Autre variation',command=self.next_music_variation).grid(row=5,column=1,columnspan=2,sticky='w',pady=5)
        self._entry(p,6,'Tempo (BPM)','music_tempo',hint='0 : tempo automatique selon l’image. Sinon : 48 à 120.')
        self._slider(p,8,'Densité de notes','music_density')
        self._slider(p,9,'Brillance','music_brightness')
        self._slider(p,10,'Espace / écho','music_space')
        self._entry(p,11,'Niveau cible (LUFS)','music_target_lufs',hint='−18 par défaut. De −26 (plus discret) à −14 (plus présent).')
        ttk.Label(p,text='En mode génératif : la forme influence les notes, la tonalité et le rythme.\nMême image + même variation = même composition.\nLe mode Classique conserve la musique d’origine ; seul le niveau s’applique.',style='Muted.TLabel',wraplength=510).grid(row=13,column=0,columnspan=3,sticky='w',pady=14)
        bar=ttk.Frame(p);bar.grid(row=14,column=0,columnspan=3,sticky='w')
        button=ttk.Button(bar,text='Générer l’écoute · audio seul',command=lambda:self.start_action('music'))
        button.pack(side='left',padx=(0,8));self.action_buttons['music']=button
        ttk.Button(bar,text='Écouter le dernier MP3',command=self.open_audio).pack(side='left')
        ttk.Label(p,text='Produit un MP3 et un WAV de la durée du film, sans rendu vidéo.\nLe bouton Écouter ouvre le lecteur audio de l’ordinateur.',style='Muted.TLabel',wraplength=510).grid(row=15,column=0,columnspan=3,sticky='w',pady=10)

    def next_music_variation(self):
        try:self.vars['music_variation'].set((int(self.vars['music_variation'].get())+1)%2147483648)
        except ValueError:self._error('La variation doit être un entier positif ou nul.')

    def _detection(self):
        p=self.detection_panel.body
        self._section(p,'Commencer avec un profil',0)
        self._combo(p,1,'Profil','trace_preset',list(TRACE_PRESETS))
        ttk.Button(p,text='Appliquer le profil',command=self.apply_detection_preset).grid(row=2,column=1,sticky='w',pady=6)
        self._combo(p,3,'Méthode','mode',MODES)
        self._combo(p,4,'Détails photo','detail',DETAILS)
        ttk.Label(p,text='Dessin au trait : suit le centre des lignes. Silhouette : suit les bords et les trous.\nPhoto : suit les variations de contraste. Le SVG conserve ses sous-tracés vectoriels.',style='Muted.TLabel',wraplength=520).grid(row=5,column=0,columnspan=3,sticky='w',pady=8)
        self._section(p,'Seuil et fond · images bitmap',6)
        self._combo(p,7,'Seuil','trace_threshold_method',THRESHOLDS)
        self._entry(p,8,'Seuil manuel · 1 à 254','trace_threshold')
        self._combo(p,9,'Couleur des traits','trace_polarity',POLARITIES)
        self._entry(p,10,'Contraste local · 0 à 40','trace_adaptive_offset')
        self._section(p,'Conserver les petits détails',11)
        for row,label,key in [(12,'Résolution d’analyse · 256 à 4096','max_size'),
                (13,'Surface minimale · pixels','min_component'),(14,'Longueur minimale · pixels','min_stroke'),
                (15,'Lissage · 0 à 3','smoothing'),(16,'Simplification · 0 à 5','simplify'),
                (17,'Refermer les petites coupures · 0 à 3','gap_close'),(18,'Limite des traits · 0 = sans limite','max_strokes')]:
            self._entry(p,row,label,'trace_'+key)
        ttk.Checkbutton(p,text='Préserver les pupilles et les petits points pleins',variable=self._var('trace_preserve_accents',True,tk.BooleanVar)).grid(row=19,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Label(p,text='Pour retrouver les détails : diminuer surface et longueur minimales.\nLe lissage et la simplification élevés peuvent effacer les petits motifs.\nRefermer les coupures peut aussi fusionner deux traits : commencer à 0.',style='Muted.TLabel',wraplength=520).grid(row=20,column=0,columnspan=3,sticky='w',pady=8)
        self._section(p,'Contours photo · réglages fins',21)
        self._entry(p,22,'Flou des contours · 0 = automatique','trace_edge_sigma')
        self._entry(p,23,'Sélectivité · 0 = auto, sinon 0,01 à 0,99','trace_edge_quantile')
        self._section(p,'Contrôler avant de produire la vidéo',24)
        tools=ttk.Frame(p);tools.grid(row=25,column=0,columnspan=3,sticky='ew',pady=6)
        for label,view in [('Voir la source','Source'),('Voir les traits','Tracé détecté'),('Superposer','Comparaison source / traits')]:
            ttk.Button(tools,text=label,command=lambda v=view:self.vars['view'].set(v)).pack(side='left',padx=(0,6))
        ttk.Button(p,text='Plus de détails Fourier',command=self.improve_fourier_details).grid(row=26,column=1,sticky='w',pady=6)
        ttk.Button(p,text='Conserver tous les traits SVG',command=self.keep_all_svg).grid(row=27,column=1,sticky='w',pady=6)
        self._section(p,'Retirer manuellement une zone · bitmap',28)
        ttk.Checkbutton(p,text='Dessiner un rectangle dans l’aperçu des traits',variable=self._var('exclude_tool',False,tk.BooleanVar,False),command=self.enable_exclusion_tool).grid(row=29,column=0,columnspan=3,sticky='w')
        self.exclusion_label=ttk.Label(p,text='Aucune zone ignorée.',style='Muted.TLabel');self.exclusion_label.grid(row=30,column=0,columnspan=3,sticky='w')
        tools=ttk.Frame(p);tools.grid(row=31,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Button(tools,text='Annuler la dernière zone',command=self.undo_exclusion).pack(side='left',padx=(0,8))
        ttk.Button(tools,text='Tout rétablir',command=self.clear_exclusions).pack(side='left')
        ttk.Button(tools,text='Exporter le tracé SVG…',command=self.export_detected_svg).pack(side='left',padx=(8,0))
        ttk.Label(p,text='Les zones sont enregistrées dans le projet. Une nouvelle source les réinitialise.\nL’export utilise exactement les réglages de l’aperçu ; le tracé SVG peut être\nretouché dans Inkscape puis réutilisé sans nouvelle détection.',style='Muted.TLabel',wraplength=520).grid(row=32,column=0,columnspan=3,sticky='w',pady=8)

    def apply_detection_preset(self):
        name=self.vars['trace_preset'].get()
        if name not in TRACE_PRESETS:return
        mode,detail,options=TRACE_PRESETS[name];c=trace_settings(options);self.loading=True
        self.state.config['trace']=c
        for key,value in c.items():
            if key not in {'exclude_regions','threshold_method','polarity'}:self.vars['trace_'+key].set(value)
        self.vars['trace_threshold_method'].set(next(k for k,v in THRESHOLDS.items() if v==c['threshold_method']))
        self.vars['trace_polarity'].set(next(k for k,v in POLARITIES.items() if v==c['polarity']))
        self.vars['mode'].set(next(k for k,v in MODES.items() if v==mode));self.vars['detail'].set(next(k for k,v in DETAILS.items() if v==detail))
        self.loading=False;self._update_exclusion_label();self._dirty()
        self.status.configure(text='Profil appliqué. Vérifier les traits puis la reconstruction Fourier dans l’aperçu.')

    def source_changed(self,*args):
        if self.loading:return
        self.clear_exclusions();self.keep_all_svg()

    def keep_all_svg(self):
        self.vars['contours'].set('Tous les traits');self.vars['path_id'].set('')
        self.status.configure(text='Tous les sous-tracés SVG sont conservés, y compris les détails intérieurs.')

    def improve_fourier_details(self):
        rows=self._get_stages();n=max(1536,rows[-1][0]);samples=max(65536,int(self.vars['samples'].get()),2*n+2)
        if samples%2:samples+=1
        rows[-1]=(n,rows[-1][1]);self.vars['samples'].set(str(samples));self._set_stages(rows);self._dirty()
        self.vars['view'].set('Image finale');self.status.configure(text=f'{n} cercles à la dernière étape · {samples} échantillons. Les durées restent identiques.')

    def enable_exclusion_tool(self):
        if self.vars['exclude_tool'].get():
            if Path(self.vars['source'].get()).suffix.lower()=='.svg':
                self.vars['exclude_tool'].set(False);self.status.configure(text='Les zones à retirer concernent les bitmaps. Retoucher le SVG dans Inkscape, ou choisir Tous les traits.');return
            self.vars['view'].set('Tracé détecté');self.status.configure(text='Dans l’aperçu, tracer un rectangle autour des éléments à retirer. Décocher pour terminer.')

    def _image_position(self,event):
        if not hasattr(self,'preview_placement') or not hasattr(self,'preview_image'):return None
        box=self.preview_image.info.get('image_box')
        if not box:return None
        left,top,width,height=self.preview_placement
        x=(event.x-left)*self.preview_image.width/width;y=(event.y-top)*self.preview_image.height/height
        return (max(0,min(1,(x-box[0])/(box[2]-box[0]))),max(0,min(1,(y-box[1])/(box[3]-box[1]))))

    def exclusion_start(self,event):
        if not self.vars['exclude_tool'].get() or self.vars['view'].get() not in {'Tracé détecté','Comparaison source / traits'}:return
        self.exclusion_anchor=self._image_position(event);self.exclusion_end=self.exclusion_anchor

    def exclusion_move(self,event):
        if getattr(self,'exclusion_anchor',None) is not None:
            self.exclusion_end=self._image_position(event);self._fit_preview()

    def exclusion_finish(self,event):
        start=getattr(self,'exclusion_anchor',None);end=self._image_position(event)
        self.exclusion_anchor=None;self.exclusion_end=None
        if start is None or end is None:return
        box=[min(start[0],end[0]),min(start[1],end[1]),max(start[0],end[0]),max(start[1],end[1])]
        if box[2]-box[0]<.005 or box[3]-box[1]<.005:self._fit_preview();return
        if len(self.state.config['trace']['exclude_regions'])>=100:self._error('Au plus 100 zones.');return
        self.state.config['trace']['exclude_regions'].append(box);self._update_exclusion_label();self._dirty()

    def _update_exclusion_label(self):
        n=len(self.state.config.get('trace',{}).get('exclude_regions',[]));self.exclusion_label.configure(text=f'{n} zone(s) ignorée(s).' if n else 'Aucune zone ignorée.')

    def undo_exclusion(self):
        zones=self.state.config['trace']['exclude_regions']
        if zones:zones.pop();self._update_exclusion_label();self._dirty()

    def clear_exclusions(self):
        self.state.config.setdefault('trace',{})['exclude_regions']=[];self._update_exclusion_label();self._dirty()

    def export_detected_svg(self):
        try:
            state=self.collect();source=Path(state.source)
            if not source.is_file():raise ValueError('Choisir une image seule pour exporter son tracé.')
            destination=filedialog.asksaveasfilename(title='Exporter le tracé pour retouche',defaultextension='.svg',filetypes=[('SVG','*.svg')])
            if not destination:return
            def work():
                try:
                    if source.suffix.lower()=='.svg':
                        import shutil
                        if source.resolve()!=Path(destination).resolve():shutil.copyfile(source,destination)
                    else:
                        from trace_image import trace
                        trace(source,destination,mode=state.mode,detail=state.detail,options=state.config.get('trace'))
                    self.events.put(('trace_exported',destination))
                except Exception as exc:self.events.put(('trace_export_error',str(exc)))
            self.executor.submit(work);self.status.configure(text='Export du tracé SVG en cours…')
        except Exception as exc:self._error(exc)

    def _export(self):
        p=self.export_panel.body
        self._section(p,'Image vers contours',0)
        ttk.Button(p,text='Régler la détection et vérifier les détails…',command=lambda:self.notebook.select(self.detection_panel)).grid(row=1,column=0,columnspan=3,sticky='w')
        ttk.Label(p,text='Les dessins au trait donnent les meilleurs résultats. Pour une photo,\ncommencer par Images fixes et ajuster le niveau de détails.',style='Muted.TLabel').grid(row=3,column=0,columnspan=3,sticky='w',pady=8)
        self._section(p,'Vidéo',4)
        self._combo(p,5,'Résolution','quality',QUALITIES)
        self._combo(p,6,'Images / seconde','fps',['Automatique','24','25','30','50','60','120'],False)
        ttk.Label(p,text='Musique : réglages et écoute dans l’onglet Musique.',style='Muted.TLabel').grid(row=7,column=0,columnspan=3,sticky='w',pady=8)
        self._entry(p,8,'Dossier de sortie','output',browse=self.choose_output)
        self._section(p,'Calcul et cache',10)
        self._combo(p,11,'Images en parallèle','jobs',['Auto (adaptatif, max. 4)','1','2','3','4'])
        ttk.Checkbutton(p,text='Forcer le recalcul des exports déjà prêts',variable=self._var('force',False,tk.BooleanVar)).grid(row=12,column=0,columnspan=3,sticky='w',pady=6)
        self._section(p,'Quel bouton utiliser ?',13)
        explanations='Vérifier : contrôle des fichiers et paramètres, sans rendu.\n\nImages fixes : trois images pour contrôler cadrage et couleurs.\n\nVidéo test : petite vidéo 540 × 960 avec le vrai rythme et le son.\n\nExporter : vidéo en pleine résolution, avec la musique si elle est activée.'
        ttk.Label(p,text=explanations,wraplength=550,style='Muted.TLabel').grid(row=14,column=0,columnspan=3,sticky='w')

    def _advanced(self):
        p=self.advanced_panel.body
        ttk.Label(p,text='Tous les paramètres d’animation et de thème sont accessibles ici.\nLes chemins relatifs saisis ici partent du dossier du programme.',style='Muted.TLabel').grid(row=0,column=0,columnspan=3,sticky='w',pady=8)
        self.json_text=tk.Text(p,height=27,width=50,wrap='none',bg='#0d1523',fg=INK,insertbackground=INK,font=('DejaVu Sans Mono',10),undo=True)
        self.json_text.grid(row=1,column=0,columnspan=3,sticky='ew')
        bar=ttk.Frame(p);bar.grid(row=2,column=0,columnspan=3,sticky='w',pady=10)
        ttk.Button(bar,text='Actualiser depuis les champs',command=self.refresh_json).pack(side='left',padx=(0,6))
        ttk.Button(bar,text='Appliquer le JSON',command=self.apply_json).pack(side='left')
        ttk.Button(p,text='Importer un JSON d’animation…',command=self.import_animation).grid(row=3,column=0,columnspan=3,sticky='w')

    def _replace(self,widget,text):widget.delete('1.0','end');widget.insert('1.0',text)

    def _populate(self,state):
        self.loading=True;self.state=deepcopy(state);c=state.config
        direct={key:c.get(key,'') for key in ['title','brand','tagline','episode','intro','outro','hero_scale','samples','background']}
        direct.update(source=state.source,output=state.output,theme_name=state.theme_meta['name'],
                      opacity=c['background_opacity'],dim_top=c['background_dimming']['top'],dim_bottom=c['background_dimming']['bottom'],
                      jobs='Auto (adaptatif, max. 4)' if state.jobs==0 else str(state.jobs),force=state.force,
                      fps='Automatique' if state.fps is None else str(state.fps),audio=c['audio'],recursive=state.recursive,
                      path_id=c.get('path_id') or '')
        for key,mapping,value in [('layout',LAYOUTS,c['layout']),('mode',MODES,state.mode),('detail',DETAILS,state.detail),
                                  ('quality',QUALITIES,state.quality),('contours',{'Tous les traits':'all','Contour fermé principal':'largest'},c['contours'])]:
            direct[key]=next(k for k,v in mapping.items() if v==value)
        detection=trace_settings(c.get('trace'));self.state.config['trace']=detection
        for key,value in detection.items():
            if key!='exclude_regions':direct['trace_'+key]=value
        direct['trace_threshold_method']=next(k for k,v in THRESHOLDS.items() if v==detection['threshold_method'])
        direct['trace_polarity']=next(k for k,v in POLARITIES.items() if v==detection['polarity'])
        direct['trace_preset']=next(iter(TRACE_PRESETS));direct['exclude_tool']=False
        self._update_exclusion_label()
        music=music_settings(c.get('music'))
        direct['music_mode']='Générative par image' if music['mode']=='generative' else 'Classique original'
        direct['music_style']={'orbital':'Orbite · arpèges doux','ambient':'Brume · nappes aériennes','crystalline':'Cristal · notes légères'}[music['style']]
        for key in ['variation','tempo','density','brightness','space','target_lufs']:direct['music_'+key]=music[key]
        area=safe_settings(c.get('safe_area'))
        direct['safe_enabled']=area['enabled']
        for key in ['top','bottom','left','right']:direct['safe_'+key]=area[key]
        for key,value in c['colors'].items():direct['color_'+key]=value
        for key,value in c['fonts'].items():direct['font_'+key]=value
        for key,value in c['captions'].items():direct[key]=value
        for key,value in direct.items():
            if key in self.vars:self.vars[key].set(value)
        self.vars['base_style'].set(state.theme_meta['name'])
        self._replace(self.final_text,c['final_title']);self._replace(self.credit_text,c['source_credit'])
        self._replace(self.description_text,state.theme_meta.get('description',''))
        self._set_stages(list(zip(c['steps'],c['durations'])))
        self._replace(self.json_text,json.dumps(c,ensure_ascii=False,indent=2))
        self.loading=False;self._update_chips();self._dirty()

    def collect(self,validate=True):
        s=deepcopy(self.state);v={key:var.get() for key,var in self.vars.items()};c=s.config
        for key in ['title','brand','tagline','episode','background']:c[key]=v[key]
        c['final_title']=self.final_text.get('1.0','end-1c');c['source_credit']=self.credit_text.get('1.0','end-1c')
        c['colors']={key:v['color_'+key].strip() for key in COLOR_LABELS}
        c['fonts']={key:str(Path(v['font_'+key]).expanduser().resolve()) for key in ['sans','bold','serif']}
        c['captions']={key:v[key] for key in ['early','middle','late']}
        c['background_opacity']=float(v['opacity']);c['background_dimming']={'top':float(v['dim_top']),'bottom':float(v['dim_bottom'])}
        detection=trace_settings(c.get('trace'))
        for key in ['threshold','max_size','min_component','gap_close','max_strokes']:detection[key]=int(v['trace_'+key])
        for key in ['adaptive_offset','min_stroke','smoothing','simplify','edge_sigma','edge_quantile']:detection[key]=float(str(v['trace_'+key]).replace(',','.'))
        detection['threshold_method']=THRESHOLDS[v['trace_threshold_method']];detection['polarity']=POLARITIES[v['trace_polarity']]
        detection['preserve_accents']=bool(v['trace_preserve_accents']);c['trace']=detection
        c['layout']=LAYOUTS[v['layout']];c['contours']={'Tous les traits':'all','Contour fermé principal':'largest'}[v['contours']]
        c['path_id']=v['path_id'].strip() or None;c['samples']=int(v['samples'])
        for key in ['intro','outro','hero_scale']:c[key]=float(str(v[key]).replace(',','.'))
        c['steps'],c['durations']=map(list,zip(*self._get_stages()))
        c['audio']=bool(v['audio'])
        c['music']={'mode':'generative' if v['music_mode']=='Générative par image' else 'classic',
                    'style':{'Orbite · arpèges doux':'orbital','Brume · nappes aériennes':'ambient','Cristal · notes légères':'crystalline'}[v['music_style']],
                    'variation':int(v['music_variation']),
                    **{key:float(str(v['music_'+key]).replace(',','.')) for key in ['tempo','density','brightness','space','target_lufs']}}
        c['safe_area']={'enabled':bool(v['safe_enabled']),**{key:float(str(v['safe_'+key]).replace(',','.')) for key in ['top','bottom','left','right']}}
        s.source=str(Path(v['source']).expanduser().resolve()) if v['source'].strip() else ''
        s.output=str(Path(v['output']).expanduser().resolve()) if v['output'].strip() else ''
        if c['background']:c['background']=str(Path(c['background']).expanduser().resolve())
        s.mode=MODES[v['mode']];s.detail=DETAILS[v['detail']];s.quality=QUALITIES[v['quality']]
        s.jobs=0 if v['jobs']=='Auto (adaptatif, max. 4)' else int(v['jobs']);s.force=bool(v['force'])
        s.fps=None if v['fps']=='Automatique' else int(v['fps']);s.recursive=bool(v['recursive'])
        s.theme_meta={'version':1,'name':v['theme_name'],'description':self.description_text.get('1.0','end-1c')}
        c['theme_name']=s.theme_meta['name']
        if validate:s.validate()
        return s

    def _dirty(self,*args):
        if self.loading or self.closed:return
        self._update_chips()
        if self.preview_after:self.root.after_cancel(self.preview_after)
        if self.preview_enabled:self.preview_after=self.root.after(450,self._submit_preview)

    def _update_chips(self):
        for key,button in self.color_buttons.items():
            color=self.vars['color_'+key].get()
            try:button.configure(bg=color,activebackground=color)
            except tk.TclError:pass

    def _submit_preview(self):
        self.preview_after=None
        self.preview_generation+=1;generation=self.preview_generation
        try:state=self.collect();self.state=deepcopy(state)
        except Exception as exc:self.preview_caption.configure(text=str(exc));return
        if self.preview_future:self.preview_future.cancel()
        self.preview_caption.configure(text='Mise à jour de l’aperçu…')
        future=self.executor.submit(self.preview_builder.build,state,self.vars['view'].get());self.preview_future=future
        def complete(f):
            if f.cancelled():return
            try:self.events.put(('preview',(generation,*f.result(),deepcopy(state.config['safe_area']))))
            except Exception as exc:self.events.put(('preview_error',(generation,str(exc))))
        future.add_done_callback(complete)

    def choose_base(self,event=None):
        name=self.vars['base_style'].get()
        if name not in self.builtins:return
        try:
            s=self.collect(validate=False);s.apply_theme(self.builtins[name],preserve_text=True)
            self._populate(s);self.status.configure(text='Style chargé. Les textes et réglages d’animation sont conservés.')
        except Exception as exc:self._error(exc)

    def _get_stages(self):
        return [(int(self.stages.item(i,'values')[0]),float(self.stages.item(i,'values')[1])) for i in self.stages.get_children()]
    def _set_stages(self,rows):
        for item in self.stages.get_children():self.stages.delete(item)
        for n,d in rows:self.stages.insert('','end',values=(n,d))
        if self.stages.get_children():self.stages.selection_set(self.stages.get_children()[0])
    def select_stage(self,event=None):
        if self.stages.selection():
            n,d=self.stages.item(self.stages.selection()[0],'values');self.vars['stage_n'].set(n);self.vars['stage_d'].set(d)
    def apply_stage(self):
        try:
            n=int(self.vars['stage_n'].get());d=float(self.vars['stage_d'].get().replace(',','.'))
            if n<1 or not math.isfinite(d) or not d>.4:raise ValueError('Choisir au moins un cercle et une durée supérieure à 0.4 s.')
            rows=self._get_stages();selection=self.stages.selection()
            index=list(self.stages.get_children()).index(selection[0]) if selection else 0
            rows[index]=(n,d)
            if len({a for a,b in rows})!=len(rows):raise ValueError('Chaque nombre de cercles doit être différent.')
            rows=sorted(rows);self._set_stages(rows)
            self.stages.selection_set(self.stages.get_children()[rows.index((n,d))]);self._dirty()
        except Exception as exc:self._error(exc)
    def add_stage(self):
        rows=self._get_stages();rows.append((rows[-1][0]*2,3.0));self._set_stages(rows)
        self.stages.selection_set(self.stages.get_children()[-1]);self._dirty()
    def remove_stage(self):
        if len(self.stages.get_children())<=1:self._error('Conserver au moins une étape.');return
        for item in self.stages.selection():self.stages.delete(item)
        self._dirty()
    def reset_safe_area(self):
        self.loading=True
        self.vars['safe_enabled'].set(True)
        for key in ['top','bottom','left','right']:self.vars['safe_'+key].set(DEFAULT_SAFE_AREA[key])
        self.loading=False;self._dirty()

    def reset_stages(self):
        default=StudioState.initial().config;self._set_stages(list(zip(default['steps'],default['durations'])));self._dirty()

    def choose_source(self):
        file=filedialog.askopenfilename(title='Choisir l’image à dessiner',filetypes=[('Images et SVG','*.svg *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff'),('Tous les fichiers','*')])
        if file:
            self.clear_exclusions();self.keep_all_svg();self.vars['source'].set(file)
    def choose_folder(self):
        folder=filedialog.askdirectory(title='Choisir un dossier d’images')
        if folder:
            self.clear_exclusions();self.keep_all_svg();self.vars['source'].set(folder)
    def choose_output(self):
        folder=filedialog.askdirectory(title='Dossier des vidéos et aperçus')
        if folder:self.vars['output'].set(folder)
    def choose_background(self):
        file=filedialog.askopenfilename(title='Image de fond',filetypes=[('Images','*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff')])
        if file:
            self.vars['background'].set(file)
            if self.vars['auto_palette'].get():self.suggest_palette()
    def choose_font(self,kind):
        file=filedialog.askopenfilename(title='Choisir une police',filetypes=[('Polices','*.ttf *.otf *.ttc'),('Tous les fichiers','*')])
        if file:self.vars['font_'+kind].set(file)
    def pick_color(self,key):
        value=colorchooser.askcolor(color=self.vars['color_'+key].get(),title=COLOR_LABELS[key],parent=self.root)[1]
        if value:self.vars['color_'+key].set(value)
    def suggest_palette(self):
        source=self.vars['background'].get()
        if not source:self.status.configure(text='Choisir une image de fond pour en proposer les couleurs.');return
        self.status.configure(text='Recherche d’une palette adaptée au fond…')
        def work():
            try:self.events.put(('palette',(source,palette_from_image(source))))
            except Exception as exc:self.events.put(('palette_error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def refresh_json(self):
        try:self._replace(self.json_text,json.dumps(self.collect().config,ensure_ascii=False,indent=2))
        except Exception as exc:self._error(exc)
    def apply_json(self):
        try:
            data=json.loads(self.json_text.get('1.0','end-1c'))
            if not isinstance(data,dict):raise ValueError('Le JSON doit être un objet.')
            data=resolve_visual_paths(data,ROOT)
            s=self.collect(validate=False)
            if data.get('svg'):s.source=str((ROOT/data.pop('svg')).resolve())
            s.config=merge_configs(s.config,data)
            if 'theme_name' in data:s.theme_meta['name']=data['theme_name']
            s.validate();self._populate(s);self.status.configure(text='JSON appliqué à tous les champs.')
        except Exception as exc:self._error(exc)
    def import_animation(self):
        file=filedialog.askopenfilename(title='Importer une configuration d’animation',filetypes=[('JSON','*.json')])
        if not file:return
        try:s=self.collect(validate=False);s.import_animation(file);s.validate();self._populate(s)
        except Exception as exc:self._error(exc)
    def open_project(self):
        file=filedialog.askopenfilename(title='Ouvrir un projet ORBITE',filetypes=[('Projet JSON','*.json')])
        if not file:return
        try:self._populate(StudioState.load_project(file));self.project_file=file;self.status.configure(text='Projet chargé.')
        except Exception as exc:self._error(exc)
    def save_project(self):
        folder=data_root()/'projects'
        try:folder.mkdir(parents=True,exist_ok=True)
        except OSError:folder=Path.home()
        file=filedialog.asksaveasfilename(initialdir=str(folder),title='Enregistrer le projet',defaultextension='.json',initialfile='mon_projet.orbite.json',filetypes=[('Projet ORBITE','*.json')])
        if not file:return
        try:self.collect().save_project(file);self.project_file=file;self.status.configure(text='Projet enregistré : '+file)
        except Exception as exc:self._error(exc)
    def import_theme(self):
        file=filedialog.askopenfilename(title='Charger une identité visuelle',filetypes=[('Thème JSON','*.json')])
        if not file:return
        try:s=self.collect(validate=False);s.apply_theme(file);self._populate(s);self.status.configure(text='Thème chargé ; contenu et animation conservés.')
        except Exception as exc:self._error(exc)
    def save_theme(self):
        folder=data_root()/'themes'
        try:folder.mkdir(parents=True,exist_ok=True)
        except OSError:folder=Path.home()
        file=filedialog.asksaveasfilename(initialdir=str(folder),title='Enregistrer l’identité visuelle',defaultextension='.json',initialfile='mon_theme.json',filetypes=[('Thème JSON','*.json')])
        if not file:return
        try:self.collect().save_theme(file);self.status.configure(text='Thème enregistré : '+file)
        except Exception as exc:self._error(exc)

    def start_action(self,action):
        if self.runner.running:return
        try:
            state=self.collect();argv=state.command(action)
            self.state=state;self.last_output=state.output;self.current_action=action
            self.progress.stop();self.progress.configure(mode='indeterminate',value=0);self.progress.start(16)
            for button in self.action_buttons.values():button.configure(state='disabled')
            self.cancel_button.configure(state='normal')
            self._append_log('\n—— '+{'check':'Vérification','stills':'Images fixes','preview':'Vidéo test','export':'Export','music':'Écoute musicale'}[action]+' ——')
            self.status.configure(text='Traitement en cours. Les modifications suivantes seront utilisées au prochain lancement.')
            self.runner.start(argv)
        except Exception as exc:self._error(exc)
    def cancel_task(self):
        self.runner.cancel();self.status.configure(text='Arrêt du traitement en cours…');self.cancel_button.configure(state='disabled')
    def _append_log(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def toggle_log(self):
        if self.log.winfo_manager():self.log.pack_forget()
        else:self.log.pack(fill='x',pady=(8,0))
    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,data=self.events.get_nowait()
                if kind=='trace_exported':self.status.configure(text='Tracé SVG exporté : '+data)
                elif kind=='trace_export_error':self._error(data)
                elif kind=='preview':
                    generation,image,caption,area=data
                    if generation==self.preview_generation:
                        self.preview_image=image;self.preview_area=area;self._fit_preview()
                        self.preview_caption.configure(text=caption)
                elif kind=='preview_error':
                    if data[0]==self.preview_generation:self.preview_caption.configure(text=data[1])
                elif kind=='palette':
                    file,colors=data
                    if file==self.vars['background'].get():
                        self.loading=True
                        for key,value in colors.items():self.vars['color_'+key].set(value)
                        self.loading=False;self._dirty();self.status.configure(text='Palette proposée. Chaque couleur peut encore être modifiée.')
                elif kind=='palette_error':self.status.configure(text='Palette non disponible : '+data)
                elif kind in {'update_check','update_check_error'}:self.updates.handle(kind,data)
                elif kind=='log':self._append_log(data)
                elif kind=='progress':self.progress.stop();self.progress.configure(mode='determinate',value=data)
                elif kind in {'done','failed','cancelled'}:
                    self.progress.stop();self.progress.configure(mode='determinate',value=100 if kind=='done' else 0)
                    for button in self.action_buttons.values():button.configure(state='normal')
                    self.cancel_button.configure(state='disabled')
                    if self.current_action=='update':
                        self.updates.finished(kind,data)
                        if self.closed:return
                    elif kind=='done':self.status.configure(text='Vérification terminée, aucun rendu créé.' if self.current_action=='check' else 'Musique prête : onglet Musique → Écouter le dernier MP3.' if self.current_action=='music' else 'Terminé. Les fichiers sont accessibles dans Ouvrir les résultats.')
                    elif kind=='cancelled':self.status.configure(text='Traitement annulé. Les projets et sources sont conservés.')
                    else:
                        self.status.configure(text='Le traitement a échoué. Les détails figurent dans le journal.')
                        if not self.log.winfo_manager():self.log.pack(fill='x',pady=(8,0))
        except queue.Empty:pass
        if not self.closed:self.poll_after=self.root.after(80,self._poll)
    def _fit_preview(self):
        if self.closed or not hasattr(self,'preview_image'):return
        size=(max(1,self.preview_label.winfo_width()-4),max(1,self.preview_label.winfo_height()-4))
        image=self.preview_image.copy()
        area=getattr(self,'preview_area',safe_settings(self.state.config.get('safe_area')))
        if self.vars['show_safe_area'].get() and area['enabled']:
            x0,y0,x1,y1=safe_box(area,*image.size)
            overlay=Image.new('RGBA',image.size,(0,0,0,0));draw=ImageDraw.Draw(overlay)
            w,h=image.size
            for rectangle in [(0,0,w,y0),(0,y1,w,h),(0,y0,x0,y1),(x1,y0,w,y1)]:
                draw.rectangle(rectangle,fill=(220,90,120,55))
            draw.rectangle((x0,y0,x1-1,y1-1),outline=(132,223,230,210),width=1)
            image=Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')
        if self.vars['view'].get() in {'Tracé détecté','Comparaison source / traits'}:
            box=self.preview_image.info.get('image_box')
            if box:
                draw=ImageDraw.Draw(image)
                zones=list(self.state.config.get('trace',{}).get('exclude_regions',[]))
                if getattr(self,'exclusion_anchor',None) is not None and getattr(self,'exclusion_end',None) is not None:
                    a,b=self.exclusion_anchor,self.exclusion_end;zones.append([min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])])
                for x0,y0,x1,y1 in zones:draw.rectangle((box[0]+x0*(box[2]-box[0]),box[1]+y0*(box[3]-box[1]),box[0]+x1*(box[2]-box[0]),box[1]+y1*(box[3]-box[1])),outline='#e44466',width=2)
        image.thumbnail(size)
        self.preview_placement=((self.preview_label.winfo_width()-image.width)/2,(self.preview_label.winfo_height()-image.height)/2,image.width,image.height)
        self.preview_photo=ImageTk.PhotoImage(image,master=self.root)
        self.preview_label.configure(image=self.preview_photo,text='')
    def _wheel(self,event):
        widget=self.root.winfo_containing(event.x_root,event.y_root)
        while widget is not None:
            if isinstance(widget,ScrollPanel):widget.canvas.yview_scroll(-1 if event.delta>0 or getattr(event,'num',None)==4 else 1,'units');return
            widget=getattr(widget,'master',None)
    def open_audio(self):
        try:
            folder=Path(self.last_output);report=folder/'batch_report.json'
            candidates=[]
            if report.is_file():
                for job in json.loads(report.read_text(encoding='utf-8')):
                    if job.get('status')=='ok' and job.get('folder'):
                        candidate=Path(job['folder'])/'orbite_soundtrack.mp3'
                        if candidate.is_file():candidates.append(candidate)
            if not candidates:
                self.status.configure(text='Générer une écoute audio seule pour créer le MP3.');return
            file=candidates[-1]
            if sys.platform=='win32':os.startfile(file)
            else:subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(file)])
        except Exception as exc:self._error(exc)

    def open_results(self):
        path=Path(self.last_output)
        if not path.exists():self.status.configure(text='Aucun résultat pour le moment. Lancer Images fixes ou Exporter.');return
        try:
            if sys.platform=='win32':os.startfile(path)
            else:subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)])
        except Exception as exc:self._error(exc)
    def _error(self,exc):messagebox.showerror('ORBITE Studio',str(exc),parent=self.root)
    def close(self):
        self.closed=True;self.runner.cancel();self.updates.close()
        if self.preview_after:self.root.after_cancel(self.preview_after)
        self.root.after_cancel(self.poll_after)
        for event in ["<MouseWheel>","<Button-4>","<Button-5>"]:self.root.unbind_all(event)
        self.executor.shutdown(wait=False,cancel_futures=True);self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description='ORBITE Studio')
    parser.add_argument('--project',type=Path);parser.add_argument('--no-update-check',action='store_true')
    args=parser.parse_args()
    try:root=tk.Tk()
    except tk.TclError as exc:
        print('ORBITE Studio nécessite un écran graphique et Tkinter. Sous Linux, installer python3-tk.\n'+str(exc),file=sys.stderr)
        return 1
    app=StudioApp(root,updates_enabled=not args.no_update_check)
    if args.project:
        try:app._populate(StudioState.load_project(args.project));app.project_file=str(args.project)
        except Exception as exc:app._error(exc)
    root.mainloop();return 0


if __name__=='__main__':sys.exit(main())

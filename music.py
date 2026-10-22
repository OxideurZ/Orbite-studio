"""Image-conditioned, constrained procedural composition. No model or samples required.

The mapping is an artistic choice, not a universal image-to-emotion relation.
See MUSIQUE.md for references, mappings and reproducibility guarantees.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import wave
from runtime import require_ffmpeg

import numpy as np
from scipy.signal import butter,sosfilt

DEFAULT_MUSIC={'mode':'generative','style':'orbital','variation':0,'tempo':0,
               'density':.55,'brightness':.35,'space':.35,'target_lufs':-18.}
STYLES={'orbital':{'bpm':78,'pad':.034,'key':.074,'decay':.68},
        'ambient':{'bpm':64,'pad':.048,'key':.048,'decay':1.15},
        'crystalline':{'bpm':84,'pad':.028,'key':.070,'decay':.9}}
PENTA=np.array([0,2,4,7,9,12,14,16])
# All chord tones belong to the same pentatonic collection. No semitone clusters.
CHORDS=[(0,4,7,9),(9,0,4,7),(2,7,9,0),(7,9,2,4)]
PROGRESSIONS=[(0,1,2,3),(0,2,1,3),(1,2,0,3),(0,3,2,1)]


def settings(value=None):return {**DEFAULT_MUSIC,**(value or {})}


def validate_music(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_MUSIC):
        raise ValueError('music attend '+', '.join(DEFAULT_MUSIC)+'.')
    if value['mode'] not in {'generative','classic'}:raise ValueError('Mode musical inconnu.')
    if value['style'] not in STYLES:raise ValueError('Ambiance musicale inconnue.')
    if type(value['variation']) is not int or not 0<=value['variation']<=2147483647:
        raise ValueError('La variation musicale doit être un entier entre 0 et 2147483647.')
    for key in ['tempo','density','brightness','space','target_lufs']:
        x=value[key]
        if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x):
            raise ValueError(f'music.{key} doit être un nombre fini.')
    if value['tempo']!=0 and not 48<=value['tempo']<=120:raise ValueError('Tempo : 0 (auto) ou 48 à 120 BPM.')
    for key in ['density','brightness','space']:
        if not 0<=value[key]<=1:raise ValueError(f'music.{key} doit être entre 0 et 1.')
    if not -26<=value['target_lufs']<=-14:raise ValueError('Niveau musical : entre -26 et -14 LUFS.')


def smooth(x):
    x=np.clip(x,0,1);return x*x*(3-2*x)


def image_features(z,pen):
    z=np.asarray(z,complex);pen=np.asarray(pen,bool)
    center=z[pen].mean() if pen.any() else z.mean()
    norm=np.round((z-center)/max(float(np.sqrt(np.mean(abs(z-center)**2))),1e-9),10)
    indices=np.linspace(0,len(z)-1,512).astype(int)
    # Fixed-size geometry fingerprint, independent of styling/title/background.
    signature=np.column_stack([norm[indices].real,norm[indices].imag,pen[indices]])
    fingerprint=hashlib.sha256(np.round(signature,4).astype('<f8').tobytes()).hexdigest()
    power=abs(np.fft.rfft(norm.real))**2+abs(np.fft.rfft(norm.imag))**2
    power=power[1:129];power/=max(float(power.sum()),1e-12)
    entropy=float(-(power*np.log(np.maximum(power,1e-15))).sum()/np.log(max(2,len(power))))
    ratio=float(np.ptp(norm.real)/max(np.ptp(norm.imag),1e-9))
    return {'fingerprint':fingerprint,'complexity':round(float(np.clip(entropy,0,1)),12),
            'aspect_ratio':round(ratio,12),'pen_down_fraction':float(pen.mean())},norm


def compose(z,pen,config,total):
    """Return an inspectable symbolic score. First-order transitions are constrained
    by register, maximum melodic leap, current harmony and recurring phrase motifs.
    Probabilities are designed here, not learned from copyrighted recordings.
    """
    m=settings(config.get('music'));validate_music(m)
    features,norm=image_features(z,pen)
    seed=int.from_bytes(hashlib.sha256((features['fingerprint']+':'+str(m['variation'])).encode()).digest()[:8],'little')
    rng=np.random.default_rng(seed);style=STYLES[m['style']]
    bpm=float(m['tempo'] or np.clip(style['bpm']+round(features['complexity']*10)+rng.choice([-6,-3,0,3]),58,100))
    beat=60/bpm;bar=beat*4
    root=int(rng.choice([48,50,51,53,55,57]));progression=PROGRESSIONS[int(rng.integers(len(PROGRESSIONS)))]
    candidates=root+12+PENTA;candidates=candidates[candidates<=84]
    notes=[];chords=[];previous=int(candidates[2]);recent=[]
    motifs=rng.integers(0,len(candidates),size=(2,8))
    ends=np.cumsum(config['durations'])+config['intro']
    previous_voicing=np.array([root,root+7,root+12,root+16])
    stop=max(.2,total-min(1.25,total*.16))
    for bar_index,start in enumerate(np.arange(0,stop,bar)):
        last_bar=start+bar>=stop
        chord_id=0 if last_bar or start+bar>=ends[-1] else progression[bar_index%len(progression)]
        chord=CHORDS[chord_id];pcs={(root+p)%12 for p in chord}
        # Smooth voice leading: each pad voice chooses the nearest octave of its
        # assigned pitch class, rather than jumping with every chord root.
        voicing=[]
        for j,pitch in enumerate(sorted(chord)):
            choices=np.array([root+pitch-12,root+pitch,root+pitch+12])
            choices=choices[(choices>=43)&(choices<=79)]
            voicing.append(int(choices[np.argmin(abs(choices-previous_voicing[j]))]))
        previous_voicing=np.array(voicing)
        chords.append({'on':float(start),'duration':float(min(bar+.55,total-start)),
                       'midi':voicing,'bass':int(root+chord[0]-12),'chord':chord_id})
        patterns=[(0,1,2,3),(0,1.5,2,3.5),(0,.5,2,3),(0,2,3),(0,1,2.5)]
        pattern=patterns[int(rng.integers(len(patterns)))]
        if m['style']=='ambient':pattern=(0,2,3) if bar_index%2 else (0,2)
        for event,position in enumerate(pattern):
            on=float(start+position*beat)
            if on>=stop:continue
            progress=on/max(total,1)
            if event and rng.random()>(.35+.65*m['density'])*(.78+.22*progress):continue
            stage=min(int(np.searchsorted(ends,on,side='right')),len(ends)-1)
            stage_start=config['intro'] if stage==0 else ends[stage-1]
            phase=float(np.clip((on-stage_start)/config['durations'][stage],0,1))
            j=min(int(phase*len(norm)),len(norm)-1)
            # Height steers a melodic target, horizontal movement the stereo pan.
            height=float(np.clip(.5-norm[j].imag*.25,0,1))
            motif=int(motifs[(bar_index//2)%2,(bar_index*4+event)%8])
            target=.55*candidates[min(len(candidates)-1,round(height*(len(candidates)-1)))]+.45*candidates[motif]
            weights=np.exp(-abs(candidates-previous)/4.0)*np.exp(-abs(candidates-target)/7)
            weights*=np.where(np.isin(candidates%12,list(pcs)),2.7 if position%2==0 else 1.4,1.)
            weights[abs(candidates-previous)>7]=0
            if len(recent)>=2 and recent[-1]==recent[-2]:weights[candidates==previous]=0
            weights/=weights.sum()
            note=int(rng.choice(candidates,p=weights));previous=note;recent.append(note)
            on=max(0,on+float(rng.uniform(-.009,.009)))
            duration=min(2.3 if m['style']=='ambient' else 1.65,total-on)
            notes.append({'on':on,'duration':float(duration),'midi':note,
                          'velocity':float(rng.uniform(.80,1.)*(.88+.12*progress)),
                          'pan':float(np.clip(.5+norm[j].real*.10,.32,.68)),'kind':'key'})
    # Explicit cadence: lower tonic at the start of the final plan, instead of an
    # endless random walk cut abruptly by the video end.
    cadence=max(.1,min(float(ends[-1])+.3,stop))
    notes=[n for n in notes if n['on']<cadence]
    notes.append({'on':cadence,'duration':min(3.,total-cadence),'midi':root+12,
                  'velocity':.9,'pan':.5,'kind':'key'})
    # Stage cues use existing chord tones and remain softer than the melody.
    for on in [config['intro'],*ends[:-1]]:
        if on>=stop:continue
        chord=chords[min(int(on/bar),len(chords)-1)]
        notes.append({'on':float(on),'duration':min(1.3,total-on),
                      'midi':int(max(chord['midi'])),'velocity':.32,'pan':.5,'kind':'spark'})
    return {'version':1,'seed':str(seed),'features':features,'bpm':bpm,'root_midi':root,
            'key':['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][root%12]+' pentatonique majeure',
            'style':m['style'],'notes':sorted(notes,key=lambda n:n['on']),'chords':chords}


def synthesize(z,pen,cx,cy,config,total,path,sample_rate=48000):
    m=settings(config.get('music'));score=compose(z,pen,config,total)
    sr=sample_rate;n=round(total*sr);audio=np.zeros((n,2),np.float64)
    style=STYLES[m['style']];bright=m['brightness']
    magnitudes=abs(cx[1:7])+abs(cy[1:7]);magnitudes/=max(float(magnitudes.max()),1e-9)
    def add(on,duration,midi,gain,pan,kind):
        a=max(0,round(on*sr));length=min(round(duration*sr),n-a)
        if length<2:return
        u=np.arange(length)/sr;f=440*2**((midi-69)/12)
        if kind=='pad':
            envelope=smooth(u/.45)*smooth((length/sr-u)/.65)
            tone=np.sin(2*np.pi*f*u)
            for harmonic in range(2,6):
                weight=(.025+.07*bright)*magnitudes[harmonic-1]/harmonic
                tone+=weight*np.sin(2*np.pi*f*harmonic*u)
            tone*=.92+.08*np.sin(2*np.pi*.19*u)
        else:
            attack=.035 if kind=='bass' else .022 if kind=='key' else .035
            decay=style['decay'] if kind=='key' else .65 if kind=='bass' else .38
            envelope=smooth(u/attack)*np.exp(-u/decay)*smooth((length/sr-u)/.2)
            tone=np.sin(2*np.pi*f*u)
            tone+=(.025+bright*.13)*np.sin(2*np.pi*2*f*u)*np.exp(-u/.3)
            if m['style']=='crystalline' and kind=='key':tone+=.045*bright*np.sin(2*np.pi*3*f*u)*np.exp(-u/.18)
        signal=tone*envelope*gain;signal[0]=signal[-1]=0
        audio[a:a+length,0]+=signal*np.sqrt(1-pan)
        audio[a:a+length,1]+=signal*np.sqrt(pan)
    for chord in score['chords']:
        for j,note in enumerate(chord['midi']):
            add(chord['on'],chord['duration'],note,style['pad'],.4+.2*j/3,'pad')
        add(chord['on'],min(2.4,chord['duration']),chord['bass'],.055,.5,'bass')
    for note in score['notes']:
        add(note['on'],note['duration'],note['midi'],style['key']*note['velocity'],note['pan'],note['kind'])
    # Quiet harmonic texture follows the number of active Fourier terms; only
    # the first four partials are audible, smoothly gated, never the raw FFT.
    t=np.arange(n)/sr;ends=np.cumsum(config['durations'])+config['intro']
    for harmonic in range(1,min(4,len(magnitudes))+1):
        stage=next((i for i,k in enumerate(config['steps']) if k>=harmonic),None)
        if stage is None:continue
        start=config['intro'] if stage==0 else ends[stage-1]
        gate=smooth((t-start)/.45)
        f=440*2**((score['root_midi']-69)/12)*harmonic
        drone=np.sin(2*np.pi*f*t)*gate*magnitudes[harmonic-1]*.008/harmonic
        audio+=drone[:,None]
    dry=audio.copy()
    for delay,amount in [(.23,.25),(.37,.16),(.53,.09)]:
        shift=round(delay*sr)
        if shift<n:audio[shift:]+=dry[:-shift,::-1]*amount*m['space']
    cutoff=min(sr*.4,2200+bright*2200+(400 if m['style']=='crystalline' else 0))
    audio=sosfilt(butter(2,35,'highpass',fs=sr,output='sos'),audio,axis=0)
    audio=sosfilt(butter(3,cutoff,'lowpass',fs=sr,output='sos'),audio,axis=0)
    audio*= (smooth(t/.18)*smooth((total-t)/min(1.4,total*.2)))[:,None]
    peak=float(np.max(abs(audio)));audio/=max(1,peak/.78);audio[0]=audio[-1]=0
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as file:
        file.setnchannels(2);file.setsampwidth(2);file.setframerate(sr)
        file.writeframes(np.round(audio*32767).astype('<i2').tobytes())
    return {'mode':'generative','settings':m,'sample_rate':sr,'channels':2,
            'synthesis_peak_dbfs':float(20*np.log10(max(np.max(abs(audio)),1e-12))),
            'score':score}


def master_audio(source,destination,music=None):
    """Two-pass BS.1770 loudness normalization; level is an editorial choice,
    not a claim that -18 LUFS is a platform requirement. FFmpeg measures true peak.
    """
    m=settings(music);validate_music(m)
    base=f"loudnorm=I={m['target_lufs']}:TP=-2:LRA=7"
    def run(filter_text,output):
        result=subprocess.run([require_ffmpeg(),'-hide_banner','-nostdin','-y','-i',str(source),
            '-af',filter_text,'-ar','48000',*output],capture_output=True,text=True,check=True)
        matches=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',result.stderr,re.S)
        if not matches:raise RuntimeError('FFmpeg ne renvoie pas les mesures de normalisation.')
        return json.loads(matches[-1])
    measured=run(base+':print_format=json',['-f','null','-'])
    fields={'input_i':'measured_I','input_tp':'measured_TP','input_lra':'measured_LRA',
            'input_thresh':'measured_thresh','target_offset':'offset'}
    if any(not math.isfinite(float(measured[k])) for k in fields):raise ValueError('Le signal audio est vide ou non mesurable.')
    parameters=''.join(':'+dest+'='+measured[key] for key,dest in fields.items())
    stats=run(base+parameters+':linear=true:print_format=json',['-c:a','pcm_s24le',str(destination)])
    return {'target_lufs':m['target_lufs'],'true_peak_ceiling_dbtp':-2.,
            'integrated_lufs':float(stats['output_i']),'true_peak_dbtp':float(stats['output_tp']),
            'loudness_range_lu':float(stats['output_lra']),'method':stats['normalization_type'],'passes':2}

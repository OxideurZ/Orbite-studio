"""Social UI clearance in logical 1080 × 1920 coordinates."""
from copy import deepcopy
import math

DEFAULT_SAFE_AREA={'enabled':False,'left':48,'right':180,'top':240,'bottom':440}
# Existing layouts use this envelope, including the lower captions/playhead.
CONTENT_VIEWPORT=(40,145,1010,1720)


def safe_settings(value=None):
    return {**deepcopy(DEFAULT_SAFE_AREA),**(value or {})}


def validate_safe_area(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_SAFE_AREA):
        raise ValueError('safe_area attend enabled, left, right, top et bottom.')
    if type(value['enabled']) is not bool:raise ValueError('safe_area.enabled doit être vrai ou faux.')
    for key in ['left','right','top','bottom']:
        n=value[key]
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0:
            raise ValueError(f'safe_area.{key} doit être un nombre positif ou nul.')
    if value['left']+value['right']>540 or value['top']+value['bottom']>960:
        raise ValueError('Les marges doivent laisser au moins la moitié de la largeur et de la hauteur.')


def safe_transform(value):
    """Uniform scale keeps the epicycles circular, centered within the usable frame."""
    a=safe_settings(value)
    if not a['enabled']:return 1.,(0.,0.)
    x0,y0,x1,y1=CONTENT_VIEWPORT
    w,h=1080-a['left']-a['right'],1920-a['top']-a['bottom']
    scale=min(w/(x1-x0),h/(y1-y0))
    offset=(a['left']+(w-(x1-x0)*scale)/2-x0*scale,
            a['top']+(h-(y1-y0)*scale)/2-y0*scale)
    return scale,offset


def safe_box(value,width,height):
    a=safe_settings(value)
    if not a['enabled']:return (0,0,width,height)
    return (math.ceil(a['left']*width/1080),math.ceil(a['top']*height/1920),
            math.floor((1080-a['right'])*width/1080),math.floor((1920-a['bottom'])*height/1920))

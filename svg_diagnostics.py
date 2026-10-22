"""Preview SVG subpaths before Fourier, respecting transformed coordinates and holes."""
import numpy as np
from PIL import Image,ImageDraw,ImageChops


def svg_preview(source,view='Tracé détecté',path_id=None,contours='all'):
    from render_social import svg_paths
    paths=svg_paths(source,path_id);parts=[(p,sub) for p in paths for sub in p.continuous_subpaths() if sub.length()>1e-9]
    boxes=np.array([sub.bbox() for _,sub in parts]);left,right=boxes[:,0].min(),boxes[:,1].max();top,bottom=boxes[:,2].min(),boxes[:,3].max()
    scale=min(336/max(right-left,1e-9),520/max(bottom-top,1e-9))
    offset=(180-scale*(left+right)/2,320-scale*(top+bottom)/2)
    target=Image.new('RGB',(360,640),'#e9eef4');surface=Image.new('RGB',target.size,'white');outlines=Image.new('RGB',target.size,'white');out=ImageDraw.Draw(outlines)
    selected=parts
    if contours=='largest':
        closed=[(p,s) for p,s in parts if s.isclosed()]
        if closed:selected=[max(closed,key=lambda pair:pair[1].length())]
    for path in paths:
        mask=Image.new('1',target.size,0);winding=np.zeros((640,360),np.int16)
        attrs=path.element.attrib;style=attrs.get('style','');filled=attrs.get('fill','black')!='none' and 'fill:none' not in style.replace(' ','')
        for p,sub in parts:
            if p is not path:continue
            points=[]
            for seg in sub:
                n=max(1,min(256,int(seg.length()*scale/2)+1))
                points.extend([(offset[0]+seg.point(t).real*scale,offset[1]+seg.point(t).imag*scale) for t in np.linspace(0,1,n,endpoint=False)])
            points.append((offset[0]+sub.end.real*scale,offset[1]+sub.end.imag*scale))
            if filled and sub.isclosed():
                # Compound glyphs use nested contours for counters/holes.
                layer=Image.new('1',target.size,0);ImageDraw.Draw(layer).polygon(points,fill=1)
                if 'evenodd' in style or attrs.get('fill-rule')=='evenodd':mask=ImageChops.logical_xor(mask,layer)
                else:
                    q=np.array(points);area=np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))
                    winding+=np.asarray(layer).astype(np.int16)*(1 if area>=0 else -1)
            else:ImageDraw.Draw(surface).line(points,fill='black',width=1)
            if any(s is sub for _,s in selected):out.line(points,fill='#152441',width=1)
        if np.any(winding):mask=Image.fromarray(np.uint8(np.asarray(mask)|(winding!=0))*255)
        surface.paste('black',mask=mask)
    image=surface if view=='Source' else outlines
    if view=='Comparaison source / traits':
        a=np.array(surface);ink=np.asarray(outlines).min(axis=2)<160;a[ink]=[20,165,210];image=Image.fromarray(a)
    target.paste(image);target.info['svg']=True
    caption=f'SVG · {len(selected)}/{len(parts)} sous-tracés · sans détection bitmap'
    if contours=='largest':caption+='\nContour principal : les détails intérieurs sont exclus. Choisir Tous les traits.'
    return target,caption

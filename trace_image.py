"""Extract centerline strokes from dark line art on a light background.

python trace_image.py portrait.jpg --output portrait.svg
Uses NumPy, SciPy and Pillow. No external vectorization service.
"""
from pathlib import Path
import argparse
import json
import xml.etree.ElementTree as ET
import numpy as np
from scipy import ndimage
from PIL import Image, ImageOps


def thin(mask):
    """Zhang–Suen skeletonization; preserves the centers of the drawn strokes."""
    img=np.pad(mask.astype(bool),1)
    while True:
        changed=False
        for second in [False,True]:
            p=img[1:-1,1:-1]
            neighbors=[img[:-2,1:-1],img[:-2,2:],img[1:-1,2:],img[2:,2:],
                       img[2:,1:-1],img[2:,:-2],img[1:-1,:-2],img[:-2,:-2]]
            count=sum(n.astype(np.uint8) for n in neighbors)
            turns=sum((~a&b).astype(np.uint8) for a,b in zip(neighbors,neighbors[1:]+neighbors[:1]))
            n,e,s,w=neighbors[0],neighbors[2],neighbors[4],neighbors[6]
            triple=(~(n&e&w)&~(n&s&w)) if second else (~(n&e&s)&~(e&s&w))
            remove=p&(count>=2)&(count<=6)&(turns==1)&triple
            if remove.any():p[remove]=False;changed=True
        if not changed:return img[1:-1,1:-1]


def simplify(points,tolerance=.55):
    """Iterative Ramer–Douglas–Peucker simplification in original image pixels."""
    if len(points)<3:return points
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        v=points[b]-points[a]
        p=points[a+1:b]-points[a]
        if abs(v)<1e-9:dist=abs(p)
        else:
            projection=np.clip((p.real*v.real+p.imag*v.imag)/abs(v)**2,0,1)
            dist=abs(p-projection*v)
        j=int(np.argmax(dist))
        if dist[j]>tolerance:
            j+=a+1;keep.add(j);stack.extend([(a,j),(j,b)])
    return points[sorted(keep)]


def extract_strokes(skeleton,min_stroke=6,smoothing=1,tolerance=.55):
    ys,xs=np.where(skeleton)
    coords=list(zip(ys.tolist(),xs.tolist()))
    ids={point:i for i,point in enumerate(coords)}
    graph=[set() for _ in coords]
    for i,(y,x) in enumerate(coords):
        for dy,dx in [(0,1),(1,0),(1,1),(1,-1)]:
            j=ids.get((y+dy,x+dx))
            if j is None:continue
            # Avoid artificial triangles on a one-pixel staircase.
            if dx and dy and ((y+dy,x) in ids or (y,x+dx) in ids):continue
            graph[i].add(j);graph[j].add(i)
    # Remove very short dangling skeleton spurs, mostly raster junction artifacts.
    for _ in range(2):
        remove=[]
        for start,adj in enumerate(graph):
            if len(adj)!=1:continue
            route=[start];prev=None;cur=start
            while len(route)<=4:
                candidates=graph[cur]-({prev} if prev is not None else set())
                if not candidates:break
                nxt=next(iter(candidates));prev,cur=cur,nxt
                if len(graph[cur])!=2:break
                route.append(cur)
            if len(route)<=min(3,min_stroke/2) and len(graph[cur])>2:remove.extend(route)
        for i in remove:
            for j in list(graph[i]):graph[j].discard(i)
            graph[i].clear()
    used=set();routes=[]
    def edge(a,b):return (min(a,b),max(a,b))
    def walk(a,b):
        route=[a];used.add(edge(a,b));prev,cur=a,b
        while True:
            route.append(cur)
            if len(graph[cur])!=2:break
            nxt=next(iter(graph[cur]-{prev}))
            if edge(cur,nxt) in used:break
            used.add(edge(cur,nxt));prev,cur=cur,nxt
        return route
    for i,adj in enumerate(graph):
        if len(adj)==2:continue
        for j in sorted(adj):
            if edge(i,j) not in used:routes.append(walk(i,j))
    for i,adj in enumerate(graph):
        for j in sorted(adj):
            if edge(i,j) not in used:routes.append(walk(i,j))
    strokes=[]
    for route in routes:
        z=np.array([complex(coords[i][1],coords[i][0]) for i in route])
        if len(z)<3 or abs(np.diff(z)).sum()<min_stroke:continue
        # Subpixel smoothing removes the bitmap staircase without changing the drawing.
        closed=abs(z[0]-z[-1])<1.5
        mode='wrap' if closed else 'nearest'
        sm=(ndimage.gaussian_filter1d(z.real,smoothing,mode=mode)+1j*ndimage.gaussian_filter1d(z.imag,smoothing,mode=mode)) if smoothing>0 else z.copy()
        if closed:sm[-1]=sm[0]
        else:sm[0]=z[0];sm[-1]=z[-1]
        sm=simplify(sm,tolerance)
        if len(sm)>=2:strokes.append(sm)
    return strokes


def edge_mask(gray,detail='medium',sigma_override=0,quantile_override=0):
    """Gaussian gradients, subpixel nonmax suppression and hysteresis (Canny-style)."""
    sigma,quantile={'low':(2.1,.88),'medium':(1.5,.78),'high':(1.1,.65)}[detail]
    sigma=sigma_override or sigma;quantile=quantile_override or quantile
    image=ndimage.gaussian_filter(gray.astype(float)/255,sigma)
    gx=ndimage.sobel(image,axis=1)/8;gy=ndimage.sobel(image,axis=0)/8
    magnitude=np.hypot(gx,gy)
    yy,xx=np.indices(gray.shape,dtype=float)
    dx=gx/np.maximum(magnitude,1e-12);dy=gy/np.maximum(magnitude,1e-12)
    ahead=ndimage.map_coordinates(magnitude,[yy+dy,xx+dx],order=1,mode='nearest')
    behind=ndimage.map_coordinates(magnitude,[yy-dy,xx-dx],order=1,mode='nearest')
    maxima=(magnitude>=ahead)&(magnitude>=behind)&(magnitude>.006)
    positive=magnitude[maxima]
    if not len(positive):return np.zeros(gray.shape,dtype=bool)
    high=float(np.quantile(positive,quantile));low=high*.40
    strong=maxima&(magnitude>=high);weak=maxima&(magnitude>=low)
    return ndimage.binary_propagation(strong,mask=weak)


def outline_strokes(mask,min_stroke=3,smoothing=.65,tolerance=.35):
    """Trace oriented pixel-cell boundaries, including interior holes.

    Edges keep ink on their right. At diagonal contacts, right turns keep the
    two regions separate; no thinning of filled silhouettes into stick figures.
    """
    padded=np.pad(mask,1);h,w=mask.shape
    boundaries=[mask&~padded[:-2,1:-1],mask&~padded[1:-1,2:],
                mask&~padded[2:,1:-1],mask&~padded[1:-1,:-2]]
    graph={}
    for direction,boundary in enumerate(boundaries):
        yy,xx=np.where(boundary)
        for y,x in zip(yy.tolist(),xx.tolist()):
            corners=[(x,y),(x+1,y),(x+1,y+1),(x,y+1)]
            a,b=corners[direction],corners[(direction+1)%4]
            graph.setdefault(a,[]).append((b,direction))
    strokes=[]
    while graph:
        start=next(iter(graph));cur=start;direction=None;route=[complex(*start)]
        while cur in graph:
            candidates=graph[cur]
            index=0 if direction is None else min(range(len(candidates)),key=lambda j:({1:0,0:1,3:2,2:3}[(candidates[j][1]-direction)%4]))
            nxt,direction=candidates.pop(index)
            if not candidates:del graph[cur]
            route.append(complex(*nxt));cur=nxt
            if cur==start:break
        z=np.array(route)
        if len(z)<4 or abs(np.diff(z)).sum()<min_stroke:continue
        closed=z[-1]==z[0]
        if smoothing>0:
            body=z[:-1] if closed else z
            body=ndimage.gaussian_filter1d(body.real,smoothing,mode='wrap' if closed else 'nearest')+1j*ndimage.gaussian_filter1d(body.imag,smoothing,mode='wrap' if closed else 'nearest')
            z=np.r_[body,body[0]] if closed else body
        z=simplify(z,tolerance)
        if len(z)>=3:strokes.append(z)
    return strokes


# Extraction settings are shared by preview, CLI and exported videos.
DEFAULT_TRACE={
    'threshold_method':'auto','threshold':180,'polarity':'auto','adaptive_offset':8.,
    'max_size':1800,'min_component':4,'min_stroke':3.,'smoothing':.65,'simplify':.35,
    'gap_close':0,'edge_sigma':0.,'edge_quantile':0.,'max_strokes':0,
    'preserve_accents':True,'exclude_regions':[],
}


TRACE_PRESETS={
    'Automatique · préserver les détails':('auto','medium',{}),
    'Portrait / dessin au trait':('lineart','high',{'min_component':3,'min_stroke':2.,'smoothing':.5,'simplify':.2}),
    'Silhouette / logo plein':('outline','high',{'min_component':4,'min_stroke':2.,'smoothing':.35,'simplify':.25,'preserve_accents':False}),
    'Photo · détails fins':('edges','high',{'min_component':4,'min_stroke':3.,'max_strokes':0,'max_size':1600}),
    'Ancien tracé · seuil 180':('lineart','medium',{'threshold_method':'global','threshold':180,'min_component':16,'min_stroke':6.,'smoothing':1.,'simplify':.55}),
}


def trace_settings(value=None):
    from copy import deepcopy
    if value is not None and not isinstance(value,dict):raise ValueError('trace doit être un objet JSON.')
    value=value or {};unknown=set(value)-set(DEFAULT_TRACE)
    if unknown:raise ValueError('Réglages de détection inconnus : '+', '.join(sorted(unknown)))
    c={**deepcopy(DEFAULT_TRACE),**deepcopy(value)}
    for key,allowed in [('threshold_method',{'auto','global','adaptive'}),('polarity',{'auto','dark','light'})]:
        if c[key] not in allowed:raise ValueError('Valeur incorrecte pour trace.'+key)
    for key,low,high,integer in [('threshold',1,254,True),('adaptive_offset',0,40,False),
            ('max_size',256,4096,True),('min_component',1,1000,True),('min_stroke',0,100,False),
            ('smoothing',0,3,False),('simplify',0,5,False),('gap_close',0,3,True),
            ('edge_sigma',0,5,False),('edge_quantile',0,.99,False),('max_strokes',0,10000,True)]:
        v=c[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or not low<=v<=high or (integer and type(v) is not int):
            raise ValueError(f'trace.{key} : valeur entre {low} et {high}'+(' (entier).' if integer else '.'))
    if type(c['preserve_accents']) is not bool:raise ValueError('trace.preserve_accents doit être vrai ou faux.')
    if not isinstance(c['exclude_regions'],list) or len(c['exclude_regions'])>100:raise ValueError('Au plus 100 zones à ignorer.')
    for box in c['exclude_regions']:
        if not isinstance(box,list) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not np.isfinite(v) or not 0<=v<=1 for v in box) or not(box[0]<box[2] and box[1]<box[3]):
            raise ValueError('Chaque zone ignorée doit être [gauche, haut, droite, bas], entre 0 et 1.')
    return c


def open_raster(file,max_size=1800):
    with Image.open(file) as original:im=ImageOps.exif_transpose(original).convert('RGBA')
    rgba=np.array(im);visible=rgba[:,:,3]>128
    light=visible.any() and np.mean(rgba[:,:,:3][visible])>170 and not visible.all()
    bg=Image.new('RGBA',im.size,'black' if light else 'white')
    im=Image.alpha_composite(bg,im).convert('RGB')
    im.thumbnail((max_size,max_size),Image.Resampling.LANCZOS)
    return im


def otsu_threshold(gray):
    hist=np.bincount(gray.ravel(),minlength=256).astype(float)
    weight=np.cumsum(hist);moment=np.cumsum(hist*np.arange(256));den=weight*(weight[-1]-weight)
    score=np.divide((moment[-1]*weight-moment*weight[-1])**2,den,out=np.zeros(256),where=den>0)
    return int(np.argmax(score))+1


def detect_mode(gray):
    middle=float(np.mean((gray>35)&(gray<220)));white=float(np.mean(gray>220));black=float(np.mean(gray<35))
    # Antialiased/grey pencil strokes on mostly blank paper are still line art.
    # A global fraction of intermediate pixels alone misclassifies blurred scans.
    threshold=otsu_threshold(gray);foreground=float(np.mean(gray<min(210,threshold)))
    lineart=(middle<.09 and white>.001 and black>.001) or (white>.65 and .0002<foreground<.28 and threshold<215)
    return ('lineart' if lineart else 'edges'),{'intermediate_fraction':round(middle,4),
        'light_fraction':round(white,4),'dark_fraction':round(black,4),'otsu_threshold':threshold}


def trace(input_file,output_file,threshold=None,min_component=None,mode='lineart',detail='medium',options=None):
    """One extraction path for all entry points; filtering is explicit and reported."""
    c=trace_settings(options)
    if threshold is not None:c.update(threshold=threshold,threshold_method='global')
    if min_component is not None:c['min_component']=min_component
    c=trace_settings(c)
    if mode not in {'auto','lineart','outline','edges'} or detail not in {'low','medium','high'}:raise ValueError('Mode ou niveau de détails inconnu.')
    im=open_raster(input_file,c['max_size']);gray=np.asarray(im.convert('L'))
    automatic,analysis=detect_mode(gray);requested=mode
    if mode=='auto':mode=automatic
    if c['polarity']=='light' or (c['polarity']=='auto' and np.median(np.r_[gray[0],gray[-1],gray[:,0],gray[:,-1]])<128):gray=255-gray
    effective_threshold=c['threshold'];method=c['threshold_method']
    if mode=='edges':ink=edge_mask(gray,detail,c['edge_sigma'],c['edge_quantile'])
    else:
        if method=='auto':
            # Otsu adapts to pale strokes instead of imposing a hard-coded 180.
            effective_threshold=max(32,min(245,otsu_threshold(gray)))
            ink=gray<effective_threshold
        elif method=='adaptive':
            background=ndimage.gaussian_filter(gray.astype(float),sigma=max(8,min(gray.shape)/35))
            ink=gray.astype(float)<background-c['adaptive_offset']
        else:ink=gray<effective_threshold
    if c['gap_close']:ink=ndimage.binary_closing(ink,iterations=c['gap_close'])
    for left,top,right,bottom in c['exclude_regions']:
        ink[int(top*ink.shape[0]):int(np.ceil(bottom*ink.shape[0])),int(left*ink.shape[1]):int(np.ceil(right*ink.shape[1]))]=False
    labels,n=ndimage.label(ink,np.ones((3,3)));sizes=np.bincount(labels.ravel());sizes[0]=0
    removed_components=int(np.count_nonzero((sizes>0)&(sizes<c['min_component'])))
    ink=sizes[labels]>=c['min_component']
    distance=None
    if requested=='auto' and mode=='lineart' and ink.mean()>.12:
        distance=ndimage.distance_transform_edt(ink);widths=distance[ink]
        if len(widths) and np.quantile(widths,.75)>3:mode='outline'
    skeleton=np.zeros_like(ink) if mode=='outline' else thin(ink)
    strokes=(outline_strokes(ink,c['min_stroke'],c['smoothing'],c['simplify']) if mode=='outline'
             else extract_strokes(skeleton,c['min_stroke'],c['smoothing'],c['simplify']))
    accent_count=0
    if c['preserve_accents'] and mode=='lineart':
        # Large filled areas and tiny isolated pupils both collapse under thinning.
        distance=ndimage.distance_transform_edt(ink)
        peaks=(distance==ndimage.maximum_filter(distance,size=21))&(distance>=8)
        peak_labels,large_count=ndimage.label(peaks,np.ones((3,3)))
        centers=[]
        for label in range(1,large_count+1):
            yy,xx=np.where(peak_labels==label);j=int(np.argmax(distance[yy,xx]));centers.append((xx[j],yy[j],distance[yy[j],xx[j]]))
        compact_labels,compact_count=ndimage.label(ink,np.ones((3,3)))
        for label,box in enumerate(ndimage.find_objects(compact_labels),1):
            if box is None:continue
            sy,sx=box;h,w=sy.stop-sy.start,sx.stop-sx.start
            if max(h,w)>20 or max(h,w)>2*max(1,min(h,w)):continue
            region=compact_labels[box]==label
            if np.count_nonzero(skeleton[box]&region)>2:continue
            local=np.where(region,distance[box],0);y,x=np.unravel_index(np.argmax(local),local.shape)
            if local[y,x]>=1 and sizes[labels[sy.start+y,sx.start+x]]>=c['min_component']:
                centers.append((sx.start+x,sy.start+y,local[y,x]))
        for x,y,radius in centers:
            u=np.linspace(0,1,80);r=radius*.72*(1-u)
            strokes.append(x+1j*y+r*np.exp(1j*(6*np.pi*u-np.pi/2)))
        accent_count=len(centers)
    extracted=len(strokes)
    if c['max_strokes'] and len(strokes)>c['max_strokes']:
        strokes=sorted(strokes,key=lambda z:float(abs(np.diff(z)).sum()),reverse=True)[:c['max_strokes']]
    if not strokes:raise ValueError('Aucun trait détecté. Essayer Dessin au trait, le seuil manuel ou réduire le filtre des petits détails.')
    svg=ET.Element('svg',xmlns='http://www.w3.org/2000/svg',viewBox=f'0 0 {im.width} {im.height}')
    ET.SubElement(svg,'title').text='Centerline strokes extracted locally by ORBITE Studio'
    for i,z in enumerate(strokes):
        d='M '+' L '.join(f'{v.real:.3f},{v.imag:.3f}' for v in z)
        if abs(z[0]-z[-1])<.1:d+=' Z'
        ET.SubElement(svg,'path',id=f'stroke_{i:03d}',d=d,fill='none',stroke='black',
                      attrib={'stroke-width':'1.4','stroke-linecap':'round','stroke-linejoin':'round'})
    output_file=Path(output_file);output_file.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(svg).write(output_file,encoding='utf-8',xml_declaration=True)
    warnings=[]
    if extracted>len(strokes):warnings.append(f'{extracted-len(strokes)} traits supprimés par la limite manuelle ; mettre 0 pour tout conserver.')
    if len(strokes)>600:warnings.append('Beaucoup de traits : vérifier le bruit et prévoir plus de cercles pour les détails.')
    report={'input':str(input_file),'output':str(output_file),'size':list(im.size),
            'strokes':len(strokes),'skeleton_pixels':int(skeleton.sum()),
            'vector_vertices':sum(len(s) for s in strokes),'filled_accents':accent_count,'threshold':effective_threshold,
            'threshold_method':method,'requested_mode':requested,'mode':mode,'detail':detail,
            'extracted_strokes':extracted,'removed_components':removed_components,
            'settings':c,'analysis':analysis,'warnings':warnings}
    output_file.with_suffix('.trace.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def detection_preview(source,vector,report,view='Tracé détecté'):
    """Diagnostic sheet, before Fourier; image_box supports manual exclusion zones."""
    from PIL import ImageDraw
    from svgpathtools import svg2paths
    source_image=open_raster(source);size=source_image.size
    if view=='Source':return diagnostic_sheet(source_image)
    strokes=Image.new('RGB',tuple(report['size']) if report else size,'white');draw=ImageDraw.Draw(strokes)
    for path in svg2paths(str(vector))[0]:
        for segment in path:
            draw.line([(segment.start.real,segment.start.imag),(segment.end.real,segment.end.imag)],fill='#152441',width=2)
    if strokes.size!=size:strokes=strokes.resize(size,Image.Resampling.LANCZOS)
    image=source_image.copy() if view=='Source' else strokes
    if view=='Comparaison source / traits':
        image=source_image.copy();ink=np.asarray(strokes).min(axis=2)<160
        pixels=np.array(image);pixels[ink]=[20,165,210];image=Image.fromarray(pixels)
    return diagnostic_sheet(image)


def diagnostic_sheet(image):
    result=Image.new('RGB',(360,640),'#e9eef4');fitted=ImageOps.contain(image,(336,520),Image.Resampling.LANCZOS)
    x=(360-fitted.width)//2;y=(640-fitted.height)//2
    result.paste(fitted,(x,y));result.info['image_box']=[x,y,x+fitted.width,y+fitted.height]
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image');p.add_argument('--output',required=True)
    p.add_argument('--threshold',type=int)
    p.add_argument('--mode',choices=['auto','lineart','outline','edges'],default='auto')
    p.add_argument('--detail',choices=['low','medium','high'],default='medium')
    p.add_argument('--settings',help='Fichier JSON des réglages de détection')
    args=p.parse_args()
    options=json.loads(Path(args.settings).read_text()) if args.settings else None
    print(json.dumps(trace(args.image,args.output,args.threshold,mode=args.mode,detail=args.detail,options=options),ensure_ascii=False,indent=2))

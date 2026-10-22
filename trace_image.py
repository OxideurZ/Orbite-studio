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


def extract_strokes(skeleton):
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
            if len(route)<=3 and len(graph[cur])>2:remove.extend(route)
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
        if len(z)<3 or abs(np.diff(z)).sum()<6:continue
        # Subpixel smoothing removes the bitmap staircase without changing the drawing.
        closed=abs(z[0]-z[-1])<1.5
        mode='wrap' if closed else 'nearest'
        sm=ndimage.gaussian_filter1d(z.real,1,mode=mode)+1j*ndimage.gaussian_filter1d(z.imag,1,mode=mode)
        if closed:sm[-1]=sm[0]
        else:sm[0]=z[0];sm[-1]=z[-1]
        sm=simplify(sm)
        if len(sm)>=2:strokes.append(sm)
    return strokes


def edge_mask(gray,detail='medium'):
    """Gaussian gradients, subpixel nonmax suppression and hysteresis (Canny-style)."""
    sigma,quantile={'low':(2.1,.88),'medium':(1.5,.78),'high':(1.1,.65)}[detail]
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


def trace(input_file,output_file,threshold=180,min_component=16,mode='lineart',detail='medium'):
    im=ImageOps.exif_transpose(Image.open(input_file)).convert('RGBA')
    # Transparent logos retain contrast, including white logos on transparent pixels.
    rgba=np.array(im);visible=rgba[:,:,3]>128
    light=visible.any() and np.mean(rgba[:,:,:3][visible])>170 and not visible.all()
    bg=Image.new('RGBA',im.size,'black' if light else 'white')
    im=Image.alpha_composite(bg,im).convert('L')
    # Bound raster cost while preserving fine portrait detail.
    im.thumbnail((1800,1800),Image.Resampling.LANCZOS)
    gray=np.array(im)
    if mode=='auto':
        middle=float(np.mean((gray>35)&(gray<220)))
        has_ink=np.mean(gray<35)>.001 and np.mean(gray>220)>.001
        mode='lineart' if middle<.09 and has_ink else 'edges'
    if mode=='edges':
        im.thumbnail((960,960),Image.Resampling.LANCZOS);gray=np.array(im)
        ink=edge_mask(gray,detail)
    else:
        border=np.r_[gray[0],gray[-1],gray[:,0],gray[:,-1]]
        if np.median(border)<128:gray=255-gray
        ink=gray<threshold
    labels,n=ndimage.label(ink,np.ones((3,3)))
    sizes=np.bincount(labels.ravel());sizes[0]=0
    ink=sizes[labels]>=min_component
    skeleton=thin(ink)
    strokes=extract_strokes(skeleton)
    # Compact filled accents (for instance, pupils) disappear under pure thinning.
    # Preserve their visual weight as a short inward spiral, still a pen trajectory.
    distance=ndimage.distance_transform_edt(ink)
    peaks=(distance==ndimage.maximum_filter(distance,size=21))&(distance>=8)&(mode=='lineart')
    labels,accent_count=ndimage.label(peaks,np.ones((3,3)))
    for label in range(1,accent_count+1):
        yy,xx=np.where(labels==label)
        j=int(np.argmax(distance[yy,xx]));x,y=xx[j],yy[j]
        u=np.linspace(0,1,120)
        radius=distance[y,x]*.72*(1-u)
        strokes.append(x+1j*y+radius*np.exp(1j*(6*np.pi*u-np.pi/2)))
    extracted=len(strokes)
    if mode=='edges':
        limit={'low':80,'medium':180,'high':320}[detail]
        strokes=sorted(strokes,key=lambda z:float(abs(np.diff(z)).sum()),reverse=True)[:limit]
    if not strokes:raise ValueError('No usable strokes found. Try another mode or a clearer image.')
    svg=ET.Element('svg',xmlns='http://www.w3.org/2000/svg',viewBox=f'0 0 {im.width} {im.height}')
    ET.SubElement(svg,'title').text='Centerline strokes extracted from user-provided line art'
    for i,z in enumerate(strokes):
        d='M '+' L '.join(f'{v.real:.3f},{v.imag:.3f}' for v in z)
        if abs(z[0]-z[-1])<.1:d+=' Z'
        ET.SubElement(svg,'path',id=f'stroke_{i:03d}',d=d,fill='none',stroke='black',
                      attrib={'stroke-width':'1.4','stroke-linecap':'round','stroke-linejoin':'round'})
    output_file=Path(output_file);output_file.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(svg).write(output_file,encoding='utf-8',xml_declaration=True)
    report={'input':str(input_file),'output':str(output_file),'size':list(im.size),
            'strokes':len(strokes),'skeleton_pixels':int(skeleton.sum()),
            'vector_vertices':sum(len(s) for s in strokes),'filled_accents':accent_count,'threshold':threshold,
            'mode':mode,'detail':detail,'extracted_strokes':extracted}
    output_file.with_suffix('.trace.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image');p.add_argument('--output',required=True)
    p.add_argument('--threshold',type=int,default=180)
    p.add_argument('--mode',choices=['auto','lineart','edges'],default='auto')
    p.add_argument('--detail',choices=['low','medium','high'],default='medium')
    args=p.parse_args()
    print(json.dumps(trace(args.image,args.output,args.threshold,mode=args.mode,detail=args.detail),ensure_ascii=False,indent=2))

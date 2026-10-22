"""Shared-scale circle composition and centered subject fitting in logical pixels."""
import numpy as np


def value_bounds(values,pen=None):
    values=np.asarray(values)
    if pen is not None and np.any(pen):values=values[pen]
    return np.array([values.real.min(),values.imag.min(),values.real.max(),values.imag.max()],float)


def union_bounds(boxes):
    a=np.array(boxes);return np.r_[a[:,:2].min(axis=0),a[:,2:].max(axis=0)]


def fit_bounds(bounds,box,padding=20):
    x0,y0,x1,y1=bounds;left,top,right,bottom=box
    scale=min((right-left-2*padding)/max(x1-x0,1e-9),(bottom-top-2*padding)/max(y1-y0,1e-9))
    center=np.array([(left+right)/2,(top+bottom)/2])-scale*np.array([(x0+x1)/2,(y0+y1)/2])
    return {'center':center.tolist(),'scale':float(scale),'box':list(box),'padding':padding}


def chain_bounds(coeff,count,rotation=0,phases=1024,explicit_terms=128):
    """Conservative bound of EVERY prefix circle at EVERY phase.

    Low terms are sampled with an analytic Lipschitz remainder between samples.
    The unsampled high-frequency tail is bounded by the sum of its radii.
    This is a bound for the configured finite series, not a convergence claim
    for arbitrary infinite Fourier series.
    """
    r=2*abs(coeff[1:count+1]);m=min(count,explicit_terms)
    ns=np.arange(1,m+1);ts=np.arange(phases)/phases
    v=r[:m,None]*np.exp(1j*(2*np.pi*ns[:,None]*ts+np.angle(coeff[1:m+1,None])+rotation))
    starts=np.vstack([np.zeros((1,phases),complex),np.cumsum(v,axis=0)])
    dc=coeff[0].real*np.exp(1j*rotation);starts+=dc
    # Every phase is at most half a grid step from one of these samples.
    error=np.r_[0,np.cumsum(np.minimum(2*r[:m],np.pi*ns*r[:m]/phases))]
    a=starts[:-1];margin=r[:m]+error[:-1]
    low=np.array([(a.real-margin[:,None]).min(),(a.imag-margin[:,None]).min(),
                  (a.real+margin[:,None]).max(),(a.imag+margin[:,None]).max()])
    tail=float(r[m:].sum())+error[-1]
    endpoint=starts[-1]
    high=[endpoint.real.min()-tail,endpoint.imag.min()-tail,endpoint.real.max()+tail,endpoint.imag.max()+tail]
    return union_bounds([low,high])


def adaptive_composition(z,pen,approximations,cx,cy,count,geometry):
    """Original shared-scale composition: horizontal/vertical straight projections.

    A common display unit is essential: X circles end at the pencil's x and Y
    circles end at its y. Preserve this geometry rather than enlarging the drawing
    independently, which would require distracting elbow connectors.
    """
    center=list(geometry['center'])
    def panel(coeff,rotation,translation):
        b=chain_bounds(coeff,count,rotation)+np.tile(translation,2)
        return {'center':list(translation),'scale':1.,'box':b.tolist(),'padding':0}
    return {'landscape':False,'drawing':{'center':center,'scale':1.,
                'box':[365,805,1010,1460],'padding':0},
            'x':panel(cx,0,[center[0],geometry['x_root_y']]),
            'y':panel(cy,np.pi/2,[geometry['y_root_x'],center[1]])}

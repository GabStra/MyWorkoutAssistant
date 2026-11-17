from __future__ import annotations

import numpy as np


UNIFORM_CAPSULE_RADIUS = 0.046


def support_surface_height(joint_height: float) -> float:
    """Return the lowest rendered surface for a support joint on a Y-up plane."""
    return float(joint_height) - UNIFORM_CAPSULE_RADIUS


def support_joint_height_for_surface(surface_height: float) -> float:
    return float(surface_height) + UNIFORM_CAPSULE_RADIUS

def knee_support_region(points, names, joint, *, lengths=None, side_axes=None, body_axes=None):
    """Native wearSphere cap and the two incident wearSegment end rings.

    Coefficients mirror wear_exact_mesh.js and buildSingleLowPolyMesh; only the
    anatomical knee region is returned, not a capsule or an invented pad.
    """
    side = joint.split('_', 1)[0]
    hip, knee, ankle = [points[:, names.index(side+'_'+n)] for n in ('hip','knee','ankle')]
    unit = lambda a: a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    lateral = unit(points[:, names.index('right_hip')]-points[:, names.index('left_hip')])
    up = unit(points[:, names.index('neck')]-points[:, names.index('pelvis')])
    forward = unit(np.cross(lateral, up))
    if body_axes is not None:
        lateral, up, forward = np.moveaxis(np.asarray(body_axes), 1, 0)
    thigh, shin = knee-hip, ankle-knee
    thigh_length, shin_length = (float(v) for v in lengths) if lengths is not None else (np.linalg.norm(thigh[0]), np.linalg.norm(shin[0]))
    radius = max(thigh_length*.215, shin_length*.225)*.40
    cap = [knee-radius*up, knee+radius*up]
    for height in (-.5,.5):
        for angle in np.arange(8)*np.pi/4:
            cap.append(knee+radius*(height*up+.866*np.cos(angle)*lateral+.866*np.sin(angle)*forward))
    result = list(cap)
    for direction, length, width, depth_scale, sign in ((unit(thigh),thigh_length,thigh_length*.215,.46,-1), (unit(shin),shin_length,shin_length*.225,.44,1)):
        center = knee+sign*direction*min(width*.08,length*.15)
        preferred = side_axes if side_axes is not None else np.cross(unit(thigh),unit(shin))
        axis = unit(preferred-direction*np.sum(preferred*direction,axis=1)[:,None])
        fallback = unit(lateral-direction*np.sum(lateral*direction,axis=1)[:,None])
        axis = np.where((np.linalg.norm(axis,axis=1)<1e-8)[:,None],fallback,axis)
        depth = unit(np.cross(axis,direction))
        corners = [center+sx*axis*width*.5+sz*depth*width*depth_scale for sx,sz in ((1,1),(-1,1),(-1,-1),(1,-1))]
        for i,corner in enumerate(corners):
            result.extend((.7*corner+.3*corners[(i-1)%4], .7*corner+.3*corners[(i+1)%4]))
    return np.stack(result,axis=1)


def material_body_axes(points, names):
    """Native wearBuildStableBodyAxesByFrame's seven-frame weighted axes."""
    unit = lambda a: a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    side = unit(points[:, names.index('right_hip')]-points[:, names.index('left_hip')])
    up = unit(points[:, names.index('neck')]-points[:, names.index('pelvis')])
    result = []
    for i in range(len(points)):
        indexes = np.arange(max(0,i-3),min(len(points),i+4))
        weights = (4-abs(indexes-i))[:,None]
        align = lambda a: a[indexes]*np.where((a[indexes]@a[i])[:,None]<0,-weights,weights)
        stable_up = unit(align(up).sum(axis=0))
        stable_side = align(side).sum(axis=0)
        stable_side = unit(stable_side-stable_up*np.dot(stable_side,stable_up))
        result.append([stable_side,stable_up,unit(np.cross(stable_side,stable_up))])
    return np.asarray(result)


def upper_back_material_binding(points, names):
    """Native first-valid-frame dimensions; independent of later contact poses."""
    for row in np.asarray(points):
        at = lambda name: row[names.index(name)]
        hip = np.linalg.norm(at('right_hip')-at('left_hip'))
        shoulder = np.linalg.norm(at('right_shoulder')-at('left_shoulder'))
        if hip > .0001 and shoulder > .0001:
            return {'shoulderWidth': float(shoulder), 'upperArmLengths': [
                float(np.linalg.norm(at(side+'_elbow')-at(side+'_shoulder')))
                for side in ('left', 'right')]}
    raise ValueError('Native upper-back material dimensions unavailable')


def upper_back_material_quads(points, names, *, binding=None, body_axes=None, _return_components=False):
    """Exact wearSmoothTorsoTube posterior quads, with a moving contact region.

    Returns (frames, 15, 4, 3), not one fixed scapular contact point. Native
    rounded-ring corners 4..7 are posterior; the surface spans chest through
    upperBackRing and shoulder/trapezius transitions. No mesh/style changes.
    ``body_axes`` may supply the full-context seven-frame native axes when
    evaluating only a subset; ``binding`` retains the original clip dimensions.
    """
    points = np.asarray(points, dtype=float)
    binding = upper_back_material_binding(points, names) if binding is None else binding
    axes = material_body_axes(points, names) if body_axes is None else np.asarray(body_axes)
    at = lambda name: points[:, names.index(name)]
    def unit(value, fallback):
        length2 = np.sum(value*value, axis=-1, keepdims=True)
        return np.where(length2 > 1e-8, value/np.sqrt(np.maximum(length2, 1e-30)), fallback)
    def dot(a, b):
        return np.sum(a*b, axis=-1, keepdims=True)
    def ring_axes(previous, center, following, reference):
        tangent = unit(following-previous, unit(following-center, reference[1]))
        side = unit(reference[0]-tangent*dot(reference[0], tangent), reference[0])
        side = np.where(dot(side, reference[0]) < 0, -side, side)
        return side, tangent, unit(np.cross(side, tangent), reference[2])
    side, up, forward = np.moveaxis(axes, 1, 0)
    sw = binding['shoulderWidth']
    arm_lengths = np.asarray(binding['upperArmLengths'])
    # wearBuildHumanoid's display shoulder offset leaves saved joints intact.
    shoulder_offset = unit(at('left_shoulder')-at('right_shoulder'), -side)*sw*.075
    left = at('left_shoulder')+shoulder_offset
    right = at('right_shoulder')-shoulder_offset
    hip = (at('left_hip')+at('right_hip'))*.5
    torso_up = unit(at('neck')-hip, up)
    source_waist = at('spine1') if 'spine1' in names else hip+(at('neck')-hip)*.40
    source_chest = at('spine2') if 'spine2' in names else source_waist*.55+at('neck')*.45
    source_upper = at('spine3') if 'spine3' in names else source_chest*.65+at('neck')*.35
    waist = source_waist*.5+(hip+source_chest)*.25
    chest = source_chest*.5+(source_waist+source_upper)*.25
    upper = source_upper*.5+(source_chest+at('neck'))*.25
    shoulder_side = unit(left-right, -side)
    native_shoulder_side = shoulder_side.copy()
    shoulder_up = unit(at('neck')-source_upper-shoulder_side*dot(at('neck')-source_upper, shoulder_side), torso_up)
    shoulder_forward = unit(np.cross(shoulder_side, shoulder_up), -forward)
    shoulder_radius = float(np.mean(arm_lengths))*.30*.44
    upper_chest = (left+right)*.5+shoulder_up*shoulder_radius*.35
    neck_length = np.minimum(sw*.10, np.maximum(dot(at('neck')-upper_chest, shoulder_up)*.55, sw*.05))
    transition = at('neck')-shoulder_up*neck_length
    pelvis_up = unit(waist-hip, torso_up)
    hip_side = at('left_hip')-at('right_hip')
    pelvis_side = unit(hip_side-pelvis_up*dot(hip_side, pelvis_up), -side)
    pelvis_axes = pelvis_side, pelvis_up, unit(np.cross(pelvis_side, pelvis_up), -forward)
    waist_axes = ring_axes(hip, waist, chest, pelvis_axes)
    chest_axes = ring_axes(waist, chest, upper, waist_axes)
    upper_axes = ring_axes(chest, upper, upper_chest, chest_axes)
    shoulder_side = np.where(dot(shoulder_side, upper_axes[0]) < 0, -shoulder_side, shoulder_side)
    shoulder_axes = shoulder_side, shoulder_up, unit(np.cross(shoulder_side, shoulder_up), shoulder_forward)
    def ring(center, frame, half_width, front_depth, back_depth, back_width_scale=1., *, rounded=True):
        outline = np.asarray([[.94,.34],[.15,.99],[-.15,.99],[-.94,.34],
                              [-.94,-.34],[-.15,-.99],[.15,-.99],[.94,-.34]] if rounded else
                             [[1.,.24],[.24,1.],[-.24,1.],[-1.,.24],
                              [-1.,-.24],[-.24,-1.],[.24,-1.],[1.,-.24]])
        widths = np.broadcast_to(np.asarray(half_width), (len(points), 1))
        width = widths*outline[:,0]*np.where(outline[:,1] < 0, max(1.,back_width_scale), 1.)
        depth = outline[:,1]*np.where(outline[:,1] < 0, back_depth, front_depth)
        return center[:,None]+frame[0][:,None]*width[:,:,None]+frame[2][:,None]*depth[None,:,None]
    wr = ring(waist+waist_axes[2]*sw*.012, waist_axes, sw*1.15*.295, sw*.165, sw*.1752)
    cr = ring(chest+chest_axes[2]*sw*.02, chest_axes, sw*1.15*.38, sw*.21, sw*.255*.88, 1.07)
    br = ring(upper, upper_axes, sw*1.15*.44, sw*.26, sw*.255)
    upper_center = upper_chest+shoulder_axes[2]*(dot(at('neck')-upper_chest, shoulder_axes[2])-(sw*.24-sw*.255*.86)*.495)
    cap = arm_lengths*.30*.44*.90
    half_width = np.maximum(np.linalg.norm(left-right, axis=1, keepdims=True)*.5-(cap.sum())*.30, .001)
    sr = ring(upper_center, shoulder_axes, half_width, sw*.24, sw*.255*.86)
    for corner in (0,3,4,7):
        positive = corner in (0,7)
        center, radius = (left,cap[0]) if positive else (right,cap[1])
        sr[:,corner] = center+shoulder_axes[0]*((-1 if positive else 1)*radius*.45)+shoulder_axes[2]*((1 if corner<4 else -1)*radius*.40)+shoulder_up*radius*.25
    tr = ring(transition, shoulder_axes, sw*.12, sw*.09, sw*.09, rounded=False)
    rise = np.maximum(np.sum((tr-sr)*shoulder_up[:,None],axis=2,keepdims=True),0.)
    bias = shoulder_up[:,None]*np.maximum(rise*.35,sw*.05)+shoulder_axes[2][:,None]*np.where(np.arange(8)[None,:,None]>=4,-sw*.025,0.)
    traps = (sr+tr)*.5+bias*.5
    rounded = [(wr+cr)*.5,(cr+br)*.5,(br+sr)*.5,sr,(sr+traps)*.5,(traps+tr)*.5]
    posterior_quads = np.stack([np.stack([a[:,corner],b[:,corner],b[:,corner+1],a[:,corner+1]],axis=1)
                                for a,b in zip(rounded[:-1],rounded[1:]) for corner in (4,5,6)],axis=1)
    if not _return_components:
        return posterior_quads
    return {
        'posteriorQuads': posterior_quads, 'points': points, 'names': list(names),
        'axes': axes, 'binding': binding, 'side': side, 'up': up, 'forward': forward,
        'shoulderWidth': sw, 'armLengths': arm_lengths, 'leftShoulder': left,
        'rightShoulder': right, 'hipCenter': hip, 'sourceWaist': source_waist,
        'sourceChest': source_chest, 'sourceUpper': source_upper, 'waist': waist,
        'chest': chest, 'upper': upper, 'waistAxes': waist_axes,
        'chestAxes': chest_axes, 'upperAxes': upper_axes,
        'nativeShoulderSide': native_shoulder_side, 'shoulderUp': shoulder_up,
        'shoulderForward': shoulder_forward, 'shoulderAxes': shoulder_axes,
        'upperChest': upper_chest, 'transition': transition, 'pelvisAxes': pelvis_axes,
        'waistRing': wr, 'chestRing': cr, 'upperBackRing': br,
        'legacyShoulderRing': sr, 'upperTransitionRing': tr, 'legacyTrapeziusRing': traps,
    }


def native_torso_material_binding(points, names):
    """Bind native torso widths and hip-cap lengths to the first valid clip frame."""
    points = np.asarray(points, dtype=float)
    base = upper_back_material_binding(points, names)
    required = ('left_hip', 'right_hip', 'left_shoulder', 'right_shoulder')
    for row in points:
        at = lambda name: row[names.index(name)]
        hip_width = np.linalg.norm(at('right_hip')-at('left_hip'))
        shoulder_width = np.linalg.norm(at('right_shoulder')-at('left_shoulder'))
        if hip_width <= .0001 or shoulder_width <= .0001:
            continue
        return {**base, 'hipWidth': float(hip_width),
                'thighLengths': [float(np.linalg.norm(at(side+'_knee')-at(side+'_hip')))
                                 if side+'_knee' in names else 0.
                                 for side in ('left','right')]}
    raise ValueError('Native torso bind dimensions unavailable')


def native_torso_shell_geometry(points, names, *, binding=None, body_axes=None):
    """Return exact wearBuildHumanoid torso rings as a shared native mesh.

    The established upper-back observer and this whole shell share the native
    torso-ring construction. The returned mesh has 8-corner rings, the native
    rounded longitudinal strips, hip-socket edits, and underside fan.
    """
    points = np.asarray(points, dtype=float)
    names = list(names)
    if points.ndim != 3 or points.shape[1:] != (len(names), 3) or not np.isfinite(points).all():
        raise ValueError('torso points must be finite frames x jointNames x 3')
    required = ('pelvis','neck','left_hip','right_hip','left_shoulder','right_shoulder')
    if not all(name in names for name in required):
        raise ValueError('native torso mesh requires pelvis, neck, hips, and shoulders')
    bound = native_torso_material_binding(points, names) if binding is None else {
        **native_torso_material_binding(points, names), **binding}
    components = upper_back_material_quads(points, names, binding=bound,
        body_axes=body_axes, _return_components=True)
    at = lambda name: points[:, names.index(name)]
    axes = components['axes']
    side, up, forward = components['side'], components['up'], components['forward']
    sw = float(bound['shoulderWidth'])
    hip_width = float(bound['hipWidth'])
    thigh_lengths = np.asarray(bound['thighLengths'], dtype=float)
    arm_lengths = np.asarray(bound['upperArmLengths'], dtype=float)
    if (not np.isfinite([sw, hip_width]).all() or sw <= .0001 or hip_width <= .0001
            or thigh_lengths.shape != (2,) or arm_lengths.shape != (2,)
            or not np.isfinite(thigh_lengths).all() or not np.isfinite(arm_lengths).all()):
        raise ValueError('native torso clip bindings are malformed')
    def unit(value, fallback):
        norm = np.linalg.norm(value, axis=-1, keepdims=True)
        return np.where(norm > 1e-8, value/np.maximum(norm,1e-30), fallback)
    def dot(a,b):
        return np.sum(a*b,axis=-1,keepdims=True)
    def align(reference,candidate):
        candidate_side,candidate_up,candidate_forward=candidate
        candidate_side=np.where(dot(candidate_side,reference[0])<0,-candidate_side,candidate_side)
        return candidate_side,candidate_up,unit(np.cross(candidate_side,candidate_up),candidate_forward)
    def spine_axes(before,center,after,reference):
        tangent=unit(after-before,unit(after-center,reference[1]))
        ring_side=unit(reference[0]-tangent*dot(reference[0],tangent),reference[0])
        return ring_side,tangent,unit(np.cross(ring_side,tangent),reference[2])
    def rounded_ring(center,frame,half_width,front_depth,back_depth,back_width_scale=1.):
        outline=np.asarray([[.94,.34],[.15,.99],[-.15,.99],[-.94,.34],[-.94,-.34],[-.15,-.99],[.15,-.99],[.94,-.34]])
        width=np.asarray(half_width).reshape(-1,1)*outline[None,:,0]*np.where(outline[None,:,1]<0,max(1.,back_width_scale),1.)
        depth=outline[None,:,1]*np.where(outline[None,:,1]<0,back_depth,front_depth)
        return center[:,None,:]+frame[0][:,None,:]*width[:,:,None]+frame[2][:,None,:]*depth[:,:,None]
    def directional_ring(center,frame,half_width,front_depth,back_depth,*,corner_bevel=0.):
        side_axis,depth_axis=frame[0],frame[2]
        corners=np.stack([center+side_axis*half_width+depth_axis*front_depth,
                          center-side_axis*half_width+depth_axis*front_depth,
                          center-side_axis*half_width-depth_axis*back_depth,
                          center+side_axis*half_width-depth_axis*back_depth],axis=1)
        bevel=max(0.,min(.45,float(corner_bevel)))
        if bevel==0.:
            return corners
        return np.stack([corners[:,i]*(1.-bevel)+corners[:,(i-1)%4]*bevel
                         for i in range(4) for _ in (0,)],axis=1) if False else np.stack([
            point for i in range(4) for point in (
                corners[:,i]*(1.-bevel)+corners[:,(i-1)%4]*bevel,
                corners[:,i]*(1.-bevel)+corners[:,(i+1)%4]*bevel)],axis=1)
    def torso_ring(center,frame,half_width,half_depth,lat_width_scale,lat_depth_scale,erector_depth_scale,corner_bevel,back_tracker):
        lat_scale=max(1.,min(1.18,lat_width_scale))
        front_depth=max(half_depth*.85,min(half_depth*1.08,half_depth*(.90+lat_depth_scale*.08)))
        back_depth=max(half_depth*.86,min(half_depth*1.12,half_depth*(.92+erector_depth_scale*.04)))
        if back_tracker[0]>0:
            back_depth=max(back_depth,back_tracker[0])
        back_tracker[0]=max(back_tracker[0],back_depth)
        return directional_ring(center,frame,half_width*lat_scale,front_depth,back_depth,corner_bevel=corner_bevel)

    hip=components['hipCenter']; waist=components['waist']; chest=components['chest']; upper=components['upper']
    shoulder_center=(components['leftShoulder']+components['rightShoulder'])*.5
    shoulder_side=components['nativeShoulderSide']; shoulder_up=components['shoulderUp']; shoulder_forward=components['shoulderForward']
    pelvis_up=unit(waist-hip,unit(at('neck')-hip,up))
    hip_side=at('left_hip')-at('right_hip')
    pelvis_side=unit(hip_side-pelvis_up*dot(hip_side,pelvis_up),-side)
    pelvis_axes=(pelvis_side,pelvis_up,unit(np.cross(pelvis_side,pelvis_up),-forward))
    waist_axes=components['waistAxes']; chest_axes=components['chestAxes']
    upper_axes=components['upperAxes']
    shoulder_axes=(shoulder_side,shoulder_up,unit(np.cross(shoulder_side,shoulder_up),shoulder_forward))
    upper_chest_axes=align(chest_axes,shoulder_axes)
    pelvis_depth=max(hip_width*.36,sw*.18)
    display_shoulder_width=sw*1.15
    display_hip_width=max(hip_width*1.25,display_shoulder_width*.56)
    pelvis_width=max(display_hip_width*1.08,sw*.64)
    hip_cap_radius=max(thigh_lengths)*.27*.46*.90
    socket_half_width=max(display_hip_width*.50,np.linalg.norm(at('left_hip')-at('right_hip'))*.50+hip_cap_radius*.95)
    pelvis_top=hip+(waist-hip)*.52
    pelvis_mid=hip+(waist-hip)*.38
    pelvis_bottom=hip+pelvis_up*(-hip_cap_radius*.50)
    pelvis_junction=pelvis_top+pelvis_axes[2]*pelvis_width*.03
    tracker=[0.]
    pelvis_bottom_ring=torso_ring(pelvis_bottom+pelvis_axes[2]*(-pelvis_width*.015),pelvis_axes,
        socket_half_width*.40,pelvis_depth*.65,1.,.42,1.08,.44,tracker)
    pelvis_bottom_ring=pelvis_bottom_ring.copy()
    socket_extent=np.linalg.norm(at('left_hip')-at('right_hip'))*.5+hip_cap_radius*.65
    for corner in (0,3,4,7):
        offset=pelvis_bottom_ring[:,corner]-hip
        pelvis_bottom_ring[:,corner]+=pelvis_axes[0]*(np.sign(dot(offset,pelvis_axes[0]))[:,0]*socket_extent-dot(offset,pelvis_axes[0])[:,0])[:,None]
        pelvis_bottom_ring[:,corner]+=pelvis_axes[1]*(hip_cap_radius*.25-dot(offset,pelvis_axes[1])[:,0])[:,None]
    pelvis_mid_ring=torso_ring(pelvis_mid+pelvis_axes[2]*(-pelvis_width*.025),pelvis_axes,
        socket_half_width,max(pelvis_depth*1.25,hip_cap_radius*1.4),1.,.40,1.14,.38,tracker)
    waist_back_depth=sw*.1752
    pelvis_junction_ring=directional_ring(pelvis_junction,pelvis_axes,display_shoulder_width*.297,sw*.155,waist_back_depth*.95,corner_bevel=.38)
    waist_ring=components['waistRing']; chest_ring=components['chestRing']; back_ring=components['upperBackRing']
    upper_chest=components['upperChest']
    upper_chest_back_depth=sw*.255*.86
    upper_center_projection=dot(at('neck')-upper_chest,upper_chest_axes[2])[:,0]-(sw*.24-upper_chest_back_depth)*.495
    upper_center=upper_chest+upper_chest_axes[2]*upper_center_projection[:,None]
    cap=arm_lengths*.30*.44*.90
    half_width=np.maximum(np.linalg.norm(components['leftShoulder']-components['rightShoulder'],axis=1,keepdims=True)*.5-cap.sum()*.30,.001)
    upper_chest_ring=rounded_ring(upper_center,upper_chest_axes,half_width[:,0],sw*.24,upper_chest_back_depth)
    for corner in (0,3,4,7):
        positive=corner in (0,7); s='left' if positive else 'right'; radius=cap[0 if positive else 1]
        upper_chest_ring[:,corner]=components['leftShoulder' if positive else 'rightShoulder']+upper_chest_axes[0]*((-1 if positive else 1)*radius*.45)+upper_chest_axes[2]*((1 if corner<4 else -1)*radius*.40)+upper_chest_axes[1]*radius*.25
    transition=components['transition']
    upper_transition_ring=directional_ring(transition,upper_chest_axes,sw*.12,sw*.09,sw*.09,corner_bevel=.38)
    rise=np.maximum(np.sum((upper_transition_ring-upper_chest_ring)*shoulder_up[:,None,:],axis=2,keepdims=True),0.)
    bias=shoulder_up[:,None,:]*np.maximum(rise*.35,sw*.05)+upper_chest_axes[2][:,None,:]*np.where(np.arange(8)[None,:,None]>=4,-sw*.025,0.)
    trapezius_ring=(upper_chest_ring+upper_transition_ring)*.5+bias*.5
    neck_mid=transition+(at('neck')-transition)*.55
    neck_mid_axes=align(upper_chest_axes,spine_axes(transition,neck_mid,at('neck'),shoulder_axes))
    neck_mid_ring=directional_ring(neck_mid,neck_mid_axes,sw*.115,sw*.085,sw*.085,corner_bevel=.38)
    neck_upper_ring=directional_ring(at('neck'),neck_mid_axes,sw*.10,sw*.075,sw*.075,corner_bevel=.38)
    source_rings=[pelvis_bottom_ring,pelvis_mid_ring,pelvis_junction_ring,waist_ring,chest_ring,
                  back_ring,upper_chest_ring,trapezius_ring,upper_transition_ring,neck_mid_ring,neck_upper_ring]
    smooth=[source_rings[0]]
    for index,(lower,upper_ring) in enumerate(zip(source_rings[:-1],source_rings[1:])):
        smooth.append((lower+upper_ring)*.5)
        if index+1==6:
            smooth.append(upper_ring)
    smooth.append(source_rings[-1])
    frame_vertices=[]
    for fi in range(len(points)):
        frame_vertices.append(np.concatenate([*([ring[fi] for ring in smooth]),
            (pelvis_bottom[fi]-pelvis_axes[1][fi]*hip_cap_radius*.30-pelvis_axes[2][fi]*pelvis_width*.015)[None,:]],axis=0))
    quads=[]
    for ring_index in range(len(smooth)-1):
        lower=range(ring_index*8,(ring_index+1)*8); upper_ids=range((ring_index+1)*8,(ring_index+2)*8)
        for i in range(8):
            nxt=(i+1)%8; quads.append((i+ring_index*8,i+(ring_index+1)*8,nxt+(ring_index+1)*8,nxt+ring_index*8))
    underside_index=len(smooth)*8
    bottom_ring_index=0
    for i in range(8):
        quads.append((underside_index,bottom_ring_index*8+i,bottom_ring_index*8+(i+1)%8))
    triangles=[]
    for face in quads:
        if len(face)==3: triangles.append(face)
        else: triangles.extend(((face[0],face[1],face[2]),(face[0],face[2],face[3])))
    return {'vertices':np.asarray(frame_vertices,dtype=float),'triangles':np.asarray(triangles,dtype=np.int64),
            'ringNames':['pelvisJunction','pelvisMid','pelvisBottom','waist','chest','upperBack','upperChest','trapezius','upperTransition','neckMid','neckUpper'],
            'upperBackQuads':components['posteriorQuads']}

def leg_roll_closure_angle(last_side, first_side, last_axis, first_axis):
    from .foot_geometry import transport_sides
    last = transport_sides(last_side[None], last_axis[None], first_axis[None], first_side[None])[0]
    return np.arctan2(np.dot(first_axis, np.cross(last, first_side)), np.dot(last, first_side))


def material_leg_sides(frames, *, loopable=False):
    """Existing native knee-frame replay plus renderer loop-roll closure."""
    from .temporal_quality import rendered_leg_sides
    tracks = rendered_leg_sides(frames)
    if not loopable or len(tracks) < 2:
        return tracks
    for side in ('left', 'right'):
        for start,end in (('hip','knee'),('knee','ankle')):
            key = f'{side}_{start}->{side}_{end}'
            if not all(key in row for row in tracks):
                continue
            axes = np.asarray([np.asarray(f['joints'][side+'_'+end])-f['joints'][side+'_'+start] for f in frames])
            axes /= np.maximum(np.linalg.norm(axes,axis=1,keepdims=True),1e-12)
            vectors = np.asarray([row[key] for row in tracks])
            angle = leg_roll_closure_angle(vectors[-1], vectors[0], axes[-1], axes[0])
            angles = angle*np.arange(len(frames))/len(frames)
            rotated = (vectors*np.cos(angles)[:,None]+np.cross(axes,vectors)*np.sin(angles)[:,None]
                       +axes*np.sum(axes*vectors,axis=1)[:,None]*(1-np.cos(angles))[:,None])
            for row,vector in zip(tracks,rotated):
                row[key] = vector.tolist()
    return tracks


def head_material_binding(points, names):
    """Bind native dimensions to the first valid stored frame, not a seek pose."""
    points = np.asarray(points, dtype=float)
    required = ('left_hip', 'right_hip', 'left_shoulder', 'right_shoulder', 'neck', 'head')
    if not all(name in names for name in required):
        raise ValueError('Head material binding joints are unavailable')
    for index, row in enumerate(points):
        at = lambda name: row[names.index(name)]
        if not np.isfinite([at(name) for name in required[:4]]).all():
            continue
        hip_width = np.linalg.norm(at('right_hip')-at('left_hip'))
        shoulder_width = np.linalg.norm(at('right_shoulder')-at('left_shoulder'))
        if hip_width <= .0001 or shoulder_width <= .0001:
            continue
        head_length = np.linalg.norm(at('head')-at('neck'))
        if not np.isfinite(head_length) or head_length <= .0001:
            raise ValueError('Head material binding segment is unavailable')
        return {'frameIndex': index, 'headLength': float(head_length),
                'shoulderWidth': float(shoulder_width)}
    raise ValueError('Head material binding frame is unavailable')

def _head_material_unit(value, fallback):
    length = np.linalg.norm(value)
    return value/length if length*length > 1e-8 else np.asarray(fallback).copy()


def head_material_vertices(points, names, *, binding=None):
    """wearNeutralHeadPitchJoint + native four beveled head rings (32 vertices).

    Binding uses the same first valid stored clip frame as Kotlin/JavaScript.
    Callers sampling a clip must pass its full-clip binding. Ordinary geometry is smooth;
    native unit-vector fallbacks retain their existing piecewise behavior.
    """
    from scipy.spatial.transform import Rotation
    binding = head_material_binding(points, names) if binding is None else binding
    bind_head_length = binding['headLength']
    bind_shoulder_width = binding['shoulderWidth']
    output = []
    for row in np.asarray(points):
        at = lambda name: row[names.index(name)]
        neck, head = at('neck'), at('head')
        body_side = _head_material_unit(at('right_hip')-at('left_hip'), [1.,0.,0.])
        body_up = _head_material_unit(neck-at('pelvis'), [0.,1.,0.])
        body_forward = _head_material_unit(np.cross(body_side, body_up), [0.,0.,1.])
        shoulder_side = _head_material_unit(at('left_shoulder')-at('right_shoulder'), -body_side)
        upper_spine = at('spine3') if 'spine3' in names else at('spine2')
        torso = neck-upper_spine
        delta = head-neck
        display_head = head.copy()
        if np.linalg.norm(torso) >= 1e-4 and np.linalg.norm(delta) >= 1e-4:
            torso = torso/np.linalg.norm(torso)
            pitch_axis = shoulder_side-torso*np.dot(shoulder_side,torso)
            if np.linalg.norm(pitch_axis) >= 1e-6:
                display_head = neck+Rotation.from_rotvec(
                    pitch_axis/np.linalg.norm(pitch_axis)*(-np.pi/6)).apply(delta)
        up = _head_material_unit(display_head-neck, body_up)
        side = _head_material_unit(shoulder_side-up*np.dot(shoulder_side,up), shoulder_side)
        forward = _head_material_unit(np.cross(side,up), -body_forward)
        height = max(bind_head_length*1.65,bind_shoulder_width*.45)
        width = max(bind_head_length*1.08,bind_shoulder_width*.37)
        depth = width*.82
        base = neck+up*height*.02
        vertices=[]
        for h,w,d in ((.20,.40,.42),(.52,.52,.52),(.82,.44,.44),(1.,.22,.22)):
            center=base+up*height*h
            corners=[center+sx*side*width*w+sz*forward*depth*d
                     for sx,sz in ((1,1),(-1,1),(-1,-1),(1,-1))]
            for i,corner in enumerate(corners):
                vertices.extend((.7*corner+.3*corners[(i-1)%4],
                                 .7*corner+.3*corners[(i+1)%4]))
        output.append(vertices)
    return np.asarray(output)

"""Bounded whole-body sequence proposals with independent final acceptance.

Contact coordinates are eliminated from the optimization variables. Torso shape
and limb hinges use dependent coordinates; the remaining variables are solved
together. No later local IK is allowed to overwrite the result.
Penalty minimization only proposes a trajectory: explicit tolerances decide
whether it can be returned. Unresolved input goes back for reconstruction/review.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from time import monotonic
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.sparse import csr_matrix, diags, eye, kron

from .contact_constraints import contact_frame_bounds, is_stationary_contact, motion_support_contacts, stationary_target_track
from .models import MotionFrame
from .temporal_quality import body_orientation_axes, body_orientation_noise
from .foot_kinematics import _source_knee_poles, _transport_knee_poles, _unit
from .physical_validation import (
    ARTICULATIONS, angles, body_bones, body_scale, collision_clearances,
    validate_physical_motion,
)


class HingeCoordinates:
    """Keep a two-bone chain on its source bend branch during optimization.

    Joint angles alone cannot distinguish the two sides of the endpoint axis.
    Solve the hinge analytically from the endpoints and a transported source
    pole, rather than letting independent Cartesian variables switch branches.
    """

    def __init__(self, reference, names, pinned):
        self.chains = []
        for side in ('left', 'right'):
            for chain in (('hip', 'knee', 'ankle'), ('shoulder', 'elbow', 'wrist')):
                keys = [side + '_' + name for name in chain]
                if not all(name in names for name in keys):
                    continue
                a, h, b = [names.index(name) for name in keys]
                if pinned[:, h].any():
                    continue
                parent, hinge, child = reference[:, a], reference[:, h], reference[:, b]
                proximal = np.linalg.norm(hinge - parent, axis=1)
                distal = np.linalg.norm(child - hinge, axis=1)
                source_axes = _unit(child - parent)
                poles = _source_knee_poles(parent, hinge, child)
                reliable = np.sin(angles(parent, hinge, child)) > np.sin(np.deg2rad(15.))
                # Near extension the bend plane is ill-conditioned. Transport
                # neighboring reliable poles into that frame before blending.
                valid = np.flatnonzero(reliable)
                usable = np.flatnonzero(np.linalg.norm(poles,axis=1)>1e-6)
                fallback_index = int(usable[0]) if len(usable) else 0
                fallback_pole = poles[fallback_index].copy()
                if np.linalg.norm(fallback_pole)<1e-6:
                    basis=np.eye(3)[np.argmin(np.abs(source_axes[fallback_index]))]
                    fallback_pole=_unit(basis-source_axes[fallback_index]*np.dot(basis,source_axes[fallback_index]))
                for i in np.flatnonzero(~reliable):
                    if len(valid):
                        left = valid[valid < i]
                        right = valid[valid > i]
                        lo = int(left[-1]) if len(left) else int(valid[0])
                        hi = int(right[0]) if len(right) else int(valid[-1])
                        first = _transport_knee_poles(poles[lo], source_axes[lo], source_axes[i])
                        last = _transport_knee_poles(poles[hi], source_axes[hi], source_axes[i])
                        alpha = (i-lo)/(hi-lo) if hi != lo else 0.
                        mixed = first*(1-alpha) + last*alpha
                        poles[i] = _unit(mixed) if np.linalg.norm(mixed) > 1e-6 else first
                    else:
                        poles[i]=_transport_knee_poles(fallback_pole,source_axes[fallback_index],source_axes[i])
                self.chains.append((a,h,b,proximal,distal,source_axes,poles))

    def dependent_joints(self):
        return [chain[1] for chain in self.chains]

    def apply(self, points, pole_rotations=None):
        for chain_index,(a,h,b,proximal,distal,source_axes,poles) in enumerate(self.chains):
            parent,child = points[:,a],points[:,b]
            reach = child-parent
            distance = np.maximum(np.linalg.norm(reach,axis=1),1e-8)
            direction = reach/distance[:,None]
            transported = _transport_knee_poles(poles,source_axes,direction)
            bend = _unit(transported-direction*np.sum(transported*direction,axis=1,keepdims=True))
            if pole_rotations is not None:
                rotation=pole_rotations[:,chain_index,None]
                bend=bend*np.cos(rotation)+np.cross(direction,bend)*np.sin(rotation)
            along = (proximal**2-distal**2+distance**2)/(2*distance)
            height = np.sqrt(np.maximum(0.,proximal**2-along**2))
            points[:,h] = parent+direction*along[:,None]+bend*height[:,None]
        return points


def torso_shape_pairs(names):
    """Preserve the source torso shape without locking its world orientation.

    A chain of bone lengths leaves the waist, chest and hip attachments free
    to shear. Distances across the torso preserve its observed flexion and
    twist per frame, including legitimately curved or asymmetric poses.
    """
    core = ('pelvis', 'left_hip', 'right_hip', 'spine1', 'spine2',
            'spine3', 'neck', 'left_collar', 'right_collar',
            'left_shoulder', 'right_shoulder')
    return list(combinations([names.index(name) for name in core if name in names], 2))


def pair_distances(points, pairs):
    if not pairs:
        return np.empty((len(points), 0))
    first, second = np.asarray(pairs).T
    return np.linalg.norm(points[:, first] - points[:, second], axis=-1)


def trajectory_acceleration(points, fps, scale):
    """Regularize output acceleration, including inherited sub-threshold shake."""
    return np.diff(points / scale, n=2, axis=0) * (fps * .20) ** 2


class TorsoCoordinates:
    """Move the observed torso with six coordinates instead of shearing joints."""

    def __init__(self, reference, names, pinned):
        pairs = torso_shape_pairs(names)
        self.joints = sorted({index for pair in pairs for index in pair})
        if 'pelvis' not in names or pinned[:, self.joints].any():
            self.joints = []
        # The head is an attached articulation, not a free point chasing its
        # old world position when contact repair moves the chest. Preserve its
        # observed motion relative to the torso, including intentional nods.
        # A supported head stays under the contact solver's ownership.
        if self.joints and 'head' in names and not pinned[:, names.index('head')].any():
            self.joints.append(names.index('head'))
        self.width = 6 if self.joints else 0
        if self.width:
            self.origin = reference[:, names.index('pelvis')]
            self.local = reference[:, self.joints] - self.origin[:, None]

    def apply(self, points, coordinates):
        if self.width:
            matrices = Rotation.from_rotvec(coordinates[:, 3:]).as_matrix()
            points[:, self.joints] = (np.einsum('fij,fkj->fki', matrices, self.local)
                                     + coordinates[:, None, :3])
        return points


def contact_pins(reference, proposal, names, evidence):
    """Use only explicit stationary episodes; releases/rolling stay free."""
    pinned = np.zeros(reference.shape[:2], dtype=bool)
    supported = {side: np.zeros(len(reference), dtype=bool) for side in ('left','right')}
    other_support = False
    for contact in motion_support_contacts(evidence):
        if not isinstance(contact, dict) or not is_stationary_contact(contact):
            continue
        name = str(contact.get('jointName',''))
        if name not in names:
            continue
        start,end = contact_frame_bounds(contact,len(reference))
        if end < start:
            continue
        state = contact.get('contactState')
        side = name.split('_')[0]
        if side in supported and name.endswith(('_foot','_ankle')):
            if state == 'heel_only':
                # Heel pivot requires an explicit heel point. Do not pin the toe.
                continue
            pinned[start:end+1,names.index(name)] = True
            if state == 'full_sole':
                for suffix in ('ankle','foot'):
                    key=side+'_'+suffix
                    if key in names:
                        pinned[start:end+1,names.index(key)] = True
                supported[side][start:end+1] = True
        else:
            pinned[start:end+1,names.index(name)] = True
            proposal[start:end+1,names.index(name)] = np.median(reference[start:end+1,names.index(name)],axis=0)
            other_support = True
    # The reduced balance screen cannot represent benches or hand supports.
    balance_mask = supported['left'] & supported['right']
    if other_support:
        balance_mask[:] = False
    return pinned, balance_mask


def stationary_full_sole_proposal(clip, evidence):
    """Build contact targets without first distorting knees to reach them.

    Mixed heel/toe pivots retain the existing geometric proposal generator;
    their output must still pass the whole-body solver and independent gate.
    """
    contacts=motion_support_contacts(evidence)
    feet=[c for c in contacts if str(c.get('jointName','')).endswith(('_ankle','_foot'))]
    if not feet or not all(c.get('contactState')=='full_sole' and is_stationary_contact(c) for c in feet):
        return None
    if len(clip.frames)<3:
        return None
    frames=[MotionFrame(time_sec=f.time_sec,joints=dict(f.joints)) for f in clip.frames]
    floor=clip.metadata.get('renderFloorY')
    if floor is None or not np.isfinite(floor):
        floor=min(f.joints[n][1] for f in frames for n in ('left_foot','right_foot') if n in f.joints)
    reports={}
    for side in ('left','right'):
        ankle,toe=side+'_ankle',side+'_foot'
        if any(ankle not in f.joints or toe not in f.joints for f in frames):
            continue
        supported=np.zeros(len(frames),dtype=bool)
        anchor_ids=np.full(len(frames),None,dtype=object)
        for contact in feet:
            if str(contact['jointName']).startswith(side+'_'):
                start,end=contact_frame_bounds(contact,len(frames))
                supported[start:end+1]=True
                anchor_ids[start:end+1]=contact.get('anchorGroupId')
        if not supported.any():
            continue
        ankles,toes=[np.array([f.joints[n] for f in frames]) for n in (ankle,toe)]
        length=float(np.median(np.linalg.norm(toes-ankles,axis=1)))
        headings=toes-ankles
        headings[:,1]=0.
        headings/=np.maximum(np.linalg.norm(headings,axis=1,keepdims=True),1e-9)
        headings,_=stationary_target_track(headings,supported)
        headings/=np.maximum(np.linalg.norm(headings,axis=1,keepdims=True),1e-9)
        targets,episodes=stationary_target_track(toes,supported,anchor_ids=anchor_ids,fps=clip.fps)
        targets[supported,1]=floor
        for i in np.flatnonzero(supported):
            frames[i].joints[toe]=tuple(targets[i])
            frames[i].joints[ankle]=tuple(targets[i]-headings[i]*length)
        reports[side]={'stationaryContactEpisodes':episodes,'fullSoleFrames':np.flatnonzero(supported).tolist()}
    if not reports:
        return None
    return replace(clip,frames=frames),{'applied':True,'strategy':'whole_body_stationary_contact_targets',
                                       'supportPlaneY':float(floor),'feet':reports}


def repair_whole_body(reference_clip, contact_proposal, evidence, *, max_evaluations=80, timeout_seconds=90.):
    started = monotonic()
    names = [n for n in reference_clip.joint_names if all(n in f.joints for f in reference_clip.frames)]
    reference = np.asarray([[f.joints[n] for n in names] for f in reference_clip.frames], dtype=float)
    source_joints=reference_clip.metadata.get('contactSourceReferenceJoints')
    physical_reference=(np.asarray([[f[n] for n in names] for f in source_joints],dtype=float)
                        if source_joints is not None else reference)
    proposal = np.asarray([[f.joints[n] for n in names] for f in contact_proposal.frames], dtype=float)
    if reference.shape != proposal.shape or not np.isfinite(proposal).all():
        return reference_clip, {'applied':False,'reason':'invalid_whole_body_input','requiresReconstruction':True}
    pinned, balance_mask = contact_pins(reference,proposal,names,evidence)
    scale = body_scale(reference,names)
    before = validate_physical_motion(proposal,names,reference=physical_reference,fps=reference_clip.fps,support_mask=balance_mask)
    before_orientation=body_orientation_noise(proposal,names,physical_reference,reference_clip.fps)
    if before['passed'] and not before_orientation['severe']:
        return contact_proposal, {'applied':True,'reason':'contact_proposal_passed_whole_body_check','validation':before}
    unsupported_pivots=[c for c in motion_support_contacts(evidence)
                        if str(c.get('jointName','')).endswith(('_foot','_ankle'))
                        and (c.get('contactState')=='heel_only' or not is_stationary_contact(c))]
    if unsupported_pivots:
        # Never improve anatomy by silently releasing an unrepresented pivot.
        return reference_clip, {'applied':False,'reason':'contact_manifold_requires_reconstruction',
                                'requiresReconstruction':True,'validation':before}
    if not pinned.any():
        return reference_clip, {'applied':False,'reason':'unsupported_contact_parameterization',
                                'requiresReconstruction':True,'validation':before}
    count,joint_count,_ = reference.shape
    if count < 3:
        return reference_clip, {'applied':False,'reason':'insufficient_sequence_for_repair',
                                'requiresReconstruction':True,'validation':before}
    hinges = HingeCoordinates(reference,names,pinned)
    torso = TorsoCoordinates(reference, names, pinned)
    independent = ~pinned
    independent[:,hinges.dependent_joints()] = False
    independent[:,torso.joints] = False
    free = np.repeat(independent[...,None],3,axis=2).ravel()
    bones = body_bones(names)
    torso_pairs = torso_shape_pairs(names)
    torso_distances = pair_distances(reference, torso_pairs)
    source_body_axes = body_orientation_axes(reference, names)
    body_axis_count = source_body_axes.shape[1]
    lengths = np.stack([np.linalg.norm(reference[:,a]-reference[:,b],axis=1) for a,b in bones],axis=1)
    specs = [(label, [names.index(n) for n in (a,b,c)],tol)
             for label,a,b,c,tol in ARTICULATIONS if all(n in names for n in (a,b,c))]
    source_angles = np.stack([angles(*(physical_reference[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
    # Leave room for numerical residuals before the independent acceptance bound.
    tolerances = np.deg2rad([tol-.5 for _,_,tol in specs])
    low,high = source_angles-tolerances,source_angles+tolerances
    for col,(label,_,_) in enumerate(specs):
        if label.endswith('_ankle'):
            low[:,col] = np.maximum(low[:,col],np.deg2rad(35.))
            high[:,col] = np.minimum(high[:,col],np.deg2rad(165.))
        if label.endswith('_knee'):
            source_bounds=reference_clip.metadata.get('contactSourceKneeBounds',{}).get(label.split('_')[0])
            if source_bounds is not None:
                source_bounds=np.asarray(source_bounds)
                low[:,col]=np.maximum(low[:,col],source_bounds[:,0])
                high[:,col]=np.minimum(high[:,col],source_bounds[:,1])
        hinge_bounds=reference_clip.metadata.get('contactSourceHingeBounds',{}).get(label)
        if hinge_bounds is not None:
            hinge_bounds=np.asarray(hinge_bounds)
            low[:,col]=np.maximum(low[:,col],hinge_bounds[:,0])
            high[:,col]=np.minimum(high[:,col],hinge_bounds[:,1])
        # Numerical room inside the exact downstream envelope.
        low[:,col]+=np.deg2rad(.1)
        high[:,col]-=np.deg2rad(.1)
    floor = float(np.min(proposal[pinned,1]))
    base = reference.copy()
    # A coherent rigid translation is a better starting point than moving only
    # endpoints far away while leaving the entire body behind.
    for i in range(count):
        if pinned[i].any():
            shift = np.mean(proposal[i,pinned[i]]-reference[i,pinned[i]],axis=0)
            offsets,radii_squared=[],[]
            for a,h,b,proximal,distal,*_ in hinges.chains:
                if not names[h].endswith('_knee') or not pinned[i,b]:
                    continue
                col=next(j for j,(label,_,_) in enumerate(specs) if label==names[h])
                target_angle=np.clip(source_angles[i,col],low[i,col],high[i,col])
                radii_squared.append(proximal[i]**2+distal[i]**2-2*proximal[i]*distal[i]*np.cos(target_angle))
                offsets.append(proposal[i,b]-reference[i,a])
            if offsets:
                offsets,radii_squared=np.asarray(offsets),np.asarray(radii_squared)
                seed=np.clip(shift,-.44*scale,.44*scale)
                def seed_residual(candidate):
                    # Solve both reach spheres together. Alternating projection
                    # can leave the first leg outside its reach after the last.
                    return np.r_[(np.sum((offsets-candidate)**2,axis=1)-radii_squared)/scale**2,
                                 .0001*(candidate-seed)/scale]
                shift=least_squares(seed_residual,seed,max_nfev=60,
                                    ftol=1e-10,xtol=1e-10,gtol=1e-10,
                                    bounds=(-.45*scale,.45*scale)).x
            base[i] += np.clip(shift,-.45*scale,.45*scale)
    base[pinned] = proposal[pinned]
    coordinate_count=int(np.sum(free))
    hinge_count=len(hinges.chains)
    hinge_end=coordinate_count+count*hinge_count
    spike_joints=[names.index(n) for n in ('left_wrist','right_wrist','left_ankle','right_ankle') if n in names]
    if 'pelvis' not in names:
        spike_joints=[]
    pelvis_index=names.index('pelvis') if 'pelvis' in names else 0
    source_relative=physical_reference[:,spike_joints]-physical_reference[:,pelvis_index,None]
    source_residual=np.linalg.norm(np.diff(source_relative,n=2,axis=0)*.5,axis=-1)
    source_span=float(np.median(np.linalg.norm(np.ptp(physical_reference,axis=1),axis=1)))
    spike_limits=np.maximum(source_residual*2.5,source_span*.009)

    class RepairTimeout(Exception):
        pass

    def expand(values):
        result=base.copy().ravel()
        result[free]=values[:coordinate_count]
        rotations=values[coordinate_count:hinge_end].reshape(count,hinge_count)
        points=torso.apply(result.reshape(reference.shape), values[hinge_end:].reshape(count,torso.width))
        return hinges.apply(points,rotations)

    def residual(values):
        if monotonic() - started > timeout_seconds:
            raise RepairTimeout
        points=expand(values)
        rotations=values[coordinate_count:hinge_end].reshape(count,hinge_count)
        correction=(points-reference)/scale
        lengths_now=np.stack([np.linalg.norm(points[:,a]-points[:,b],axis=1) for a,b in bones],axis=1)
        values_now=np.stack([angles(*(points[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
        articulation=np.minimum(values_now-low,0.)+np.maximum(values_now-high,0.)
        clearances,_=collision_clearances(points,names,scale)
        per_frame=np.concatenate([
            correction.reshape(count,-1),
            (body_orientation_axes(points, names)-source_body_axes).reshape(count,-1),
            1000.*(lengths_now-lengths)/scale,
            300.*articulation,
            100.*np.minimum(clearances,0.)/scale,
            100.*np.minimum(points[:,:,1]-floor,0.)/scale,
            .2*rotations,
        ],axis=1)
        temporal=trajectory_acceleration(points, reference_clip.fps, scale)
        # Root displacement is shared by the whole model. Denoise its path
        # more strongly while both feet remain planted, retaining the joint
        # angle envelopes that preserve squat timing and depth.
        planted_window=balance_mask[:-2]&balance_mask[1:-1]&balance_mask[2:]
        temporal[planted_window,pelvis_index]*=4.
        body_angular_temporal=np.diff(body_orientation_axes(points, names),n=2,axis=0)*(reference_clip.fps*.35)**2
        pole_temporal=np.diff(rotations,n=2,axis=0)*(reference_clip.fps*.10)**2
        # Limit the *correction* speed, retaining the source's natural rotation.
        pole_steps=np.diff(rotations,axis=0)
        maximum_pole_step=np.deg2rad(90.)/reference_clip.fps
        pole_speed=100.*np.maximum(np.abs(pole_steps)-maximum_pole_step,0.)
        relative=points[:,spike_joints]-points[:,pelvis_index,None]
        spike_residual=np.linalg.norm(np.diff(relative,n=2,axis=0)*.5,axis=-1)
        spike_cost=150.*np.maximum(spike_residual-spike_limits,0.)/scale
        return np.r_[per_frame.ravel(),temporal.ravel(),pole_temporal.ravel(),pole_speed.ravel(),spike_cost.ravel(),body_angular_temporal.ravel()]

    torso_initial=(np.column_stack([base[:,pelvis_index],np.zeros((count,3))])
                   if torso.width else np.empty((count,0)))
    initial=np.r_[base.ravel()[free],np.zeros(count*hinge_count),torso_initial.ravel()]
    # Physical residuals are local to a frame; output acceleration residuals
    # couple neighboring frames separately. Balance is diagnostic only.
    temporal_rows=max(0,count-2)*(joint_count*3+hinge_count+len(spike_joints)+body_axis_count*3)+(count-1)*hinge_count
    try:
        per_frame_rows=(len(residual(initial))-temporal_rows)//count
    except RepairTimeout:
        return reference_clip, {'applied':False,'reason':'whole_body_repair_timeout',
                                'requiresReconstruction':True,'elapsedSeconds':monotonic()-started}
    frame_pattern=kron(eye(count),csr_matrix(np.ones((per_frame_rows,joint_count*3))),format='csr')
    from scipy.sparse import vstack, hstack
    # A hinge's temporal residual depends on both endpoints, not just its own
    # (now eliminated) coordinates. Include the chain dependencies in the Jacobian.
    temporal_dependencies=np.eye(joint_count*3)
    for a,h,b,*_ in hinges.chains:
        temporal_dependencies[h*3:h*3+3,a*3:a*3+3]=1.
        temporal_dependencies[h*3:h*3+3,b*3:b*3+3]=1.
    temporal_pattern=kron(diags([np.ones(max(0,count-2))]*3,[0,1,2],shape=(max(0,count-2),count)),csr_matrix(temporal_dependencies),format='csr')
    frame_angles=kron(eye(count),csr_matrix(np.ones((per_frame_rows,hinge_count))),format='csr')
    temporal_angle_dependencies=np.zeros((joint_count*3,hinge_count))
    for index,(_,h,*_) in enumerate(hinges.chains):
        temporal_angle_dependencies[h*3:h*3+3,index]=1.
    second_difference=diags([np.ones(max(0,count-2))]*3,[0,1,2],shape=(max(0,count-2),count))
    temporal_angles=kron(second_difference,csr_matrix(temporal_angle_dependencies),format='csr')
    angle_smoothing=kron(second_difference,eye(hinge_count),format='csr')
    angle_speed=kron(diags([np.ones(count-1)]*2,[0,1],shape=(count-1,count)),eye(hinge_count),format='csr')
    spike_dependencies=np.zeros((len(spike_joints),joint_count*3))
    for row,joint in enumerate(spike_joints):
        spike_dependencies[row,joint*3:joint*3+3]=1.
        spike_dependencies[row,pelvis_index*3:pelvis_index*3+3]=1.
    spike_pattern=kron(second_difference,csr_matrix(spike_dependencies),format='csr')[:,free]
    pattern=vstack([
        hstack([frame_pattern[:,free],frame_angles]),
        hstack([temporal_pattern[:,free],temporal_angles]),
        hstack([csr_matrix((angle_smoothing.shape[0],coordinate_count)),angle_smoothing]),
        hstack([csr_matrix((angle_speed.shape[0],coordinate_count)),angle_speed]),
        hstack([spike_pattern,csr_matrix((spike_pattern.shape[0],count*hinge_count))]),
    ],format='csr')
    torso_dependencies=np.zeros((joint_count*3,torso.width))
    torso_dependents=set(torso.joints)
    for a,h,b,*_ in hinges.chains:
        if a in torso_dependents or b in torso_dependents:
            torso_dependents.add(h)
    for joint in torso_dependents:
        torso_dependencies[joint*3:joint*3+3]=1.
    torso_pattern=vstack([
        kron(eye(count),csr_matrix(np.ones((per_frame_rows,torso.width)))),
        kron(second_difference,csr_matrix(torso_dependencies)),
        csr_matrix((angle_smoothing.shape[0]+angle_speed.shape[0],count*torso.width)),
        kron(second_difference,csr_matrix(np.ones((len(spike_joints),torso.width)))),
    ],format='csr')
    pattern=hstack([pattern,torso_pattern],format='csr')
    body_dependencies=np.zeros((body_axis_count*3,joint_count*3))
    for name in ('left_hip','right_hip','pelvis','neck'):
        if name in names:
            index=names.index(name)
            body_dependencies[:,index*3:index*3+3]=1.
    body_pattern=hstack([
        kron(second_difference,csr_matrix(body_dependencies),format='csr')[:,free],
        csr_matrix((max(0,count-2)*body_axis_count*3,count*hinge_count)),
        kron(second_difference,csr_matrix(np.ones((body_axis_count*3,torso.width)))),
    ],format='csr')
    pattern=vstack([pattern,body_pattern],format='csr')
    torso_radius=np.tile([.5*scale]*3+[np.pi/3]*3,(count,1)) if torso.width else np.empty((count,0))
    try:
        solution=least_squares(residual,initial,jac_sparsity=pattern,max_nfev=max_evaluations,
                               # Near-straight analytic hinges amplify tiny
                               # differences. Do not scale the trust region
                               # from those noisy derivative magnitudes.
                               ftol=1e-7,xtol=1e-8,gtol=1e-7, x_scale=1.,diff_step=1e-5,
                               tr_options={'maxiter':400, 'atol':1e-7, 'btol':1e-7},
                               bounds=(np.r_[reference.ravel()[free]-.5*scale,np.full(count*hinge_count,-np.pi/3),(torso_initial-torso_radius).ravel()],
                                       np.r_[reference.ravel()[free]+.5*scale,np.full(count*hinge_count,np.pi/3),(torso_initial+torso_radius).ravel()]))
    except RepairTimeout:
        return reference_clip, {'applied':False, 'reason':'whole_body_repair_timeout',
                                'requiresReconstruction':True, 'elapsedSeconds':monotonic()-started,
                                'validation':before}
    result=expand(solution.x)
    final=validate_physical_motion(result,names,reference=physical_reference,fps=reference_clip.fps,support_mask=balance_mask)
    resulting_lengths=np.stack([np.linalg.norm(result[:,a]-result[:,b],axis=1) for a,b in bones],axis=1)
    length_error=float(np.max(np.abs(resulting_lengths-lengths)))
    contact_error=float(np.max(np.linalg.norm(result[pinned]-proposal[pinned],axis=1)))
    floor_error=float(max(0.,floor-np.min(result[:,:,1])))
    torso_error=float(np.max(np.abs(pair_distances(result, torso_pairs)-torso_distances), initial=0.))
    orientation_quality=body_orientation_noise(result,names,physical_reference,reference_clip.fps)
    passed=final['passed'] and length_error<=.002 and contact_error<=1e-6 and floor_error<=.002 and torso_error<=.005 and not orientation_quality['severe']
    report={'applied':bool(passed),'strategy':'coupled_whole_body_sequence',
            'torsoParameterization':'source_shape_rigid_transform' if torso.width else 'free_contact_supported_torso',
            'temporalObjective':'output_position_and_body_orientation_acceleration',
            'reason':'whole_body_constraints_satisfied' if passed else 'whole_body_constraints_unresolved',
            'requiresReconstruction':not passed,'evaluations':int(solution.nfev),
            'solverStatus':int(solution.status),'solverOptimality':float(solution.optimality),
            'maximumBoneLengthErrorMeters':length_error,'maximumContactErrorMeters':contact_error,
            'maximumFloorPenetrationMeters':floor_error,'validation':final,
            'maximumTorsoShapeErrorMeters':torso_error,
            'bodyOrientationNoise':orientation_quality,
            'initialValidation':before}
    if not passed:
        return reference_clip,report
    frames=[MotionFrame(time_sec=f.time_sec,joints={**f.joints,**{n:tuple(result[i,j]) for j,n in enumerate(names)}})
            for i,f in enumerate(reference_clip.frames)]
    return replace(reference_clip,frames=frames),report

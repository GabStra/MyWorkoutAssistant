"""Independent, conservative checks on completed joint trajectories.

These are repair/acceptance limits, not a clinical range-of-motion database.
Capsules are inner collision proxies, not an exact triangle-mesh collision test.
The support calculation is a reduced COM model without external equipment mass
or angular momentum; it reports review evidence, never a physics certificate.
"""
from __future__ import annotations

import numpy as np

from .contact_constraints import contact_frame_bounds, motion_support_contacts
from .temporal_quality import body_local_head_direction


ARTICULATIONS = tuple(
    (f"{side}_{joint}", parent.format(s=side), f"{side}_{joint}", child.format(s=side), tolerance)
    for side in ("left", "right")
    for joint, parent, child, tolerance in (
        ("hip", "neck", "{s}_knee", 20.),
        ("knee", "{s}_hip", "{s}_ankle", 10.),
        ("ankle", "{s}_knee", "{s}_foot", 15.),
        ("shoulder", "{s}_hip", "{s}_elbow", 20.),
        ("elbow", "{s}_shoulder", "{s}_wrist", 15.),
    )
)


def body_bones(names):
    edges = [('pelvis','spine1'), ('spine1','spine2'), ('spine2','spine3'),
             ('spine3','neck'), ('neck','head'), ('left_hip','right_hip'),
             ('left_shoulder','right_shoulder'), ('pelvis','neck')]
    for side in ('left','right'):
        edges.extend([('pelvis',side+'_hip'), ('neck',side+'_collar'),
                      (side+'_collar',side+'_shoulder')])
        for start, end in [('hip','knee'), ('knee','ankle'), ('ankle','foot'),
                           ('shoulder','elbow'), ('elbow','wrist'), ('wrist','hand')]:
            edges.append((side+'_'+start,side+'_'+end))
    return [(names.index(a),names.index(b)) for a,b in edges if a in names and b in names]


def angles(a, b, c):
    u, v = a - b, c - b
    denominator = np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1)
    return np.arccos(np.clip(np.sum(u * v, axis=-1) / np.maximum(denominator, 1e-12), -1., 1.))


def source_hinge_angle_bounds(clip, *, phase_tolerance_degrees=10., envelope_tolerance_degrees=1.):
    """One authoritative knee/elbow envelope for solving and final validation."""
    bounds = {}
    for label,a,h,b,_ in ARTICULATIONS:
        if not label.endswith(('_knee','_elbow')) or any(
            any(n not in f.joints for n in (a,h,b)) for f in clip.frames
        ):
            continue
        values=angles(*(np.asarray([f.joints[n] for f in clip.frames]) for n in (a,h,b)))
        phase=np.deg2rad(phase_tolerance_degrees)
        envelope=np.deg2rad(envelope_tolerance_degrees)
        bounds[label]=np.column_stack([np.maximum(values-phase,values.min()-envelope),
                                       np.minimum(values+phase,values.max()+envelope)]).tolist()
    return bounds


def segment_distance(a, b, c, d):
    """Closest points of finite segments, including parallel/degenerate cases."""
    u, v, w = b - a, d - c, a - c
    aa, bb, cc = np.sum(u*u, -1), np.sum(u*v, -1), np.sum(v*v, -1)
    dd, ee = np.sum(u*w, -1), np.sum(v*w, -1)
    determinant = aa * cc - bb * bb
    s = np.where(determinant > 1e-12, (bb*ee - cc*dd) / np.maximum(determinant, 1e-12), 0.)
    s = np.clip(s, 0., 1.)
    t = np.clip((bb*s + ee) / np.maximum(cc, 1e-12), 0., 1.)
    s = np.clip((bb*t - dd) / np.maximum(aa, 1e-12), 0., 1.)
    return np.linalg.norm(w + s[..., None]*u - t[..., None]*v, axis=-1)


def collision_specs(names):
    """Inner limb capsules; skip connected endpoints and expected joint overlap."""
    pairs = []
    for part, start, end in (("thigh", "hip", "knee"), ("shin", "knee", "ankle"),
                             ("forearm", "elbow", "wrist")):
        pairs.append((part, (f"left_{start}", f"left_{end}"),
                      (f"right_{start}", f"right_{end}"), .018, False))
    for side in ("left", "right"):
        pairs.append((side + "_shin_foot", (side+"_ankle", side+"_knee"),
                      (side+"_ankle", side+"_foot"), .050, True))
        pairs.append((side + "_forearm_torso", (side+"_elbow", side+"_wrist"),
                      ("pelvis", "neck"), .045, False))
    return [item for item in pairs if all(n in names for n in (*item[1], *item[2]))]


def collision_clearances(points, names, scale):
    index = {name: i for i, name in enumerate(names)}
    values, labels = [], []
    for label, first, second, radius_ratio, adjacent in collision_specs(names):
        a, b, c, d = [points[:, index[n]] for n in (*first, *second)]
        if adjacent:
            # Remove the intentional ankle junction, keep distal shoe/shin overlap.
            a = a + (b-a)*.25
            c = c + (d-c)*.35
        else:
            a, b = a + (b-a)*.12, b - (b-a)*.12
            c, d = c + (d-c)*.12, d - (d-c)*.12
        values.append(segment_distance(a, b, c, d) - scale * radius_ratio)
        labels.append(label)
    return np.stack(values, axis=1) if values else np.zeros((len(points), 0)), labels


def body_scale(points, names):
    index = {name: i for i, name in enumerate(names)}
    for side in ("left", "right"):
        chain = [side+"_"+n for n in ("hip", "knee", "ankle")]
        if all(n in index for n in chain):
            h, k, a = [points[:, index[n]] for n in chain]
            return max(.01, float(np.median(np.linalg.norm(k-h, axis=1) + np.linalg.norm(a-k, axis=1))))
    return max(.01, float(np.max(np.ptp(points, axis=1))))


def support_balance(points, names, fps, support_mask=None):
    """Reduced dynamic support screen; includes acceleration, excludes flight.

    Returns distances outside the foot support rectangle. This deliberately
    conservative outer envelope avoids mistaking a rough COM for exact ZMP.
    Other contacts require a different support model and are reported separately.
    """
    index = {name: i for i, name in enumerate(names)}
    required = [s+"_"+j for s in ("left", "right") for j in ("hip", "knee", "ankle", "foot")]
    if len(points) < 5 or not all(n in index for n in (*required, "neck")):
        return {"available": False, "reason": "insufficient_body_or_time_data"}, np.zeros(len(points))
    pelvis = (points[:, index['left_hip']] + points[:, index['right_hip']])*.5
    torso = (pelvis + points[:, index['neck']])*.5
    # Approximate mass fractions used only for conservative screening.
    weighted, total = torso*.50, .50
    for side in ('left', 'right'):
        for start, end, mass in (('hip','knee',.10), ('knee','ankle',.047),
                                 ('ankle','foot',.015), ('shoulder','elbow',.028),
                                 ('elbow','wrist',.016), ('wrist','hand',.006)):
            if side+'_'+start in index and side+'_'+end in index:
                weighted += (points[:, index[side+'_'+start]] + points[:, index[side+'_'+end]]) * (.5*mass)
                total += mass
    if 'head' in index:
        weighted += points[:, index['head']]*.082
        total += .082
    com = weighted/total
    acceleration = np.zeros_like(com)
    acceleration[1:-1] = np.diff(com, n=2, axis=0)*fps**2
    feet = np.stack([points[:, index[n]] for n in required if n.endswith(('_ankle','_foot'))], axis=1)
    floor = np.min(feet[..., 1], axis=1)
    effective_gravity = 9.81 + acceleration[:, 1]
    support_point = com[:, [0, 2]] - (com[:, 1]-floor)[:, None] * acceleration[:, [0, 2]] / np.maximum(effective_gravity[:, None], 1.)
    margin = body_scale(points, names)*.06
    low = np.min(feet[..., [0, 2]], axis=1)-margin
    high = np.max(feet[..., [0, 2]], axis=1)+margin
    outside = np.linalg.norm(np.maximum(low-support_point, 0.) + np.maximum(support_point-high, 0.), axis=1)
    valid = np.zeros(len(points), dtype=bool) if support_mask is None else support_mask.copy()
    valid[[0,-1]] = False
    valid &= effective_gravity > 2.
    outside[~valid] = 0.
    return {"available": bool(valid.any()), "model": "approximate_com_acceleration_support_screen",
            "evaluatedFrames": np.flatnonzero(valid).tolist(),
            "maximumOutsideSupportMeters": float(outside.max()),
            "maximumOutsideSupportFrameIndex": int(np.argmax(outside)) if valid.any() else None,
            "outsideSupportFrames": np.flatnonzero(outside > .12*body_scale(points,names)).tolist(),
            "limitations": "No equipment mass, contact forces, or angular momentum; not full dynamics validation."}, outside


def anatomical_structure_residuals(points, names, *, pose_only=False):
    """Source-independent limits for our simplified exercise rig.

    These dimensionless model limits are not clinical ROM claims. They allow
    torso flexion and independent limbs, but reject folded spine chains,
    displaced sockets, collapsed bones and mismatched bilateral proportions.
    Positive residuals are violations; fitting and acceptance share this policy.
    """
    index = {name: i for i, name in enumerate(names)}
    rows, labels = [], []

    def add(label, value):
        labels.append(label)
        rows.append(np.maximum(value, 0.))

    def point(name):
        return points[:, index[name]]

    from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
    lengths = {}
    for name, parent in ([] if pose_only else zip(SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS)):
        if parent < 0 or name not in index or SMPL_JOINT_NAMES[parent] not in index:
            continue
        lengths[name] = np.linalg.norm(point(name)-point(SMPL_JOINT_NAMES[parent]), axis=-1)
        add('anatomy_degenerate_bone:'+name, .001-lengths[name])
    for name in lengths:
        other = name.replace('left_', 'right_', 1)
        if not name.startswith('left_') or other not in lengths:
            continue
        mean = (lengths[name]+lengths[other])*.5
        add('anatomy_bilateral_proportions:'+name,
            abs(lengths[name]-lengths[other])/np.maximum(mean, 1e-9)-.05)
    # Broad proportions for this generic display rig. Bilateral agreement
    # alone would also accept two equally stretched forearms or shins.
    for side in ('left', 'right'):
        for child, base, low, high in [('elbow', 'knee', .4, 1.2),
                                        ('wrist', 'elbow', .55, 1.25),
                                        ('ankle', 'knee', .65, 1.4),
                                        ('foot', 'ankle', .15, .65)]:
            a, b = side+'_'+child, side+'_'+base
            if a in lengths and b in lengths:
                ratio = lengths[a]/np.maximum(lengths[b], 1e-9)
                add('anatomy_segment_proportion:'+a, np.maximum(low-ratio, ratio-high))
    for a, b, center in [('left_hip', 'right_hip', 'pelvis'),
                          ('left_collar', 'right_collar', 'spine3'),
                          ('left_collar', 'right_collar', 'neck')]:
        if pose_only and center != 'neck':
            continue
        if not all(n in index for n in (a, b, center)):
            continue
        span = point(b)-point(a)
        width = np.linalg.norm(span, axis=-1)
        displacement = point(center)-(point(a)+point(b))*.5
        add('anatomy_socket_alignment:'+center,
            abs(np.sum(displacement*span, axis=-1))/np.maximum(width**2, 1e-9)-.06)
    chain = ['pelvis', 'spine1', 'spine2', 'spine3', 'neck']
    if all(n in index for n in chain):
        if all(n in index for n in ('left_hip', 'right_hip')):
            hips = (point('left_hip')+point('right_hip'))*.5
            add('anatomy_torso_bend:spine1',
                np.deg2rad(145.)-angles(hips, point('spine1'), point('neck')))
        if all(n in index for n in ('left_collar', 'right_collar', 'left_shoulder', 'right_shoulder')):
            collars = (point('left_collar')+point('right_collar'))*.5
            shoulders = (point('left_shoulder')+point('right_shoulder'))*.5
            neck_axis = point('neck')-point('spine3')
            collar_axis = collars-point('spine3')
            cosine = np.sum(neck_axis*collar_axis, axis=-1)/np.maximum(
                np.linalg.norm(neck_axis, axis=-1)*np.linalg.norm(collar_axis, axis=-1), 1e-9)
            add('anatomy_chest_attachment:neck', np.cos(np.deg2rad(30.))-cosine)
            progress = np.sum((shoulders-point('spine3'))*neck_axis, axis=-1)/np.maximum(np.sum(neck_axis**2, axis=-1), 1e-9)
            add('anatomy_chest_attachment:shoulders', np.maximum(.35-progress, progress-1.25))
            if all(n in index for n in ('left_hip', 'right_hip')):
                add('anatomy_torso_bend:shoulders',
                    np.deg2rad(145.)-angles(hips, point('spine1'), shoulders))
        axis = point('neck')-point('pelvis')
        height = np.linalg.norm(axis, axis=-1)
        direction = axis/np.maximum(height[:, None], 1e-9)
        for name in chain[1:-1]:
            delta = point(name)-point('pelvis')
            progress = np.sum(delta*direction, axis=-1)
            deviation = np.linalg.norm(delta-progress[:, None]*direction, axis=-1)
            add('anatomy_spine_deviation:'+name, deviation/np.maximum(height, 1e-9)-.15)
        for a, b in zip(chain, chain[1:]):
            segment = point(b)-point(a)
            cosine = np.sum(segment*direction, axis=-1)/np.maximum(np.linalg.norm(segment, axis=-1), 1e-9)
            add('anatomy_spine_fold:'+b, np.cos(np.deg2rad(60.))-cosine)
        if 'head' in index:
            # Neck direction is relative to the upper chest, never world-up.
            value = angles(point('spine3'), point('neck'), point('head'))
            add('anatomy_neck_fold:head', np.deg2rad(95.)-value)
    for side in ('left', 'right'):
        for a, b, c in [('hip', 'knee', 'ankle'), ('shoulder', 'elbow', 'wrist')]:
            joints = [side+'_'+n for n in (a, b, c)]
            if all(n in index for n in joints):
                add('anatomy_hinge_collapse:'+joints[1],
                    np.deg2rad(15.)-angles(*(point(n) for n in joints)))
    return (np.stack(rows, axis=1) if rows else np.empty((len(points), 0))), labels


def validate_physical_motion(points, names, *, reference=None, fps=30., support_mask=None):
    """Evaluate final coordinates, independently of optimizer success/cost."""
    if not np.isfinite(points).all():
        return {"passed": False, "reasons": ['nonfinite_pose'], "events": [{'reason': 'nonfinite_pose'}]}
    index = {name: i for i, name in enumerate(names)}
    scale = body_scale(reference if reference is not None else points, names)
    events = []
    structure, labels = anatomical_structure_residuals(points, names)
    for frame, column in np.argwhere(structure > 1e-6):
        reason, joint = labels[column].split(':', 1)
        events.append({'reason': reason, 'joint': joint, 'frameIndex': int(frame)})
    # A malformed source must not authorize changing proportions over time.
    from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
    for name, parent in zip(SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS):
        if parent < 0 or name not in index or SMPL_JOINT_NAMES[parent] not in index:
            continue
        lengths = np.linalg.norm(points[:, index[name]]-points[:, index[SMPL_JOINT_NAMES[parent]]], axis=-1)
        median = float(np.median(lengths))
        for frame in np.flatnonzero(abs(lengths-median) > max(.005, median*.015)):
            events.append({'reason': 'anatomy_bone_length_variation', 'joint': name, 'frameIndex': int(frame)})
    if reference is not None:
        # Use the same body-relative, temporally supported branch definition
        # as the final articulation guard. Matching angles is not sufficient.
        from .models import MotionFrame
        from .structural_refinement import (
            _local_hinge_bend, _source_branch_is_temporally_supported, _transport_hinge_bend,
        )
        source_frames=[MotionFrame(i/fps,dict(zip(names,map(tuple,f)))) for i,f in enumerate(reference)]
        target_frames=[MotionFrame(i/fps,dict(zip(names,map(tuple,f)))) for i,f in enumerate(points)]
        for label,a,h,b,_ in ARTICULATIONS:
            if not label.endswith(('_knee','_elbow')) or not all(n in index for n in (a,h,b)):
                continue
            source_track=[_local_hinge_bend(f,a,h,b) for f in source_frames]
            proposed_track=[_local_hinge_bend(f,a,h,b) for f in target_frames]
            reliable=(np.sin(angles(*(reference[:,index[n]] for n in (a,h,b))))>np.sin(np.deg2rad(15.))) & (
                np.sin(angles(*(points[:,index[n]] for n in (a,h,b))))>np.sin(np.deg2rad(15.)))
            for frame in np.flatnonzero(reliable):
                source_bend,proposed_bend=source_track[frame],proposed_track[frame]
                if source_bend is None or proposed_bend is None or not _source_branch_is_temporally_supported(
                    source_track,int(frame),max(1,round(fps*.1))
                ):
                    continue
                transported=_transport_hinge_bend(source_bend[1],source_bend[0],proposed_bend[0])
                if np.dot(transported,proposed_bend[1])<0.:
                    events.append({'reason':'repair_hinge_branch_flip','joint':label,'frameIndex':int(frame)})
        for a,b in body_bones(names):
            lengths=np.linalg.norm(reference[:,a]-reference[:,b],axis=1)
            changes=np.abs(np.linalg.norm(points[:,a]-points[:,b],axis=1)-lengths)
            for frame in np.flatnonzero(changes>np.maximum(.005,lengths*.015)):
                events.append({'reason':'repair_bone_length_distortion','bone':names[a]+':'+names[b],
                               'frameIndex':int(frame),'changeMeters':float(changes[frame])})
        source_head = body_local_head_direction(reference, names)
        output_head = body_local_head_direction(points, names)
        if source_head is not None and output_head is not None:
            changes = np.rad2deg(np.arccos(np.clip(np.sum(source_head * output_head, axis=1), -1., 1.)))
            # Source-relative repair budget, not an absolute human neck limit.
            for frame in np.flatnonzero(changes > 15.25):
                events.append({'reason': 'repair_head_articulation_distortion', 'joint': 'head',
                               'frameIndex': int(frame), 'changeDegrees': float(changes[frame])})
    for label, parent, joint, child, tolerance in ARTICULATIONS:
        if not all(n in index for n in (parent, joint, child)):
            continue
        cols = [index[n] for n in (parent, joint, child)]
        values = np.rad2deg(angles(*(points[:, i] for i in cols)))
        if label.endswith('_ankle'):
            # Conservative repair policy: extreme collapse is never auto-approved.
            bad = (values < 35.) | (values > 165.)
            for frame in np.flatnonzero(bad):
                events.append({'reason': 'ankle_collapse', 'joint': label, 'frameIndex': int(frame), 'degrees': float(values[frame])})
        if reference is not None:
            baseline = np.rad2deg(angles(*(reference[:, i] for i in cols)))
            for frame in np.flatnonzero(np.abs(values-baseline) > tolerance + .25):
                events.append({'reason': 'repair_articulation_distortion', 'joint': label, 'frameIndex': int(frame), 'changeDegrees': float(values[frame]-baseline[frame])})
    clearances, labels = collision_clearances(points, names, scale)
    for frame, pair in np.argwhere(clearances < -.003):
        events.append({'reason': 'body_self_intersection', 'pair': labels[pair], 'frameIndex': int(frame), 'penetrationMeters': float(-clearances[frame, pair])})
    balance, outside = support_balance(points, names, fps, support_mask)
    # Dynamic support uncertainty must not block or drive motion repair.
    balance['advisoryWarning'] = bool(np.any(outside > .12*scale))
    balance['advisoryOnly'] = True
    return {'passed': not events, 'reasons': sorted({e['reason'] for e in events}),
            'events': events, 'balance': balance, 'collisionModel': 'inner_capsules',
            'policy': 'whole_body_repair_v5_anatomical_structure'}


def physical_metrics_from_payload(payload):
    frames = payload.get('frames') or []
    names = payload.get('jointNames') or []
    names = [n for n in names if all(n in f.get('joints', {}) for f in frames)]
    if not frames or not names:
        return {'passed': False, 'reasons': ['physical_pose_unavailable'], 'events': []}
    points = np.asarray([[f['joints'][n] for n in names] for f in frames], dtype=float)
    reference = None
    if all(all(n in f.get('sourceJoints', {}) for n in names) for f in frames):
        reference = np.asarray([[f['sourceJoints'][n] for n in names] for f in frames], dtype=float)
    fixed_rig = payload.get('fixedRig')
    if fixed_rig:
        if not all(all(n in f.get('controlledSourceJoints',{}) for n in names) for f in frames):
            return {'passed':False,'reasons':['fixed_rig_reference_unavailable'],'events':[]}
        reference=np.asarray([[f.get('controlledArticulationReferenceJoints',f['controlledSourceJoints'])[n] for n in names] for f in frames],dtype=float)
        if payload.get('anatomicalSourceRepair'):
            if not all(all(n in f.get('correctedAnatomicalReferenceJoints', {}) for n in names) for f in frames):
                return {'passed': False, 'reasons': ['anatomical_reference_unavailable'], 'events': []}
            reference = np.asarray([[f['correctedAnatomicalReferenceJoints'][n] for n in names] for f in frames], dtype=float)
            from .anatomical_repair import repair_residuals
            if not np.isfinite(reference).all() or np.any(repair_residuals(reference, names)[0] > 1e-6):
                return {'passed': False, 'reasons': ['anatomical_reference_invalid'],
                        'events': [{'reason': 'anatomical_reference_invalid'}]}
    supported={side:np.zeros(len(frames),dtype=bool) for side in ('left','right')}
    other_support=False
    for contact in motion_support_contacts(payload.get('sourceFootSupportEvidence')):
        name=str(contact.get('jointName',''))
        side=name.split('_')[0]
        if side in supported and name.endswith(('_foot','_ankle')):
            if contact.get('contactState')=='full_sole':
                start,end=contact_frame_bounds(contact,len(frames))
                supported[side][start:end+1]=True
        elif name:
            other_support=True
    support_mask=supported['left'] & supported['right']
    if other_support:
        support_mask[:]=False
    report=validate_physical_motion(points, names, reference=reference,
                                   fps=float(payload.get('fps') or 30.),support_mask=support_mask)
    if fixed_rig:
        # Calibrated rig lengths replace noisy source lengths, but every other
        # anatomical constraint and the actual interpolated playback still apply.
        report['events']=[e for e in report['events'] if e['reason']!='repair_bone_length_distortion']
        from .rig_playback import validate_rig_playback
        playback=validate_rig_playback(payload)
        report['rigPlayback']=playback
        if not playback['passed']:
            report['events'].append({'reason':'fixed_rig_playback_invalid'})
        if (payload.get('loop') or {}).get('enabled') and not playback['seamContinuous']:
            report['events'].append({'reason':'unsafe_loop_transition'})
        report['reasons']=sorted({e['reason'] for e in report['events']})
        report['passed']=not report['events']
    return report

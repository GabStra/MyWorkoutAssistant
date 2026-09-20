"""Observe support semantics in the source, then instantiate rig constraints.

Visual review owns contact identity; source tracks independently own stationarity.
Reconstructed joints supply dimensions, never evidence that a contact exists.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

POLICY_VERSION = 3
BODY_SUPPORT_ANCHORS = ('pelvis', 'left_shoulder', 'right_shoulder')
_REGION_ANCHORS = {
    'shoulders': ('left_shoulder', 'right_shoulder'),
    'upper_body': ('left_shoulder', 'right_shoulder'),
    'upper_limb': ('left_shoulder', 'right_shoulder'),
    'pelvis': ('pelvis',),
    'hips': ('pelvis',),
    'core': ('pelvis',),
}


def _contract_primary_moving_regions(contract):
    contract = contract or {}
    regions = set(contract.get('primaryMovingRegions') or [])
    spec = contract.get('observableMotionSpec') or {}
    if isinstance(spec, dict):
        regions.update(spec.get('primaryMovingRegions') or [])
    return {str(region).casefold() for region in regions if region}


def body_support_required_anchors(contract=None):
    """Stationary torso anchors, excluding joints the contract says must move."""
    excluded = set()
    for region in _contract_primary_moving_regions(contract):
        excluded.update(_REGION_ANCHORS.get(region, ()))
    return tuple(name for name in BODY_SUPPORT_ANCHORS if name not in excluded)


def requires_body_support(contract):
    contract = contract or {}
    moving = _contract_primary_moving_regions(contract)
    reference = set(contract.get('referenceRegions') or [])
    spec = contract.get('observableMotionSpec') or {}
    if isinstance(spec, dict):
        reference.update(spec.get('referenceRegions') or [])
    return ((contract.get('startPoseConstraints') or {}).get('supportMode') == 'lying'
            and 'torso' in {str(region).casefold() for region in reference}
            and not moving.intersection({'torso', 'spine', 'hips', 'pelvis', 'core'}))


def observe_body_support(video_path, caption_images, cache_dir):
    """One cached, target-blind contact observation for the exact selected cut."""
    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    cache = cache_dir / f'body-support-{digest}-v{POLICY_VERSION}.json'
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    if caption_images is None:
        return {'status': 'unknown', 'reason': 'support_observer_unavailable'}
    import cv2
    cache_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    paths = []
    try:
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        for index, ratio in enumerate((.05, .25, .5, .75, .95)):
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(max(0, count-1)*ratio))
            ok, frame = capture.read()
            if not ok:
                return {'status': 'unknown', 'reason': 'support_source_frame_unavailable'}
            path = cache_dir / f'{digest}-support-{index}.jpg'
            if not cv2.imwrite(str(path), frame):
                raise OSError(f'Cannot write support observation frame: {path}')
            paths.append(path)
    finally:
        capture.release()
    prompt = '''Inspect these chronological frames of the SAME source movement.
Report only visible support contacts; do not judge exercise correctness or infer
contacts from an exercise name. Stationary means resting at the same place on
the surface throughout the samples. A body part merely near a surface is NOT
confirmed support. Choose unknown when hidden or ambiguous. Do not mistake the
left/right sides of the image for the person's anatomical left/right.
Return JSON only with these exact fields:
{"torsoSurface":"horizontal|inclined|vertical|unknown",
 "pelvisAndUpperBackSameSurface":true or false,
 "pelvis":"stationary_support|moving|unknown",
 "upperBack":"stationary_support|moving|unknown",
 "head":"stationary_support|moving|unknown",
 "leftFoot":"stationary_full_sole|stationary_forefoot|moving|unknown",
 "rightFoot":"stationary_full_sole|stationary_forefoot|moving|unknown",
 "leftFootSurface":"ground|raised_surface|unknown",
 "rightFootSurface":"ground|raised_surface|unknown",
 "leftHand":"stationary_support|moving|unknown",
 "rightHand":"stationary_support|moving|unknown",
 "handsSameHorizontalSurface":true or false,
 "observations":"Brief visible evidence for the reported contacts"}
Horizontal describes the actual surface, not its apparent screen angle.
Full sole means heel AND forefoot visibly planted. A lifted heel is forefoot.
Do not assume both feet or hands agree when only one is visible.
For handsSameHorizontalSurface, require both hands visibly resting on the same
level surface throughout; a bar, handle, wall or hidden contact is not evidence
of a shared horizontal surface.'''
    raw = caption_images(frame_paths=paths, prompt=prompt, max_tokens=1000, temperature=0.)
    try:
        answer = json.loads(raw[raw.index('{'):raw.rindex('}')+1])
        if not isinstance(answer, dict):
            raise ValueError('Support response must be an object')
    except (ValueError, TypeError):
        return {'status': 'unknown', 'reason': 'support_observation_unparseable'}
    result = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
              'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
              'observation': answer}
    cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def stationary_source_track(source_pose, joint):
    """Reject absent, sparse, moving, or low-confidence source observations."""
    from .bake_and_rank import (
        SOURCE_POSE_SUPPORT_STATIONARY_CHUNK_RANGE_RATIO_THRESHOLD,
        SOURCE_POSE_SUPPORT_STATIONARY_ENDPOINT_RATIO_THRESHOLD,
    )
    frames = (source_pose or {}).get('frames') or []
    if len(frames) < 6:
        return False
    key = 'nose' if joint == 'head' else joint
    tracks = []
    spans = []
    for index, frame in enumerate(frames):
        joints = frame.get('joints') or {}
        p = joints.get(key)
        confidence = (frame.get('jointConfidence') or {}).get(key, 1.)
        if (p is not None and confidence >= .5 and np.isfinite(p[:2]).all()
                and (source_pose.get('coordinateSpace') != 'normalized_image_xy'
                     or all(0. <= value <= 1. for value in p[:2]))):
            tracks.append((index, np.asarray(p[:2], dtype=float)))
        if joints:
            points = np.asarray(list(joints.values()), dtype=float)[:, :2]
            spans.append(np.linalg.norm(np.ptp(points, axis=0)))
    if len(tracks) < max(6, .7*len(frames)) or not spans:
        return False
    indexes, points = zip(*tracks)
    if indexes[0] > .15*len(frames) or indexes[-1] < .85*(len(frames)-1):
        return False
    centers = np.asarray([np.median(chunk, axis=0) for chunk in np.array_split(points, 4)])
    scale = max(float(np.median(spans)), 1e-8)
    return bool(np.isfinite(centers).all()
                and np.linalg.norm(np.ptp(centers, axis=0))/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_CHUNK_RANGE_RATIO_THRESHOLD
                and np.linalg.norm(centers[-1]-centers[0])/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_ENDPOINT_RATIO_THRESHOLD)


def materialize_body_support(payload, source_pose, contract=None):
    """Convert confirmed contacts to constraints in the baked coordinate frame.

    Stationary anchors respect the contract's primary movers (e.g. shoulders on
    a lying press). Readiness and plane pin use that filtered anchor set; the
    bench/normal direction may still be estimated from torso landmark medians.
    """
    evidence = payload.get('sourceFootSupportEvidence') or {}
    if (evidence.get('bodySupport') or {}).get('status') == 'confirmed':
        return  # Existing explicit source annotations remain authoritative.
    observed = evidence.get('bodySupportObservation') or {}
    answer = observed.get('observation') or {}
    anchors = list(body_support_required_anchors(contract))
    if not (observed.get('status') == 'observed'
            and answer.get('pelvisAndUpperBackSameSurface') is True
            and answer.get('pelvis') == answer.get('upperBack') == 'stationary_support'
            and answer.get('torsoSurface') in {'horizontal', 'inclined', 'vertical'}
            and body_support_source_readiness(source_pose, contract)['ready']):
        return
    if not anchors:
        return
    names = payload.get('jointNames') or []
    plane_refs = [name for name in BODY_SUPPORT_ANCHORS if name in names]
    required = list(dict.fromkeys([*anchors, *plane_refs, 'neck', 'spine1', 'spine2', 'spine3']))
    if not set(required).issubset(names) or not payload.get('frames'):
        return
    medians = {n: np.median([f['joints'][n] for f in payload['frames']], axis=0) for n in names}
    normal = np.array([0., 1., 0.])
    if answer['torsoSurface'] != 'horizontal':
        side = medians['right_shoulder']-medians['left_shoulder']
        longitudinal = (medians['left_shoulder']+medians['right_shoulder'])*.5-medians['pelvis']
        normal = np.cross(side, longitudinal)
        if np.linalg.norm(normal) < 1e-8:
            return
        normal /= np.linalg.norm(normal)
        if normal[1] < 0:
            normal *= -1
    normal = normal.tolist()
    plane_offset = float(np.dot(medians[anchors[0]], normal))
    support = {'required': True, 'status': 'confirmed',
               'source': 'exact_source_contacts_and_stationary_pose_tracks',
               'sourceVideoSha256': observed['sourceVideoSha256'],
               'observation': deepcopy(answer), 'stationaryJoints': list(anchors),
               'coplanarGroups': [{'joints': list(anchors), 'normal': normal,
                                   'anchorJoint': anchors[0],
                                   'planeOffsetMeters': plane_offset}],
               'nonPenetrationChains': [{'endpoints': ['pelvis', 'neck'],
                                         'joints': ['spine1', 'spine2', 'spine3'], 'normal': normal}],
               'soleContacts': []}
    if answer.get('head') == 'stationary_support' and stationary_source_track(source_pose, 'head'):
        support['stationaryJoints'].append('head')
    sides = []
    for side in ('left', 'right'):
        if (answer.get(f'{side}Foot') != 'stationary_full_sole'
                or answer.get(f'{side}FootSurface') != 'ground'
                or not stationary_source_track(source_pose, f'{side}_ankle')):
            continue
        sides.append(side)
    add_ground_sole_contacts(payload, support, medians, sides)
    evidence['bodySupport'] = support


def _support_for_observed_contacts(evidence, observed):
    support = evidence.get('bodySupport') or {}
    if support.get('required') and support.get('status') != 'confirmed':
        return None  # Distal evidence cannot resolve an unknown torso support.
    return deepcopy(support) if support else {
        'required': True, 'status': 'confirmed',
        'source': 'exact_source_contacts_and_stationary_pose_tracks',
        'sourceVideoSha256': observed.get('sourceVideoSha256'),
        'stationaryJoints': [], 'coplanarGroups': [],
        'nonPenetrationChains': [], 'soleContacts': []}


def materialize_hand_support(payload, source_pose):
    """Constrain observed hand contacts without freezing the torso or arms."""
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = observed.get('observation') or {}
    if observed.get('status') != 'observed':
        return
    stationary = [f'{side}_wrist' for side in ('left', 'right')
                  if answer.get(f'{side}Hand') == 'stationary_support'
                  and f'{side}_wrist' in payload.get('jointNames', [])
                  and stationary_source_track(source_pose, f'{side}_wrist')]
    if not stationary:
        return
    support = _support_for_observed_contacts(evidence, observed)
    if support is None:
        return
    support['stationaryJoints'] = list(dict.fromkeys(support['stationaryJoints'] + stationary))
    group = {'joints': stationary, 'normal': [0., 1., 0.]}
    if (len(stationary) == 2 and answer.get('handsSameHorizontalSurface') is True
            and group not in support['coplanarGroups']):
        support['coplanarGroups'].append(group)
    evidence['bodySupport'] = support


def materialize_observed_ground_contacts(payload, source_pose):
    """Full sole and forefoot observations both establish a planted toe.

    This deliberately says nothing about heel height or shoe pitch. Those
    require independent heel/toe geometry, even when a visual label says sole.
    """
    # A few support-review frames cannot establish an uninterrupted ground
    # anchor when the movement permits release. Keep the timed observations.
    if payload.get('groundContactMode') in {'intermittent', 'none'}:
        return
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = observed.get('observation') or {}
    floor = payload.get('renderFloorY')
    if (observed.get('status') != 'observed' or not isinstance(floor, (int, float))
            or not np.isfinite(floor)):
        return
    contacts = []
    for side in ('left', 'right'):
        states = ((evidence.get('footPatchEvidence') or {}).get('feet', {}).get(side) or {}).get('states', [])
        if (answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
                and answer.get(f'{side}FootSurface') == 'ground'
                and f'{side}_foot' in payload.get('jointNames', [])
                and stationary_source_track(source_pose, f'{side}_ankle')
                and not any(state in {'airborne', 'heel_only'} for state in states)):
            contacts.append(f'{side}_foot')
    if not contacts:
        return
    support = _support_for_observed_contacts(evidence, observed)
    if support is None:
        return
    # Existing calibrated full-sole geometry already owns these toe heights.
    contacts = [name for name in contacts if name not in support['stationaryJoints']]
    if not contacts:
        return
    support['stationaryJoints'].extend(contacts)
    support['coplanarGroups'].append({'joints': contacts, 'normal': [0., 1., 0.],
                                     'planeOffsetMeters': float(floor)})
    evidence['bodySupport'] = support


def add_ground_sole_contacts(payload, support, medians, sides):
    """Use the same shoe dimensions for every explicitly observed ground contact."""
    hip_width = np.linalg.norm(medians['right_hip']-medians['left_hip'])
    shoulder_width = np.linalg.norm(medians['right_shoulder']-medians['left_shoulder'])
    foot_scale = max(hip_width*.98, shoulder_width*.58)
    for side in sides:
        ankle, foot, knee = [f'{side}_{part}' for part in ('ankle', 'foot', 'knee')]
        if not {ankle, foot, knee}.issubset(medians):
            continue
        shoe_height = max(np.linalg.norm(medians[foot]-medians[ankle])*.28, foot_scale*.15)
        for joint in (ankle, foot):
            if joint not in support['stationaryJoints']:
                support['stationaryJoints'].append(joint)
        support['coplanarGroups'].append({'joints': [ankle, foot], 'normal': [0, 1, 0],
            'planeOffsetMeters': float(payload.get('renderFloorY') or 0.)+.04*shoe_height})
        support['soleContacts'].append({'joints': [knee, ankle, foot], 'normal': [0, 1, 0]})


def observed_stationary_sole_contacts(evidence):
    from .contact_constraints import motion_support_contacts
    return [c for c in motion_support_contacts(evidence)
            if c.get('contactState') == 'full_sole' and c.get('contactMotion') == 'stationary'
            and c.get('verticalOnly') is not True]


def corroborated_stationary_sole(evidence, side):
    """Bridge unobserved sole samples only with independent full-stance evidence."""
    if evidence.get('temporalResolutionSufficient') is not True:
        return False
    patch = evidence.get('footPatchEvidence') or {}
    states = (patch.get('feet', {}).get(side) or {}).get('states') or []
    if not patch.get('available') or not states or 'full_sole' not in states:
        return False
    if any(state not in {'unknown', 'full_sole'} for state in states):
        return False
    # These ratios describe the full source, so this evidence also covers any
    # selected subinterval. Partial ankle tracks cannot fill missing contacts.
    return any(c.get('jointName') == f'{side}_ankle'
               and c.get('contactMotion') == 'stationary'
               and c.get('startRatio') == 0. and c.get('endRatio') == 1.
               for c in evidence.get('footContactCandidates') or [])


def materialize_stationary_sole_support(payload):
    """Materialize full-cycle ground contacts after selecting/slicing a cycle."""
    from .contact_constraints import contact_frame_bounds
    evidence = payload.get('sourceFootSupportEvidence') or {}
    existing = evidence.get('bodySupport') or {}
    if existing.get('required') and existing.get('status') != 'confirmed':
        return  # New foot evidence cannot resolve missing torso observations.
    observed = evidence.get('bodySupportObservation') or {}
    if observed.get('status') != 'observed':
        return
    answer = observed.get('observation') or {}
    count = len(payload.get('frames') or [])
    names = payload.get('jointNames') or []
    if count < 7 or not {'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder'}.issubset(names):
        return
    floor = payload.get('renderFloorY')
    if not isinstance(floor, (int, float)) or not np.isfinite(floor):
        return
    sides = []
    existing_soles = {c['joints'][2] for c in existing.get('soleContacts', [])}
    for side in ('left', 'right'):
        if f'{side}_foot' in existing_soles:
            continue
        if answer.get(f'{side}Foot') != 'stationary_full_sole' or answer.get(f'{side}FootSurface') != 'ground':
            continue
        contacts = [c for c in observed_stationary_sole_contacts(evidence)
                    if c.get('jointName') == f'{side}_foot']
        if any(('startRatio' in c or 'startFrame' in c) and ('endRatio' in c or 'endFrame' in c)
               and contact_frame_bounds(c, count) == (0, count-1)
               for c in contacts) or (contacts and corroborated_stationary_sole(evidence, side)):
            sides.append(side)
    if not sides:
        return
    medians = {n: np.median([f['joints'][n] for f in payload['frames']], axis=0) for n in names}
    support = deepcopy(existing) if existing else {'required': True, 'status': 'confirmed',
               'source': 'observed_full_cycle_ground_sole_contacts',
               'sourceVideoSha256': observed.get('sourceVideoSha256'),
               'stationaryJoints': [], 'coplanarGroups': [], 'nonPenetrationChains': [], 'soleContacts': []}
    for field in ('stationaryJoints', 'coplanarGroups', 'nonPenetrationChains', 'soleContacts'):
        support.setdefault(field, [])
    affected = {f'{side}_{part}' for side in sides for part in ('ankle', 'foot')}
    groups = []
    for group in support['coplanarGroups']:
        joints = [name for name in group['joints'] if name not in affected]
        if joints:
            groups.append({**group, 'joints': joints})
    support['coplanarGroups'] = groups
    add_ground_sole_contacts(payload, support, medians, sides)
    if support['soleContacts']:
        evidence['bodySupport'] = support


def body_support_source_readiness(source_pose, contract=None):
    """Expose the fitter's existing evidence prerequisites before reconstruction."""
    anchors = body_support_required_anchors(contract)
    if not anchors:
        return {'required': True, 'ready': True, 'unresolvedAnchors': [],
                'reason': 'no_stationary_body_support_anchors_required',
                'requiredAnchors': []}
    unresolved = [name for name in anchors
                  if not stationary_source_track(source_pose, name)]
    return {'required': True, 'ready': not unresolved, 'unresolvedAnchors': unresolved,
            'requiredAnchors': list(anchors),
            'reason': 'stationary_support_anchors_observed' if not unresolved
                      else 'supported_body_stationarity_unresolved'}

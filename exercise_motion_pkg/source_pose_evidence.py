"""Audit image landmark identity before using a detector as pose evidence."""
from copy import deepcopy
from pathlib import Path

import numpy as np

POLICY_VERSION = 1
PAIRS = (('wrist', ('shoulder', 'elbow', 'wrist')), ('ankle', ('hip', 'knee', 'ankle')))


def suspicious_tracks(payload):
    """Flag abrupt unilateral association jumps into a previously separate limb.

    Proximity alone is not an error: crossing, clapping, and changing perspective
    are legitimate. A flag requires a collapse plus a one-sided discontinuity
    while the other observed body landmarks remain comparatively stable.
    """
    frames = payload.get('frames') or []
    if payload.get('coordinateSpace') != 'normalized_image_xy' or len(frames) < 5:
        return {}
    width, height = payload.get('imageWidth', 0), payload.get('imageHeight', 0)
    if min(width, height) <= 0:
        return {}
    factor = np.array([width/height, 1.])
    def point(frame, name):
        value = frame.get('joints', {}).get(name)
        if value is None or frame.get('jointConfidence', {}).get(name, 1.) < .35:
            return None
        value = np.asarray(value[:2], dtype=float) * factor
        return value if np.isfinite(value).all() else None
    spans = []
    for frame in frames:
        values = [point(frame, n) for n in frame.get('joints', {}) if n.startswith(('left_', 'right_'))]
        values = [v for v in values if v is not None]
        if len(values) >= 6:
            spans.append(float(np.ptp(values, axis=0).max()))
    scale = float(np.median(spans)) if spans else 0.
    if scale <= 1e-8:
        return {}
    flagged = {}
    for endpoint, chain in PAIRS:
        tracks = [[point(f, f'{side}_{endpoint}') for f in frames] for side in ('left', 'right')]
        spacing = np.array([np.linalg.norm(a-b) if a is not None and b is not None else np.nan
                            for a, b in zip(*tracks)])
        valid = spacing[np.isfinite(spacing)]
        if len(valid) < 5:
            continue
        normal = float(np.percentile(valid, 75))
        if normal < .15 * scale:
            continue
        collapsed = spacing < .45 * normal
        for i in range(1, len(frames)):
            dt = frames[i].get('sourceTimeSec', i)-frames[i-1].get('sourceTimeSec', i-1)
            if not (0 < dt <= .3 and collapsed[i] and not collapsed[i-1]):
                continue
            if any(track[i] is None or track[i-1] is None for track in tracks):
                continue
            steps = [float(np.linalg.norm(track[i]-track[i-1])) for track in tracks]
            moving = int(np.argmax(steps))
            names = [n for n in frames[i]['joints'] if n.startswith(('left_', 'right_'))]
            body_steps = [np.linalg.norm(point(frames[i], n)-point(frames[i-1], n)) for n in names
                          if point(frames[i], n) is not None and point(frames[i-1], n) is not None]
            if (steps[moving] < .15*scale or steps[moving] < 3*max(steps[1-moving], .01*scale)
                    or np.median(body_steps) > .08*scale):
                continue
            side = ('left', 'right')[moving]
            stop = i
            while stop < len(frames) and collapsed[stop]:
                flagged.setdefault(stop, set()).update(f'{side}_{joint}' for joint in chain)
                stop += 1
    return flagged


def audit_source_pose(payload, observations=None):
    """Recover only independently supported observations; otherwise abstain."""
    if (payload.get('sourcePoseEvidenceAudit') or {}).get('policyVersion') == POLICY_VERSION:
        return payload
    result = deepcopy(payload)
    flags = suspicious_tracks(payload)
    frames = result.get('frames', [])
    secondary = (observations or {}).get('frames', [])
    factor = np.array([payload.get('imageWidth', 1)/max(payload.get('imageHeight', 1), 1), 1.])
    events = []
    for index, names in sorted(flags.items()):
        frame = frames[index]
        time = frame['sourceTimeSec']
        other = min(secondary, key=lambda f: abs(f['timeSeconds']-time), default=None)
        if other is not None and abs(other['timeSeconds']-time) > .07:
            other = None
        anchors, errors = [], []
        for name, value in frame['joints'].items():
            if name in names or not name.startswith(('left_', 'right_')):
                continue
            observed = (other or {}).get('joints', {}).get(name, {})
            if observed.get('confidence', 0) < .65 or frame.get('jointConfidence', {}).get(name, 0) < .65:
                continue
            primary = np.asarray(value[:2])*factor
            independent = np.asarray(observed['image'])*factor
            anchors.append(primary)
            errors.append(float(np.linalg.norm(primary-independent)))
        span = float(np.ptp(anchors, axis=0).max()) if len(anchors) >= 6 else 0.
        anchored = span > 0 and np.median(errors) < .08*span and np.percentile(errors, 90) < .15*span
        recovered = {}
        if anchored:
            for name in names:
                observed = other['joints'].get(name, {})
                if observed.get('confidence', 0) < .65:
                    continue
                candidate = np.asarray(observed['image'])*factor
                primary = np.asarray(payload['frames'][index]['joints'][name][:2])*factor
                if np.linalg.norm(candidate-primary) < .05*span:
                    recovered[name] = observed
                    continue
                # A replacement must also connect to trusted temporal context.
                neighbors = [i for i in range(len(frames)) if i not in flags and name in payload['frames'][i]['joints']]
                before = max((i for i in neighbors if i < index), default=None)
                after = min((i for i in neighbors if i > index), default=None)
                if before is None or after is None:
                    continue
                boundary = [np.asarray(payload['frames'][i]['joints'][name][:2])*factor for i in (before, after)]
                if max(np.linalg.norm(candidate-v) for v in boundary) > .30*span:
                    continue
                recovered[name] = observed
        # A limb is one association, so do not mix a partly recovered chain
        # with the original contradictory shoulder/elbow/wrist identities.
        resolved = len(recovered) == len(names)
        for name in names:
            if resolved:
                frame['joints'][name] = [*recovered[name]['image'], 0.]
                frame.setdefault('jointConfidence', {})[name] = recovered[name]['confidence']
            else:
                frame['joints'].pop(name, None)
                frame.setdefault('jointConfidence', {})[name] = 0.
        for derived, dependencies in (('shoulders', ('left_shoulder', 'right_shoulder')),
                                      ('pelvis', ('left_hip', 'right_hip')), ('hips', ('left_hip', 'right_hip'))):
            if any(name in names for name in dependencies):
                if all(name in frame['joints'] for name in dependencies):
                    frame['joints'][derived] = np.mean([frame['joints'][n] for n in dependencies], axis=0).tolist()
                else:
                    frame['joints'].pop(derived, None)
        events.append({'frameIndex': index, 'sourceTimeSec': time, 'joints': sorted(names),
                       'originalJoints': {n: payload['frames'][index]['joints'].get(n) for n in names},
                       'originalConfidence': {n: payload['frames'][index].get('jointConfidence', {}).get(n) for n in names},
                       'reason': 'unilateral_limb_association_collapse',
                       'status': 'recovered' if resolved else 'unknown',
                       'independentAnchorsAgree': bool(anchored)})
    result['sourcePoseEvidenceAudit'] = {'policyVersion': POLICY_VERSION, 'events': events,
        'unresolved': any(e['status'] == 'unknown' for e in events),
        'independentSource': (observations or {}).get('source'),
        'independentAvailable': bool((observations or {}).get('available'))}
    return result


def verify_source_pose(payload, video_path: Path | None):
    if not isinstance(payload, dict):
        return payload
    if (payload.get('sourcePoseEvidenceAudit') or {}).get('policyVersion') == POLICY_VERSION:
        return payload
    observations = None
    if suspicious_tracks(payload) and video_path is not None:
        from .foot_contact_observation import observe_foot_landmarks
        try:
            observations = observe_foot_landmarks(video_path)
        except (OSError, ValueError, RuntimeError) as error:
            observations = {'available': False, 'reason': str(error)}
    return audit_source_pose(payload, observations)


# The audit is a data-cleaning pass, not a gate: it removes joints it cannot
# trust and records what it found (`unresolved` marks recovery gaps for
# diagnostics). Whether the cleaned remainder is good enough is decided by
# the phase, contract, support, and fidelity validations that consume it —
# and ultimately by the VLM review of the rendered movement.


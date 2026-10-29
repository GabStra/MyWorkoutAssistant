"""Observe support semantics in the source, then instantiate rig constraints.

Visual review owns contact identity; source tracks independently own stationarity.
Reconstructed joints supply dimensions, never evidence that a contact exists.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

POLICY_VERSION = 5
BODY_SUPPORT_ANCHORS = ('pelvis', 'left_shoulder', 'right_shoulder')
_REGION_ANCHORS = {
    'shoulders': ('left_shoulder', 'right_shoulder'),
    'upper_body': ('left_shoulder', 'right_shoulder'),
    'upper_limb': ('left_shoulder', 'right_shoulder'),
    'pelvis': ('pelvis',),
    'hips': ('pelvis',),
    'core': ('pelvis',),
}
_SUPPORT_SURFACES = {'floor', 'bench', 'seat', 'wall', 'other'}
_OBSERVATION_FIELDS = {
    'torsoSurface', 'pelvisAndUpperBackSameSurface', 'pelvis', 'upperBack', 'head',
    'pelvisContactSurface', 'upperBackContactSurface', 'headContactSurface',
    'leftFoot', 'rightFoot', 'leftFootSurface', 'rightFootSurface',
    'leftHand', 'rightHand', 'handsSameHorizontalSurface', 'observations',
}
CONTACT_TIMELINE_POLICY_VERSION = 1
_CONTACT_STATES = {'full_sole', 'forefoot', 'heel_only', 'airborne', 'unknown'}
_CONTACT_SURFACES = {'ground', 'raised_surface', 'none', 'unknown'}
_MAX_CONTACT_TIMELINE_SAMPLES = 24
CONTACT_TIMELINE_CROP_POLICY = 'ankle-centered-marked-header-atlas-v3'


def validated_body_support_answer(observed):
    """Return only current, schema-valid support claims; incomplete fields stay unknown."""
    if (not isinstance(observed, dict)
            or observed.get('status') != 'observed'
            or observed.get('source') != 'exact_source_visual_support_observation'
            or not isinstance(observed.get('sourceVideoSha256'), str)
            or not observed['sourceVideoSha256'].strip()
            or observed.get('policyVersion') != POLICY_VERSION):
        return None
    answer = observed.get('observation')
    if not isinstance(answer, dict) or not answer or set(answer) - _OBSERVATION_FIELDS:
        return None
    if not set(answer).intersection(_OBSERVATION_FIELDS - {'observations'}):
        return None
    answer = deepcopy(answer)
    enum_fields = {
        'torsoSurface': {'horizontal', 'inclined', 'vertical', 'unknown'},
        'pelvis': {'stationary_support', 'moving', 'unknown'},
        'upperBack': {'stationary_support', 'moving', 'unknown'},
        'head': {'stationary_support', 'moving', 'unknown'},
        'pelvisContactSurface': _SUPPORT_SURFACES | {'none', 'unknown'},
        'upperBackContactSurface': _SUPPORT_SURFACES | {'none', 'unknown'},
        'headContactSurface': _SUPPORT_SURFACES | {'none', 'unknown'},
        'leftFoot': {'stationary_full_sole', 'stationary_forefoot', 'moving', 'unknown'},
        'rightFoot': {'stationary_full_sole', 'stationary_forefoot', 'moving', 'unknown'},
        'leftFootSurface': {'ground', 'raised_surface', 'unknown'},
        'rightFootSurface': {'ground', 'raised_surface', 'unknown'},
        'leftHand': {'stationary_support', 'moving', 'unknown'},
        'rightHand': {'stationary_support', 'moving', 'unknown'},
    }
    for field, choices in enum_fields.items():
        if field in answer and (not isinstance(answer[field], str) or answer[field] not in choices):
            return None
    for field in ('pelvisAndUpperBackSameSurface', 'handsSameHorizontalSurface'):
        if field in answer and not isinstance(answer[field], bool):
            return None
    if 'observations' in answer and not isinstance(answer['observations'], str):
        return None
    for region in ('pelvis', 'upperBack', 'head'):
        state, surface = answer.get(region), answer.get(f'{region}ContactSurface')
        if state == 'stationary_support' and surface not in _SUPPORT_SURFACES:
            return None
        elif state == 'unknown' and surface in _SUPPORT_SURFACES:
            return None
    if answer.get('pelvisAndUpperBackSameSurface') is True:
        same_surface = (
            answer.get('pelvis') == answer.get('upperBack') == 'stationary_support'
            and answer.get('pelvisContactSurface') in _SUPPORT_SURFACES
            and answer.get('pelvisContactSurface') == answer.get('upperBackContactSurface')
        )
        if not same_surface:
            return None
    for side in ('left', 'right'):
        if (answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
                and answer.get(f'{side}FootSurface') not in {'ground', 'raised_surface'}):
            return None
        if answer.get(f'{side}Foot') == 'unknown':
            if answer.get(f'{side}FootSurface') in {'ground', 'raised_surface'}:
                return None
    if answer.get('handsSameHorizontalSurface') is True and not (
            answer.get('leftHand') == answer.get('rightHand') == 'stationary_support'):
        return None
    return answer


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


def source_support_observation_needed(source_pose, evidence):
    """Source tracks request contact observation; contracts cannot declare contact."""
    return bool(observed_stationary_sole_contacts(evidence)) or any(
        stationary_source_track(source_pose, name)
        for name in (*BODY_SUPPORT_ANCHORS, 'left_wrist', 'right_wrist', 'left_ankle', 'right_ankle'))


def observe_body_support(video_path, caption_images, cache_dir):
    """One cached, target-blind contact observation for the exact selected cut."""
    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    cache = cache_dir / f'body-support-{digest}-v{POLICY_VERSION}.json'
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = None
        if (isinstance(cached, dict) and cached.get('status') == 'unknown'
                and cached.get('policyVersion') == POLICY_VERSION
                and cached.get('sourceVideoSha256') == digest):
            return cached
        answer = validated_body_support_answer(cached)
        if answer is not None and cached.get('sourceVideoSha256') == digest:
            return {**cached, 'observation': answer}
        # A malformed v5 result gets one fresh observation, then an unknown
        # cache entry prevents repeated model calls for the same source bytes.
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
 "pelvisContactSurface":"floor|bench|seat|wall|other|none|unknown",
 "upperBackContactSurface":"floor|bench|seat|wall|other|none|unknown",
 "headContactSurface":"floor|bench|seat|wall|other|none|unknown",
 "leftFoot":"stationary_full_sole|stationary_forefoot|moving|unknown",
 "rightFoot":"stationary_full_sole|stationary_forefoot|moving|unknown",
 "leftFootSurface":"ground|raised_surface|unknown",
 "rightFootSurface":"ground|raised_surface|unknown",
 "leftHand":"stationary_support|moving|unknown",
 "rightHand":"stationary_support|moving|unknown",
 "handsSameHorizontalSurface":true or false,
 "observations":"Brief visible evidence for the reported contacts"}
Horizontal describes the actual surface, not its apparent screen angle.
ContactSurface means DIRECT visible contact with that surface, not indirect
support through the feet. A free-standing torso has contact surface none even
when upright and stationary. Require direct contact throughout the samples.
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
    validated = validated_body_support_answer(result)
    if validated is None:
        result = {'status': 'unknown', 'reason': 'support_observation_schema_invalid',
                  'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION}
        cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result['observation'] = validated
    cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def _contact_timeline_candidates(source_pose, evidence):
    """Select bounded, code-owned pose samples only inside unknown patch intervals."""
    pose = source_pose if isinstance(source_pose, dict) else {}
    if pose.get('coordinateSpace') != 'normalized_image_xy':
        return []
    frames = pose.get('frames') or []
    patch = (evidence or {}).get('footPatchEvidence') or {}
    times = patch.get('sourceTimesSec')
    feet = patch.get('feet') or {}
    if not isinstance(times, list) or not times:
        return []
    try:
        cadences = np.diff(np.asarray(times, dtype=float))
        cadences = cadences[np.isfinite(cadences) & (cadences > 0.)]
    except (TypeError, ValueError):
        return []
    cadence = float(np.median(cadences)) if len(cadences) else None
    if cadence is None:
        return []

    candidates = []
    for side in ('left', 'right'):
        foot_patch = feet.get(side) or {}
        states = foot_patch.get('states') or []
        intervals = ((evidence or {}).get('feet') or {}).get(side, {}).get('contactIntervals') or []
        unknown_intervals = []
        for interval_index, interval in enumerate(intervals):
            if (interval.get('contactMotion') != 'stationary'
                    or interval.get('sourceTimeBasis') != patch.get('sourceTimeBasis')):
                continue
            try:
                start = float(interval['sourceStartTimeSec'])
                end = float(interval['sourceEndTimeSec'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not np.isfinite([start, end]).all() or end < start:
                continue
            pose_samples = []
            for pose_index, frame in enumerate(frames):
                try:
                    source_time = float(frame['sourceTimeSec'])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                joints = frame.get('joints') or {}
                point = joints.get(f'{side}_ankle')
                confidence = (frame.get('jointConfidence') or {}).get(f'{side}_ankle', 0.)
                if (not start <= source_time <= end or point is None or confidence < .5
                        or len(point) < 2 or not np.isfinite(point[:2]).all()
                        or any(value < 0. or value > 1. for value in point[:2])):
                    continue
                try:
                    patch_index = min(range(len(times)),
                                      key=lambda index: abs(float(times[index]) - source_time))
                    patch_time = float(times[patch_index])
                except (TypeError, ValueError, OverflowError):
                    continue
                if (patch_index >= len(states) or str(states[patch_index]).casefold() != 'unknown'
                        or not np.isfinite(patch_time)
                        or abs(patch_time - source_time) > cadence * .5 + 1e-6):
                    continue
                pose_samples.append({
                    'side': side, 'poseFrameIndex': pose_index,
                    'sourceTimeSec': source_time,
                    'ankle': [float(point[0]), float(point[1])],
                    'intervalIndex': interval_index,
                    'stationaryStartTimeSec': start,
                    'stationaryEndTimeSec': end,
                })
            if pose_samples:
                # Boundary and interior samples expose variation without turning
                # sparse visual observations into an interval-wide contact claim.
                indexes = sorted({0, len(pose_samples) // 2, len(pose_samples) - 1})
                unknown_intervals.extend(pose_samples[index] for index in indexes)
        candidates.extend(unknown_intervals)

    deduplicated = {}
    for row in candidates:
        key = (row['side'], row['poseFrameIndex'])
        deduplicated[key] = row
    ordered = sorted(deduplicated.values(), key=lambda row: (row['sourceTimeSec'], row['side']))
    if len(ordered) > _MAX_CONTACT_TIMELINE_SAMPLES:
        return []
    for row in ordered:
        row['sampleId'] = f"contact-{row['side']}-pose-{row['poseFrameIndex']}"
        row['sourceTrackStationary'] = True
    return ordered


def _render_contact_timeline_crop(cv2, frame, candidate):
    """Mark the code-selected ankle and put its label outside source pixels."""
    frame_height, frame_width = frame.shape[:2]
    radius_x = max(16, int(round(frame_width * .075)))
    radius_y_top = max(8, int(round(frame_height * .025)))
    radius_y_bottom = max(24, int(round(frame_height * .13)))
    ankle_x, ankle_y = candidate['ankle']
    x = int(round(ankle_x * frame_width))
    y = int(round(ankle_y * frame_height))
    x0, x1 = max(0, x - radius_x), min(frame_width, x + radius_x)
    y0, y1 = max(0, y - radius_y_top), min(frame_height, y + radius_y_bottom)
    if x1 <= x0 or y1 <= y0:
        return None

    crop = frame[y0:y1, x0:x1].copy()
    label = f"TARGET {candidate['side'].upper()} FOOT  {candidate['sampleId']}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale, thickness = .48, 1
    (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
    padding_x, padding_y = 8, 6
    header_height = text_height + baseline + 2 * padding_y
    canvas_width = max(crop.shape[1], text_width + 2 * padding_x)
    left_padding = (canvas_width - crop.shape[1]) // 2
    right_padding = canvas_width - crop.shape[1] - left_padding
    canvas = cv2.copyMakeBorder(
        crop, header_height, 0, left_padding, right_padding,
        cv2.BORDER_CONSTANT, value=(24, 24, 24))
    cv2.putText(canvas, label, (padding_x, padding_y + text_height), font,
                font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    marker_x = left_padding + x - x0
    marker_y = header_height + y - y0
    # Black outlines keep the crosshair visible against both the shoe and floor.
    cv2.circle(canvas, (marker_x, marker_y), 5, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.line(canvas, (marker_x - 7, marker_y), (marker_x + 7, marker_y),
             (0, 0, 0), 4, cv2.LINE_AA)
    cv2.line(canvas, (marker_x, marker_y - 7), (marker_x, marker_y + 7),
             (0, 0, 0), 4, cv2.LINE_AA)
    cv2.circle(canvas, (marker_x, marker_y), 5, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.line(canvas, (marker_x - 7, marker_y), (marker_x + 7, marker_y),
             (0, 255, 255), 1, cv2.LINE_AA)
    cv2.line(canvas, (marker_x, marker_y - 7), (marker_x, marker_y + 7),
             (0, 255, 255), 1, cv2.LINE_AA)
    return canvas, (marker_x, marker_y), (x0, y0, x1, y1), header_height


def _assemble_contact_timeline_atlas(tiles, sample_ids, columns=3, gutter=8):
    """Pack labeled native-size tiles into one lossless, bounded image input."""
    if (not tiles or len(tiles) != len(sample_ids)
            or len(set(sample_ids)) != len(sample_ids)
            or type(columns) is not int or columns < 1):
        return None
    columns = min(columns, len(tiles))
    cell_width = max(tile.shape[1] for tile in tiles)
    cell_height = max(tile.shape[0] for tile in tiles)
    rows = (len(tiles) + columns - 1) // columns
    atlas = np.full((rows * cell_height + (rows + 1) * gutter,
                     columns * cell_width + (columns + 1) * gutter, 3),
                    24, dtype=np.uint8)
    positions = []
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        x = gutter + column * (cell_width + gutter)
        y = gutter + row * (cell_height + gutter)
        height, width = tile.shape[:2]
        atlas[y:y + height, x:x + width] = tile
        positions.append((x, y, width, height))
    return atlas, positions


def _contact_timeline_response_schema(sample_ids):
    return {
        'type': 'object', 'additionalProperties': False, 'required': ['samples'],
        'properties': {'samples': {
            'type': 'array', 'minItems': len(sample_ids), 'maxItems': len(sample_ids),
            'uniqueItems': True,
            'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['sampleId', 'contactState', 'surface', 'visible'],
                'properties': {
                    'sampleId': {'type': 'string', 'enum': list(sample_ids)},
                    'contactState': {'type': 'string', 'enum': sorted(_CONTACT_STATES)},
                    'surface': {'type': 'string', 'enum': sorted(_CONTACT_SURFACES)},
                    'visible': {'type': 'boolean'},
                },
            },
        }},
    }


def _validated_contact_timeline_response(raw, candidates):
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return None
    rows = answer.get('samples') if isinstance(answer, dict) else None
    expected = {row['sampleId']: row for row in candidates}
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(row, dict) for row in rows)):
        return None
    by_id = {row.get('sampleId'): row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != set(expected):
        return None
    normalized = []
    for sample_id, candidate in expected.items():
        observed = by_id[sample_id]
        state, surface, visible = (observed.get('contactState'), observed.get('surface'),
                                   observed.get('visible'))
        if state not in _CONTACT_STATES or surface not in _CONTACT_SURFACES or type(visible) is not bool:
            return None
        if visible is False and state != 'unknown':
            return None
        if state in {'full_sole', 'forefoot', 'heel_only'}:
            if visible is not True or surface not in {'ground', 'raised_surface'}:
                return None
        elif state == 'airborne' and surface not in {'none', 'unknown'}:
            return None
        elif state == 'unknown' and surface not in {'none', 'unknown'}:
            return None
        normalized.append({
            'sampleId': sample_id,
            'sourceTimeSec': candidate['sourceTimeSec'],
            'side': candidate['side'],
            'contactState': state,
            'surface': surface,
            'visible': visible,
            'sourceTrackStationary': True,
            'sourcePoseFrameIndex': candidate['poseFrameIndex'],
            'sourceFrameIndex': candidate['sourceFrameIndex'],
            'sourceFps': candidate['sourceFps'],
        })
    return normalized


def validated_body_support_contact_timeline(observed, *, expected_video_sha256=None):
    """Return exact-video, code-timed contact rows; malformed or stale proof is absent."""
    if not isinstance(observed, dict):
        return None
    timeline = observed.get('contactTimeline', observed)
    if (not isinstance(timeline, dict)
            or timeline.get('schemaVersion') != 1
            or timeline.get('policyVersion') != CONTACT_TIMELINE_POLICY_VERSION
            or timeline.get('source') != 'exact_source_visual_contact_timeline'
            or timeline.get('sourceClock') != 'video_frame_zero_seconds'
            or timeline.get('status') != 'observed'
            or not isinstance(timeline.get('sourceVideoSha256'), str)
            or not timeline['sourceVideoSha256']):
        return None
    digest = timeline['sourceVideoSha256']
    if expected_video_sha256 is not None and digest != expected_video_sha256:
        return None
    if 'contactTimeline' in observed:
        if (observed.get('sourceVideoSha256') != digest
                or observed.get('status') != 'observed'
                or observed.get('source') != 'exact_source_visual_support_observation'):
            return None
    rows = timeline.get('samples')
    if not isinstance(rows, list):
        return None
    seen = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        sample_id, side = row.get('sampleId'), row.get('side')
        state, surface, visible = row.get('contactState'), row.get('surface'), row.get('visible')
        try:
            source_time = float(row.get('sourceTimeSec'))
            source_fps = float(row.get('sourceFps'))
        except (TypeError, ValueError, OverflowError):
            return None
        source_frame_index = row.get('sourceFrameIndex')
        pose_frame_index = row.get('sourcePoseFrameIndex')
        if (not isinstance(sample_id, str) or not sample_id or sample_id in seen
                or side not in {'left', 'right'} or not np.isfinite(source_time)
                or type(source_frame_index) is not int or source_frame_index < 0
                or type(pose_frame_index) is not int or pose_frame_index < 0
                or not np.isfinite(source_fps) or source_fps <= 0.
                or abs(source_time - source_frame_index / source_fps) > 1e-6
                or state not in _CONTACT_STATES or surface not in _CONTACT_SURFACES
                or type(visible) is not bool or row.get('sourceTrackStationary') is not True):
            return None
        if visible is False and state != 'unknown':
            return None
        if state in {'full_sole', 'forefoot', 'heel_only'}:
            if visible is not True or surface not in {'ground', 'raised_surface'}:
                return None
        elif state == 'airborne' and surface not in {'none', 'unknown'}:
            return None
        elif state == 'unknown' and surface not in {'none', 'unknown'}:
            return None
        seen.add(sample_id)
        normalized.append({**row, 'sourceTimeSec': source_time})
    return normalized


def observe_foot_contact_timeline(video_path, source_pose, source_foot_support_evidence,
                                  caption_images, cache_dir):
    """Visually label bounded pose-selected foot crops at exact source times.

    Vision owns only visible contact state for each code-selected target crop.
    Side, sample identity, source time, and source stationarity remain code-owned.
    Returned rows are point observations and never imply contact between samples.
    """
    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    evidence = source_foot_support_evidence if isinstance(source_foot_support_evidence, dict) else {}
    pose_reference = source_pose if isinstance(source_pose, dict) else {}
    pose = pose_reference.get('pose') if isinstance(pose_reference.get('pose'), dict) else pose_reference
    patch = evidence.get('footPatchEvidence') or {}
    pose_origin = (pose.get('sourceTimeOriginSec') if isinstance(pose, dict) else None)
    patch_origin = patch.get('sourceTimeOriginSec')
    try:
        same_clock = (pose_origin is not None and patch_origin is not None
                      and abs(float(pose_origin) - float(patch_origin)) <= 1e-6)
    except (TypeError, ValueError, OverflowError):
        same_clock = False
    if (evidence.get('sourceVideoSha256') != digest
            or patch.get('sourceVideoSha256') != digest
            or pose_reference.get('sourceVideoSha256') != digest or not same_clock):
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'source_contact_evidence_identity_mismatch',
                'samples': []}
    candidates = _contact_timeline_candidates(pose, evidence)
    if not candidates:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'no_bounded_unknown_stationary_contact_samples',
                'samples': []}
    request_identity = [CONTACT_TIMELINE_POLICY_VERSION, digest,
                        {'cropPolicy': CONTACT_TIMELINE_CROP_POLICY, 'radiusX': .075,
                         'radiusYTop': .025, 'radiusYBottom': .13,
                         'minRadiusX': 16, 'minRadiusYTop': 8, 'minRadiusYBottom': 24,
                         'marker': 'black-outlined-yellow-crosshair-v1',
                         'label': 'padded-header-autosized-v1'},
                        [(row['sampleId'], row['sourceTimeSec'], row['side'],
                          row['poseFrameIndex'], row['ankle'],
                          row['stationaryStartTimeSec'], row['stationaryEndTimeSec'])
                         for row in candidates]]
    request_sha = hashlib.sha256(json.dumps(request_identity, separators=(',', ':')).encode()).hexdigest()
    cache = cache_dir / f'body-support-contact-timeline-{request_sha}.json'
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = None
        if isinstance(cached, dict) and cached.get('requestSha256') == request_sha:
            if cached.get('status') == 'unknown':
                return cached
            rows = validated_body_support_contact_timeline(cached, expected_video_sha256=digest)
            expected = {(row['sampleId'], row['side']) for row in candidates}
            if rows is not None and {(row['sampleId'], row['side']) for row in rows} == expected:
                return cached

    if caption_images is None:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'support_timeline_observer_unavailable',
                'requestSha256': request_sha, 'samples': []}
    from .bake_and_rank import call_caption_images_json, callable_accepts_keyword
    if not callable_accepts_keyword(caption_images, 'response_schema'):
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'structured_support_timeline_output_unavailable',
                'requestSha256': request_sha, 'samples': []}

    import cv2
    cache_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    tiles = []
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0. or frame_count <= 0:
            return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                    'source': 'exact_source_visual_contact_timeline',
                    'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                    'status': 'unknown', 'reason': 'support_timeline_video_clock_unavailable',
                    'requestSha256': request_sha, 'samples': []}
        for candidate in candidates:
            frame_index = int(round(candidate['sourceTimeSec'] * fps))
            if frame_index < 0 or frame_index >= frame_count:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_out_of_range',
                        'requestSha256': request_sha, 'samples': []}
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_unavailable',
                        'requestSha256': request_sha, 'samples': []}
            decoded_time = frame_index / fps
            if not (candidate['stationaryStartTimeSec'] <= decoded_time
                    <= candidate['stationaryEndTimeSec']):
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_outside_stationary_interval',
                        'requestSha256': request_sha, 'samples': []}
            rendered = _render_contact_timeline_crop(cv2, frame, candidate)
            if rendered is None:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_crop_unavailable',
                        'requestSha256': request_sha, 'samples': []}
            crop, marker, bounds, header_height = rendered
            tiles.append(crop)
            candidate['cropMarkerXY'] = list(marker)
            candidate['cropBoundsXYXY'] = list(bounds)
            candidate['cropHeaderHeight'] = header_height
            candidate['sourceFrameIndex'] = frame_index
            candidate['sourceFps'] = fps
            candidate['sourceTimeSec'] = decoded_time
    finally:
        capture.release()

    atlas_data = _assemble_contact_timeline_atlas(
        tiles, [row['sampleId'] for row in candidates])
    if atlas_data is None:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'support_timeline_atlas_unavailable',
                'requestSha256': request_sha, 'samples': []}
    atlas, tile_positions = atlas_data
    for candidate, position in zip(candidates, tile_positions):
        candidate['atlasPanelXYWH'] = list(position)
    atlas_path = cache_dir / f'{request_sha}-contact-atlas.png'
    if not cv2.imwrite(str(atlas_path), atlas):
        raise OSError(f'Cannot write target-foot atlas: {atlas_path}')

    prompt = '''This single PNG is a grid of code-selected foot crops from exact source-video frames. Each panel has a padded header giving the target side and unique sample ID; a yellow crosshair marks the code-selected ankle. For each ID, judge only the foot connected to that panel's crosshair; do not infer or swap anatomical sides. Report visible physical contact and visible surface at that instant. Use unknown when the shoe or surface is hidden/ambiguous. A visible sole touching ground is full_sole only when heel and forefoot both touch; forefoot means the front sole touches while the heel is raised; heel_only means the heel touches while the forefoot is raised; airborne means no shoe contact with a surface. Do not infer contact between panels or from stationary motion. Return one row for every panel sample ID, with no timestamps or other IDs.'''
    schema = _contact_timeline_response_schema([row['sampleId'] for row in candidates])
    raw = call_caption_images_json(
        caption_images, frame_paths=[atlas_path], prompt=prompt, max_tokens=600,
        json_response=True, response_schema=schema, disable_reasoning=True,
        temperature=0., top_p=1., top_k=1)
    observations = _validated_contact_timeline_response(raw, candidates)
    if observations is None:
        result = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                  'source': 'exact_source_visual_contact_timeline',
                  'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                  'status': 'unknown', 'reason': 'support_timeline_response_invalid',
                  'requestSha256': request_sha, 'responseSha256': hashlib.sha256(
                      str(raw).encode()).hexdigest(), 'samples': []}
        cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
              'source': 'exact_source_visual_contact_timeline',
              'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
              'status': 'observed', 'requestSha256': request_sha,
              'responseSha256': hashlib.sha256(str(raw).encode()).hexdigest(),
              'samples': observations}
    cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def materialize_timed_visual_contact_points(evidence, frames=None, joint_names=None):
    """Add only exact-time, visible ground point contacts to fit evidence."""
    if not isinstance(evidence, dict):
        return evidence
    if 'supportContacts' not in evidence:
        evidence['_fitGeneratedSupportContactsCollection'] = True
    contacts = evidence.setdefault('supportContacts', [])
    if not isinstance(contacts, list):
        contacts = []
        evidence['supportContacts'] = contacts
    # These rows are derived from the current timeline and fit clock. Never
    # carry them across a rematerialization when either input has changed.
    contacts[:] = [contact for contact in contacts
                   if not (isinstance(contact, dict)
                           and contact.get('supportKind') == 'exact_timed_visual_contact')]
    observed = evidence.get('bodySupportObservation') or {}
    rows = validated_body_support_contact_timeline(observed)
    if rows is None:
        return evidence
    digest = observed.get('sourceVideoSha256')
    mapping = evidence.get('motionSpaceMapping') or {}
    swapped = mapping.get('bilateralAssignment') == 'swapped'
    from .contact_constraints import (
        _body_timeline_parent_exposure_time,
        _source_timeline_mapping_for_payload,
    )
    source_timeline_mapping = evidence.get('_fitSourceTimelineMapping')
    if source_timeline_mapping is None:
        source_timeline_mapping = _source_timeline_mapping_for_payload(evidence)
    names = set(joint_names or [])
    times = []
    for frame in frames or []:
        if not isinstance(frame, dict) or frame.get('syntheticLoopBridge'):
            times.append(None)
            continue
        try:
            time = float(frame.get('sourceTimeSec'))
        except (TypeError, ValueError, OverflowError):
            times.append(None)
        else:
            times.append(time if np.isfinite(time) else None)
    for row in rows:
        # This rig has a forefoot pivot but no heel pivot or measured raised
        # surface plane. Preserve those observations without inventing a pin.
        if (row['visible'] is not True
                or not row['sourceTrackStationary'] or row['surface'] != 'ground'
                or row['contactState'] not in {'full_sole', 'forefoot'}):
            continue
        source_side = row['side']
        parent_exposure_time = _body_timeline_parent_exposure_time(
            row, source_timeline_mapping, str(digest or '').casefold())
        if parent_exposure_time is None:
            continue
        rig_side = ('right' if source_side == 'left' else 'left') if swapped else source_side
        joint = f'{rig_side}_foot'
        if names and joint not in names:
            continue
        point = {
            'jointName': joint,
            'supportKind': 'exact_timed_visual_contact',
            'contactState': 'full_sole' if row['contactState'] == 'full_sole' else 'toe_only',
            'contactMotion': 'stationary',
            'surfaceKind': 'ground',
            'verticalOnly': False,
            'sourceTimeSec': parent_exposure_time,
            'sourceTimeBasis': 'absolute_source_video',
            'contactTimelineSourceTimeSec': row['sourceTimeSec'],
            'contactTimelineParentExposureTimeSec': parent_exposure_time,
            'contactTimelineSourceClock': 'video_frame_zero_seconds',
            'contactTimelineSampleId': row['sampleId'],
            'contactTimelineSourceVideoSha256': digest,
        }
        if times:
            exact = [index for index, time in enumerate(times)
                     if time is not None and abs(time - point['sourceTimeSec']) <= 1e-6]
            if not exact:
                continue
            index = exact[0]
            point['_fitFrameBounds'] = [index, index]
            point['_fitFrameCount'] = len(times)
        contacts.append(point)
    return evidence


def stationary_source_track(source_pose, joint, *, max_leading_gap_ratio=0.15):
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
    if (indexes[0] > max_leading_gap_ratio*len(frames)
            or indexes[-1] < .85*(len(frames)-1)):
        return False
    centers = np.asarray([np.median(chunk, axis=0) for chunk in np.array_split(points, 4)])
    scale = max(float(np.median(spans)), 1e-8)
    return bool(np.isfinite(centers).all()
                and np.linalg.norm(np.ptp(centers, axis=0))/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_CHUNK_RANGE_RATIO_THRESHOLD
                and np.linalg.norm(centers[-1]-centers[0])/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_ENDPOINT_RATIO_THRESHOLD)


def observed_body_support_contacts(observed):
    """Direct contact and stationarity are separate evidence requirements."""
    answer = validated_body_support_answer(observed)
    if answer is None:
        return set()
    contacts = set()
    for region, joints in (
        ('pelvis', ('pelvis',)),
        ('upperBack', ('left_shoulder', 'right_shoulder')),
        ('head', ('head',)),
    ):
        if answer.get(region) == 'stationary_support':
            contacts.update(joints)
    return contacts


def remove_unobserved_torso_support(evidence):
    support = evidence.get('bodySupport') or {}
    if support.get('reason') == 'supported_reference_body_requires_observed_surface_geometry':
        evidence.pop('bodySupport', None)
    elif support.get('source') == 'exact_source_contacts_and_stationary_pose_tracks':
        observed = evidence.get('bodySupportObservation') or {}
        answer = validated_body_support_answer(observed)
        same_source = (
            answer is not None
            and support.get('sourceVideoSha256') == observed.get('sourceVideoSha256')
        )
        contacts = observed_body_support_contacts(observed) if same_source else set()
        if not set(BODY_SUPPORT_ANCHORS).issubset(contacts):
            contacts = set()
        removed = set(BODY_SUPPORT_ANCHORS) | {'head', 'neck', 'spine1', 'spine2', 'spine3'}
        if contacts:
            removed -= contacts | {'neck', 'spine1', 'spine2', 'spine3'}
        if not same_source:
            for side in ('left', 'right'):
                removed.update((f'{side}_ankle', f'{side}_foot'))
        _remove_materialized_support_joints(evidence, removed)


def materialize_body_support(payload, source_pose, contract=None):
    """Convert confirmed contacts to constraints in the baked coordinate frame.

    Stationary anchors respect the contract's primary movers (e.g. shoulders on
    a lying press). Readiness and plane pin use that filtered anchor set; the
    bench/normal direction may still be estimated from torso landmark medians.
    """
    evidence = payload.get('sourceFootSupportEvidence') or {}
    remove_unobserved_torso_support(evidence)
    existing = evidence.get('bodySupport') or {}
    if (existing.get('status') == 'confirmed'
            and set(BODY_SUPPORT_ANCHORS).intersection(existing.get('stationaryJoints') or [])):
        # Add foot anchors only when the temporal patch confirms full sole for
        # every selected frame; keep existing torso constraints intact.
        _augment_confirmed_ground_sole_support(payload, evidence, source_pose)
        return
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if answer is None:
        return
    anchors = list(body_support_required_anchors(contract))
    contacts = observed_body_support_contacts(observed)
    if not (set(BODY_SUPPORT_ANCHORS).issubset(contacts)
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
    if 'head' in contacts and stationary_source_track(source_pose, 'head'):
        support['stationaryJoints'].append('head')
    sides = []
    for side in ('left', 'right'):
        if (answer.get(f'{side}Foot') != 'stationary_full_sole'
                or answer.get(f'{side}FootSurface') != 'ground'
                or not _has_uninterrupted_full_sole_patch(evidence, side)
                or not stationary_source_track(source_pose, f'{side}_ankle')):
            continue
        sides.append(side)
    add_ground_sole_contacts(payload, support, medians, sides, evidence=evidence)
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
    answer = validated_body_support_answer(observed)
    if answer is None:
        return
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
    """Full sole and forefoot observations can establish a planted toe.

    Temporal patch evidence must corroborate a full-clip anchor; partial source
    contacts remain interval constraints. This deliberately says nothing about
    heel height or shoe pitch, which require independent heel/toe geometry.
    """
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if answer is None:
        return
    floor = payload.get('renderFloorY')
    patch = evidence.get('footPatchEvidence') or {}
    temporal_patch_available = patch.get('available') is True
    source_confirmed_sides = _augment_confirmed_ground_sole_support(
        payload, evidence, source_pose)
    if temporal_patch_available:
        patch_contact_count = len(payload.get('frames') or [])
        full_cycle_sides = {
            side for side in ('left', 'right')
            if _has_full_cycle_stationary_sole(evidence, side, patch_contact_count)
        }
        full_cycle_sides.update(source_confirmed_sides)
        _remove_unverified_materialized_foot_support(evidence, full_cycle_sides)
    # A few support-review frames cannot establish an uninterrupted ground
    # anchor when the movement permits release. First remove stale cached
    # full-clip anchors using temporal evidence, then retain only timed contacts.
    if payload.get('groundContactMode') in {'intermittent', 'none'}:
        return
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
            if temporal_patch_available and side not in full_cycle_sides:
                continue
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


def add_ground_sole_contacts(payload, support, medians, sides, *, evidence):
    """Use the same shoe dimensions for every explicitly observed ground contact."""
    camera_reference = payload.get('sourcePoseCameraReference') or {}
    camera = camera_reference.get('camera') or {}
    source_labels_swapped = (
        camera.get('bilateralAssignment') == 'swapped'
        and not isinstance(evidence.get('motionSpaceMapping'), dict)
    )
    for side in sides:
        ankle, foot, knee = [f'{side}_{part}' for part in ('ankle', 'foot', 'knee')]
        if not {ankle, foot, knee}.issubset(medians):
            continue
        # Canonical source labels can name the opposite baked rig side. Keep
        # constraint labels canonical, but measure geometry on their rig side.
        geometry_side = ('right' if side == 'left' else 'left') if source_labels_swapped else side
        geometry_ankle, geometry_foot = (f'{geometry_side}_{part}' for part in ('ankle', 'foot'))
        if not {geometry_ankle, geometry_foot}.issubset(medians):
            continue
        for joint in (ankle, foot):
            if joint not in support['stationaryJoints']:
                support['stationaryJoints'].append(joint)
        # `foot` is the renderer's forefoot pivot and the lowest material-sole
        # vertices lie on its calibrated ground plane. Do not add a shoe-height
        # offset here: that creates a visible gap at the anchor and fails the
        # rendered full-sole contact check.
        plane_height = float(payload.get('renderFloorY') or 0.)
        existing_planes = [group for group in support['coplanarGroups']
                           if set(group['joints']) in ({foot}, {ankle, foot})
                           and np.allclose(group['normal'], [0., 1., 0.])]
        if existing_planes:
            # Confirmed ground contact belongs to today's floor and shoe geometry,
            # not a cached per-foot height from another placement or bake. The
            # forefoot is the observed sole anchor; ankle-to-toe pitch belongs
            # to the calibrated shoe geometry below, not a horizontal bone rule.
            for group in existing_planes:
                group['joints'] = [foot]
                group.pop('anchorJoint', None)
                group['planeOffsetMeters'] = plane_height
        else:
            support['coplanarGroups'].append({'joints': [foot], 'normal': [0, 1, 0],
                                             'planeOffsetMeters': plane_height})
        if not any(contact['joints'] == [knee, ankle, foot] for contact in support['soleContacts']):
            support['soleContacts'].append({'joints': [knee, ankle, foot], 'normal': [0, 1, 0]})
    canonical_planes = []
    seen_feet = set()
    for group in support['coplanarGroups']:
        joints = group.get('joints') or []
        side = (joints[0].removesuffix('_foot')
                if len(joints) == 1 and joints[0].endswith('_foot') else None)
        if (side in sides and np.allclose(group.get('normal'), [0., 1., 0.])):
            if side in seen_feet:
                continue
            seen_feet.add(side)
        canonical_planes.append(group)
    support['coplanarGroups'] = canonical_planes
    _remove_superseded_ground_sole_planes(support, sides)


def _confirmed_observed_ground_sole_sides(evidence, source_pose, joint_names):
    """Return foot sides backed by the same confirmed video and stable source tracks."""
    support = evidence.get('bodySupport') or {}
    observed = evidence.get('bodySupportObservation') or {}
    video_digest = observed.get('sourceVideoSha256')
    if (support.get('status') != 'confirmed'
            or not isinstance(video_digest, str) or not video_digest
            or support.get('sourceVideoSha256') != video_digest
            or validated_body_support_answer(observed) is None):
        return set()

    answer = validated_body_support_answer(observed)
    names = set(joint_names or [])
    mapping = evidence.get('motionSpaceMapping') or {}
    swapped = mapping.get('bilateralAssignment') == 'swapped'
    confirmed = set()
    for side in ('left', 'right'):
        if not {f'{side}_ankle', f'{side}_foot', f'{side}_knee'}.issubset(names):
            continue
        if (answer.get(f'{side}Foot') != 'stationary_full_sole'
                or answer.get(f'{side}FootSurface') != 'ground'):
            continue
        # Sparse visual review and unknown patch samples cannot establish a
        # whole-clip full-sole anchor; timed contacts remain available below.
        if not _has_uninterrupted_full_sole_patch(evidence, side):
            continue
        source_side = ('right' if side == 'left' else 'left') if swapped else side
        # An exact-video observation can confirm that a foot remains planted
        # while the source pose tracker briefly loses it at the clip start.
        # Keep the usual 70% sample, endpoint, and displacement checks; relax
        # only the leading-coverage guard for this hash- and patch-gated path.
        if stationary_source_track(
                source_pose, f'{source_side}_ankle', max_leading_gap_ratio=.30):
            confirmed.add(side)
    return confirmed


def _body_support_has_complete_ground_sole(support, side):
    ankle, foot, knee = (f'{side}_ankle', f'{side}_foot', f'{side}_knee')
    stationary = set(support.get('stationaryJoints') or [])
    has_plane = any(
        list(group.get('joints') or []) == [foot]
        and isinstance(group.get('planeOffsetMeters'), (int, float))
        and np.isfinite(group.get('planeOffsetMeters'))
        for group in support.get('coplanarGroups') or []
    )
    has_sole = any(
        {knee, ankle, foot}.issubset(set(contact.get('joints') or []))
        for contact in support.get('soleContacts') or []
    )
    return {ankle, foot}.issubset(stationary) and has_plane and has_sole


def _remove_superseded_ground_sole_planes(support, sides):
    """A calibrated full sole replaces earlier ground-point plane estimates."""
    complete = [side for side in sides if _body_support_has_complete_ground_sole(support, side)]
    groups = []
    for group in support.get('coplanarGroups', []):
        joints = list(group['joints'])
        for side in complete:
            sole = {f'{side}_ankle', f'{side}_foot'}
            if sole.issubset(group['joints']):
                joints = [name for name in joints if name not in sole]
        if len(joints) < (1 if 'planeOffsetMeters' in group else 2):
            continue
        updated = {**group, 'joints': joints}
        if 'anchorJoint' in updated and updated['anchorJoint'] not in joints:
            updated['anchorJoint'] = joints[0]
        groups.append(updated)
    support['coplanarGroups'] = groups


def _augment_confirmed_ground_sole_support(payload, evidence, source_pose, *, sides=None):
    support = evidence.get('bodySupport') or {}
    if (support.get('status') != 'confirmed'
            or payload.get('groundContactMode') in {'intermittent', 'none'}):
        return set()
    confirmed_sides = (_confirmed_observed_ground_sole_sides(
        evidence, source_pose, payload.get('jointNames'))
        if sides is None else set(sides))
    _remove_superseded_ground_sole_planes(support, confirmed_sides)
    frames = payload.get('frames') or []
    names = payload.get('jointNames') or []
    if not confirmed_sides or not frames or not set(names).issubset(
            set(frames[0].get('joints') or {})):
        return confirmed_sides
    medians = {
        name: np.median([frame['joints'][name] for frame in frames], axis=0)
        for name in names
    }
    add_ground_sole_contacts(payload, support, medians, sorted(confirmed_sides), evidence=evidence)
    return confirmed_sides


def observed_stationary_sole_contacts(evidence):
    from .contact_constraints import motion_support_contacts
    return [c for c in motion_support_contacts(evidence)
            if c.get('contactState') == 'full_sole' and c.get('contactMotion') == 'stationary'
            and c.get('verticalOnly') is not True]


def _has_uninterrupted_full_sole_patch(evidence, side):
    patch = evidence.get('footPatchEvidence') or {}
    states = ((patch.get('feet') or {}).get(side) or {}).get('states') or []
    contact_intervals = patch.get('contacts') or []
    return bool(patch.get('available') is True and states
                and all(str(state).casefold() == 'full_sole' for state in states)
                and any(contact.get('jointName') == f'{side}_foot'
                        and contact.get('contactState') == 'full_sole'
                        and contact.get('contactMotion') == 'stationary'
                        and contact.get('startRatio') == 0.
                        and contact.get('endRatio') == 1.
                        for contact in contact_intervals))


def corroborated_stationary_sole(evidence, side):
    """Require frame-complete full-sole patches before bridging ankle evidence."""
    if evidence.get('temporalResolutionSufficient') is not True:
        return False
    if not _has_uninterrupted_full_sole_patch(evidence, side):
        return False
    # These ratios describe the full source, so this evidence also covers any
    # selected subinterval. Partial ankle tracks cannot fill missing contacts.
    return any(c.get('jointName') == f'{side}_ankle'
               and c.get('contactMotion') == 'stationary'
               and c.get('startRatio') == 0. and c.get('endRatio') == 1.
               for c in evidence.get('footContactCandidates') or [])


def _has_full_cycle_stationary_sole(evidence, side, frame_count):
    if not _has_uninterrupted_full_sole_patch(evidence, side):
        return False
    if frame_count > 1:
        from .contact_constraints import contact_frame_bounds
        if any(
            ('startRatio' in contact or 'startFrame' in contact)
            and ('endRatio' in contact or 'endFrame' in contact)
            and contact_frame_bounds(contact, frame_count) == (0, frame_count - 1)
            for contact in observed_stationary_sole_contacts(evidence)
            if contact.get('jointName') == f'{side}_foot'
        ):
            return True
    return corroborated_stationary_sole(evidence, side)


def _remove_unverified_materialized_foot_support(evidence, corroborated_sides):
    support = evidence.get('bodySupport')
    if not isinstance(support, dict) or support.get('source') not in {
        'exact_source_contacts_and_stationary_pose_tracks',
        'observed_full_cycle_ground_sole_contacts',
    }:
        return

    removed_joints = {
        f'{side}_{joint}'
        for side in ('left', 'right') if side not in corroborated_sides
        for joint in ('ankle', 'foot')
    }
    _remove_materialized_support_joints(evidence, removed_joints)


def _remove_materialized_support_joints(evidence, removed_joints):
    support = evidence.get('bodySupport') or {}
    if not removed_joints.intersection(support.get('stationaryJoints') or []):
        return

    support['stationaryJoints'] = [
        joint for joint in support.get('stationaryJoints') or []
        if joint not in removed_joints
    ]
    groups = []
    for group in support.get('coplanarGroups') or []:
        joints = [joint for joint in group.get('joints') or [] if joint not in removed_joints]
        minimum_count = 1 if 'planeOffsetMeters' in group else 2
        if len(joints) < minimum_count:
            continue
        updated_group = {**group, 'joints': joints}
        if ('anchorJoint' in updated_group
                and updated_group['anchorJoint'] not in joints):
            updated_group['anchorJoint'] = joints[0]
        groups.append(updated_group)
    support['coplanarGroups'] = groups
    support['soleContacts'] = [
        contact for contact in support.get('soleContacts') or []
        if not removed_joints.intersection(contact.get('joints') or [])
    ]
    support['nonPenetrationChains'] = [
        chain for chain in support.get('nonPenetrationChains') or []
        if not removed_joints.intersection(
            [*(chain.get('joints') or []), *(chain.get('endpoints') or [])])
    ]

    if (not support['stationaryJoints'] and not support['coplanarGroups']
            and not support.get('nonPenetrationChains') and not support['soleContacts']):
        evidence.pop('bodySupport', None)


def materialize_stationary_sole_support(payload):
    """Return rig-side evidence with eligible full-cycle sole support materialized."""
    from .contact_constraints import (
        contact_frame_bounds,
        motion_space_support_evidence,
    )
    evidence = deepcopy(motion_space_support_evidence(payload))
    materialize_timed_visual_contact_points(
        evidence, payload.get('frames'), payload.get('jointNames'))
    remove_unobserved_torso_support(evidence)
    existing = evidence.get('bodySupport') or {}
    if existing.get('required') and existing.get('status') != 'confirmed':
        return evidence  # New foot evidence cannot resolve missing torso observations.
    count = len(payload.get('frames') or [])
    names = payload.get('jointNames') or []
    patch = evidence.get('footPatchEvidence') or {}
    source_pose_reference = payload.get('sourcePoseCameraReference') or {}
    source_pose = source_pose_reference.get('sourcePose') or {}
    source_confirmed_sides = set()
    if payload.get('groundContactMode') not in {'intermittent', 'none'}:
        source_confirmed_sides = _confirmed_observed_ground_sole_sides(
            evidence, source_pose, names)
    if patch.get('available') is True:
        corroborated_sides = {
            side for side in ('left', 'right')
            if _has_full_cycle_stationary_sole(evidence, side, count)
        }
        corroborated_sides.update(source_confirmed_sides)
        # Retained source evidence may carry bodySupport anchors materialized by
        # an older cache policy. Recheck them in the fit's motion-space view so
        # direct fitting and source digests cannot bypass the temporal patch
        # gate used by the normal source-preparation path.
        _remove_unverified_materialized_foot_support(evidence, corroborated_sides)
    existing = evidence.get('bodySupport') or {}
    _augment_confirmed_ground_sole_support(
        payload, evidence, source_pose, sides=source_confirmed_sides)
    existing = evidence.get('bodySupport') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if answer is None:
        return evidence
    if count < 7 or not {'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder'}.issubset(names):
        return evidence
    floor = payload.get('renderFloorY')
    if not isinstance(floor, (int, float)) or not np.isfinite(floor):
        return evidence
    sides = []
    existing_soles = {c['joints'][2] for c in existing.get('soleContacts', [])}
    for side in ('left', 'right'):
        if side in source_confirmed_sides:
            if not _body_support_has_complete_ground_sole(existing, side):
                sides.append(side)
            continue
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
        return evidence
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
    add_ground_sole_contacts(payload, support, medians, sides, evidence=evidence)
    if support['soleContacts']:
        evidence['bodySupport'] = support
    return evidence


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

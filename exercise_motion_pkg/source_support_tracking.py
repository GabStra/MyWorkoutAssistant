"""Measure supported-body travel from source pixels without rewriting pose landmarks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

POLICY_VERSION = 3
FOOT_MATERIAL_POLICY_VERSION = 3
MIN_MATERIAL_CORNERS_PER_PATCH = 3
MIN_MATERIAL_PATCH_SPREAD_EIGENVALUE_PX2 = 0.5


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def observe_support_relative_tracks(video_path, source_pose, observation, *, cache_dir):
    """Corroborate hip-to-foot travel where visual review observed a planted foot.

    Low texture, occlusion, inconsistent tracking or mismatched source bytes leave
    the original detector evidence in charge. Pixel motion is checked against the
    observed source pose; no stationary body trajectory is assumed.
    """
    unavailable = {'available': False, 'policyVersion': POLICY_VERSION, 'tracks': {}}
    from .body_support_observation import validated_body_support_answer
    answer = validated_body_support_answer(observation or {})
    if (answer is None
            or (source_pose or {}).get('coordinateSpace') != 'normalized_image_xy'):
        return {**unavailable, 'reason': 'source_support_observation_unavailable'}
    video_path = Path(video_path)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    if digest != observation.get('sourceVideoSha256'):
        return {**unavailable, 'reason': 'source_identity_mismatch'}
    key = hashlib.sha256(json.dumps(
        [POLICY_VERSION, digest, source_pose, answer], sort_keys=True).encode()).hexdigest()
    cache = Path(cache_dir) / f'pixel-support-{key}.json'
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    result = _track_support_pixels(video_path, source_pose, answer)
    result.update(policyVersion=POLICY_VERSION, sourceVideoSha256=digest,
                  source='forward_backward_source_pixel_tracks')
    cache.parent.mkdir(parents=True, exist_ok=True)
    from .bake_and_rank import write_json_atomic
    write_json_atomic(cache, result)
    return result


def _track_support_pixels(video_path, pose, answer):
    import cv2

    unavailable = {'available': False, 'tracks': {}}
    frames = pose.get('frames') or []
    if len(frames) < 6:
        return {**unavailable, 'reason': 'insufficient_pose_coverage'}
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, image = capture.read()
        if not ok or not np.isfinite(fps) or fps <= 0 or count/fps > 30.:
            return {**unavailable, 'reason': 'source_decode_or_duration_unavailable'}
        height, width = image.shape[:2]
        axes = np.array([width, height], dtype=float)
        origin = float(pose.get('sourceTimeOriginSec', 0.))
        if abs(float(frames[0]['sourceTimeSec'])-origin) > .5/fps:
            return {**unavailable, 'reason': 'source_start_observation_missing'}
        first = frames[0]
        joints = first.get('joints') or {}
        confidence = first.get('jointConfidence') or {}
        centers = ('left_hip', 'right_hip')
        supports = [f'{side}_ankle' for side in ('left', 'right')
                    if answer.get(f'{side}Foot') == 'stationary_full_sole'
                    and answer.get(f'{side}FootSurface') == 'ground']
        if not all(n in joints and confidence.get(n, 0.) >= .65 for n in centers):
            return {**unavailable, 'reason': 'hip_observation_unavailable'}
        supports = [n for n in supports if n in joints and confidence.get(n, 0.) >= .65]
        if not supports:
            return {**unavailable, 'reason': 'support_observation_unavailable'}
        observed_points = np.array([p[:2] for p in joints.values()], dtype=float)*axes
        body_span = float(np.linalg.norm(np.ptp(observed_points, axis=0)))
        radius = max(10, round(.05*body_span))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        groups = {}
        for group, names in [('hips', centers), *((n, (n,)) for n in supports)]:
            mask = np.zeros_like(gray)
            for name in names:
                point = np.asarray(joints[name][:2])*axes
                cv2.circle(mask, tuple(point.astype(int)), radius, 255, -1)
            features = cv2.goodFeaturesToTrack(gray, 30, .01, 3, mask=mask)
            if features is None or len(features) < 6:
                continue
            groups[group] = {'points': features, 'initial': features.copy(),
                             'valid': np.ones(len(features), dtype=bool),
                             'origin': np.mean([joints[n][:2] for n in names], axis=0)*axes}
        if 'hips' not in groups:
            return {**unavailable, 'reason': 'hip_texture_unavailable'}
        tracks = {n: [] for n in supports if n in groups}
        hip_center_observed = 0
        samples = {int(round((float(f['sourceTimeSec'])-origin)*fps)): f for f in frames}
        for index in range(count):
            if index:
                ok, image = capture.read()
                if not ok:
                    return {**unavailable, 'reason': 'incomplete_source_decode'}
                current_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                for data in groups.values():
                    moved, status, _ = cv2.calcOpticalFlowPyrLK(gray, current_gray, data['points'], None)
                    if moved is None or status is None or not np.isfinite(moved).all():
                        data['valid'][:] = False
                        continue
                    back, back_status, _ = cv2.calcOpticalFlowPyrLK(current_gray, gray, moved, None)
                    if back is None or back_status is None:
                        data['valid'][:] = False
                        continue
                    data['valid'] &= ((status[:, 0] == 1) & (back_status[:, 0] == 1)
                                      & (np.linalg.norm(back-data['points'], axis=2)[:, 0] < 1.))
                    data['points'] = moved
                gray = current_gray
            frame = samples.get(index)
            if frame is None:
                continue
            positions = {}
            for group, data in groups.items():
                valid = data['valid']
                if valid.sum() < max(6, .7*len(valid)):
                    continue
                displacements = (data['points']-data['initial'])[valid, 0]
                displacement = np.median(displacements, axis=0)
                if np.percentile(np.linalg.norm(displacements-displacement, axis=1), 90) > max(1., .01*body_span):
                    continue
                names = centers if group == 'hips' else (group,)
                pose_joints = frame.get('joints') or {}
                if not all(n in pose_joints and (frame.get('jointConfidence') or {}).get(n, 0.) >= .65 for n in names):
                    continue
                point = data['origin']+displacement
                pose_point = np.mean([pose_joints[n][:2] for n in names], axis=0)*axes
                if np.linalg.norm(point-pose_point) <= .08*body_span:
                    positions[group] = point
            if 'hips' in positions:
                hip_center_observed += 1
                for name in tracks:
                    if name in positions:
                        tracks[name].append({'sourceTimeSec': float(frame['sourceTimeSec']),
                                             'sourceDelta': ((positions['hips']-positions[name])/height).tolist()})
        # Partial tracking cannot silently replace the rest with stationary data.
        # Keep coverage counts for diagnosis while withholding incomplete tracks.
        coverage = {name: {'observed': len(rows), 'expected': len(frames)}
                    for name, rows in tracks.items()}
        tracks = {name: rows for name, rows in tracks.items() if len(rows) == len(frames)}
        return {'available': bool(tracks), 'tracks': tracks,
                'hipCenterCoverage': {'observed': hip_center_observed,
                                      'expected': len(frames)},
                'trackCoverage': coverage,
                'reason': None if tracks else 'pixel_track_coverage_incomplete'}
    finally:
        capture.release()


def observe_foot_material_episodes(
        video_path, observations, patch_evidence, episodes, *, cache_dir):
    """Measure exact-window shoe-material motion for caller-proposed full-sole episodes.

    This corroborates a contact proposal; it never creates a contact or changes
    the detector's contact-state labels. Each result requires independent,
    fully covered heel and toe texture tracks plus a stable heading vector.
    """
    video_path = Path(video_path)
    episodes = [dict(row) for row in (episodes or []) if isinstance(row, dict)]
    unavailable = {
        'available': False, 'policyVersion': FOOT_MATERIAL_POLICY_VERSION,
        'source': 'forward_backward_heel_toe_material_tracks', 'episodes': [],
    }
    if not video_path.is_file():
        return {**unavailable, 'reason': 'source_video_unavailable'}
    digest = _sha256_file(video_path)
    if (not isinstance(observations, dict)
            or observations.get('available') is not True
            or observations.get('sourceVideoSha256') != digest
            or (patch_evidence or {}).get('sourceVideoSha256') != digest):
        return {**unavailable, 'sourceVideoSha256': digest,
                'reason': 'source_identity_mismatch'}
    if not episodes:
        return {**unavailable, 'sourceVideoSha256': digest,
                'reason': 'no_proposed_full_sole_episodes'}

    observation_digest = hashlib.sha256(json.dumps(
        observations, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (not isinstance(patch_evidence, dict)
            or patch_evidence.get('available') is not True
            or patch_evidence.get('sourceTimeBasis') != 'absolute_source_video'):
        return {**unavailable, 'sourceVideoSha256': digest,
                'reason': 'timed_full_sole_patch_evidence_unavailable'}
    foot_states = (patch_evidence.get('feet') or {})
    normalized_episodes = []
    for episode in episodes:
        normalized_episodes.append({
            'episodeId': episode.get('episodeId'),
            'side': str(episode.get('side') or '').casefold(),
            'contactState': str(episode.get('contactState') or '').casefold(),
            'startFrame': episode.get('startFrame'),
            'endFrame': episode.get('endFrame'),
            'startTimeSec': episode.get('startTimeSec'),
            'endTimeSec': episode.get('endTimeSec'),
            'maximumDisplacementPixels': episode.get('maximumDisplacementPixels'),
        })
    cache_key = hashlib.sha256(json.dumps([
        FOOT_MATERIAL_POLICY_VERSION, digest, observation_digest,
        (patch_evidence or {}).get('sourceTimeOriginSec', 0.),
        (patch_evidence or {}).get('sourceFps'),
        (patch_evidence or {}).get('sourceTimesSec'),
        foot_states, normalized_episodes,
    ], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    cache = Path(cache_dir) / f'foot-material-{cache_key}.json'
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
            if (cached.get('sourceVideoSha256') == digest
                    and cached.get('observationDigest') == observation_digest
                    and cached.get('episodeIdentity') == normalized_episodes):
                return cached
        except (ValueError, OSError):
            pass

    result = {
        **unavailable,
        'sourceVideoSha256': digest,
        'observationDigest': observation_digest,
        'episodeIdentity': normalized_episodes,
        'episodes': [],
    }
    try:
        import cv2
    except ImportError:
        return {**result, 'reason': 'opencv_unavailable'}
    frames = observations.get('frames') or []
    if not frames:
        return {**result, 'reason': 'landmark_observations_unavailable'}
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (not capture.isOpened() or not np.isfinite(fps) or fps <= 0.
                or frame_count != len(frames)
                or (int(observations.get('imageWidth') or 0),
                    int(observations.get('imageHeight') or 0)) != (width, height)
                or abs(float(observations.get('fps') or 0.) - fps) > max(1e-6, fps * 1e-4)):
            return {**result, 'reason': 'source_clock_or_image_geometry_mismatch'}
        try:
            patch_fps = float((patch_evidence or {}).get('sourceFps'))
        except (TypeError, ValueError, OverflowError):
            patch_fps = float('nan')
        try:
            patch_frame_count = ((patch_evidence or {}).get('sourceFrameCount')
                                 if (patch_evidence or {}).get('sourceFrameCount') is None
                                 else int((patch_evidence or {})['sourceFrameCount']))
        except (TypeError, ValueError, OverflowError):
            patch_frame_count = -1
        if (not np.isfinite(patch_fps)
                or abs(patch_fps - fps) > max(1e-6, fps * 1e-4)
                or (patch_frame_count is not None and patch_frame_count != frame_count)):
            return {**result, 'reason': 'patch_source_clock_or_frame_count_mismatch'}
        patch_times = (patch_evidence or {}).get('sourceTimesSec') or []
        observation_origin = float(observations.get('sourceTimeOriginSec') or 0.)
        if ((patch_evidence or {}).get('sourceTimeBasis') != 'absolute_source_video'
                or len(patch_times) != frame_count):
            return {**result, 'reason': 'patch_clock_coverage_mismatch'}
        clock_tolerance = .5 / fps + 1e-7
        try:
            frame_local_times = np.asarray([
                float(frame.get('timeSeconds', float('nan'))) for frame in frames
            ], dtype=float)
            native_times = np.asarray(patch_times, dtype=float)
        except (TypeError, ValueError, OverflowError):
            return {**result, 'reason': 'source_native_clock_mismatch'}
        expected_native_times = observation_origin + frame_local_times
        if (not np.isfinite(frame_local_times).all()
                or not np.isfinite(native_times).all()
                or np.any(np.diff(native_times) <= 0.)
                or np.any(np.abs(frame_local_times - np.arange(frame_count) / fps)
                          > clock_tolerance)
                or np.any(np.abs(native_times - expected_native_times) > clock_tolerance)):
            return {**result, 'reason': 'source_native_clock_mismatch'}

        for episode in episodes:
            side = str(episode.get('side') or '').casefold()
            start = episode.get('startFrame')
            end = episode.get('endFrame')
            record = {
                'episodeId': episode.get('episodeId'), 'side': side,
                'startFrame': start, 'endFrame': end,
                'contactState': str(episode.get('contactState') or '').casefold(),
                'sourceVideoSha256': digest,
                'source': 'forward_backward_heel_toe_material_tracks',
                'passed': None, 'status': 'unresolved',
            }
            states = ((foot_states.get(side) or {}).get('states')
                      if side in {'left', 'right'} else None)
            if (record['contactState'] != 'full_sole' or not isinstance(states, list)
                    or not isinstance(start, int) or not isinstance(end, int)
                    or start < 0 or end >= frame_count or end < start
                    or len(states) != frame_count
                    or any(str(state).casefold() != 'full_sole'
                           for state in states[start:end + 1])):
                result['episodes'].append({
                    **record, 'status': 'not_applicable',
                    'reason': 'interval_not_observed_full_sole',
                })
                continue
            tolerance = episode.get('maximumDisplacementPixels')
            if (not isinstance(tolerance, (int, float))
                    or not np.isfinite(float(tolerance)) or float(tolerance) <= 0.):
                result['episodes'].append({
                    **record, 'reason': 'material_displacement_tolerance_unavailable',
                })
                continue
            source_start = float(native_times[start])
            source_end = float(native_times[end])
            try:
                requested_start = (float(episode['startTimeSec'])
                                   if 'startTimeSec' in episode else source_start)
                requested_end = (float(episode['endTimeSec'])
                                 if 'endTimeSec' in episode else source_end)
            except (TypeError, ValueError, OverflowError):
                requested_start = requested_end = float('nan')
            if (not np.isfinite(requested_start) or not np.isfinite(requested_end)
                    or abs(requested_start - source_start) > clock_tolerance
                    or abs(requested_end - source_end) > clock_tolerance):
                result['episodes'].append({
                    **record, 'reason': 'episode_clock_mismatch',
                })
                continue
            record.update({
                'sourceStartTimeSec': source_start,
                'sourceEndTimeSec': source_end,
                'maximumDisplacementPixels': float(tolerance),
            })
            if end - start + 1 < 3:
                result['episodes'].append({
                    **record, 'status': 'not_applicable',
                    'reason': 'episode_too_short_for_material_tracking',
                })
                continue
            episode_joints = [(frame.get('joints') or {}) for frame in frames[start:end + 1]]
            material_points = {
                part: [joints.get(f'{side}_{part}') or {} for joints in episode_joints]
                for part in ('ankle', 'heel', 'toe')
            }
            points_observable = all(
                float(point.get('confidence') or 0.) >= .8
                and isinstance(point.get('image'), list)
                and len(point['image']) >= 2
                and np.isfinite(point['image'][:2]).all()
                and all(0. <= float(value) <= 1. for value in point['image'][:2])
                for part in ('heel', 'toe') for point in material_points[part]
            ) and all(
                float(point.get('confidence') or 0.) >= .65
                and isinstance(point.get('image'), list)
                and len(point['image']) >= 2
                and np.isfinite(point['image'][:2]).all()
                and all(0. <= float(value) <= 1. for value in point['image'][:2])
                for point in material_points['ankle']
            )
            if not points_observable:
                result['episodes'].append({
                    **record, 'reason': 'foot_material_landmarks_occluded_or_low_confidence',
                })
                continue
            first_joints = episode_joints[0]
            heel = material_points['heel'][0]
            toe = material_points['toe'][0]
            scale = np.array([width, height], dtype=float)
            heel_xy = np.asarray(heel.get('image'), dtype=float) * scale
            toe_xy = np.asarray(toe.get('image'), dtype=float) * scale
            if (heel_xy.shape != (2,) or toe_xy.shape != (2,)
                    or not np.isfinite(heel_xy).all() or not np.isfinite(toe_xy).all()):
                result['episodes'].append({
                    **record, 'reason': 'heel_toe_landmark_geometry_invalid',
                })
                continue
            foot_vector = toe_xy - heel_xy
            foot_length = float(np.linalg.norm(foot_vector))
            if foot_length < 4.:
                result['episodes'].append({
                    **record, 'reason': 'foot_material_region_too_small',
                })
                continue
            ok = capture.set(cv2.CAP_PROP_POS_FRAMES, start)
            decoded, image = capture.read()
            if not ok or not decoded:
                result['episodes'].append({**record, 'reason': 'episode_frame_decode_failed'})
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            material_groups = {}
            # Restrict seeds to disjoint heel/toe halves of the observed sole hull.
            ankle_xy = np.asarray(material_points['ankle'][0]['image'][:2], dtype=float) * scale
            if not np.isfinite(ankle_xy).all():
                result['episodes'].append({
                    **record, 'reason': 'foot_material_ankle_geometry_invalid',
                })
                continue
            mask = np.zeros_like(gray)
            foot_hull = cv2.convexHull(np.round(
                np.asarray([ankle_xy, heel_xy, toe_xy], dtype=np.float32)).astype(np.int32))
            cv2.fillConvexPoly(mask, foot_hull, 255)
            # A small boundary allowance accounts for landmark localization
            # error; the ROI remains attached to the observed foot hull.
            margin = max(2, int(round(.15 * foot_length)))
            mask = cv2.dilate(mask, np.ones((2*margin+1, 2*margin+1), np.uint8))
            yy, xx = np.indices(gray.shape)
            along = ((xx - heel_xy[0]) * foot_vector[0]
                     + (yy - heel_xy[1]) * foot_vector[1]) / (foot_length ** 2)
            for name, region in (('heel', along <= .5), ('toe', along > .5)):
                region_mask = np.where(region, mask, 0).astype(np.uint8)
                features = cv2.goodFeaturesToTrack(
                    gray, maxCorners=40, qualityLevel=.01,
                    minDistance=2, mask=region_mask,
                )
                well_conditioned = False
                if features is not None and len(features) >= MIN_MATERIAL_CORNERS_PER_PATCH:
                    centered = features[:, 0, :] - features[:, 0, :].mean(axis=0)
                    spread = np.linalg.eigvalsh(centered.T @ centered / len(centered))
                    well_conditioned = bool(
                        np.isfinite(spread).all()
                        and spread[0] >= MIN_MATERIAL_PATCH_SPREAD_EIGENVALUE_PX2
                    )
                if (features is None or len(features) < MIN_MATERIAL_CORNERS_PER_PATCH
                        or not well_conditioned):
                    material_groups[name] = {
                        'available': False,
                        'reason': f'{name}_material_texture_or_2d_spread_insufficient',
                        'featureCount': 0 if features is None else int(len(features)),
                    }
                else:
                    material_groups[name] = {
                        'available': True, 'points': features,
                        'initial': features.copy(), 'valid': np.ones(len(features), dtype=bool),
                        'positions': [], 'validFeatureCounts': [], 'consensusPassed': True,
                    }
            if not all(material_groups[name].get('available')
                       for name in ('heel', 'toe')):
                result['episodes'].append({
                    **record,
                    'reason': 'heel_toe_material_texture_unavailable',
                    'heel': {k: v for k, v in material_groups['heel'].items()
                             if k not in {'points', 'initial', 'valid', 'positions', 'validFeatureCounts'}},
                    'toe': {k: v for k, v in material_groups['toe'].items()
                            if k not in {'points', 'initial', 'valid', 'positions', 'validFeatureCounts'}},
                })
                continue
            body_points = [
                np.asarray(point.get('image')[:2], dtype=float) * scale
                for point in first_joints.values()
                if isinstance(point, dict) and isinstance(point.get('image'), list)
                and len(point['image']) >= 2 and float(point.get('confidence') or 0.) >= .65
                and np.isfinite(point['image'][:2]).all()
            ]
            body_span = (float(np.linalg.norm(np.ptp(np.asarray(body_points), axis=0)))
                         if len(body_points) >= 3 else float(height))
            consensus_limit = max(1., .01 * body_span)
            previous_gray = gray
            for _frame_index in range(start, end + 1):
                if _frame_index > start:
                    decoded, image = capture.read()
                    if not decoded:
                        break
                    current_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    for track in material_groups.values():
                        points = track['points']
                        moved, status, _ = cv2.calcOpticalFlowPyrLK(
                            previous_gray, current_gray, points, None,
                            winSize=(21, 21), maxLevel=3,
                        )
                        back, back_status, _ = (
                            cv2.calcOpticalFlowPyrLK(
                                current_gray, previous_gray, moved, None,
                                winSize=(21, 21), maxLevel=3,
                            ) if moved is not None and status is not None else (None, None, None)
                        )
                        if moved is None or status is None or back is None or back_status is None:
                            track['valid'][:] = False
                            track['validFeatureCounts'].append(int(track['valid'].sum()))
                            track['positions'].append(None)
                            continue
                        round_trip = np.linalg.norm(back - points, axis=2)[:, 0]
                        track['valid'] &= (
                            (status[:, 0] == 1) & (back_status[:, 0] == 1)
                            & (round_trip < 1.)
                        )
                        track['points'] = moved
                    previous_gray = current_gray
                for track in material_groups.values():
                    valid = track['valid']
                    required_features = max(
                        MIN_MATERIAL_CORNERS_PER_PATCH,
                        int(np.ceil(.7 * len(track['initial']))),
                    )
                    if valid.sum() < required_features:
                        track['validFeatureCounts'].append(int(valid.sum()))
                        track['positions'].append(None)
                        continue
                    displacements = (track['points'] - track['initial'])[valid, 0]
                    center = np.median(displacements, axis=0)
                    residual_p90 = float(np.percentile(
                        np.linalg.norm(displacements - center, axis=1), 90))
                    track['consensusPassed'] &= residual_p90 <= consensus_limit
                    track['positions'].append(
                        (track['initial'][valid, 0] + displacements).mean(axis=0).tolist())
                    track['validFeatureCounts'].append(int(valid.sum()))

            metrics = {}
            for name, track in material_groups.items():
                positions = [point for point in track['positions'] if point is not None]
                if len(positions) != end - start + 1:
                    metrics[name] = {
                        'available': False,
                        'featureCount': int(len(track['initial'])),
                        'validFrameCount': len(positions),
                        'frameCount': end - start + 1,
                        'coverageRatio': len(positions) / (end - start + 1),
                        'consensusPassed': bool(track['consensusPassed']),
                    }
                    continue
                positions = np.asarray(positions, dtype=float)
                delta = positions - positions[0]
                metrics[name] = {
                    'available': bool(track['consensusPassed']),
                    'featureCount': int(len(track['initial'])),
                    'validFrameCount': len(positions),
                    'frameCount': end - start + 1,
                    'coverageRatio': 1.,
                    'maximumDisplacementPixels': float(np.max(np.linalg.norm(delta, axis=1))),
                    'rangePixels': float(np.linalg.norm(np.ptp(positions, axis=0))),
                    'consensusP90LimitPixels': consensus_limit,
                    'consensusPassed': bool(track['consensusPassed']),
                }
            heel_positions = material_groups['heel']['positions']
            toe_positions = material_groups['toe']['positions']
            heading = {'available': False, 'passed': None}
            if (len(heel_positions) == end - start + 1
                    and len(toe_positions) == end - start + 1
                    and all(point is not None for point in heel_positions + toe_positions)):
                heel_positions = np.asarray(heel_positions, dtype=float)
                toe_positions = np.asarray(toe_positions, dtype=float)
                heading_vectors = toe_positions - heel_positions
                initial_heading = heading_vectors[0]
                heading_length = max(float(np.linalg.norm(initial_heading)), 1e-6)
                vector_delta = heading_vectors - initial_heading
                angles = np.arctan2(
                    initial_heading[0] * heading_vectors[:, 1]
                    - initial_heading[1] * heading_vectors[:, 0],
                    initial_heading @ heading_vectors.T,
                )
                heading = {
                    'available': True,
                    'maximumHeadingChangeDegrees': float(np.max(np.abs(np.rad2deg(angles)))),
                    'maximumHeadingVectorDisplacementPixels': float(
                        np.max(np.linalg.norm(vector_delta, axis=1))),
                    'headingLengthPixels': heading_length,
                    'passed': bool(np.max(np.linalg.norm(vector_delta, axis=1))
                                   <= float(tolerance)),
                }
            evidence_complete = all(metrics.get(name, {}).get('available')
                                    for name in ('heel', 'toe')) and heading.get('available')
            passed = bool(
                evidence_complete and heading.get('passed')
                and all(metrics[name]['maximumDisplacementPixels'] <= float(tolerance)
                        for name in ('heel', 'toe'))
            )
            timed_samples = [
                {
                    'sourceTimeSec': float(native_times[start + offset]),
                    'heelCenterPx': heel_positions[offset].tolist(),
                    'toeCenterPx': toe_positions[offset].tolist(),
                }
                for offset in range(end - start + 1)
            ] if (len(heel_positions) == end - start + 1
                  and len(toe_positions) == end - start + 1
                  and all(point is not None for point in heel_positions + toe_positions)) else []
            result['episodes'].append({
                **record,
                'status': ('verified' if passed else 'failed') if evidence_complete else 'unresolved',
                'passed': passed if evidence_complete else None,
                'reason': (None if passed else 'material_motion_exceeds_stationary_tolerance')
                if evidence_complete else 'material_track_coverage_or_consensus_incomplete',
                'heel': metrics['heel'], 'toe': metrics['toe'], 'heading': heading,
                'landmarkConfidence': {
                    part: {
                        'minimum': float(min(float(point.get('confidence') or 0.)
                                             for point in material_points[part])),
                        'median': float(np.median([
                            float(point.get('confidence') or 0.)
                            for point in material_points[part]
                        ])),
                    }
                    for part in ('heel', 'toe', 'ankle')
                },
                'timedMaterialCenters': timed_samples,
            })
        result['available'] = bool(result['episodes'])
        result['status'] = 'verified' if any(row.get('passed') for row in result['episodes']) else 'unresolved'
        result['reason'] = None if result['available'] else 'no_material_episode_results'
        result['fps'] = fps
        result['frameCount'] = frame_count
    finally:
        capture.release()

    cache_path = Path(cache_dir) / f'foot-material-{cache_key}.json'
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    from .bake_and_rank import write_json_atomic
    write_json_atomic(cache_path, result)
    return result

"""Measure supported-body travel from source pixels without rewriting pose landmarks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

POLICY_VERSION = 1


def observe_support_relative_tracks(video_path, source_pose, observation, *, cache_dir):
    """Corroborate hip-to-foot travel where visual review observed a supported pelvis.

    Low texture, occlusion, inconsistent tracking or mismatched source bytes leave
    the original detector evidence in charge. No stationary trajectory is assumed.
    """
    unavailable = {'available': False, 'policyVersion': POLICY_VERSION, 'tracks': {}}
    answer = (observation or {}).get('observation') or {}
    from .body_support_observation import observed_body_support_contacts
    if ((observation or {}).get('status') != 'observed'
            or 'pelvis' not in observed_body_support_contacts(observation or {})
            or (source_pose or {}).get('coordinateSpace') != 'normalized_image_xy'):
        return {**unavailable, 'reason': 'supported_pelvis_not_observed'}
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
                for name in tracks:
                    if name in positions:
                        tracks[name].append({'sourceTimeSec': float(frame['sourceTimeSec']),
                                             'sourceDelta': ((positions['hips']-positions[name])/height).tolist()})
        # Partial tracking cannot silently replace the rest with stationary data.
        tracks = {n: rows for n, rows in tracks.items() if len(rows) == len(frames)}
        return {'available': bool(tracks), 'tracks': tracks,
                'reason': None if tracks else 'pixel_track_coverage_incomplete'}
    finally:
        capture.release()

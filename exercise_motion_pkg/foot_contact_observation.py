"""Observe heel/forefoot contact from the exact source, independently of RECONSTRUCTION."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from urllib.request import urlopen

import numpy as np
from .contact_constraints import contact_frame_bounds, is_stationary_contact

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"
POLICY_VERSION = 18
# Classification changes reuse the exact same expensive landmark observations.
OBSERVATION_CACHE_VERSION = 3
LANDMARKS = {"left_shoulder": 11, "right_shoulder": 12,
             "left_elbow": 13, "right_elbow": 14, "left_wrist": 15, "right_wrist": 16,
             "left_hip": 23, "right_hip": 24, "left_knee": 25, "right_knee": 26,
             "left_ankle": 27, "right_ankle": 28, "left_heel": 29, "right_heel": 30,
             "left_toe": 31, "right_toe": 32}
_RUNTIME_WARNING_EMITTED = False


def _patch_source_timing_metadata(frames, source_origin, source_fps=None):
    """Persist the same absolute source clock used by heel observations."""
    source_times = [float(source_origin) + float(frame['timeSeconds']) for frame in frames]
    result = {
        'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': float(source_origin),
        'sourceTimesSec': source_times,
        'sourceStartTimeSec': source_times[0],
        'sourceEndTimeSec': source_times[-1],
    }
    if source_fps is not None:
        fps = float(source_fps)
        if np.isfinite(fps) and fps > 0.:
            # Duration is relative to the source origin; callers add the
            # origin only when comparing absolute source-video timestamps.
            result['sourceVideoDurationSec'] = len(source_times) / fps
    return result


def _model_asset_path() -> Path:
    configured = os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL")
    return Path(configured) if configured else Path.home() / ".cache/myworkoutassistant/pose_models/pose_landmarker_full.task"


def _model_path() -> Path:
    path = _model_asset_path()
    if path.is_file():
        return path
    if os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL"):
        raise FileNotFoundError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".download") as stream:
        temporary = Path(stream.name)
        try:
            with urlopen(MODEL_URL, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    stream.write(block)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    except PermissionError:
        if not path.is_file():
            raise
        temporary.unlink(missing_ok=True)
    return path


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _observation_cache_path(cache_dir: Path, video_sha256: str, model_sha256: str) -> Path:
    return cache_dir / f"{video_sha256}.{model_sha256[:16]}.v{OBSERVATION_CACHE_VERSION}.json"


def _valid_observation_cache(payload: Any, video_sha256: str, model_sha256: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("available") is True
        and payload.get("observationCacheVersion") == OBSERVATION_CACHE_VERSION
        and payload.get("sourceVideoSha256") == video_sha256
        and payload.get("modelSha256") == model_sha256
    )


def copy_foot_landmark_cache(source_video_path: Path, target_video_path: Path) -> bool:
    """Copy verified observations only when both videos and model bytes match."""
    if not source_video_path.is_file() or not target_video_path.is_file():
        return False
    temporary: Path | None = None
    try:
        source_sha256 = _sha256_file(source_video_path)
        if source_sha256 != _sha256_file(target_video_path):
            return False
        model_path = _model_asset_path()
        if not model_path.is_file():
            return False
        model_sha256 = _sha256_file(model_path)
        source_cache = _observation_cache_path(
            source_video_path.parent / "foot_landmarks", source_sha256, model_sha256
        )
        payload = json.loads(source_cache.read_text(encoding="utf-8"))
        if not _valid_observation_cache(payload, source_sha256, model_sha256):
            return False
        target_cache = _observation_cache_path(
            target_video_path.parent / "foot_landmarks", source_sha256, model_sha256
        )
        if source_cache.resolve() == target_cache.resolve():
            return True
        target_cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", dir=target_cache.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(source_cache.read_bytes())
        temporary.replace(target_cache)
        temporary = None
        return True
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def observe_foot_landmarks(video_path: Path, *, cache_dir: Path | None = None) -> dict[str, Any]:
    """Local tracked inference; cache identity includes exact video bytes."""
    digest = _sha256_file(video_path)
    cache_dir = cache_dir or video_path.parent / "foot_landmarks"
    configured_model = os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL")
    model_path = _model_asset_path()
    if configured_model and not model_path.is_file():
        raise FileNotFoundError(model_path)
    model_sha256 = _sha256_file(model_path) if model_path.is_file() else None
    cache = _observation_cache_path(cache_dir, digest, model_sha256) if model_sha256 else None
    if cache is not None and cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if _valid_observation_cache(payload, digest, model_sha256):
            return payload
    try:
        import cv2
        import mediapipe as mp
    except ImportError as error:
        global _RUNTIME_WARNING_EMITTED
        if not _RUNTIME_WARNING_EMITTED:
            logging.getLogger(__name__).warning(
                "Heel/toe observation unavailable: install the motion extra in the active Python environment. "
                "Using legacy contact evidence, not observed foot-patch detection."
            )
            _RUNTIME_WARNING_EMITTED = True
        return {"available": False, "reason": f"foot_landmark_runtime_unavailable: {error}"}
    model_path = _model_path()
    model_sha256 = _sha256_file(model_path)
    cache = _observation_cache_path(cache_dir, digest, model_sha256)
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    capture = cv2.VideoCapture(str(video_path))
    frames = []
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not capture.isOpened() or fps <= 0:
            raise ValueError(f"Cannot decode foot landmark source: {video_path}")
        image_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        image_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                result = detector.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                    round(index * 1000 / fps),
                )
                joints = {}
                if result.pose_landmarks and result.pose_world_landmarks:
                    for name, landmark_index in LANDMARKS.items():
                        point = result.pose_landmarks[0][landmark_index]
                        world = result.pose_world_landmarks[0][landmark_index]
                        joints[name] = {"image": [point.x, point.y], "world": [world.x, world.y, world.z],
                                        "confidence": min(point.visibility, point.presence)}
                frames.append({"timeSeconds": index / fps, "joints": joints})
                index += 1
    finally:
        capture.release()
    payload = {"available": True, "policyVersion": POLICY_VERSION,
               "observationCacheVersion": OBSERVATION_CACHE_VERSION,
               "sourceVideoSha256": digest, "modelSha256": model_sha256,
               "source": "mediapipe_full_heel_forefoot", "fps": fps, "frames": frames,
               "imageWidth": image_width, "imageHeight": image_height}
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_dir, delete=False) as stream:
        json.dump(payload, stream)
        temporary = Path(stream.name)
    temporary.replace(cache)
    return payload


def load_cached_foot_landmarks(video_path: Path, *, cache_dir: Path | None = None) -> dict[str, Any] | None:
    """Load hash-bound landmark observations without downloading or running a model."""
    if not video_path.is_file():
        return None
    try:
        digest = _sha256_file(video_path)
        cache_dir = cache_dir or video_path.parent / "foot_landmarks"
        configured_model = os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL")
        model_path = _model_asset_path()
        required_model_hash = (
            _sha256_file(model_path)
            if (configured_model and model_path.is_file())
            else None
        )
        if configured_model and required_model_hash is None:
            return None
        matching: list[dict[str, Any]] = []
        for cache in cache_dir.glob(f"{digest}.*.v{OBSERVATION_CACHE_VERSION}.json"):
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            model_sha256 = payload.get("modelSha256") if isinstance(payload, dict) else None
            if (isinstance(model_sha256, str) and len(model_sha256) == 64
                    and _observation_cache_path(cache_dir, digest, model_sha256).name == cache.name
                    and _valid_observation_cache(payload, digest, model_sha256)):
                if required_model_hash is not None and model_sha256 != required_model_hash:
                    continue
                matching.append(payload)
        model_hashes = {payload["modelSha256"] for payload in matching}
        return matching[0] if len(model_hashes) == 1 and matching else None
    except OSError:
        return None


def _materialize_foot_patch_contacts(
    *, side, states, valid, toe_valid, heel_points, toe_points, foot_sizes, image_pitch,
    world_pitch, image_only_toe, unresolved_heel_recontact, references,
    tolerances, uncalibrated_toe, answer, support_contacts,
):
    contacts = []
    count = len(states)
    start = 0
    while start < count:
        end = start + 1
        while end < count and states[end] == states[start]:
            end += 1
        state = states[start]
        if end - start < 3:
            states[start:end] = ["unknown"] * (end - start)
        elif state not in {"unknown", "airborne"}:
            anchor_points = heel_points[start:end] if state == "heel_only" else toe_points[start:end]
            scale = float(np.median(foot_sizes[start:end]))
            chunks = np.array_split(anchor_points, min(3, len(anchor_points)))
            centers = np.array([np.median(chunk, axis=0) for chunk in chunks])
            spread = float(np.linalg.norm(np.ptp(centers, axis=0)))
            stationary = spread <= max(0.005, scale * 0.15)
            if state == 'toe_only' and np.any(image_only_toe[start:end]) and not stationary:
                states[start:end] = ['unknown'] * (end - start)
                start = end
                continue
            if uncalibrated_toe and np.linalg.norm(np.ptp(anchor_points, axis=0)) > max(.005, scale * .15):
                states[start:end] = ['unknown'] * (end - start)
                start = end
                continue
            lift_ratio = 0.0
            if state in {"toe_only", "heel_only"} and not uncalibrated_toe:
                lift_angle = min(
                    max(0.0, float(np.median(np.abs(track[start:end] - center))) - tolerance)
                    for track, center, tolerance in zip(
                        (image_pitch, world_pitch), references, tolerances
                    )
                )
                lift_ratio = float(np.sin(min(lift_angle, np.pi / 2)))
            contact = {
                "jointName": f"{side}_foot", "supportKind": "observed_foot_patch",
                "contactState": state, "contactMotion": "stationary" if stationary else "unknown",
                "verticalOnly": state == "heel_only", "startRatio": start / max(1, count - 1),
                "endRatio": (end - 1) / max(1, count - 1), "confidence": 0.8,
                "source": "observed_heel_and_forefoot", "anchorImageSpread": spread,
                "minimumLiftRatio": lift_ratio,
            }
            if state == 'toe_only' and np.any(image_only_toe[start:end]):
                contact['heelPhaseEvidence'] = {
                    'source': 'image_only_toe_pitch', 'worldHeightResolved': False,
                }
            elif state == 'toe_only' and np.any(unresolved_heel_recontact[start:end]):
                contact['heelPhaseEvidence'] = {
                    'source': 'heel_recontact_unresolved', 'worldHeightResolved': False,
                }
            if uncalibrated_toe:
                contact['surfaceKind'] = ('ground' if answer[f'{side}FootSurface'] == 'ground'
                                          else 'observed_raised_support_surface')
                contact['source'] = 'exact_visual_contact_and_independent_stationary_toe'
            if state == 'full_sole' and stationary:
                for candidate_index, candidate in enumerate(support_contacts):
                    first, last = contact_frame_bounds(candidate, count)
                    if (candidate.get('jointName') == f'{side}_ankle'
                            and is_stationary_contact(candidate)
                            and first <= start and end - 1 <= last):
                        # Missing heel observations split patches, not an
                        # independently observed stationary stance.
                        contact['ankleAnchorGroupId'] = f'{side}:ankle:{candidate_index}'
                        break
            contacts.append(contact)
        start = end
    assign_stationary_anchor_groups(
        contacts, side=side, valid=valid, toe_valid=toe_valid, toe_points=toe_points,
        foot_sizes=foot_sizes, states=states,
    )
    return contacts


def _heel_image_observations(
    *, frames, side, source_origin, image_width, image_height, states,
    stationary_groups_by_frame=None,
):
    rows = []
    for index, frame in enumerate(frames):
        heel = frame['joints'].get(f'{side}_heel')
        toe = frame['joints'].get(f'{side}_toe')
        if (not heel or not toe or heel['confidence'] < .8 or toe['confidence'] < .8
                or any(not np.isfinite(point['image']).all()
                       or any(value < 0.0 or value > 1.0 for value in point['image'])
                       for point in (heel, toe))):
            continue
        rows.append({
            'sourceTimeSec': source_origin + float(frame['timeSeconds']),
            'heelImagePoint': [float(heel['image'][0] * image_width / image_height),
                               float(heel['image'][1])],
            'toeImagePoint': [float(toe['image'][0] * image_width / image_height),
                              float(toe['image'][1])],
            'heelConfidence': float(heel['confidence']),
            'toeConfidence': float(toe['confidence']),
            'state': states[index],
            'stationaryAnchorGroupId': (stationary_groups_by_frame or {}).get(index),
        })
    return rows


def _preserve_heel_release_until_recontact(
    *, side, states, contacts, valid, toe_valid, heel_points, toe_points, foot_sizes,
    heel_toe_confidence, image_axes, unresolved_heel_recontact,
):
    """Keep a toe-pivot state until heel position returns to its stance track.

    Neutral sole pitch is not positive heel-contact evidence. A recontact must
    return the heel to the same observed stationary-toe anchor within the
    high-confidence pre-release measurement envelope for three frames.
    """
    count = len(states)
    indexed_contacts = []
    for contact in contacts:
        if contact.get('jointName') != f'{side}_foot':
            continue
        start, end = contact_frame_bounds(contact, count)
        indexed_contacts.append((start, end, contact))
    indexed_contacts.sort(key=lambda row: (row[0], row[1]))

    trusted_fullsole: dict[str, list[int]] = {}
    pending_release: dict[str, dict[str, Any]] = {}
    previous_end = -1
    for start, end, contact in indexed_contacts:
        if any(state == 'airborne' for state in states[previous_end + 1:start]):
            # A flight separates ground episodes. A later landing must establish
            # its own stance track instead of inheriting the pre-flight toe pivot.
            pending_release.clear()
            trusted_fullsole.clear()
        contact_state = contact.get('contactState')
        group = contact.get('anchorGroupId')
        indexes = list(range(start, end + 1))
        reliable = [
            index for index in indexes
            if valid[index] and heel_toe_confidence[index] >= .8
        ]
        if contact_state == 'airborne':
            pending_release.clear()
            trusted_fullsole.clear()
            previous_end = end
            continue
        if contact_state == 'toe_only':
            if group is not None:
                pending_release[group] = {
                    'lastToeOnlyEnd': end,
                    'baselineIndexes': list(trusted_fullsole.get(group, [])),
                }
            previous_end = end
            continue
        if contact_state != 'full_sole':
            previous_end = end
            continue

        if not pending_release:
            if group is not None:
                trusted_fullsole.setdefault(group, []).extend(reliable)
            previous_end = end
            continue

        release = pending_release.get(group) if group is not None else None
        if release is None:
            # A different or unlinked anchor after a pivot is a new, unresolved
            # ground pose until its heel contact is independently established.
            states[start:end + 1] = ['unknown'] * (end - start + 1)
            previous_end = end
            continue

        baseline_indexes = [
            index for index in release['baselineIndexes']
            if index < start and valid[index] and heel_toe_confidence[index] >= .8
        ]
        returned = np.zeros(count, dtype=bool)
        if len(baseline_indexes) >= 3:
            toe_anchor = np.median(toe_points[baseline_indexes], axis=0)
            baseline_heel_offsets = (heel_points[baseline_indexes] - toe_anchor) * image_axes
            stance_center = np.median(baseline_heel_offsets, axis=0)
            baseline_residuals = np.linalg.norm(
                baseline_heel_offsets - stance_center, axis=1,
            )
            noise_radius = float(np.quantile(baseline_residuals, .95, method='higher'))
            for index in reliable:
                heel_offset = (heel_points[index] - toe_anchor) * image_axes
                returned[index] = np.linalg.norm(heel_offset - stance_center) <= noise_radius

        recontact_start = None
        run = 0
        for index in indexes:
            run = run + 1 if returned[index] else 0
            if run >= 3:
                recontact_start = index - 2
                break

        toe_supported_start = release['lastToeOnlyEnd'] + 1
        toe_supported_end = release['lastToeOnlyEnd']
        if group is not None and len(baseline_indexes) >= 3:
            toe_anchor = np.median(toe_points[baseline_indexes], axis=0)
            baseline_size = float(np.median(foot_sizes[baseline_indexes]))
            toe_tolerance_pixels = max(.005 * min(image_axes), baseline_size * .15 * min(image_axes))
            for index in range(toe_supported_start, end + 1):
                if not toe_valid[index]:
                    break
                if np.linalg.norm((toe_points[index] - toe_anchor) * image_axes) > toe_tolerance_pixels:
                    break
                toe_supported_end = index
        contiguous_toe_support = toe_supported_end >= toe_supported_start
        if recontact_start is None:
            states[start:end + 1] = ['unknown'] * (end - start + 1)
            if contiguous_toe_support:
                states[toe_supported_start:toe_supported_end + 1] = ['toe_only'] * (
                    toe_supported_end - toe_supported_start + 1
                )
                unresolved_heel_recontact[toe_supported_start:toe_supported_end + 1] = True
            previous_end = end
            continue

        if recontact_start > start:
            states[start:recontact_start] = ['unknown'] * (recontact_start - start)
        if contiguous_toe_support:
            prefix_end = min(toe_supported_end, recontact_start - 1)
            if prefix_end >= toe_supported_start:
                states[toe_supported_start:prefix_end + 1] = ['toe_only'] * (
                    prefix_end - toe_supported_start + 1
                )
                unresolved_heel_recontact[toe_supported_start:prefix_end + 1] = True
        for index in range(recontact_start, end + 1):
            states[index] = 'full_sole' if returned[index] else 'unknown'
        pending_release.pop(group, None)
        trusted_fullsole.setdefault(group, []).extend(
            index for index in indexes if returned[index]
        )
        previous_end = end


def classify_foot_contacts(
    observations: dict[str, Any], evidence: dict[str, Any],
    source_pose: dict[str, Any], camera_normal: list[float] | None = None,
    depth_alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve partial contacts from observed heel-to-toe geometry.

    A stationary ankle is only a calibration candidate, never a flat-foot
    command. Image/3D agreement supports resolved heel height; a clear image-only
    toe pivot retains angular evidence but leaves heel height unresolved.
    """
    if not observations.get("available"):
        return {"available": False, "reason": observations.get("reason")}
    frames = observations.get("frames", [])
    source_frames = source_pose.get("frames", [])
    if not frames or not source_frames:
        return {"available": False, "reason": "missing_reference_frames"}
    count = len(frames)
    # MediaPipe normalizes x and y by different image dimensions. Angles
    # require equal axis units; retain normalized coordinates for identity and
    # anchor comparisons, but measure pitch in the actual image plane. Exact
    # source dimensions also cover retained v2 landmark caches without sizes.
    image_width = observations.get("imageWidth", source_pose.get("imageWidth", 1))
    image_height = observations.get("imageHeight", source_pose.get("imageHeight", 1))
    image_axes = np.asarray([image_width, image_height], dtype=float)
    if not np.isfinite(image_axes).all() or np.any(image_axes <= 0):
        return {"available": False, "reason": "invalid_image_dimensions"}
    ground_referenced = camera_normal is not None
    normal = np.asarray(camera_normal if ground_referenced else [0, -1, 0], dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-8:
        return {"available": False, "reason": "invalid_ground_normal"}
    normal /= max(np.linalg.norm(normal), 1e-8)
    contacts = evidence.get("footContactCandidates", evidence.get("contacts", []))
    source_origin = float(source_pose.get("sourceTimeOriginSec", 0.))
    result: dict[str, Any] = {"available": True, "policyVersion": POLICY_VERSION,
                            "source": observations["source"], "sourceFrameCount": count,
                            "sourceFps": observations.get("fps"),
                            **_patch_source_timing_metadata(
                                frames, source_origin, observations.get("fps")),
                            "sourceVideoSha256": observations.get("sourceVideoSha256"),
                            "feet": {}, "contacts": []}
    for side in ("left", "right"):
        valid = np.zeros(count, dtype=bool)
        toe_valid = np.zeros(count, dtype=bool)
        ray_observations = []
        image_pitch = np.zeros(count)
        world_pitch = np.zeros(count)
        toe_points = np.zeros((count, 2))
        heel_points = np.zeros((count, 2))
        foot_sizes = np.zeros(count)
        pixel_foot_sizes = np.zeros(count)
        for index, frame in enumerate(frames):
            points = frame["joints"]
            ankle, heel, toe = (points.get(f"{side}_{part}")
                                for part in ("ankle", "heel", "toe"))
            if (toe and toe['confidence'] >= .8
                    and np.isfinite(toe['image']).all()
                    and all(0.0 <= value <= 1.0 for value in toe['image'])):
                toe_points[index] = toe['image']
                toe_valid[index] = True
            # The ankle-to-toe ray is independent source motion evidence. A
            # missing/occluded heel keeps contact unknown but must not erase
            # this articulation signal.
            if any(not point or point["confidence"] < 0.8 for point in (ankle, toe)):
                continue
            if any(not np.isfinite(point['image']).all()
                   or any(value < 0.0 or value > 1.0 for value in point['image'])
                   for point in (ankle, toe)):
                continue
            source_time = source_origin + float(frame["timeSeconds"])
            reference = min(source_frames, key=lambda f: abs(float(f.get("sourceTimeSec", f.get("timeSec", 0))) - source_time))
            reference_ankle = reference.get("joints", {}).get(f"{side}_ankle")
            if reference_ankle is None or np.linalg.norm(np.asarray(ankle["image"]) - reference_ankle[:2]) > 0.08:
                continue
            ray_delta = np.asarray(toe["image"]) - ankle["image"]
            ray_pixel_delta = ray_delta * image_axes
            ray_pixel_length = np.linalg.norm(ray_pixel_delta)
            ankle_disagreement = np.linalg.norm(
                (np.asarray(ankle["image"]) - np.asarray(reference_ankle[:2])) * image_axes)
            if (ray_pixel_length < 0.005 * min(image_axes)
                    or ankle_disagreement > max(.003 * np.min(image_axes), .5 * ray_pixel_length)):
                continue
            ray_observations.append({
                "sourceTimeSec": source_origin + float(frame["timeSeconds"]),
                # Match _pose_frames' aspect-corrected normalized image plane.
                "ankleToToeImageRay": [
                    float(ray_delta[0] * image_width / image_height), float(ray_delta[1]),
                ],
                "toeImagePoint": [
                    float(toe['image'][0] * image_width / image_height),
                    float(toe['image'][1]),
                ],
                "confidence": float(min(ankle["confidence"], toe["confidence"])),
                "state": "unknown",
                "frameIndex": index,
            })
            # Contact classification still requires all three in-frame world
            # landmarks and the established whole-foot geometry checks.
            if (not heel or heel["confidence"] < 0.8
                    or any(not np.isfinite(point['image']).all()
                           or not np.isfinite(point['world']).all()
                           or any(value < 0.0 or value > 1.0 for value in point['image'])
                           for point in (ankle, heel, toe))):
                continue
            image_delta = np.asarray(toe["image"]) - heel["image"]
            world_delta = np.asarray(toe["world"]) - heel["world"]
            image_length, world_length = np.linalg.norm(image_delta), np.linalg.norm(world_delta)
            if image_length < 0.005 or world_length < 0.02:
                continue
            pixel_delta = image_delta * image_axes
            pixel_length = np.linalg.norm(pixel_delta)
            # A whole-image identity tolerance can accept an ankle displaced
            # by most of the foot's length. In that case the accompanying heel
            # and toe are not independent evidence of a support change, even
            # when the landmark model reports high confidence.
            if ankle_disagreement > max(.003 * np.min(image_axes), .5 * pixel_length):
                continue
            image_pitch[index] = np.arcsin(np.clip(-pixel_delta[1] / pixel_length, -1, 1))
            world_pitch[index] = np.arcsin(np.clip(np.dot(world_delta, normal) / world_length, -1, 1))
            if ground_referenced:
                # A stationary tilted foot is not a neutral sole. Project its
                # ground-tangent direction into the image, then measure the
                # observed toe/heel ray toward the projected ground normal.
                # This follows camera orientation instead of assuming image-up.
                tangent = world_delta - normal * np.dot(world_delta, normal)
                projected_length = np.linalg.norm(tangent[:2])
                if projected_length < .1 * world_length:
                    continue  # Nearly end-on: image evidence cannot resolve pitch.
                ground_direction = tangent[:2] / projected_length
                lift_direction = normal[:2] - ground_direction * np.dot(normal[:2], ground_direction)
                lift_length = np.linalg.norm(lift_direction)
                if lift_length < .1:
                    continue
                lift_direction /= lift_length
                image_pitch[index] = np.arctan2(
                    np.dot(pixel_delta, lift_direction), np.dot(pixel_delta, ground_direction))
            toe_points[index], heel_points[index] = toe["image"], heel["image"]
            foot_sizes[index] = image_length
            pixel_foot_sizes[index] = pixel_length
            valid[index] = True
        possible_contact = np.zeros(count, dtype=bool)
        calibration = np.zeros(count, dtype=bool)
        forefoot_contact = np.zeros(count, dtype=bool)
        whole_foot_contact = np.zeros(count, dtype=bool)
        for record in contacts:
            if str(record.get("jointName", "")) not in {f"{side}_ankle", f"{side}_foot"}:
                continue
            start, end = contact_frame_bounds(record, count)
            possible_contact[start:end + 1] = True
            if record.get('supportKind') == 'forefoot':
                forefoot_contact[start:end + 1] = True
            elif not record.get('verticalOnly'):
                whole_foot_contact[start:end + 1] = True
            if not record.get("verticalOnly"):
                calibration[start:end + 1] = True
        calibration &= valid
        states = ["unknown"] * count
        image_only_toe = np.zeros(count, dtype=bool)
        unresolved_heel_recontact = np.zeros(count, dtype=bool)
        uncalibrated_toe = np.count_nonzero(calibration) < 4
        observed = evidence.get('bodySupportObservation') or {}
        from .body_support_observation import validated_body_support_answer
        answer = validated_body_support_answer(observed)
        toe_contact_observed = (
            answer is not None
            and isinstance(observations.get('sourceVideoSha256'), str)
            and observed.get('sourceVideoSha256') == observations['sourceVideoSha256']
            and answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
            and answer.get(f'{side}FootSurface') in {'ground', 'raised_surface'})
        if uncalibrated_toe and not toe_contact_observed:
            heel_image_observations = _heel_image_observations(
                frames=frames, side=side, source_origin=source_origin,
                image_width=image_width, image_height=image_height, states=states,
            )
            for row in ray_observations:
                row.pop("frameIndex", None)
            result["feet"][side] = {"states": states, "reason": "no_observed_stance_calibration",
                                    "rayObservationCount": len(ray_observations),
                                    "rayObservations": ray_observations,
                                    "heelImageObservations": heel_image_observations}
            continue
        if uncalibrated_toe and np.count_nonzero(valid) < 3:
            heel_image_observations = _heel_image_observations(
                frames=frames, side=side, source_origin=source_origin,
                image_width=image_width, image_height=image_height, states=states,
            )
            for row in ray_observations:
                row.pop("frameIndex", None)
            result['feet'][side] = {'states': states, 'reason': 'independent_foot_identity_unverified',
                                    'validObservationCount': int(valid.sum()),
                                    'rayObservationCount': len(ray_observations),
                                    'rayObservations': ray_observations,
                                    'heelImageObservations': heel_image_observations}
            continue
        # Estimate the neutral observed sole orientation from supported stance,
        # not from the reconstructed foot or an assumed camera angle.
        references = []
        tolerances = []
        for track in (image_pitch, world_pitch):
            samples = track[calibration]
            center = 0.0 if ground_referenced or uncalibrated_toe else float(np.median(samples))
            references.append(center)
            tolerances.append(np.deg2rad(8) if ground_referenced or uncalibrated_toe else
                              max(np.deg2rad(8), 3 * 1.4826 * float(np.median(np.abs(samples - center)))))
        for index in range(count):
            if not valid[index]:
                continue
            if uncalibrated_toe:
                # Confirm only the visible toe; absent heel calibration cannot
                # establish a flat sole or a lifted heel.
                states[index] = 'toe_only'
                continue
            if not possible_contact[index]:
                # Flight needs positive separation evidence, not merely a
                # missing contact. Use depth only at its observed timestamp.
                depth = (depth_alignment or {}).get("videoFloorDistanceObservations", {}).get(f"{side}_ankle", [])
                if depth:
                    sample = min(depth, key=lambda value: abs(value["timeSeconds"] - frames[index]["timeSeconds"]))
                    ground_toe_y = float(np.median(toe_points[calibration, 1]))
                    ground_heel_y = float(np.median(heel_points[calibration, 1]))
                    world_points = frames[index]["joints"]
                    foot_reach = np.linalg.norm(np.asarray(world_points[f"{side}_toe"]["world"]) - world_points[f"{side}_heel"]["world"])
                    plane_error = float((depth_alignment or {}).get("cameraGroundPlane", {}).get("rmsError", 0.05))
                    if (abs(sample["timeSeconds"] - frames[index]["timeSeconds"]) <= 1 / observations["fps"]
                            and sample["distance"] > foot_reach + 3 * plane_error
                            and toe_points[index, 1] < ground_toe_y - foot_sizes[index]
                            and heel_points[index, 1] < ground_heel_y - foot_sizes[index]):
                        states[index] = "airborne"
                continue
            differences = [image_pitch[index] - references[0], world_pitch[index] - references[1]]
            if all(abs(value) <= tolerance for value, tolerance in zip(differences, tolerances)):
                # A neutral-looking pitch is not evidence of heel support when
                # the independent contact observation establishes only forefoot
                # contact. Keep its toe anchor without inventing an ankle lock.
                states[index] = ("toe_only" if forefoot_contact[index] and not whole_foot_contact[index]
                                 else "full_sole")
            elif all(value < -tolerance for value, tolerance in zip(differences, tolerances)):
                states[index] = "toe_only"
            elif all(value > tolerance for value, tolerance in zip(differences, tolerances)):
                states[index] = "heel_only"
            elif (differences[0] < -tolerances[0]
                  and pixel_foot_sizes[index] >= 0.5 * float(np.median(pixel_foot_sizes[calibration]))
                  and differences[1] <= tolerances[1]):
                # MediaPipe's world pose can miss a visible heel pivot. The
                # source-calibrated image angle is sufficient only when the
                # observed forefoot also stays in place across the episode.
                states[index] = "toe_only"
                image_only_toe[index] = True
        # Do not bridge unknown observations or erase a real release. Isolated
        # detections lack enough temporal evidence to impose a new constraint.
        patch_contacts = _materialize_foot_patch_contacts(
            side=side, states=states, valid=valid, toe_valid=toe_valid, heel_points=heel_points,
            toe_points=toe_points, foot_sizes=foot_sizes, image_pitch=image_pitch,
            world_pitch=world_pitch, image_only_toe=image_only_toe,
            unresolved_heel_recontact=unresolved_heel_recontact,
            references=references, tolerances=tolerances, uncalibrated_toe=uncalibrated_toe,
            answer=answer, support_contacts=contacts,
        )
        heel_toe_confidence = np.asarray([
            min(float(frame['joints'][f'{side}_heel']['confidence']),
                float(frame['joints'][f'{side}_toe']['confidence']))
            if (frame['joints'].get(f'{side}_heel') and frame['joints'].get(f'{side}_toe'))
            else 0.0
            for frame in frames
        ])
        _preserve_heel_release_until_recontact(
            side=side, states=states, contacts=patch_contacts, valid=valid, toe_valid=toe_valid,
            heel_points=heel_points, toe_points=toe_points, foot_sizes=foot_sizes,
            heel_toe_confidence=heel_toe_confidence, image_axes=image_axes,
            unresolved_heel_recontact=unresolved_heel_recontact,
        )
        patch_contacts = _materialize_foot_patch_contacts(
            side=side, states=states, valid=valid, toe_valid=toe_valid, heel_points=heel_points,
            toe_points=toe_points, foot_sizes=foot_sizes, image_pitch=image_pitch,
            world_pitch=world_pitch, image_only_toe=image_only_toe,
            unresolved_heel_recontact=unresolved_heel_recontact,
            references=references, tolerances=tolerances, uncalibrated_toe=uncalibrated_toe,
            answer=answer, support_contacts=contacts,
        )
        result["contacts"].extend(patch_contacts)
        stationary_groups_by_frame = {}
        for contact_index, contact in enumerate(result["contacts"]):
            if (contact.get('jointName') != f'{side}_foot'
                    or contact.get('contactMotion') != 'stationary'
                    or contact.get('contactState') not in {'full_sole', 'toe_only'}):
                continue
            first, last = contact_frame_bounds(contact, count)
            anchor_group = contact.get('anchorGroupId') or f'{side}:stationary:{contact_index}'
            for frame_index in range(first, last + 1):
                if states[frame_index] == contact.get('contactState'):
                    stationary_groups_by_frame[frame_index] = anchor_group
        for row in ray_observations:
            frame_index = row.get('frameIndex')
            if frame_index in stationary_groups_by_frame:
                row['stationaryAnchorGroupId'] = stationary_groups_by_frame[frame_index]
        ray_by_frame = {
            int(row['frameIndex']): row for row in ray_observations
            if row.get('frameIndex') is not None
        }
        for row in ray_observations:
            row["state"] = states[row["frameIndex"]]
            row.pop("frameIndex", None)
        # The heel trajectory is a separate camera-space observation. Keep it
        # available even when ankle identity prevents an ankle-to-toe ray row.
        heel_image_observations = _heel_image_observations(
            frames=frames, side=side, source_origin=source_origin,
            image_width=image_width, image_height=image_height, states=states,
            stationary_groups_by_frame=stationary_groups_by_frame,
        )
        result["feet"][side] = {"states": states, "validObservationCount": int(valid.sum()),
                                "rayObservationCount": len(ray_observations),
                                "rayObservations": ray_observations,
                                "heelImageObservations": heel_image_observations,
                                "pitchReferenceSource": ("heel_unobserved" if uncalibrated_toe else
                                                         "observed_ground_plane" if ground_referenced else "relative_stance"),
                                "imagePitchReference": references[0], "worldPitchReference": references[1],
                                "pitchTolerances": tolerances}
    return result


def assign_stationary_anchor_groups(
    contacts, *, side, valid, toe_points, foot_sizes, states, toe_valid=None,
):
    """Retain a toe anchor across a pitch-uncertain but visibly stationary gap.

    Contact classification can change from full sole to toe-only without the
    toe changing its location. Unknown contact frames remain unconstrained;
    only the observed episodes share an anchor. A missing toe observation can
    also be resolved by an independently shared stationary ankle and matching
    observed sole positions on either side; it never labels the gap as contact.
    """
    previous = None
    observed_stances = {}
    count = len(valid)
    toe_valid = valid if toe_valid is None else toe_valid
    for number, contact in enumerate(contacts):
        if contact.get('jointName') != f'{side}_foot':
            continue
        if contact.get('contactMotion') != 'stationary' or contact.get('contactState') not in {'full_sole', 'toe_only'}:
            previous = None
            continue
        start, end = contact_frame_bounds(contact, count)
        group = f'{side}:toe:{number}'
        if previous is not None:
            previous_contact, previous_end = previous
            indexes = slice(previous_end, start + 1)
            visible = bool(np.all(toe_valid[indexes]))
            compatible = all(state in {'unknown', 'full_sole', 'toe_only'} for state in states[indexes])
            if visible and compatible:
                points = toe_points[indexes]
                spread = float(np.linalg.norm(np.ptp(points, axis=0)))
                local_size = foot_sizes[indexes]
                local_size = local_size[local_size > 0]
                if not len(local_size):
                    previous_start, previous_end = contact_frame_bounds(previous_contact, count)
                    current_start, current_end = contact_frame_bounds(contact, count)
                    local_size = np.concatenate((
                        foot_sizes[previous_start:previous_end + 1],
                        foot_sizes[current_start:current_end + 1],
                    ))
                    local_size = local_size[local_size > 0]
                scale = float(np.median(local_size)) if len(local_size) else 0.0
                tolerance = max(.005, scale * .15)
                if spread <= tolerance:
                    group = previous_contact['anchorGroupId']
        ankle_group = contact.get('ankleAnchorGroupId') if contact.get('contactState') == 'full_sole' else None
        if ankle_group is not None:
            center = np.median(toe_points[start:end + 1], axis=0)
            size = float(np.median(foot_sizes[start:end + 1]))
            candidates = observed_stances.setdefault(ankle_group, [])
            for prior_contact, prior_end, prior_center, prior_size in reversed(candidates):
                # Independent stationary-ankle evidence plus the observed
                # return of the sole can recover spatial anchor identity.
                # This does not infer whether the obscured foot lifted or
                # pivoted in between, and observed flight contradicts it.
                if ('airborne' not in states[prior_end:start + 1]
                        and np.linalg.norm(center - prior_center) <= max(.005, .15 * min(size, prior_size))):
                    group = prior_contact['anchorGroupId']
                    break
            candidates.append((contact, end, center, size))
        contact['anchorGroupId'] = group
        previous = contact, end


def add_observed_foot_contacts(
    evidence: dict[str, Any], observations: dict[str, Any], source_pose: dict[str, Any],
    camera_normal: list[float] | None = None,
    depth_alignment: dict[str, Any] | None = None,
    *, source_video_path: Path | None = None,
) -> dict[str, Any]:
    import copy

    result = copy.deepcopy(evidence)
    patch_evidence = classify_foot_contacts(observations, evidence, source_pose, camera_normal, depth_alignment)
    material_evidence = None
    if source_video_path is not None and patch_evidence.get("available"):
        material_evidence = _corroborate_observed_full_sole_material(
            Path(source_video_path), observations, patch_evidence,
        )
        patch_evidence["materialStationarityEvidence"] = material_evidence
        patch_evidence["materialStationarityPolicyVersion"] = material_evidence.get("policyVersion")
        verified = {
            row.get("episodeId"): row for row in material_evidence.get("episodes", [])
            if isinstance(row, dict) and row.get("status") == "verified" and row.get("passed") is True
        }
        for contact_index, contact in enumerate(patch_evidence.get("contacts", [])):
            side = str(contact.get("jointName") or "").split("_", 1)[0]
            if (side not in {"left", "right"}
                    or contact.get("contactState") != "full_sole"
                    or contact.get("contactMotion") == "stationary"):
                continue
            first, last = contact_frame_bounds(contact, int(patch_evidence.get("sourceFrameCount") or 0))
            episode_id = f"{side}:full_sole:{contact_index}:{first}:{last}"
            corroboration = verified.get(episode_id)
            if corroboration is None:
                continue
            # Material tracks corroborate the existing full-sole proposal. They
            # do not change the frame interval or detector state labels.
            source_digest = corroboration.get("sourceVideoSha256")
            if (not isinstance(source_digest, str)
                    or source_digest != observations.get("sourceVideoSha256")
                    or corroboration.get("side") != side
                    or corroboration.get("contactState") != "full_sole"
                    or corroboration.get("startFrame") != first
                    or corroboration.get("endFrame") != last):
                continue
            anchor_prefix = f"source-material:{source_digest[:16]}:{side}:{first}:{last}"
            toe_anchor_id = f"{anchor_prefix}:foot"
            ankle_anchor_id = f"{anchor_prefix}:ankle"
            contact["contactMotion"] = "stationary"
            contact["materialStationarityEvidence"] = corroboration
            contact["anchorGroupId"] = toe_anchor_id
            contact["ankleAnchorGroupId"] = ankle_anchor_id
            contact["materialAnchorIdentity"] = {
                "sourceVideoSha256": source_digest,
                "side": side,
                "contactState": "full_sole",
                "startFrame": first,
                "endFrame": last,
                "footAnchorGroupId": toe_anchor_id,
                "ankleAnchorGroupId": ankle_anchor_id,
            }
            _stamp_material_anchor_on_observations(
                patch_evidence, side, first, last, toe_anchor_id,
            )
    result["footPatchEvidence"] = patch_evidence
    if material_evidence is not None:
        result["sourceMaterialStationarityPolicyVersion"] = material_evidence.get("policyVersion")
        result["sourceMaterialStationarityEvidence"] = material_evidence
    if patch_evidence.get("available"):
        result.setdefault("footContactCandidates", result.get("contacts", []))
        # Uncertain observations must not silently fall back to an ankle-only
        # flat-foot assumption. Non-foot support evidence is unaffected.
        result["contacts"] = [record for record in result.get("contacts", [])
                              if not str(record.get("jointName", "")).endswith(("_ankle", "_foot"))]
        # Preserve independently observed source-pose stance through patch
        # frames classified as unknown. Only explicit airborne observations
        # contradict a continuous stance; in that case retain its supported
        # spans as temporal ankle contacts around the observed release.
        source_support_contacts = []
        patch_feet = patch_evidence.get("feet") or {}
        patch_frame_count = int(patch_evidence.get("sourceFrameCount") or 0)

        # Keep independently measured ankle stationarity as an ankle-only
        # positional constraint. It must not be upgraded to a whole-foot pose:
        # heel/toe heading can still pivot, and only observed airborne frames
        # contradict a source ankle support interval.
        if patch_frame_count >= 3:
            for source_contact in evidence.get("contacts", []):
                if (not isinstance(source_contact, dict)
                        or source_contact.get("contactMotion") != "stationary"
                        or source_contact.get("supportKind") != "foot"):
                    continue
                joint_name = str(source_contact.get("jointName") or "")
                if joint_name not in {"left_ankle", "right_ankle"}:
                    continue
                side = joint_name.split("_", 1)[0]
                if result.get("feet", {}).get(side, {}).get("continuousSupport"):
                    continue
                states = (patch_feet.get(side) or {}).get("states")
                if not isinstance(states, (list, tuple)) or len(states) != patch_frame_count:
                    continue
                bounds = _source_contact_native_frame_bounds(
                    source_contact, evidence, patch_evidence, source_pose,
                )
                if bounds is None:
                    continue
                first, last = bounds
                active = [str(state).casefold() != "airborne" for state in states]
                start = None
                for index in range(first, last + 2):
                    supported = index <= last and active[index]
                    if supported and start is None:
                        start = index
                    if supported or start is None:
                        continue
                    end = index - 1
                    if end - start + 1 >= 3:
                        source_support_contacts.append({
                            "jointName": joint_name,
                            "supportKind": "foot",
                            "contactMotion": "stationary",
                            "anchorKind": "ankle",
                            "startFrame": start,
                            "endFrame": end,
                            "startRatio": start / max(1, patch_frame_count - 1),
                            "endRatio": end / max(1, patch_frame_count - 1),
                            "confidence": min(0.8, float(source_contact.get("confidence", 0.8))),
                            "source": "source_pose_stationary_ankle_excluding_observed_airborne",
                            "sourcePoseStartSample": source_contact.get("sourceStartSample"),
                            "sourcePoseEndSample": source_contact.get("sourceEndSample"),
                            "sourcePoseStartTimeSec": source_contact.get("sourceStartTimeSec"),
                            "sourcePoseEndTimeSec": source_contact.get("sourceEndTimeSec"),
                            "sourceTimeBasis": source_contact.get("sourceTimeBasis"),
                        })
                    start = None

        for side, foot in (result.get("feet") or {}).items():
            if (
                not isinstance(foot, dict)
                or not foot.get("continuousSupport")
                or not is_stationary_contact(foot)
            ):
                continue
            states = (patch_feet.get(side) or {}).get("states")
            if not isinstance(states, (list, tuple)) or not states:
                continue
            airborne = [str(state).casefold() == "airborne" for state in states]
            if not any(airborne):
                if any(str(state).casefold() != 'full_sole' for state in states):
                    foot['continuousSupport'] = False
                    foot['supportSplitByUnresolvedFootPatch'] = True
                continue

            foot["continuousSupport"] = False
            foot["supportSplitByObservedAirborne"] = True
            if any(str(state).casefold() == 'unknown' for state in states):
                foot['supportSplitByUnresolvedFootPatch'] = True
            joint_name = str(foot.get("jointName") or f"{side}_ankle")
            try:
                confidence = max(0.0, min(1.0, float(foot.get("confidence", 1.0))))
            except (TypeError, ValueError):
                confidence = 1.0
            start = None
            for index in range(len(airborne) + 1):
                supported = index < len(airborne) and str(states[index]).casefold() == 'full_sole'
                if supported and start is None:
                    start = index
                if supported or start is None:
                    continue
                end = index - 1
                if end > start and confidence > 0.0:
                    source_support_contacts.append({
                        "jointName": joint_name,
                        "supportKind": "foot",
                        "contactMotion": "stationary",
                        "startFrame": start,
                        "endFrame": end,
                        "startRatio": start / max(1, len(airborne) - 1),
                        "endRatio": end / max(1, len(airborne) - 1),
                        "confidence": confidence,
                        "source": "source_pose_continuous_support_excluding_observed_airborne",
                    })
                start = None
        result["contacts"].extend(patch_evidence["contacts"])
        result["contacts"].extend(source_support_contacts)
    return result


def _source_contact_native_frame_bounds(source_contact, support_evidence, patch_evidence, source_pose):
    """Map sparse source-pose support to native observations by exact source clock.

    Ratios encode the source-pose sample array's endpoints, not native video
    frame timestamps. They are only safe as direct indices for a clockless,
    equal-length legacy payload. Otherwise missing/mismatched time authority
    leaves the ankle interval unresolved.
    """
    source_times = (patch_evidence or {}).get("sourceTimesSec")
    try:
        native_times = np.asarray(source_times, dtype=float)
        fps = float((patch_evidence or {}).get("sourceFps"))
        start_time = float(source_contact.get("sourceStartTimeSec"))
        end_time = float(source_contact.get("sourceEndTimeSec"))
    except (TypeError, ValueError, OverflowError):
        native_times = np.asarray([], dtype=float)
        fps = float("nan")
        start_time = end_time = float("nan")
    if (source_contact.get("sourceTimeBasis") == "absolute_source_video"
            and (patch_evidence or {}).get("sourceTimeBasis") == "absolute_source_video"
            and np.isfinite(native_times).all() and native_times.size >= 3
            and np.isfinite(fps) and fps > 0.
            and np.isfinite(start_time) and np.isfinite(end_time)
            and start_time <= end_time
            and np.all(np.diff(native_times) > 0.)):
        source_digest = str((support_evidence or {}).get("sourceVideoSha256") or "").casefold()
        patch_digest = str((patch_evidence or {}).get("sourceVideoSha256") or "").casefold()
        if not source_digest or source_digest != patch_digest:
            return None
        tolerance = .5 / fps + 1e-7
        start = int(np.argmin(np.abs(native_times - start_time)))
        if abs(float(native_times[start]) - start_time) > tolerance:
            return None
        end = int(np.argmin(np.abs(native_times - end_time)))
        if abs(float(native_times[end]) - end_time) > tolerance:
            # A source-pose sample at the exact media end can represent the
            # final exposure only when the patch clock proves that boundary.
            try:
                origin = float((patch_evidence or {}).get("sourceTimeOriginSec", native_times[0]))
                duration = float((patch_evidence or {}).get("sourceVideoDurationSec"))
                count = int((patch_evidence or {}).get("sourceFrameCount"))
            except (TypeError, ValueError, OverflowError):
                return None
            video_end = origin + duration
            if (count != native_times.size
                    or not np.isfinite(video_end)
                    or abs(end_time - video_end) > 1e-6
                    or abs(float(native_times[-1]) - (video_end - 1. / fps)) > 1e-6):
                return None
            end = native_times.size - 1
        return (start, end) if 0 <= start <= end < native_times.size else None

    # Legacy index identity is accepted only when both arrays are explicitly
    # clockless and have the same row count. A sparse pose ratio is never used
    # to manufacture native frame bounds.
    pose_frames = (source_pose or {}).get("frames") or []
    if (source_times is not None or (patch_evidence or {}).get("sourceTimeBasis") is not None
            or (source_pose or {}).get("sourceTimeBasis") is not None
            or len(pose_frames) != int((patch_evidence or {}).get("sourceFrameCount") or 0)):
        return None
    try:
        start = int(source_contact["sourceStartSample"])
        end = int(source_contact["sourceEndSample"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    count = int((patch_evidence or {}).get("sourceFrameCount") or 0)
    return (start, end) if 0 <= start <= end < count else None


def _stamp_material_anchor_on_observations(patch_evidence, side, first, last, anchor_group_id):
    """Carry a verified material owner only onto same-state native samples."""
    feet = patch_evidence.get("feet") or {}
    foot = feet.get(side) or {}
    states = foot.get("states")
    times = patch_evidence.get("sourceTimesSec")
    try:
        fps = float(patch_evidence.get("sourceFps"))
        native_times = np.asarray(times, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return
    if (not isinstance(states, list) or native_times.shape != (len(states),)
            or not np.isfinite(native_times).all() or not np.isfinite(fps) or fps <= 0.):
        return
    if not (0 <= first <= last < len(states)):
        return
    tolerance = .5 / fps + 1e-7
    for field in ("rayObservations", "heelImageObservations"):
        for row in foot.get(field) or []:
            if not isinstance(row, dict) or str(row.get("state") or "").casefold() != "full_sole":
                continue
            try:
                sample_time = float(row.get("sourceTimeSec"))
            except (TypeError, ValueError, OverflowError):
                continue
            index = int(np.argmin(np.abs(native_times - sample_time)))
            if (first <= index <= last and states[index] == "full_sole"
                    and abs(float(native_times[index]) - sample_time) <= tolerance):
                existing = row.get("stationaryAnchorGroupId")
                if existing in (None, anchor_group_id):
                    row["stationaryAnchorGroupId"] = anchor_group_id


def _corroborate_observed_full_sole_material(video_path, observations, patch_evidence):
    """Measure only classifier-proposed full-sole windows against video texture."""
    from .source_support_tracking import FOOT_MATERIAL_POLICY_VERSION, observe_foot_material_episodes

    video_path = Path(video_path)
    frames = observations.get("frames") or []
    width, height = int(observations.get("imageWidth") or 0), int(observations.get("imageHeight") or 0)
    frame_count = int(patch_evidence.get("sourceFrameCount") or 0)
    if (not video_path.is_file() or not width or not height or not frames
            or frame_count != len(frames)):
        return {
            "available": False,
            "policyVersion": FOOT_MATERIAL_POLICY_VERSION,
            "source": "forward_backward_heel_toe_material_tracks",
            "episodes": [],
            "reason": "source_video_or_frame_geometry_unavailable",
        }

    episodes = []
    for contact_index, contact in enumerate(patch_evidence.get("contacts") or []):
        if (not isinstance(contact, dict)
                or not str(contact.get("jointName") or "").endswith("_foot")
                or contact.get("contactState") != "full_sole"
                or contact.get("contactMotion") == "stationary"):
            continue
        side = str(contact["jointName"]).split("_", 1)[0]
        if side not in {"left", "right"}:
            continue
        start, end = contact_frame_bounds(contact, frame_count)
        if end - start + 1 < 3:
            continue
        states = ((patch_evidence.get("feet") or {}).get(side) or {}).get("states")
        if (not isinstance(states, list) or len(states) != frame_count
                or any(str(state).casefold() != "full_sole" for state in states[start:end + 1])):
            continue
        # Reuse the classifier's established material-spread tolerance:
        # max(.005 normalized image units, 15% of the observed foot ray).
        foot_sizes = []
        for frame in frames[start:end + 1]:
            joints = frame.get("joints") or {}
            heel, toe = joints.get(f"{side}_heel"), joints.get(f"{side}_toe")
            if not isinstance(heel, dict) or not isinstance(toe, dict):
                continue
            if min(float(heel.get("confidence") or 0.), float(toe.get("confidence") or 0.)) < .8:
                continue
            try:
                heel_xy = np.asarray(heel.get("image"), dtype=float)
                toe_xy = np.asarray(toe.get("image"), dtype=float)
            except (TypeError, ValueError):
                continue
            if (heel_xy.shape == (2,) and toe_xy.shape == (2,)
                    and np.isfinite(heel_xy).all() and np.isfinite(toe_xy).all()):
                delta = toe_xy - heel_xy
                foot_sizes.append(float(np.linalg.norm(delta)))
        if not foot_sizes:
            continue
        maximum_displacement = max(.005, float(np.median(foot_sizes)) * .15) * min(width, height)
        source_times = patch_evidence.get("sourceTimesSec") or []
        if len(source_times) != frame_count:
            start_time = end_time = None
        else:
            start_time, end_time = float(source_times[start]), float(source_times[end])
        episodes.append({
            "episodeId": f"{side}:full_sole:{contact_index}:{start}:{end}",
            "side": side,
            "contactState": "full_sole",
            "startFrame": start,
            "endFrame": end,
            "startTimeSec": start_time,
            "endTimeSec": end_time,
            "maximumDisplacementPixels": maximum_displacement,
        })
    if not episodes:
        return {
            "available": False,
            "policyVersion": FOOT_MATERIAL_POLICY_VERSION,
            "source": "forward_backward_heel_toe_material_tracks",
            "sourceVideoSha256": observations.get("sourceVideoSha256"),
            "episodes": [],
            "reason": "no_proposed_full_sole_episodes",
        }
    return observe_foot_material_episodes(
        video_path, observations, patch_evidence, episodes,
        cache_dir=video_path.parent / "foot_landmarks",
    )

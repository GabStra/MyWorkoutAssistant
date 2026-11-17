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
POLICY_VERSION = 22
# Classification changes reuse the exact same expensive landmark observations.
OBSERVATION_CACHE_VERSION = 3
LANDMARKS = {"left_shoulder": 11, "right_shoulder": 12,
             "left_elbow": 13, "right_elbow": 14, "left_wrist": 15, "right_wrist": 16,
             "left_hip": 23, "right_hip": 24, "left_knee": 25, "right_knee": 26,
             "left_ankle": 27, "right_ankle": 28, "left_heel": 29, "right_heel": 30,
             "left_toe": 31, "right_toe": 32}
_RUNTIME_WARNING_EMITTED = False

_SOURCE_POSE_ANKLE_MAX_NORMALIZED_DISTANCE = 0.08
_SOURCE_POSE_ANKLE_MAX_PIXEL_FOOT_RATIO = 0.5
_SOURCE_POSE_ANKLE_MAX_PIXEL_IMAGE_RATIO = 0.003
# A frame may resolve to the nearest pose sample only inside that sample's
# actual observation cell (half of the measured sampling interval). A wider
# query would invent support across a genuinely uncovered source gap.
_SOURCE_POSE_SAMPLE_BOUNDARY_MAX_TOLERANCE_SECONDS = 0.5
_SOURCE_POSE_SAMPLE_CLOCK_MIN_SAMPLE_COUNT = 5
_SOURCE_POSE_SAMPLE_TOLERANCE_SOURCE_ACTUAL = "actual_sample_interval"
_SOURCE_POSE_SAMPLE_TOLERANCE_SOURCE_EXPLICIT = "explicit_contract"


def _source_pose_digest(source_pose: dict[str, Any]) -> str:
    from .pose_fidelity import _canonical_source_pose_sha256

    return _canonical_source_pose_sha256(source_pose)


def _source_pose_frame_times(source_pose: dict[str, Any]) -> list[float]:
    """Return the ordered finite source-pose sample clock from its own frames."""
    times = []
    for frame in source_pose.get('frames') or []:
        if not isinstance(frame, dict):
            continue
        try:
            frame_time = float(frame.get('sourceTimeSec', frame.get('timeSec')))
        except (TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(frame_time):
            times.append(frame_time)
    times.sort()
    return times


def source_pose_sample_interval_seconds(sample_times: Any):
    """Median observed spacing of an actual source-pose clock, if measurable."""
    times = []
    for value in sample_times or []:
        try:
            time_value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(time_value):
            times.append(time_value)
    times.sort()
    if len(times) < _SOURCE_POSE_SAMPLE_CLOCK_MIN_SAMPLE_COUNT:
        return None
    gaps = np.diff(np.asarray(times, dtype=float))
    positive = gaps[gaps > 1e-9]
    if not len(positive):
        return None
    return float(np.median(positive))


def source_pose_representative_sample_interval_seconds(source_pose: dict[str, Any]):
    """Median observed spacing of the payload's own frame clock."""
    return source_pose_sample_interval_seconds(
        _source_pose_frame_times(source_pose) if isinstance(source_pose, dict) else [])


def source_pose_sample_boundary_tolerance_details(source_pose: dict[str, Any]):
    """Resolve the time-match bound from the actual sample clock.

    The stored field is producer metadata. Older payloads derived it from the
    *requested* FPS (for example 0.5 / 8 Hz) even when the decoder could only
    deliver every fourth 29.97 fps frame (7.49 Hz). That nominal half-step is
    smaller than the real half-cell and turns legitimate in-cell frames into
    "unknown". Prefer the measured interval; honor an explicit contract limit;
    fall back to the stored value only when the clock cannot be measured.
    """
    if not isinstance(source_pose, dict):
        return None, None
    try:
        stored = float(source_pose.get('sourcePoseSampleBoundaryToleranceSeconds'))
    except (TypeError, ValueError, OverflowError):
        stored = None
    if stored is not None and (not np.isfinite(stored) or stored < 0.):
        stored = None
    declared_source = str(
        source_pose.get('sourcePoseSampleBoundaryToleranceSource') or ''
    ).casefold()
    if declared_source == _SOURCE_POSE_SAMPLE_TOLERANCE_SOURCE_EXPLICIT and stored is not None:
        return stored, _SOURCE_POSE_SAMPLE_TOLERANCE_SOURCE_EXPLICIT
    interval = source_pose_representative_sample_interval_seconds(source_pose)
    if interval is not None:
        return (
            min(_SOURCE_POSE_SAMPLE_BOUNDARY_MAX_TOLERANCE_SECONDS, interval * .5),
            _SOURCE_POSE_SAMPLE_TOLERANCE_SOURCE_ACTUAL,
        )
    return stored, ("stored" if stored is not None else None)


def source_pose_sample_boundary_tolerance_seconds(source_pose: dict[str, Any]):
    return source_pose_sample_boundary_tolerance_details(source_pose)[0]


def _source_pose_frame_at_time(source_pose: dict[str, Any], source_time: float):
    frames = source_pose.get('frames') or []
    timed = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        try:
            frame_time = float(frame.get('sourceTimeSec', frame.get('timeSec')))
        except (TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(frame_time):
            timed.append((frame_time, index, frame))
    if not timed:
        return None
    timed.sort(key=lambda row: (row[0], row[1]))
    nearest = min(timed, key=lambda row: (abs(row[0] - source_time), row[1]))
    tolerance = source_pose_sample_boundary_tolerance_seconds(source_pose)
    if tolerance is None:
        if len(timed) < 2:
            return None
        times = np.asarray([row[0] for row in timed], dtype=float)
        gaps = np.diff(times)
        positive = gaps[gaps > 1e-9]
        if not len(positive):
            return None
        tolerance = float(np.median(positive) * .5)
    if abs(nearest[0] - source_time) > tolerance + 1e-7:
        return None
    return {'frameIndex': nearest[1], 'sourceTimeSec': nearest[0], 'frame': nearest[2]}


def _source_pose_ankle_association(ankle_image, toe_image, reference_ankle, image_axes):
    if reference_ankle is None or len(reference_ankle) < 2:
        return None
    ankle = np.asarray(ankle_image, dtype=float)
    toe = np.asarray(toe_image, dtype=float)
    reference = np.asarray(reference_ankle[:2], dtype=float)
    if (ankle.shape != (2,) or toe.shape != (2,) or reference.shape != (2,)
            or not np.isfinite(ankle).all() or not np.isfinite(toe).all()
            or not np.isfinite(reference).all()):
        return None
    pixel_distance = float(np.linalg.norm((ankle - reference) * image_axes))
    normalized_distance = float(np.linalg.norm(ankle - reference))
    ray_pixel_length = float(np.linalg.norm((toe - ankle) * image_axes))
    max_pixel_distance = max(
        _SOURCE_POSE_ANKLE_MAX_PIXEL_IMAGE_RATIO * float(np.min(image_axes)),
        _SOURCE_POSE_ANKLE_MAX_PIXEL_FOOT_RATIO * ray_pixel_length,
    )
    return {
        'normalizedDistance': normalized_distance,
        'pixelDistance': pixel_distance,
        'maximumPixelDistance': max_pixel_distance,
        'passed': (normalized_distance <= _SOURCE_POSE_ANKLE_MAX_NORMALIZED_DISTANCE
                   and pixel_distance <= max_pixel_distance),
    }


def foot_patch_pose_binding_failure(patch, source_pose):
    """Validate MediaPipe foot rays against the exact source-pose payload they used."""
    if not isinstance(patch, dict) or patch.get('available') is not True:
        return None
    if patch.get('source') != 'mediapipe_full_heel_forefoot':
        return None
    if patch.get('policyVersion') != POLICY_VERSION:
        return 'foot_patch_pose_binding_policy_mismatch'
    if not isinstance(source_pose, dict) or not isinstance(source_pose.get('frames'), list):
        return 'foot_patch_source_pose_missing'
    try:
        pose_digest = _source_pose_digest(source_pose)
    except (TypeError, ValueError, OverflowError):
        return 'foot_patch_source_pose_digest_invalid'
    if patch.get('sourcePosePayloadSha256') != pose_digest:
        return 'foot_patch_source_pose_digest_mismatch'
    pose_frames = source_pose.get('frames') or []
    if patch.get('sourcePoseFrameCount') != len(pose_frames):
        return 'foot_patch_source_pose_frame_count_mismatch'
    expected_tolerance = source_pose_sample_boundary_tolerance_seconds(source_pose)
    patch_tolerance = patch.get('sourcePoseSampleBoundaryToleranceSeconds')
    try:
        patch_tolerance = float(patch_tolerance)
    except (TypeError, ValueError, OverflowError):
        return 'foot_patch_source_pose_sampling_tolerance_mismatch'
    if (expected_tolerance is None
            or not np.isfinite(patch_tolerance)
            or abs(patch_tolerance - expected_tolerance) > 1e-9):
        return 'foot_patch_source_pose_sampling_tolerance_mismatch'
    patch_video = str(patch.get('sourceVideoSha256') or '').casefold()
    pose_video = str(patch.get('sourcePoseVideoSha256') or '').casefold()
    embedded_pose_video = str(source_pose.get('sourceVideoSha256') or '').casefold()
    if not patch_video or pose_video != patch_video or (embedded_pose_video and embedded_pose_video != patch_video):
        return 'foot_patch_source_video_binding_mismatch'
    if patch.get('sourceTimeBasis') != 'absolute_source_video':
        return 'foot_patch_source_clock_basis_missing'
    try:
        patch_origin = float(patch.get('sourceTimeOriginSec'))
        pose_origin = float(source_pose.get('sourceTimeOriginSec', 0.))
        source_times = np.asarray(patch.get('sourceTimesSec'), dtype=float)
    except (TypeError, ValueError, OverflowError):
        return 'foot_patch_source_clock_invalid'
    if (not np.isfinite(patch_origin) or not np.isfinite(pose_origin)
            or abs(patch_origin - pose_origin) > 1e-7
            or source_times.shape != (int(patch.get('sourceFrameCount') or -1),)
            or not np.isfinite(source_times).all()
            or (len(source_times) > 1 and np.any(np.diff(source_times) <= 0.))):
        return 'foot_patch_source_clock_mismatch'
    try:
        image_width = float(patch.get('imageWidth'))
        image_height = float(patch.get('imageHeight'))
    except (TypeError, ValueError, OverflowError):
        return 'foot_patch_image_dimensions_missing'
    axes = np.asarray([image_width, image_height], dtype=float)
    if not np.isfinite(axes).all() or np.any(axes <= 0.):
        return 'foot_patch_image_dimensions_invalid'
    try:
        pose_axes = np.asarray([source_pose.get('imageWidth'), source_pose.get('imageHeight')], dtype=float)
    except (TypeError, ValueError, OverflowError):
        pose_axes = np.asarray([], dtype=float)
    if (pose_axes.shape == (2,) and np.isfinite(pose_axes).all()
            and not np.allclose(axes, pose_axes, atol=1e-7, rtol=0.)):
        return 'foot_patch_image_dimensions_mismatch'
    for side in ('left', 'right'):
        foot = (patch.get('feet') or {}).get(side) or {}
        states = foot.get('states') or []
        rays = foot.get('rayObservations') or []
        rays_by_time = {}
        for row in rays:
            if not isinstance(row, dict):
                return 'foot_patch_ray_binding_malformed'
            try:
                sample_time = float(row.get('sourceTimeSec'))
                observation_index = int(row.get('sourceFrameIndex'))
                frame_index = int(row.get('referenceFrameIndex'))
                ref_time = float(row.get('referenceFrameSourceTimeSec'))
                ankle_image = row.get('sourceAnkleImagePoint')
                toe_image = row.get('sourceToeImagePoint')
                reference_receipt = np.asarray(row.get('referenceAnkleImagePoint'), dtype=float)
                stored_distance = float(row.get('ankleAssociationDistanceNormalized'))
                stored_pixel_distance = float(row.get('ankleAssociationDistancePixels'))
            except (TypeError, ValueError, OverflowError):
                return 'foot_patch_ray_binding_missing'
            if (observation_index < 0 or observation_index >= len(source_times)
                    or abs(float(source_times[observation_index]) - sample_time) > 1e-7):
                return 'foot_patch_ray_observation_clock_mismatch'
            frame_match = _source_pose_frame_at_time(source_pose, sample_time)
            if frame_match is None:
                return 'foot_patch_ray_source_time_unmatched'
            if (frame_match['frameIndex'] != frame_index
                    or abs(frame_match['sourceTimeSec'] - ref_time) > 1e-7):
                return 'foot_patch_ray_source_frame_mismatch'
            reference = (frame_match['frame'].get('joints') or {}).get(f'{side}_ankle')
            try:
                reference = np.asarray(reference, dtype=float)
            except (TypeError, ValueError, OverflowError):
                return 'foot_patch_ray_source_ankle_missing'
            if (reference_receipt.shape != (2,) or not np.isfinite(reference_receipt).all()
                    or not np.allclose(reference_receipt, reference[:2], atol=1e-7, rtol=0.)):
                return 'foot_patch_ray_source_ankle_receipt_mismatch'
            measured = _source_pose_ankle_association(ankle_image, toe_image, reference, axes)
            if measured is None:
                return 'foot_patch_ray_source_ankle_missing'
            if (abs(measured['normalizedDistance'] - stored_distance) > 1e-6
                    or abs(measured['pixelDistance'] - stored_pixel_distance) > 1e-4):
                return 'foot_patch_ray_source_ankle_receipt_mismatch'
            if not measured['passed']:
                return 'foot_patch_ray_source_ankle_disagreement'
            if sample_time in rays_by_time:
                return 'foot_patch_ray_duplicate_source_time'
            rays_by_time[sample_time] = row
        for index, state in enumerate(states):
            if str(state).casefold() != 'full_sole':
                continue
            if index >= len(source_times):
                return 'foot_patch_full_sole_clock_missing'
            if not any(abs(sample_time - float(source_times[index])) <= 1e-7 for sample_time in rays_by_time):
                return 'foot_patch_full_sole_without_pose_bound_ray'
    return None


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
    tolerances, uncalibrated_toe, uncalibrated_surface_kind, support_contacts,
):
    def run_has_stationary_ankle_support(run_start, run_end):
        """Whether an independently observed stationary ankle spans this run.

        The source-pose support observation owns ankle stationarity only. Its
        contact covers whole source-sampling cells, so a correct source clock
        joins adjacent cells into one stance. That still cannot establish a
        fixed toe material point: an ankle may stay in place while the toe
        rotates or slides. The local toe spread remains the sole authority for
        a horizontal toe anchor; ankle support can only retain contact presence
        as the existing height-only representation.
        """
        for candidate in support_contacts or ():
            if not isinstance(candidate, dict) or not is_stationary_contact(candidate):
                continue
            if candidate.get('jointName') != f'{side}_ankle':
                continue
            first, last = contact_frame_bounds(candidate, count)
            if first <= run_start and run_end - 1 <= last:
                return True
        return False

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
            ankle_height_support = False
            if state == 'toe_only' and np.any(image_only_toe[start:end]) and not stationary:
                states[start:end] = ['unknown'] * (end - start)
                start = end
                continue
            # An uncalibrated forefoot needs the same robust stationarity test
            # used above: per-frame peak-to-peak extrema include landmark
            # jitter and can accumulate across a long episode even when the
            # visible toe never leaves the ground. Reject only when the
            # chunk-median anchor actually moves.
            if uncalibrated_toe and not stationary:
                # A stationary ankle proves support presence, not a stationary
                # toe. Keep the observed contact as height-only and leave the
                # horizontal motion unresolved instead of fabricating a toe
                # anchor from ankle evidence.
                ankle_height_support = (state == 'toe_only'
                                        and run_has_stationary_ankle_support(start, end))
                if not ankle_height_support:
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
                "contactState": state,
                "contactMotion": "stationary" if (stationary or ankle_height_support) else "unknown",
                "verticalOnly": state == "heel_only" or ankle_height_support,
                "startRatio": start / max(1, count - 1),
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
            if uncalibrated_toe and uncalibrated_surface_kind is not None:
                contact['surfaceKind'] = uncalibrated_surface_kind
                contact['source'] = (
                    'exact_visual_contact_and_independent_stationary_toe' if stationary
                    else 'exact_visual_contact_and_independent_stationary_ankle_height_only'
                )
            if ankle_height_support:
                # The current non-calibrated forefoot observation cannot resolve
                # its world height. The height-only consumer must not invent it.
                contact['worldHeightResolved'] = False
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
    neutral_forefoot_only=None,
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
        row = {
            'sourceTimeSec': source_origin + float(frame['timeSeconds']),
            'sourceFrameIndex': int(index),
            'sourceFeature': 'anatomical_heel_to_toe',
            'heelImagePoint': [float(heel['image'][0] * image_width / image_height),
                               float(heel['image'][1])],
            'toeImagePoint': [float(toe['image'][0] * image_width / image_height),
                              float(toe['image'][1])],
            'heelConfidence': float(heel['confidence']),
            'toeConfidence': float(toe['confidence']),
            'state': states[index],
            'stationaryAnchorGroupId': (stationary_groups_by_frame or {}).get(index),
        }
        if (states[index] == 'toe_only' and neutral_forefoot_only is not None
                and bool(neutral_forefoot_only[index])):
            row['heelStateEvidence'] = {
                'state': 'unknown',
                'reason': 'neutral_pitch_with_reviewed_forefoot_contact',
                'sourceFrameIndex': int(index),
                'sourceTimeSec': row['sourceTimeSec'],
            }
        rows.append(row)
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


def _reviewed_sole_mode_masks(evidence, observations, side, source_pose=None, *, conflicts=None):
    """Use exact-video visual sole facts, never reconstructed support candidates."""
    from .body_support_observation import _CONTACT_TIMELINE_FOOT_BATCH_SIZE
    frames = observations.get('frames') or []
    neutral = np.zeros(len(frames), dtype=bool)
    contact = np.zeros(len(frames), dtype=bool)
    forefoot_only = np.zeros(len(frames), dtype=bool)
    heel_only = np.zeros(len(frames), dtype=bool)
    stationary = np.zeros(len(frames), dtype=bool)
    exact_fullsole = np.zeros(len(frames), dtype=bool)
    # Which sole mode each frame-specific atlas row asserted. Kept separately
    # from the coarse chunk decisions and from the exact_fullsole bit so a
    # contradictory exact body row can contest (rather than silently inherit)
    # the atlas classification.
    atlas_sole_modes = {}
    digest = observations.get('sourceVideoSha256')
    if not isinstance(digest, str) or not digest or evidence.get('sourceVideoSha256') != digest:
        return neutral, contact, forefoot_only, heel_only, stationary, exact_fullsole
    review = evidence.get('stationarySoleIntervalReview') or {}
    finding = (review.get('feet') or {}).get(side) or {}
    decisions = finding.get('decisions')
    frames_per_chunk = review.get('framesPerChunk')
    allowed = {'stationary_full_sole_ground', 'stationary_forefoot_ground',
               'moving_or_releasing', 'insufficient_evidence'}
    if (review.get('sourceVideoSha256') == digest
            and review.get('sourceFrameCount') == len(frames)
            and finding.get('reviewedFrameCount') == len(frames)
            and type(frames_per_chunk) is int and frames_per_chunk == _CONTACT_TIMELINE_FOOT_BATCH_SIZE
            and isinstance(decisions, list)
            and len(decisions) == (len(frames) + frames_per_chunk - 1) // frames_per_chunk
            and all(decision in allowed for decision in decisions)):
        for chunk, decision in enumerate(decisions):
            rows = slice(chunk * frames_per_chunk, min((chunk + 1) * frames_per_chunk, len(frames)))
            neutral[rows] = decision == 'stationary_full_sole_ground'
            contact[rows] = decision in {'stationary_full_sole_ground', 'stationary_forefoot_ground'}
            forefoot_only[rows] = decision == 'stationary_forefoot_ground'
            heel_only[rows] = False
            stationary[rows] = contact[rows]
        # Chunk decisions are coarse. A source-frame-bound observation from
        # the same review is more precise and must win over its containing
        # chunk, after validating the saved clock/video/pose mapping.
        clock_proof = review.get('sourceFrameClockProof') or {}
        pose_frames = (source_pose.get('frames') or []) if isinstance(source_pose, dict) else []
        pose_video = (source_pose.get('sourceVideoSha256')
                      if isinstance(source_pose, dict) else None)
        try:
            source_origin = float((source_pose or {}).get('sourceTimeOriginSec', 0.))
        except (TypeError, ValueError, OverflowError):
            source_origin = float('nan')
        finding_pose = finding.get('sourcePoseTrackProof') or {}
        try:
            proof_fps = float(clock_proof.get('outputFps', 0.))
            observed_fps = float(observations.get('fps', 0.))
        except (TypeError, ValueError, OverflowError):
            proof_fps = observed_fps = 0.
        clock_bound = (
            clock_proof.get('outputVideoSha256') == digest
            and clock_proof.get('outputFrameCount') == len(frames)
            and isinstance(clock_proof.get('receiptSha256'), str)
            and len(clock_proof['receiptSha256']) == 64
            and np.isfinite([proof_fps, observed_fps]).all()
            and proof_fps > 0. and abs(proof_fps - observed_fps) <= .02
            and pose_video == digest and len(pose_frames) == len(frames)
            and finding_pose.get('sourceVideoSha256') == digest
            and finding_pose.get('sourcePoseFrameCount') == len(pose_frames)
            and finding_pose.get('stationary') is True
        )
        if clock_bound:
            for row in finding.get('frameObservations') or []:
                if not isinstance(row, dict):
                    continue
                index = row.get('outputFrameIndex')
                try:
                    row_time = float(row.get('sourceTimeSec'))
                    pose_time = float(pose_frames[index].get('sourceTimeSec')) if (
                        type(index) is int and 0 <= index < len(pose_frames)) else float('nan')
                except (TypeError, ValueError, OverflowError):
                    continue
                if (type(index) is not int or not 0 <= index < len(frames)
                        or row.get('sourcePoseFrameIndex') != index
                        or row.get('sourceFrameClockSha256') != clock_proof.get('receiptSha256')
                        or not np.isfinite([row_time, pose_time]).all()
                        or not np.isfinite(source_origin)
                        or abs(row_time - pose_time) > 1e-6
                        or abs(row_time - (source_origin + float(frames[index]['timeSeconds'])))
                        > 1e-6):
                    continue
                state = row.get('contactState')
                if (state == 'full_sole_ground' and row.get('heelMotion') == 'stationary'
                        and row.get('forefootMotion') == 'stationary'):
                    neutral[index], contact[index], forefoot_only[index], heel_only[index], stationary[index] = (
                        True, True, False, False, True)
                    exact_fullsole[index] = True
                    atlas_sole_modes[index] = 'full_sole'
                elif state == 'forefoot_ground' and row.get('forefootMotion') == 'stationary':
                    neutral[index], contact[index], forefoot_only[index], heel_only[index], stationary[index] = (
                        False, True, True, False, True)
                    atlas_sole_modes[index] = 'forefoot'
    from .body_support_observation import validated_body_support_contact_timeline
    timeline = validated_body_support_contact_timeline(
        evidence.get('bodySupportObservation'), expected_video_sha256=digest)
    for row in timeline or []:
        index = row['sourceFrameIndex']
        if (row['side'] != side or index >= len(frames)
                or row['surface'] not in {'ground', 'raised_surface'}
                or row['visible'] is not True
                or abs(float(frames[index]['timeSeconds']) - row['sourceTimeSec']) > 1e-6):
            continue
        review_only = row.get('reviewOnly') is True
        atlas_mode = atlas_sole_modes.get(index)
        # A review-only row is not an independent physical claim. It may inform
        # an otherwise unresolved frame, but it must never override the exact
        # frame-specific atlas classification for the same exposure.
        if review_only and atlas_mode is not None:
            if conflicts is not None:
                conflicts.append({
                    'side': side, 'frameIndex': index,
                    'sourceTimeSec': float(row['sourceTimeSec']),
                    'atlasContactState': atlas_mode,
                    'bodyContactState': row['contactState'],
                    'bodyReviewOnly': True,
                    'reason': 'review_only_row_does_not_override_exact_sole_review',
                })
            continue
        timeline_mode = row['contactState']
        if (atlas_mode is not None and row['surface'] == 'ground'
                and timeline_mode in {'full_sole', 'forefoot', 'heel_only'}
                and timeline_mode != atlas_mode):
            # Two exact, same-clock reviews disagree about heel/sole mode.
            # Do not promote either winner. Retain their shared positive
            # forefoot support and leave the contested heel/sole mode unknown.
            exact_fullsole[index] = False
            neutral[index] = False
            contact[index] = True
            forefoot_only[index] = 'forefoot' in {atlas_mode, timeline_mode}
            heel_only[index] = False
            stationary[index] = row.get('sourceTrackStationary') is True
            if conflicts is not None:
                conflicts.append({
                    'side': side, 'frameIndex': index,
                    'sourceTimeSec': float(row['sourceTimeSec']),
                    'atlasContactState': atlas_mode,
                    'bodyContactState': timeline_mode,
                    'bodyReviewOnly': False,
                    'reason': 'conflicting_exact_sole_reviews',
                })
            continue
        # Sole articulation and support-surface geometry are separate facts.
        # An exact visible full-sole row on a raised surface can resolve a
        # neutral-pitch classifier label, but it is not a ground calibration
        # sample and must not add a ground contact or calibration mask.
        if row['contactState'] == 'full_sole':
            exact_fullsole[index] = True
        if row['surface'] != 'ground':
            continue
        neutral[index] = row['contactState'] == 'full_sole'
        contact[index] = row['contactState'] in {'full_sole', 'forefoot', 'heel_only'}
        forefoot_only[index] = row['contactState'] == 'forefoot'
        heel_only[index] = row['contactState'] == 'heel_only'
        stationary[index] = row.get('sourceTrackStationary') is True and contact[index]
    return neutral, contact, forefoot_only, heel_only, stationary, exact_fullsole


def _contiguous_frame_ranges(frame_indices):
    indices = np.unique(np.asarray(frame_indices, dtype=int))
    if not len(indices):
        return []
    split_at = np.flatnonzero(np.diff(indices) > 1) + 1
    return [
        {'startFrame': int(group[0]), 'endFrame': int(group[-1])}
        for group in np.split(indices, split_at)
    ]


def _relative_neutral_conflicts(
    *, neutral, contact, forefoot_only, heel_only, stationary, valid, image_pitch, world_pitch,
    ankle_image_pitch, ankle_world_pitch, image_heel_points, image_toe_points,
    image_ankle_points, world_heel_points, world_toe_points, world_ankle_points, image_axes,
):
    """Find stationary spans whose full-sole and raised-heel facts share one pose.

    The neutral samples define the same robust pitch tolerance used by the
    classifier. Both heel-to-toe and ankle-to-toe image/world vectors must also
    agree, including their full vector directions and lengths, so camera roll
    or a changed foot orientation cannot masquerade as a calibration conflict.
    """
    conflict = np.zeros(len(neutral), dtype=bool)
    diagnostics = []
    stationary = np.asarray(stationary, dtype=bool) & np.asarray(contact, dtype=bool)
    boundaries = np.diff(np.r_[False, stationary, False].astype(np.int8))
    spans = zip(np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1))
    angle_channels = {
        'heelToeImagePitch': np.asarray(image_pitch),
        'heelToeWorldPitch': np.asarray(world_pitch),
        'ankleToeImagePitch': np.asarray(ankle_image_pitch),
        'ankleToeWorldPitch': np.asarray(ankle_world_pitch),
    }
    axes = np.asarray(image_axes, dtype=float)
    vector_pairs = {
        'heelToeImage': (np.asarray(image_toe_points) - np.asarray(image_heel_points)) * axes[None, :],
        'ankleToeImage': (np.asarray(image_toe_points) - np.asarray(image_ankle_points)) * axes[None, :],
        'heelToeWorld': np.asarray(world_toe_points) - np.asarray(world_heel_points),
        'ankleToeWorld': np.asarray(world_toe_points) - np.asarray(world_ankle_points),
    }
    for start, end in spans:
        neutral_indices = np.flatnonzero(neutral[start:end] & valid[start:end]) + start
        # Reuse the existing minimums for calibration and independently
        # observed foot identity rather than fitting a new sample threshold.
        if len(neutral_indices) < 4:
            continue
        neutral_vectors = {name: vectors[neutral_indices] for name, vectors in vector_pairs.items()}
        neutral_lengths = {name: np.linalg.norm(vectors, axis=1)
                           for name, vectors in neutral_vectors.items()}
        neutral_directions = {
            name: vectors / np.maximum(neutral_lengths[name][:, None], 1e-12)
            for name, vectors in neutral_vectors.items()
        }
        angle_tolerances = {}
        for name, values in angle_channels.items():
            neutral_values = values[neutral_indices]
            center = float(np.median(neutral_values))
            angle_tolerances[name] = max(
                np.deg2rad(8.),
                3. * 1.4826 * float(np.median(np.abs(neutral_values - center))),
            )
        for mode, mode_mask in (('forefoot', forefoot_only),):
            positive_indices = np.flatnonzero(mode_mask[start:end] & valid[start:end]) + start
            if len(positive_indices) < 3:
                continue
            channel_results = {}
            matched = np.ones(len(neutral_indices), dtype=bool)
            for name, values in angle_channels.items():
                neutral_values = values[neutral_indices]
                positive_values = values[positive_indices]
                neutral_center = float(np.median(neutral_values))
                positive_center = float(np.median(positive_values))
                tolerance = angle_tolerances[name]
                positive_noise = 3. * 1.4826 * float(
                    np.median(np.abs(positive_values - positive_center)))
                stable = positive_noise <= tolerance
                matched &= np.abs(neutral_values - positive_center) <= tolerance
                channel_results[name] = {
                    'neutralMedianRadians': neutral_center,
                    'positiveMedianRadians': positive_center,
                    'medianDifferenceRadians': positive_center - neutral_center,
                    'toleranceRadians': float(tolerance),
                    'positiveRobustSpreadRadians': float(positive_noise),
                    'positiveClusterStable': bool(stable),
                }
            for name, vectors in vector_pairs.items():
                positive_vectors = vectors[positive_indices]
                positive_lengths = np.linalg.norm(positive_vectors, axis=1)
                positive_directions = positive_vectors / np.maximum(positive_lengths[:, None], 1e-12)
                positive_length = float(np.median(positive_lengths))
                positive_direction = np.median(positive_directions, axis=0)
                positive_direction /= max(float(np.linalg.norm(positive_direction)), 1e-12)
                neutral_length_values = neutral_lengths[name]
                length_tolerance = 3. * 1.4826 * float(
                    np.median(np.abs(neutral_length_values - np.median(neutral_length_values))))
                angle_name = ('heelToeImagePitch' if name == 'heelToeImage' else
                              'ankleToeImagePitch' if name == 'ankleToeImage' else
                              'heelToeWorldPitch' if name == 'heelToeWorld' else
                              'ankleToeWorldPitch')
                angle_tolerance = angle_tolerances[angle_name]
                neutral_direction_angles = np.arccos(np.clip(
                    neutral_directions[name] @ positive_direction, -1., 1.))
                positive_direction_angles = np.arccos(np.clip(
                    positive_directions @ positive_direction, -1., 1.))
                positive_direction_spread = 3. * 1.4826 * float(
                    np.median(np.abs(positive_direction_angles - np.median(positive_direction_angles))))
                direction_stable = positive_direction_spread <= angle_tolerance
                positive_length_spread = 3. * 1.4826 * float(
                    np.median(np.abs(positive_lengths - positive_length)))
                length_stable = positive_length_spread <= max(length_tolerance, 1e-12)
                matched &= (np.abs(neutral_length_values - positive_length)
                            <= max(length_tolerance, 1e-12))
                matched &= neutral_direction_angles <= angle_tolerance
                channel_results[name] = {
                    'neutralMedianLength': float(np.median(neutral_length_values)),
                    'positiveMedianLength': positive_length,
                    'lengthNoiseTolerance': float(length_tolerance),
                    'positiveLengthRobustSpread': float(positive_length_spread),
                    'maximumNeutralDirectionDifferenceRadians': float(np.max(neutral_direction_angles)),
                    'positiveDirectionRobustSpreadRadians': float(positive_direction_spread),
                    'directionToleranceRadians': float(angle_tolerance),
                    'positiveClusterStable': bool(direction_stable and length_stable),
                }
            conflicted_indices = neutral_indices[matched]
            if not len(conflicted_indices):
                continue
            conflict[conflicted_indices] = True
            diagnostics.append({
                'stationarySpanStartFrame': int(start), 'stationarySpanEndFrame': int(end - 1),
                'conflictingNeutralFrameRanges': _contiguous_frame_ranges(conflicted_indices),
                'neutralSampleCount': int(len(neutral_indices)),
                'positiveRaisedHeelSampleCount': int(len(positive_indices)),
                'positiveMode': mode,
                'indistinguishable': True,
                'reason': 'stationary_full_sole_and_forefoot_geometry_indistinguishable',
                'geometry': channel_results,
            })
    return conflict, diagnostics


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
    try:
        source_pose_digest = _source_pose_digest(source_pose)
    except (TypeError, ValueError, OverflowError):
        return {"available": False, "reason": "source_pose_binding_digest_unavailable"}
    observed_video_sha = str(observations.get('sourceVideoSha256') or '').casefold()
    evidence_video_sha = str(evidence.get('sourceVideoSha256') or '').casefold()
    if not observed_video_sha or (evidence_video_sha and evidence_video_sha != observed_video_sha):
        return {"available": False, "reason": "source_pose_binding_video_mismatch"}
    contacts = evidence.get("footContactCandidates", evidence.get("contacts", []))
    source_origin = float(source_pose.get("sourceTimeOriginSec", 0.))
    sample_tolerance, sample_tolerance_source = (
        source_pose_sample_boundary_tolerance_details(source_pose))
    result: dict[str, Any] = {"available": True, "policyVersion": POLICY_VERSION,
                            "source": observations["source"], "sourceFrameCount": count,
                            "sourceFps": observations.get("fps"),
                            **_patch_source_timing_metadata(
                                frames, source_origin, observations.get("fps")),
                            "sourceVideoSha256": observations.get("sourceVideoSha256"),
                             "sourcePoseVideoSha256": (evidence_video_sha or observed_video_sha),
                             "sourcePosePayloadSha256": source_pose_digest,
                             "sourcePoseFrameCount": len(source_frames),
                              "sourcePoseSampleBoundaryToleranceSeconds": sample_tolerance,
                              "sourcePoseSampleBoundaryToleranceSource": sample_tolerance_source,
                             "imageWidth": int(image_width), "imageHeight": int(image_height),
                            "feet": {}, "contacts": [], "neutralCalibrationConflicts": [],
                            "neutralCalibrationComparisons": []}
    for side in ("left", "right"):
        valid = np.zeros(count, dtype=bool)
        toe_valid = np.zeros(count, dtype=bool)
        ray_observations = []
        image_pitch = np.zeros(count)
        world_pitch = np.zeros(count)
        toe_points = np.zeros((count, 2))
        heel_points = np.zeros((count, 2))
        ankle_points = np.zeros((count, 2))
        world_toe_points = np.zeros((count, 3))
        world_heel_points = np.zeros((count, 3))
        world_ankle_points = np.zeros((count, 3))
        ankle_image_pitch = np.zeros(count)
        ankle_world_pitch = np.zeros(count)
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
            reference_match = _source_pose_frame_at_time(source_pose, source_time)
            if reference_match is None:
                continue
            reference = reference_match['frame']
            reference_ankle = reference.get("joints", {}).get(f"{side}_ankle")
            association = _source_pose_ankle_association(
                ankle['image'], toe['image'], reference_ankle, image_axes)
            if association is None or not association['passed']:
                continue
            ray_delta = np.asarray(toe["image"]) - ankle["image"]
            ray_pixel_delta = ray_delta * image_axes
            ray_pixel_length = np.linalg.norm(ray_pixel_delta)
            ankle_disagreement = association['pixelDistance']
            if ray_pixel_length < 0.005 * min(image_axes):
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
                "sourceFrameIndex": int(index),
                "referenceFrameIndex": int(reference_match['frameIndex']),
                "referenceFrameSourceTimeSec": float(reference_match['sourceTimeSec']),
                "sourceAnkleImagePoint": [float(ankle['image'][0]), float(ankle['image'][1])],
                "sourceToeImagePoint": [float(toe['image'][0]), float(toe['image'][1])],
                "referenceAnkleImagePoint": [float(reference_ankle[0]), float(reference_ankle[1])],
                "ankleAssociationDistanceNormalized": association['normalizedDistance'],
                "ankleAssociationDistancePixels": association['pixelDistance'],
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
            ankle_image_delta = (np.asarray(toe['image']) - np.asarray(ankle['image'])) * image_axes
            ankle_image_length = float(np.linalg.norm(ankle_image_delta))
            ankle_world_delta = np.asarray(toe['world']) - np.asarray(ankle['world'])
            ankle_world_length = float(np.linalg.norm(ankle_world_delta))
            if ankle_image_length > 1e-9:
                ankle_image_pitch[index] = np.arcsin(np.clip(-ankle_image_delta[1] / ankle_image_length, -1, 1))
            if ankle_world_length > 1e-9:
                ankle_world_pitch[index] = np.arcsin(np.clip(np.dot(ankle_world_delta, normal) / ankle_world_length, -1, 1))
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
            toe_points[index], heel_points[index], ankle_points[index] = toe["image"], heel["image"], ankle["image"]
            world_toe_points[index], world_heel_points[index], world_ankle_points[index] = (
                toe['world'], heel['world'], ankle['world'])
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
        sole_mode_conflicts = []
        (reviewed_neutral, reviewed_contact, reviewed_forefoot,
         reviewed_heel_only, stationary_review, exact_fullsole_review) = _reviewed_sole_mode_masks(
            evidence, observations, side, source_pose, conflicts=sole_mode_conflicts)
        if sole_mode_conflicts:
            result.setdefault('soleModeReviewConflicts', []).extend(sole_mode_conflicts)
        conflict_mask = np.zeros(count, dtype=bool)
        if not ground_referenced:
            conflict_mask, conflict_diagnostics = _relative_neutral_conflicts(
                neutral=reviewed_neutral, contact=reviewed_contact,
                forefoot_only=reviewed_forefoot, heel_only=reviewed_heel_only,
                stationary=stationary_review, valid=valid,
                image_pitch=image_pitch, world_pitch=world_pitch,
                ankle_image_pitch=ankle_image_pitch, ankle_world_pitch=ankle_world_pitch,
                image_heel_points=heel_points, image_toe_points=toe_points,
                image_ankle_points=ankle_points, world_heel_points=world_heel_points,
                world_toe_points=world_toe_points, world_ankle_points=world_ankle_points,
                image_axes=image_axes,
            )
            if conflict_diagnostics:
                result['neutralCalibrationComparisons'].extend(
                    {'side': side, **row} for row in conflict_diagnostics)
            if np.any(conflict_mask):
                reviewed_neutral[conflict_mask] = False
                result['neutralCalibrationConflicts'].extend(
                    {'side': side, **row} for row in conflict_diagnostics
                    if row.get('indistinguishable') is True)
        # A nonvertical support candidate does not observe the heel or neutral
        # sole. Relative marker calibration needs independent visual flatness.
        calibration = (calibration if ground_referenced else reviewed_neutral) & valid
        possible_contact |= reviewed_contact
        forefoot_contact |= reviewed_forefoot & ~reviewed_neutral
        states = ["unknown"] * count
        image_only_toe = np.zeros(count, dtype=bool)
        unresolved_heel_recontact = np.zeros(count, dtype=bool)
        neutral_pitch_forefoot_only = np.zeros(count, dtype=bool)
        uncalibrated_toe = np.count_nonzero(calibration) < 4
        observed = evidence.get('bodySupportObservation') or {}
        from .body_support_observation import validated_body_support_answer
        answer = validated_body_support_answer(observed)
        uncalibrated_surface_kind = (
            'ground' if bool(np.any(reviewed_forefoot | reviewed_heel_only)) or (
                answer is not None and answer.get(f'{side}FootSurface') == 'ground'
            ) else 'observed_raised_support_surface' if (
                answer is not None and answer.get(f'{side}FootSurface') == 'raised_surface'
            ) else None
        )
        toe_contact_observed = (
            answer is not None
            and isinstance(observations.get('sourceVideoSha256'), str)
            and observed.get('sourceVideoSha256') == observations['sourceVideoSha256']
            and answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
            and answer.get(f'{side}FootSurface') in {'ground', 'raised_surface'}) or bool(np.any(reviewed_contact))
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
                # Contact still confirms the forefoot anchor, but without a
                # trustworthy neutral reference it cannot establish sole-flat
                # or heel-lift state.
                if possible_contact[index]:
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
                if reviewed_neutral[index]:
                    states[index] = 'full_sole'
                elif not ground_referenced:
                    states[index] = 'toe_only' if toe_contact_observed or reviewed_forefoot[index] else 'unknown'
                    neutral_pitch_forefoot_only[index] = bool(reviewed_forefoot[index])
                else:
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
            # A frame-specific, clock-bound visual sole review is stronger
            # than a coarse chunk decision or a geometry-only neutral estimate.
            if exact_fullsole_review[index]:
                states[index] = 'full_sole'
                neutral_pitch_forefoot_only[index] = False
        # Do not bridge unknown observations or erase a real release. Isolated
        # detections lack enough temporal evidence to impose a new constraint.
        patch_contacts = _materialize_foot_patch_contacts(
            side=side, states=states, valid=valid, toe_valid=toe_valid, heel_points=heel_points,
            toe_points=toe_points, foot_sizes=foot_sizes, image_pitch=image_pitch,
            world_pitch=world_pitch, image_only_toe=image_only_toe,
            unresolved_heel_recontact=unresolved_heel_recontact,
            references=references, tolerances=tolerances, uncalibrated_toe=uncalibrated_toe,
            uncalibrated_surface_kind=uncalibrated_surface_kind,
            support_contacts=contacts,
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
        # Exact-video heel contact supersedes a proxy-based recontact guess;
        # preserve only those reviewed instants, never the intervening gap.
        for index in np.flatnonzero(reviewed_neutral & valid):
            states[index] = 'full_sole'
            unresolved_heel_recontact[index] = False
        patch_contacts = _materialize_foot_patch_contacts(
            side=side, states=states, valid=valid, toe_valid=toe_valid, heel_points=heel_points,
            toe_points=toe_points, foot_sizes=foot_sizes, image_pitch=image_pitch,
            world_pitch=world_pitch, image_only_toe=image_only_toe,
            unresolved_heel_recontact=unresolved_heel_recontact,
            references=references, tolerances=tolerances, uncalibrated_toe=uncalibrated_toe,
            uncalibrated_surface_kind=uncalibrated_surface_kind,
            support_contacts=contacts,
        )
        result["contacts"].extend(patch_contacts)
        stationary_groups_by_frame = {}
        for contact_index, contact in enumerate(result["contacts"]):
            if (contact.get('jointName') != f'{side}_foot'
                    or contact.get('contactMotion') != 'stationary'
                    or contact.get('verticalOnly') is True
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
            neutral_forefoot_only=neutral_pitch_forefoot_only,
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
    only the observed episodes share an anchor. Height-only contacts have no
    horizontal material anchor even when their support is stationary. A missing
    toe observation can
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
        if (contact.get('contactMotion') != 'stationary'
                or contact.get('verticalOnly') is True
                or contact.get('contactState') not in {'full_sole', 'toe_only'}):
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
        from .source_support_tracking import material_episode_scene_registered

        material_evidence = _corroborate_observed_full_sole_material(
            Path(source_video_path), observations, patch_evidence,
        )
        patch_evidence["materialStationarityEvidence"] = material_evidence
        patch_evidence["materialStationarityPolicyVersion"] = material_evidence.get("policyVersion")
        verified = {
            row.get("episodeId"): row for row in material_evidence.get("episodes", [])
            if (isinstance(row, dict) and row.get("status") == "verified"
                and row.get("passed") is True and material_episode_scene_registered(row))
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
                delta = (toe_xy - heel_xy) * [width, height]
                foot_sizes.append(float(np.linalg.norm(delta)))
        if not foot_sizes:
            continue
        maximum_displacement = max(.005 * min(width, height), float(np.median(foot_sizes)) * .15)
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

"""Observe heel/forefoot contact from the exact source, independently of WHAM."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.request import urlopen

import numpy as np
from .contact_constraints import contact_frame_bounds

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"
POLICY_VERSION = 1
LANDMARKS = {"left_hip": 23, "right_hip": 24, "left_knee": 25, "right_knee": 26,
             "left_ankle": 27, "right_ankle": 28, "left_heel": 29, "right_heel": 30,
             "left_toe": 31, "right_toe": 32}
_RUNTIME_WARNING_EMITTED = False


def _model_path() -> Path:
    configured = os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL")
    path = Path(configured) if configured else Path.home() / ".cache/myworkoutassistant/pose_models/pose_landmarker_full.task"
    if path.is_file():
        return path
    if configured:
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


def observe_foot_landmarks(video_path: Path, *, cache_dir: Path | None = None) -> dict[str, Any]:
    """Local tracked inference; cache identity includes exact video bytes."""
    with video_path.open("rb") as stream:
        hasher = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            hasher.update(block)
        digest = hasher.hexdigest()
    cache_dir = cache_dir or video_path.parent / "foot_landmarks"
    configured_model = os.environ.get("EXERCISE_MOTION_FOOT_LANDMARK_MODEL")
    model_key = ""
    if configured_model:
        model_file = Path(configured_model)
        model_key = "." + hashlib.sha256(model_file.read_bytes()).hexdigest()[:16]
    cache = cache_dir / f"{digest}{model_key}.v{POLICY_VERSION}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
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
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(_model_path())),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    capture = cv2.VideoCapture(str(video_path))
    frames = []
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not capture.isOpened() or fps <= 0:
            raise ValueError(f"Cannot decode foot landmark source: {video_path}")
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
    payload = {"available": True, "policyVersion": POLICY_VERSION, "sourceVideoSha256": digest,
               "source": "mediapipe_full_heel_forefoot", "fps": fps, "frames": frames}
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_dir, delete=False) as stream:
        json.dump(payload, stream)
        temporary = Path(stream.name)
    temporary.replace(cache)
    return payload


def classify_foot_contacts(
    observations: dict[str, Any], evidence: dict[str, Any],
    source_pose: dict[str, Any], camera_normal: list[float] | None = None,
    depth_alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve partial contacts from observed heel-to-toe geometry.

    A stationary ankle is only a calibration candidate, never a flat-foot
    command. Agreement of image and 3D heel lift is required; occlusion,
    identity mismatch, missing calibration and disagreement remain unknown.
    """
    if not observations.get("available"):
        return {"available": False, "reason": observations.get("reason")}
    frames = observations.get("frames", [])
    source_frames = source_pose.get("frames", [])
    if not frames or not source_frames:
        return {"available": False, "reason": "missing_reference_frames"}
    count = len(frames)
    normal = np.asarray(camera_normal if camera_normal is not None else [0, -1, 0], dtype=float)
    normal /= max(np.linalg.norm(normal), 1e-8)
    contacts = evidence.get("footContactCandidates", evidence.get("contacts", []))
    result: dict[str, Any] = {"available": True, "policyVersion": POLICY_VERSION,
                            "source": observations["source"], "feet": {}, "contacts": []}
    for side in ("left", "right"):
        valid = np.zeros(count, dtype=bool)
        image_pitch = np.zeros(count)
        world_pitch = np.zeros(count)
        toe_points = np.zeros((count, 2))
        heel_points = np.zeros((count, 2))
        foot_sizes = np.zeros(count)
        for index, frame in enumerate(frames):
            points = frame["joints"]
            named = [points.get(f"{side}_{part}") for part in ("ankle", "heel", "toe")]
            if any(not point or point["confidence"] < 0.8 for point in named):
                continue
            ankle, heel, toe = named
            reference = min(source_frames, key=lambda f: abs(float(f.get("sourceTimeSec", f.get("timeSec", 0))) - frame["timeSeconds"]))
            reference_ankle = reference.get("joints", {}).get(f"{side}_ankle")
            if reference_ankle is None or np.linalg.norm(np.asarray(ankle["image"]) - reference_ankle[:2]) > 0.08:
                continue
            image_delta = np.asarray(toe["image"]) - heel["image"]
            world_delta = np.asarray(toe["world"]) - heel["world"]
            image_length, world_length = np.linalg.norm(image_delta), np.linalg.norm(world_delta)
            if image_length < 0.005 or world_length < 0.02:
                continue
            image_pitch[index] = np.arcsin(np.clip(-image_delta[1] / image_length, -1, 1))
            world_pitch[index] = np.arcsin(np.clip(np.dot(world_delta, normal) / world_length, -1, 1))
            toe_points[index], heel_points[index] = toe["image"], heel["image"]
            foot_sizes[index] = image_length
            valid[index] = True
        possible_contact = np.zeros(count, dtype=bool)
        calibration = np.zeros(count, dtype=bool)
        for record in contacts:
            if str(record.get("jointName", "")) not in {f"{side}_ankle", f"{side}_foot"}:
                continue
            start, end = contact_frame_bounds(record, count)
            possible_contact[start:end + 1] = True
            if not record.get("verticalOnly"):
                calibration[start:end + 1] = True
        calibration &= valid
        states = ["unknown"] * count
        if np.count_nonzero(calibration) < 4:
            result["feet"][side] = {"states": states, "reason": "no_observed_stance_calibration"}
            continue
        # Estimate the neutral observed sole orientation from supported stance,
        # not from the reconstructed foot or an assumed camera angle.
        references = []
        tolerances = []
        for track in (image_pitch, world_pitch):
            samples = track[calibration]
            center = float(np.median(samples))
            references.append(center)
            tolerances.append(max(np.deg2rad(8), 3 * 1.4826 * float(np.median(np.abs(samples - center)))))
        for index in range(count):
            if not valid[index]:
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
                states[index] = "full_sole"
            elif all(value < -tolerance for value, tolerance in zip(differences, tolerances)):
                states[index] = "toe_only"
            elif all(value > tolerance for value, tolerance in zip(differences, tolerances)):
                states[index] = "heel_only"
        # Do not bridge unknown observations or erase a real release. Isolated
        # detections lack enough temporal evidence to impose a new constraint.
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
                lift_ratio = 0.0
                if state in {"toe_only", "heel_only"}:
                    lift_angle = min(
                        max(0.0, float(np.median(np.abs(track[start:end] - center))) - tolerance)
                        for track, center, tolerance in zip(
                            (image_pitch, world_pitch), references, tolerances
                        )
                    )
                    lift_ratio = float(np.sin(min(lift_angle, np.pi / 2)))
                result["contacts"].append({
                    "jointName": f"{side}_foot", "supportKind": "observed_foot_patch",
                    "contactState": state, "contactMotion": "stationary" if stationary else "unknown",
                    "verticalOnly": state != "full_sole", "startRatio": start / max(1, count - 1),
                    "endRatio": (end - 1) / max(1, count - 1), "confidence": 0.8,
                    "source": "observed_heel_and_forefoot", "anchorImageSpread": spread,
                    "minimumLiftRatio": lift_ratio,
                })
            start = end
        result["feet"][side] = {"states": states, "validObservationCount": int(valid.sum()),
                                "imagePitchReference": references[0], "worldPitchReference": references[1],
                                "pitchTolerances": tolerances}
    return result


def add_observed_foot_contacts(
    evidence: dict[str, Any], observations: dict[str, Any], source_pose: dict[str, Any],
    camera_normal: list[float] | None = None,
    depth_alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import copy

    result = copy.deepcopy(evidence)
    patch_evidence = classify_foot_contacts(observations, evidence, source_pose, camera_normal, depth_alignment)
    result["footPatchEvidence"] = patch_evidence
    if patch_evidence.get("available"):
        result.setdefault("footContactCandidates", result.get("contacts", []))
        # Uncertain observations must not silently fall back to an ankle-only
        # flat-foot assumption. Non-foot support evidence is unaffected.
        result["contacts"] = [record for record in result.get("contacts", [])
                              if not str(record.get("jointName", "")).endswith(("_ankle", "_foot"))]
        result["contacts"].extend(patch_evidence["contacts"])
        result["feet"] = {}
    return result

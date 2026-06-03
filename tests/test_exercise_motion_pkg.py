from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.cleanup import (
    choose_anchor_foot,
    cleanup_motion_clip,
    detect_support_contact_states,
    estimate_support_ground_height,
    lift_clip_above_support_ground,
    micro_movement_tolerance_for_joint,
    stabilize_multi_contact_support,
    stabilize_spine_chain,
    suppress_micro_movements,
)
from exercise_motion_pkg.ground import (
    PlaneEstimate,
    adjust_render_ground_height_to_clip,
    estimate_motion_ground_origin,
    estimate_motion_ground_plane,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline
from exercise_motion_pkg.physics_bundle import write_physics_bundle
from exercise_motion_pkg.physics_sim import PhysicsSimulationConfig, run_physics_simulation
from exercise_motion_pkg.preview import (
    _detect_preview_loops,
    _build_capsules,
    _prepare_preview_clip,
    refine_motion_clip_for_preview,
    write_preview_debug_json,
    write_preview_html,
)
from exercise_motion_pkg.segment_detection import (
    DetectionWindow,
    DetectedSpan,
    WindowDetection,
    build_window_prompt,
    choose_detected_span,
    detection_to_interval,
    iter_detection_windows,
    merge_detection_intervals,
    normalize_window_relative_seconds,
    parse_detection_payload,
)
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.gvhmr_runner import build_gvhmr_command


def build_fixture_clip() -> MotionClip:
    joint_names = [
        "pelvis",
        "spine",
        "neck",
        "head",
        "left_hip",
        "left_knee",
        "left_ankle",
        "right_hip",
        "right_knee",
        "right_ankle",
    ]
    frame_specs = [
        (0.0, 0.00),
        (0.0, 0.00),
        (0.2, 0.12),
        (0.3, 0.18),
        (0.2, 0.10),
        (0.0, 0.00),
        (0.0, 0.00),
    ]
    frames = []
    for index, (pelvis_x, squat_delta) in enumerate(frame_specs):
        pelvis_y = 1.0 - squat_delta
        joints = {
            "pelvis": (pelvis_x, pelvis_y, 0.25 * pelvis_x),
            "spine": (pelvis_x, pelvis_y + 0.25, 0.25 * pelvis_x),
            "neck": (pelvis_x, pelvis_y + 0.45, 0.25 * pelvis_x),
            "head": (pelvis_x, pelvis_y + 0.65, 0.25 * pelvis_x),
            "left_hip": (pelvis_x - 0.1, pelvis_y - 0.1, 0.25 * pelvis_x),
            "left_knee": (pelvis_x - 0.1, 0.55 - squat_delta, 0.25 * pelvis_x),
            "left_ankle": (pelvis_x - 0.1, 0.05, 0.25 * pelvis_x),
            "right_hip": (pelvis_x + 0.1, pelvis_y - 0.1, 0.25 * pelvis_x),
            "right_knee": (pelvis_x + 0.1, 0.55 - squat_delta, 0.25 * pelvis_x),
            "right_ankle": (pelvis_x + 0.1, 0.05, 0.25 * pelvis_x),
        }
        frames.append(MotionFrame(time_sec=index / 30.0, joints=joints))
    return MotionClip(fps=30.0, joint_names=joint_names, frames=frames)


def build_jump_fixture_clip() -> MotionClip:
    joint_names = [
        "pelvis",
        "spine",
        "neck",
        "head",
        "left_hip",
        "left_knee",
        "left_ankle",
        "right_hip",
        "right_knee",
        "right_ankle",
    ]
    frame_specs = [
        (0.00, 1.00, 0.00, 0.05),
        (0.02, 0.95, 0.00, 0.05),
        (0.18, 1.25, 0.18, 0.20),
        (0.30, 1.30, 0.30, 0.22),
        (0.40, 1.00, 0.35, 0.05),
        (0.42, 0.98, 0.35, 0.05),
    ]
    frames = []
    for index, (pelvis_x, pelvis_y, foot_x, foot_y) in enumerate(frame_specs):
        joints = {
            "pelvis": (pelvis_x, pelvis_y, 0.15 * pelvis_x),
            "spine": (pelvis_x, pelvis_y + 0.25, 0.15 * pelvis_x),
            "neck": (pelvis_x, pelvis_y + 0.45, 0.15 * pelvis_x),
            "head": (pelvis_x, pelvis_y + 0.65, 0.15 * pelvis_x),
            "left_hip": (pelvis_x - 0.1, pelvis_y - 0.1, 0.15 * pelvis_x),
            "left_knee": (pelvis_x - 0.08, pelvis_y - 0.45, 0.15 * pelvis_x),
            "left_ankle": (foot_x - 0.06, foot_y, 0.15 * foot_x),
            "right_hip": (pelvis_x + 0.1, pelvis_y - 0.1, 0.15 * pelvis_x),
            "right_knee": (pelvis_x + 0.08, pelvis_y - 0.45, 0.15 * pelvis_x),
            "right_ankle": (foot_x + 0.06, foot_y, 0.15 * foot_x),
        }
        frames.append(MotionFrame(time_sec=index / 30.0, joints=joints))
    return MotionClip(fps=30.0, joint_names=joint_names, frames=frames)


def build_loop_fixture_clip() -> MotionClip:
    joint_names = ["pelvis", "head", "left_foot", "right_foot", "left_hand", "right_hand"]
    frames: list[MotionFrame] = []
    fps = 10.0
    for index in range(30):
        phase = index / 20.0 * math.tau
        if index > 20:
            phase = (index - 20) / 20.0 * math.tau
        pelvis_x = math.sin(phase) * 0.08
        pelvis_y = 1.0 + math.cos(phase) * 0.03
        frames.append(
            MotionFrame(
                time_sec=index / fps,
                joints={
                    "pelvis": (pelvis_x, pelvis_y, 0.0),
                    "head": (pelvis_x, pelvis_y + 0.6, 0.0),
                    "left_foot": (-0.12 + pelvis_x * 0.2, 0.0, -0.05),
                    "right_foot": (0.12 + pelvis_x * 0.2, 0.0, -0.05),
                    "left_hand": (-0.2 + pelvis_x * 0.4, pelvis_y + 0.1, 0.08),
                    "right_hand": (0.2 + pelvis_x * 0.4, pelvis_y + 0.1, 0.08),
                },
            )
        )
    return MotionClip(fps=fps, joint_names=joint_names, frames=frames)


def test_cleanup_motion_clip_trims_centers_and_grounds() -> None:
    clip = build_fixture_clip()
    raw_trimmed_pelvis_xs = [frame.joints["pelvis"][0] for frame in clip.frames[1:]]
    raw_trimmed_root_span = max(raw_trimmed_pelvis_xs) - min(raw_trimmed_pelvis_xs)

    cleaned, stats = cleanup_motion_clip(clip, smoothing_window=3, motion_threshold=0.03, padding_frames=1)

    assert stats.trimmed_start_frames == 1
    assert stats.trimmed_end_frames == 0
    assert cleaned.frame_count == 6
    assert min(frame.joints["left_ankle"][1] for frame in cleaned.frames) >= 0.011999999
    cleaned_pelvis_xs = [frame.joints["pelvis"][0] for frame in cleaned.frames]
    cleaned_root_span = max(cleaned_pelvis_xs) - min(cleaned_pelvis_xs)
    assert cleaned_root_span < raw_trimmed_root_span
    assert cleaned.metadata["cleanup"]["anchorFoot"] in {"left_ankle", "right_ankle"}
    assert cleaned.metadata["cleanup"]["torsoMicroMovementTolerance"] > cleaned.metadata["cleanup"]["legMicroMovementTolerance"]
    assert cleaned.metadata["cleanup"]["reviewStatus"] == "needs_manual_review"


def test_cleanup_motion_clip_stabilizes_anchor_foot_during_ground_contact() -> None:
    clip = build_fixture_clip()

    cleaned, _ = cleanup_motion_clip(clip, smoothing_window=1, motion_threshold=0.03, padding_frames=1)

    left_ankle_xs = [frame.joints["left_ankle"][0] for frame in cleaned.frames]
    left_ankle_zs = [frame.joints["left_ankle"][2] for frame in cleaned.frames]

    assert max(left_ankle_xs) - min(left_ankle_xs) < 0.03
    assert max(left_ankle_zs) - min(left_ankle_zs) < 0.03


def test_cleanup_motion_clip_preserves_jump_travel_when_feet_leave_ground() -> None:
    clip = build_jump_fixture_clip()

    cleaned, _ = cleanup_motion_clip(clip, smoothing_window=1, motion_threshold=0.01, padding_frames=0)

    airborne_left_ankle_x = cleaned.frames[2].joints["left_ankle"][0]
    landing_left_ankle_x = cleaned.frames[4].joints["left_ankle"][0]

    assert airborne_left_ankle_x - cleaned.frames[1].joints["left_ankle"][0] > 0.08
    assert landing_left_ankle_x - cleaned.frames[1].joints["left_ankle"][0] > 0.16


def test_detect_support_contact_states_uses_hands_when_feet_are_not_supporting() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=[
            "pelvis",
            "left_foot",
            "right_foot",
            "left_hand",
            "right_hand",
        ],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "left_foot": (-0.1, 0.02, 0.0),
                    "right_foot": (0.1, 0.02, 0.0),
                    "left_hand": (-0.2, 0.20, 0.3),
                    "right_hand": (0.2, 0.20, 0.3),
                },
            ),
            MotionFrame(
                time_sec=1 / 30.0,
                joints={
                    "pelvis": (0.2, 1.2, 0.1),
                    "left_foot": (0.1, 0.24, 0.1),
                    "right_foot": (0.3, 0.24, 0.1),
                    "left_hand": (0.0, 0.03, 0.4),
                    "right_hand": (0.4, 0.03, 0.4),
                },
            ),
            MotionFrame(
                time_sec=2 / 30.0,
                joints={
                    "pelvis": (0.4, 1.25, 0.2),
                    "left_foot": (0.3, 0.25, 0.2),
                    "right_foot": (0.5, 0.25, 0.2),
                    "left_hand": (0.2, 0.03, 0.5),
                    "right_hand": (0.6, 0.03, 0.5),
                },
            ),
        ],
    )

    states = detect_support_contact_states(clip)

    assert states[2]["state"] == "double_hand_support"
    assert states[2]["leftHandInContact"] is True
    assert states[2]["rightHandInContact"] is True
    assert states[2]["leftInContact"] is False
    assert states[2]["rightInContact"] is False
    assert states[2]["supportJoint"] in {"left_hand", "right_hand"}


def test_estimate_support_ground_height_uses_contact_frames_only() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["left_foot", "right_foot"],
        frames=[
            MotionFrame(time_sec=0.0, joints={"left_foot": (-0.1, 0.01, 0.0), "right_foot": (0.1, 0.02, 0.0)}),
            MotionFrame(time_sec=1 / 30.0, joints={"left_foot": (-0.1, 0.25, 0.0), "right_foot": (0.1, 0.28, 0.0)}),
            MotionFrame(time_sec=2 / 30.0, joints={"left_foot": (-0.1, 0.015, 0.0), "right_foot": (0.1, 0.018, 0.0)}),
        ],
    )
    states = [
        {"state": "double_support", "leftInContact": True, "leftFootJoint": "left_foot", "rightInContact": True, "rightFootJoint": "right_foot"},
        {"state": "airborne", "leftInContact": False, "leftFootJoint": "left_foot", "rightInContact": False, "rightFootJoint": "right_foot"},
        {"state": "double_support", "leftInContact": True, "leftFootJoint": "left_foot", "rightInContact": True, "rightFootJoint": "right_foot"},
    ]

    support_ground_y = estimate_support_ground_height(clip, states)

    assert 0.01 <= support_ground_y <= 0.02


def test_lift_clip_above_support_ground_removes_penetration() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "left_foot": (-0.1, -0.03, 0.0),
                    "right_foot": (0.1, -0.01, 0.0),
                },
            )
        ],
    )

    corrected = lift_clip_above_support_ground(clip, support_ground_y=0.0, tolerance=0.012)

    assert min(corrected.frames[0].joints["left_foot"][1], corrected.frames[0].joints["right_foot"][1]) >= 0.011999999


def test_stabilize_multi_contact_support_anchors_hands_and_feet_together() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_foot", "right_foot", "left_hand", "right_hand"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "left_foot": (-0.2, 0.02, 0.0),
                    "right_foot": (0.2, 0.02, 0.0),
                    "left_hand": (-0.3, 0.02, 0.2),
                    "right_hand": (0.3, 0.02, 0.2),
                },
            ),
            MotionFrame(
                time_sec=1 / 30.0,
                joints={
                    "pelvis": (0.08, 1.02, 0.07),
                    "left_foot": (-0.12, 0.06, 0.07),
                    "right_foot": (0.28, 0.06, 0.07),
                    "left_hand": (-0.22, 0.06, 0.27),
                    "right_hand": (0.38, 0.06, 0.27),
                },
            ),
        ],
    )
    contact_states = [
        {
            "leftInContact": True,
            "leftFootJoint": "left_foot",
            "rightInContact": True,
            "rightFootJoint": "right_foot",
            "leftHandInContact": True,
            "leftHandJoint": "left_hand",
            "rightHandInContact": True,
            "rightHandJoint": "right_hand",
        },
        {
            "leftInContact": True,
            "leftFootJoint": "left_foot",
            "rightInContact": True,
            "rightFootJoint": "right_foot",
            "leftHandInContact": True,
            "leftHandJoint": "left_hand",
            "rightHandInContact": True,
            "rightHandJoint": "right_hand",
        },
    ]

    stabilized = stabilize_multi_contact_support(clip, contact_states=contact_states, support_ground_y=0.02)

    for joint_name in ("left_foot", "right_foot", "left_hand", "right_hand"):
        assert stabilized.frames[1].joints[joint_name][1] < clip.frames[1].joints[joint_name][1]
        assert abs(stabilized.frames[1].joints[joint_name][1] - 0.02) < 0.02


def test_suppress_micro_movements_flattens_small_jitter_but_keeps_major_motion() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_ankle"],
        frames=[
            MotionFrame(time_sec=0.0, joints={"pelvis": (0.0, 1.0, 0.0), "left_ankle": (0.0, 0.0, 0.0)}),
            MotionFrame(time_sec=1 / 30.0, joints={"pelvis": (0.004, 1.002, 0.003), "left_ankle": (0.003, 0.001, 0.0)}),
            MotionFrame(time_sec=2 / 30.0, joints={"pelvis": (0.008, 1.001, 0.004), "left_ankle": (0.004, 0.0, 0.001)}),
            MotionFrame(time_sec=3 / 30.0, joints={"pelvis": (0.12, 1.08, 0.02), "left_ankle": (0.10, 0.02, 0.0)}),
        ],
    )

    filtered = suppress_micro_movements(clip)

    assert filtered.frames[1].joints["pelvis"][0] < clip.frames[1].joints["pelvis"][0]
    assert filtered.frames[1].joints["pelvis"][0] > filtered.frames[0].joints["pelvis"][0]
    assert filtered.frames[2].joints["pelvis"][0] < clip.frames[2].joints["pelvis"][0]
    assert filtered.frames[3].joints["pelvis"] == clip.frames[3].joints["pelvis"]


def test_stabilize_spine_chain_pulls_intermediate_spine_toward_pelvis_neck_axis() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "spine1", "spine2", "spine3", "neck"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 0.0, 0.0),
                    "spine1": (0.2, 0.2, 0.1),
                    "spine2": (0.25, 0.5, 0.2),
                    "spine3": (0.3, 0.75, 0.25),
                    "neck": (0.0, 1.0, 0.0),
                },
            )
        ],
    )

    stabilized = stabilize_spine_chain(clip, blend=0.65)

    assert stabilized.frames[0].joints["spine2"][0] < clip.frames[0].joints["spine2"][0]
    assert stabilized.frames[0].joints["spine2"][2] < clip.frames[0].joints["spine2"][2]
    assert stabilized.frames[0].joints["spine2"][1] > clip.frames[0].joints["spine2"][1]


def test_micro_movement_tolerance_for_joint_is_stronger_for_torso_than_feet() -> None:
    pelvis_tolerance = micro_movement_tolerance_for_joint("pelvis", default=0.015)
    foot_tolerance = micro_movement_tolerance_for_joint("left_foot", default=0.015)
    hand_tolerance = micro_movement_tolerance_for_joint("right_hand", default=0.015)

    assert pelvis_tolerance > foot_tolerance
    assert hand_tolerance > 0.015


def test_choose_anchor_foot_prefers_less_drifting_foot() -> None:
    clip = build_fixture_clip()

    assert choose_anchor_foot(clip) == "left_ankle"


def test_estimate_motion_ground_plane_uses_grounded_ankles() -> None:
    clip = build_fixture_clip()

    plane = estimate_motion_ground_plane(clip)

    assert plane.normal == (0.0, 1.0, 0.0)
    assert math.isclose(plane.offset, -0.05, rel_tol=0.0, abs_tol=1e-9)
    assert plane.rms_error is not None


def test_cleanup_grounds_to_lowest_foot_joint_when_available() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_ankle", "right_ankle", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "left_ankle": (-0.1, 0.08, 0.0),
                    "right_ankle": (0.1, 0.09, 0.0),
                    "left_foot": (-0.1, 0.02, 0.0),
                    "right_foot": (0.1, 0.03, 0.0),
                },
            ),
            MotionFrame(
                time_sec=1 / 30.0,
                joints={
                    "pelvis": (0.0, 1.1, 0.0),
                    "left_ankle": (-0.1, 0.10, 0.0),
                    "right_ankle": (0.1, 0.11, 0.0),
                    "left_foot": (-0.1, 0.04, 0.0),
                    "right_foot": (0.1, 0.05, 0.0),
                },
            ),
        ],
    )

    cleaned, _ = cleanup_motion_clip(clip, smoothing_window=1, motion_threshold=0.0, padding_frames=0)

    assert min(frame.joints["left_foot"][1] for frame in cleaned.frames) >= 0.011999999
    assert min(frame.joints["right_foot"][1] for frame in cleaned.frames) >= 0.011999999


def test_estimate_motion_ground_origin_uses_grounded_contacts() -> None:
    clip = build_fixture_clip()
    plane = estimate_motion_ground_plane(clip)

    origin = estimate_motion_ground_origin(clip, plane)

    assert math.isclose(origin[1], 0.05, rel_tol=0.0, abs_tol=1e-9)
    assert math.isfinite(origin[0])
    assert math.isfinite(origin[2])


def test_adjust_render_ground_height_to_clip_lowers_high_floor() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["left_ankle", "right_ankle", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "left_ankle": (-0.1, 0.06, 0.0),
                    "right_ankle": (0.1, 0.06, 0.0),
                    "left_foot": (-0.1, 0.02, 0.0),
                    "right_foot": (0.1, 0.03, 0.0),
                },
            ),
            MotionFrame(
                time_sec=1 / 30.0,
                joints={
                    "left_ankle": (-0.1, 0.08, 0.0),
                    "right_ankle": (0.1, 0.08, 0.0),
                    "left_foot": (-0.1, 0.03, 0.0),
                    "right_foot": (0.1, 0.04, 0.0),
                },
            ),
            MotionFrame(
                time_sec=2 / 30.0,
                joints={
                    "left_ankle": (-0.1, 0.18, 0.0),
                    "right_ankle": (0.1, 0.18, 0.0),
                    "left_foot": (-0.1, 0.10, 0.0),
                    "right_foot": (0.1, 0.11, 0.0),
                },
            ),
        ],
    )

    adjusted_ground_y = adjust_render_ground_height_to_clip(
        clip=clip,
        proposed_ground_y=0.05,
    )

    assert math.isclose(adjusted_ground_y, 0.032, rel_tol=0.0, abs_tol=1e-9)


def test_write_preview_html_embeds_motion_payload(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    output = tmp_path / "preview.html"

    write_preview_html(output, clip, title="squat-review")

    text = output.read_text(encoding="utf-8")
    assert "squat-review" in text
    assert "Interactive skeleton preview" in text
    assert "\"pelvis\"" in text
    assert "\"defaultFixedRoot\": false" in text
    assert "<button id=\"pauseToggle\" type=\"button\">Pause</button>" in text
    assert "const cameraTarget = new THREE.Vector3();" in text
    assert "overflow-y: auto;" in text
    assert "function estimateSceneOrigin(currentFixedRoot)" in text
    assert "function refreshCameraTarget()" in text
    assert "let playbackState = buildPlaybackState(payload.frames, currentLoop);" in text
    assert "const detectedLoops = Array.isArray(payload.detectedLoops) ? payload.detectedLoops : [];" in text
    assert "<select id=\"cameraMode\">" in text
    assert "<select id=\"loopSelect\"></select>" in text
    assert "<input id=\"autoWorldAlignment\" type=\"checkbox\"" in text
    assert "<input id=\"rotateX\" type=\"range\"" in text
    assert "<input id=\"rotateY\" type=\"range\"" in text
    assert "<input id=\"rotateZ\" type=\"range\"" in text
    assert "<input id=\"translateX\" type=\"range\"" in text
    assert "<input id=\"translateY\" type=\"range\"" in text
    assert "<input id=\"translateZ\" type=\"range\"" in text
    assert "World rotation:" in text
    assert "World translation:" in text
    assert "<button id=\"resetTransform\" type=\"button\">Reset world transform</button>" in text
    assert "function populateLoopSelect()" in text
    assert "function setSelectedLoop(nextIndex)" in text
    assert "function getFrameTranslation(frame)" in text
    assert "const transformPivot = new THREE.Vector3();" in text
    assert "function refreshTransformPivot(currentFixedRoot)" in text
    assert "function updateManualTransformState()" in text
    assert "function applyManualTransform(point)" in text
    assert "type=\"module\"" in text
    assert "new THREE.WebGLRenderer" in text
    assert "new THREE.PerspectiveCamera" in text
    assert "new THREE.OrthographicCamera" in text
    assert "new THREE.GridHelper" in text
    assert "new THREE.LineSegments(" in text
    assert "new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1))" in text
    assert "new THREE.DirectionalLight" in text
    assert "\"capsules\"" in text
    assert "drawTorsoFacingMarker(frame, frameTranslation);" not in text
    assert ".filter((capsule) => !isTorsoCapsule(capsule))" in text
    assert "const pelvisMesh = new THREE.Mesh(pelvisGeometry, torsoMaterial);" in text
    assert "function updateCamera()" in text
    assert "activeCamera.lookAt(cameraTarget);" in text
    assert "function refreshMergedBoundsHelper()" in text
    assert "function computeOrientedSceneBounds(currentFixedRoot)" in text
    assert "function getInterpolatedFrame()" in text
    assert "function updateSceneForFrame(frame)" in text
    assert "tempQuaternion.setFromUnitVectors(axisY, tempVector.clone().normalize());" in text
    assert "function setOrientedEllipsoid(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "function setOrientedCylinder(mesh, start, end, radius)" in text
    assert "function setOrientedFrameVolume(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "function setOrientedBar(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "const headScale = neckSourceJoint" in text
    assert "headMesh.scale.set(headScale * 0.88, headScale * 1.08, headScale * 0.86);" in text
    assert "let paused = false;" in text
    assert "function refreshPauseLabel()" in text
    assert "yaw -= deltaX * 0.01;" in text
    assert "let playbackDirection = 1;" in text
    assert "playbackDirection = -1;" in text
    assert "deltaSeconds * payload.fps * speed" in text


def test_detect_preview_loops_finds_repeating_motion_span() -> None:
    clip = build_loop_fixture_clip()

    loops = _detect_preview_loops(clip)

    assert loops
    best = loops[0]
    assert best["durationSec"] >= 2.0
    assert best["endFrame"] > best["startFrame"]


def test_prepare_preview_clip_flips_upside_down_raw_gvhmr_clip() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "head", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 0.0, 0.0),
                    "head": (0.0, -0.5, 0.0),
                    "left_foot": (-0.1, 0.8, 0.0),
                    "right_foot": (0.1, 0.82, 0.0),
                },
            ),
        ],
        metadata={"upstream": "gvhmr"},
    )

    preview_clip = _prepare_preview_clip(clip)

    assert preview_clip.frames[0].joints["head"][1] == pytest.approx(0.5)
    assert preview_clip.frames[0].joints["left_foot"][1] == pytest.approx(-0.8)


def test_prepare_preview_clip_replaces_isolated_outlier_frame() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "head"],
        frames=[
            MotionFrame(time_sec=0.0, joints={"pelvis": (0.0, 0.0, 0.0), "head": (0.0, 0.5, 0.0)}),
            MotionFrame(time_sec=1 / 30.0, joints={"pelvis": (4.0, 4.0, 4.0), "head": (4.0, 4.5, 4.0)}),
            MotionFrame(time_sec=2 / 30.0, joints={"pelvis": (0.02, 0.0, 0.01), "head": (0.02, 0.5, 0.01)}),
        ],
    )

    preview_clip = _prepare_preview_clip(clip)

    assert preview_clip.frames[1].joints["pelvis"][0] == pytest.approx(0.01)
    assert preview_clip.frames[1].joints["pelvis"][1] == pytest.approx(0.0)


def test_prepare_preview_clip_replaces_startup_outlier_frame() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "head"],
        frames=[
            MotionFrame(time_sec=0.0, joints={"pelvis": (3.0, 3.0, 3.0), "head": (3.0, 3.5, 3.0)}),
            MotionFrame(time_sec=1 / 30.0, joints={"pelvis": (0.0, 0.0, 0.0), "head": (0.0, 0.5, 0.0)}),
            MotionFrame(time_sec=2 / 30.0, joints={"pelvis": (0.01, 0.0, 0.0), "head": (0.01, 0.5, 0.0)}),
            MotionFrame(time_sec=3 / 30.0, joints={"pelvis": (0.02, 0.0, 0.01), "head": (0.02, 0.5, 0.01)}),
        ],
    )

    preview_clip = _prepare_preview_clip(clip)

    assert 0.0 < preview_clip.frames[0].joints["pelvis"][0] < 0.05
    assert preview_clip.frames[0].joints["head"][1] == pytest.approx(0.5)


def test_prepare_preview_clip_suppresses_short_translation_burst() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "head", "left_foot", "right_foot"],
        frames=[
            MotionFrame(time_sec=0.0, joints={"pelvis": (0.0, 0.0, 5.0), "head": (0.0, 0.5, 5.0), "left_foot": (-0.1, -0.5, 5.0), "right_foot": (0.1, -0.5, 5.0)}),
            MotionFrame(time_sec=1 / 30.0, joints={"pelvis": (0.02, 0.0, 5.02), "head": (0.02, 0.5, 5.02), "left_foot": (-0.08, -0.5, 5.02), "right_foot": (0.12, -0.5, 5.02)}),
            MotionFrame(time_sec=2 / 30.0, joints={"pelvis": (0.9, 0.0, 5.9), "head": (0.9, 0.5, 5.9), "left_foot": (0.8, -0.5, 5.9), "right_foot": (1.0, -0.5, 5.9)}),
            MotionFrame(time_sec=3 / 30.0, joints={"pelvis": (0.92, 0.0, 5.92), "head": (0.92, 0.5, 5.92), "left_foot": (0.82, -0.5, 5.92), "right_foot": (1.02, -0.5, 5.92)}),
            MotionFrame(time_sec=4 / 30.0, joints={"pelvis": (0.03, 0.0, 5.03), "head": (0.03, 0.5, 5.03), "left_foot": (-0.07, -0.5, 5.03), "right_foot": (0.13, -0.5, 5.03)}),
            MotionFrame(time_sec=5 / 30.0, joints={"pelvis": (0.04, 0.0, 5.04), "head": (0.04, 0.5, 5.04), "left_foot": (-0.06, -0.5, 5.04), "right_foot": (0.14, -0.5, 5.04)}),
        ],
    )

    preview_clip = _prepare_preview_clip(clip)

    assert preview_clip.frames[2].joints["pelvis"][0] < 0.2
    assert preview_clip.frames[3].joints["pelvis"][0] < 0.2


def test_write_preview_html_defaults_fixed_root_for_raw_gvhmr(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=clip.frames,
        source=clip.source,
        metadata={"upstream": "gvhmr"},
    )
    output = tmp_path / "preview-raw-gvhmr.html"

    write_preview_html(output, clip, title="raw-gvhmr")

    text = output.read_text(encoding="utf-8")
    assert "\"defaultFixedRoot\": true" in text


def test_write_preview_debug_json_exports_rendered_joint_coordinates(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=clip.frames,
        source=clip.source,
        metadata={"upstream": "gvhmr"},
    )
    output = tmp_path / "preview-render-debug.json"

    write_preview_debug_json(output, _prepare_preview_clip(clip))

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["fixedRootApplied"] is True
    assert payload["frameCount"] == clip.frame_count
    assert "frames" in payload and len(payload["frames"]) == clip.frame_count
    assert "sourceJoints" in payload["frames"][0]
    assert "renderedJoints" in payload["frames"][0]
    assert "translationApplied" in payload["frames"][0]


def test_refine_motion_clip_for_preview_marks_clip_as_prepared() -> None:
    clip = build_fixture_clip()

    refined = refine_motion_clip_for_preview(clip)
    refined_again = refine_motion_clip_for_preview(refined)

    assert refined.metadata["previewRefinement"]["prepared"] is True
    assert refined_again.frames == refined.frames


def test_refine_motion_clip_for_preview_clamps_impossible_hinge_pose() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["left_shoulder", "left_elbow", "left_wrist", "left_hand"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "left_shoulder": (0.0, 1.0, 0.0),
                    "left_elbow": (0.0, 0.5, 0.0),
                    "left_wrist": (0.02, 0.98, 0.0),
                    "left_hand": (0.04, 1.08, 0.0),
                },
            )
        ],
    )

    refined = refine_motion_clip_for_preview(clip)
    shoulder = refined.frames[0].joints["left_shoulder"]
    elbow = refined.frames[0].joints["left_elbow"]
    wrist = refined.frames[0].joints["left_wrist"]
    angle_deg = _joint_angle_degrees(shoulder, elbow, wrist)

    assert angle_deg >= 14.0
    assert angle_deg <= 176.0
    assert refined.frames[0].joints["left_hand"][1] != clip.frames[0].joints["left_hand"][1]


def test_build_capsules_resolves_multispine_and_collar_joints() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=[
            "pelvis",
            "spine1",
            "spine2",
            "spine3",
            "neck",
            "left_collar",
            "left_shoulder",
            "right_collar",
            "right_shoulder",
        ],
        frames=[],
    )

    capsules = _build_capsules(clip)
    capsule_pairs = {(capsule["start"], capsule["end"]) for capsule in capsules}

    assert ("pelvis", "spine1") in capsule_pairs
    assert ("spine1", "spine2") in capsule_pairs
    assert ("spine2", "spine3") in capsule_pairs
    assert ("spine3", "neck") in capsule_pairs
    assert ("neck", "left_collar") in capsule_pairs
    assert ("left_collar", "left_shoulder") in capsule_pairs


def test_generation_pipeline_uses_normalized_input_without_extractor_stage(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    source_motion = tmp_path / "source_motion.json"
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake-video")
    save_motion_json(source_motion, clip)

    result = run_generation_pipeline(
        GenerateRequest(
            exercise_slug="squat",
            workspace=tmp_path / "workspace",
            video_path=source_video,
            normalized_motion_json=source_motion,
            smoothing_window=3,
            motion_threshold=0.03,
            padding_frames=1,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["previewHtmlPath"]).exists()
    assert Path(manifest["cleanedMotionJsonPath"]).exists()
    assert Path(manifest["groundMetadataPath"]).exists()
    assert manifest["groundMetadata"]["renderGroundPlane"]["space"] == "motion"
    assert manifest["groundMetadata"]["renderGroundOrigin"]["space"] == "motion"
    assert manifest["nextStage"]["status"] == "pending_rig_retarget"

    cleaned_clip = load_motion_json(result.cleaned_motion_json_path)
    assert cleaned_clip.metadata["ground"]["renderGroundPlane"]["space"] == "motion"
    assert cleaned_clip.metadata["ground"]["renderGroundOrigin"]["space"] == "motion"

    preview_html = result.preview_html_path.read_text(encoding="utf-8")
    assert "\"renderGroundPlane\"" in preview_html
    assert "\"renderGroundOrigin\"" in preview_html


def _joint_angle_degrees(a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]) -> float:
    ba = (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    bc = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
    ba_len = math.sqrt(sum(value * value for value in ba))
    bc_len = math.sqrt(sum(value * value for value in bc))
    cosine = sum(left * right for left, right in zip(ba, bc)) / (ba_len * bc_len)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def test_generation_pipeline_writes_ground_metadata_when_enabled(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    source_motion = tmp_path / "source_motion.json"
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake-video")
    save_motion_json(source_motion, clip)

    result = run_generation_pipeline(
        GenerateRequest(
            exercise_slug="snatch-arranque",
            workspace=tmp_path / "workspace",
            video_path=source_video,
            normalized_motion_json=source_motion,
            smoothing_window=3,
            motion_threshold=0.03,
            padding_frames=1,
        )
    )

    assert result.ground_metadata_path is not None
    ground_payload = json.loads(result.ground_metadata_path.read_text(encoding="utf-8"))
    assert ground_payload["renderGroundPlane"]["space"] == "motion"
    assert ground_payload["renderGroundOrigin"]["space"] == "motion"
    assert ground_payload["unidepth"]["alignmentStatus"] == "motion_space_only"

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["groundMetadataPath"] is not None
    assert manifest["groundMetadata"]["renderGroundPlane"]["space"] == "motion"
    assert manifest["groundMetadata"]["renderGroundOrigin"]["space"] == "motion"

    cleaned_clip = load_motion_json(result.cleaned_motion_json_path)
    assert cleaned_clip.metadata["ground"]["renderGroundPlane"]["space"] == "motion"
    assert cleaned_clip.metadata["ground"]["renderGroundOrigin"]["space"] == "motion"


def test_generation_pipeline_accepts_video_already_in_workspace_input(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    workspace = tmp_path / "workspace"
    input_dir = workspace / "squat" / "input"
    input_dir.mkdir(parents=True)
    source_motion = tmp_path / "source_motion.json"
    source_video = input_dir / "source.mp4"
    source_video.write_bytes(b"fake-video")
    save_motion_json(source_motion, clip)

    result = run_generation_pipeline(
        GenerateRequest(
            exercise_slug="squat",
            workspace=workspace,
            video_path=source_video,
            normalized_motion_json=source_motion,
            smoothing_window=3,
            motion_threshold=0.03,
            padding_frames=1,
        )
    )

    assert result.copied_input_video_path == source_video
    assert result.manifest_path.exists()


def test_build_gvhmr_command_uses_local_paths() -> None:
    command = build_gvhmr_command(
        gvhmr_repo_path=Path("C:/GVHMR"),
        input_video=Path("C:/videos/burpee.mp4"),
        output_root=Path("C:/out"),
        python_command="python",
        static_camera=True,
    )

    assert command[:2] == ["python", "tools/demo/demo.py"]
    assert "--video=C:\\videos\\burpee.mp4" in command
    assert "--output_root" in command
    assert "C:\\out" in command
    assert "-s" in command


def test_iter_detection_windows_uses_overlap() -> None:
    windows = iter_detection_windows(duration_seconds=20.0, window_seconds=8.0, overlap_seconds=4.0)

    assert [(round(item.start_seconds, 1), round(item.end_seconds, 1)) for item in windows] == [
        (0.0, 8.0),
        (4.0, 12.0),
        (8.0, 16.0),
        (12.0, 20.0),
    ]


def test_detection_to_interval_projects_relative_times() -> None:
    detection = WindowDetection(
        window=DetectionWindow(index=2, start_seconds=8.0, end_seconds=16.0),
        movement_present=True,
        contains_movement_start=False,
        contains_movement_end=True,
        movement_start_seconds=1.5,
        movement_end_seconds=7.0,
        confidence=0.8,
        summary="movement in progress",
        reason="visible bar path",
        camera_variation=0.2,
        frame_paths=[],
    )

    interval = detection_to_interval(detection, confidence_threshold=0.45)

    assert interval is not None
    assert interval.start_seconds == 9.5
    assert interval.end_seconds == 15.0
    assert interval.average_camera_variation == 0.2
    assert interval.contributing_windows == [2]


def test_merge_detection_intervals_merges_close_segments() -> None:
    merged = merge_detection_intervals(
        [
            DetectedSpan(start_seconds=1.0, end_seconds=5.0, confidence=0.6, average_camera_variation=0.4, contributing_windows=[0]),
            DetectedSpan(start_seconds=6.0, end_seconds=10.0, confidence=0.8, average_camera_variation=0.2, contributing_windows=[1]),
            DetectedSpan(start_seconds=20.0, end_seconds=22.0, confidence=0.7, average_camera_variation=0.1, contributing_windows=[2]),
        ],
        merge_gap_seconds=1.5,
    )

    assert len(merged) == 2
    assert merged[0].start_seconds == 1.0
    assert merged[0].end_seconds == 10.0
    assert math.isclose(merged[0].average_camera_variation, 0.3, rel_tol=0.0, abs_tol=1e-9)
    assert merged[0].contributing_windows == [0, 1]


def test_choose_detected_span_prefers_longest_positive_cluster() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=8.0),
            movement_present=False,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.2,
            summary="none",
            reason="none",
            camera_variation=0.6,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=4.0, end_seconds=12.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=False,
            movement_start_seconds=1.0,
            movement_end_seconds=None,
            confidence=0.8,
            summary="start",
            reason="start visible",
            camera_variation=0.35,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=2, start_seconds=8.0, end_seconds=16.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=True,
            movement_start_seconds=None,
            movement_end_seconds=6.5,
            confidence=0.7,
            summary="end",
            reason="end visible",
            camera_variation=0.15,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=3, start_seconds=20.0, end_seconds=28.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=1.0,
            movement_end_seconds=4.0,
            confidence=0.55,
            summary="short stable movement",
            reason="short but stable",
            camera_variation=0.05,
            frame_paths=[],
        ),
    ]

    span = choose_detected_span(detections=detections, confidence_threshold=0.45, merge_gap_seconds=2.0)

    assert span is not None
    assert span.start_seconds == 4.0
    assert span.end_seconds == 16.0
    assert span.contributing_windows == [1, 2]


def test_choose_detected_span_does_not_bridge_across_negative_window() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=8.0),
            movement_present=False,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=1.0,
            summary="none",
            reason="none",
            camera_variation=0.10,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=4.0, end_seconds=12.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.85,
            summary="movement",
            reason="movement visible",
            camera_variation=0.14,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=2, start_seconds=8.0, end_seconds=16.0),
            movement_present=False,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=1.0,
            summary="none",
            reason="none",
            camera_variation=0.30,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=3, start_seconds=12.0, end_seconds=20.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.95,
            summary="movement",
            reason="movement visible",
            camera_variation=0.08,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=4, start_seconds=16.0, end_seconds=24.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.95,
            summary="movement",
            reason="movement visible",
            camera_variation=0.07,
            frame_paths=[],
        ),
    ]

    span = choose_detected_span(detections=detections, confidence_threshold=0.45, merge_gap_seconds=2.0)

    assert span is not None
    assert span.start_seconds == 12.0
    assert span.end_seconds == 24.0
    assert span.contributing_windows == [3, 4]


def test_choose_detected_span_trims_start_against_previous_negative_window() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=8.0),
            movement_present=False,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=1.0,
            summary="none",
            reason="none",
            camera_variation=0.10,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=4.0, end_seconds=12.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.9,
            summary="movement in latter half",
            reason="movement visible late",
            camera_variation=0.05,
            frame_paths=[],
        ),
    ]

    span = choose_detected_span(detections=detections, confidence_threshold=0.45, merge_gap_seconds=2.0)

    assert span is not None
    assert span.start_seconds == 4.0
    assert span.end_seconds == 12.0
    assert span.contributing_windows == [1]


def test_choose_detected_span_prefers_complete_rep_over_preparation_only_cluster() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=8.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=False,
            movement_start_seconds=None,
            movement_end_seconds=None,
            confidence=0.95,
            summary="setup and preparation",
            reason="athlete gets into position but rep has not started",
            camera_variation=0.02,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=4.0, end_seconds=12.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=False,
            movement_start_seconds=2.0,
            movement_end_seconds=None,
            confidence=0.8,
            summary="rep start",
            reason="eccentric or initial pull begins",
            camera_variation=0.08,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=2, start_seconds=8.0, end_seconds=16.0),
            movement_present=True,
            contains_movement_start=False,
            contains_movement_end=True,
            movement_start_seconds=None,
            movement_end_seconds=5.0,
            confidence=0.82,
            summary="rep finish",
            reason="movement completes",
            camera_variation=0.09,
            frame_paths=[],
        ),
    ]

    span = choose_detected_span(detections=detections, confidence_threshold=0.45, merge_gap_seconds=2.0)

    assert span is not None
    assert span.start_seconds == 4.0
    assert span.end_seconds == 16.0
    assert span.contributing_windows == [1, 2]


def test_parse_detection_payload_accepts_minor_key_drift() -> None:
    payload = parse_detection_payload(
        '{"movement_present": true, "contains_movement_start": true, "contains_movement_end": true, '
        '"movement_start_seconds": 0.0, "movement_endseconds": 8.0, "confidence": 0.95, '
        '"summary": "exercise movement visible", "reason": "full movement window"}',
        window=DetectionWindow(index=0, start_seconds=12.0, end_seconds=20.0),
    )

    assert payload["movement_present"] is True
    assert payload["movement_start_seconds"] == 0.0
    assert payload["movement_end_seconds"] == 8.0


def test_build_window_prompt_rejects_setup_and_prefers_tight_full_rep() -> None:
    prompt = build_window_prompt(
        exercise_name="burpee",
        start_seconds=12.0,
        end_seconds=20.0,
    )

    assert "Treat setup, walking into position, unracking, bracing, idle preparation, and recovery after the rep as NOT movement" in prompt
    assert "We are specifically looking for the part where the exercise rep is actually done" in prompt
    assert "Do not mark movement_present true for preparation alone" in prompt
    assert "title cards, explanation slides, still demonstration poses" in prompt
    assert "Judge the exercise from the sequence of frames together" in prompt
    assert "Ignore on-screen instructional text, bullet points, titles, logos, or slide-like layout" in prompt
    assert "Only call it a static instructional slide if the sampled frames show essentially the same still image or pose" in prompt
    assert "Determine whether this window contains the part where the exercise rep is actively being performed" in prompt
    assert "movement_present should be true only if the athlete is actively performing the exercise rep in this window" in prompt
    assert "For cyclical exercises, prefer windows where one rep is actively being performed rather than rest between reps" in prompt
    assert "contains_loop_anchor" not in prompt
    assert '"movement_start_seconds"' not in prompt
    assert '"movement_end_seconds"' not in prompt


def test_write_physics_bundle_emits_reference_and_mjcf(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names + [
            "left_foot",
            "right_foot",
            "left_hand",
            "right_hand",
            "left_elbow",
            "right_elbow",
            "left_knee",
            "right_knee",
            "head",
        ],
        frames=[
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    **frame.joints,
                    "left_foot": (-0.1, 0.0, -0.2),
                    "right_foot": (0.1, 0.0, -0.2),
                    "left_hand": (-0.2, 0.8, -0.1),
                    "right_hand": (0.2, 0.8, -0.1),
                    "left_elbow": (-0.15, 0.6, -0.05),
                    "right_elbow": (0.15, 0.6, -0.05),
                    "left_knee": (-0.1, 0.3, -0.15),
                    "right_knee": (0.1, 0.3, -0.15),
                    "head": (0.0, 1.1, 0.0),
                },
            )
            for frame in clip.frames
        ],
        source=clip.source,
        metadata={
            "cleanup": {
                "supportGroundY": 0.0,
                "footContacts": [
                    {
                        "frameIndex": index,
                        "supportJoint": "left_foot",
                        "state": "double_support",
                    }
                    for index, _ in enumerate(clip.frames)
                ],
            }
        },
    )
    result = write_physics_bundle(clip=clip, out_dir=tmp_path / "physics")

    reference_payload = json.loads(result.reference_json_path.read_text(encoding="utf-8"))
    controller_payload = json.loads(result.controller_config_path.read_text(encoding="utf-8"))

    assert reference_payload["rootJoint"] == "pelvis"
    assert "left_foot" in reference_payload["effectors"]
    assert reference_payload["initialPose"]["pelvis"] == list(clip.frames[0].joints["pelvis"])
    assert "joints" in reference_payload["frames"][0]
    assert reference_payload["frames"][0]["supportState"]["supportJoint"] == "left_foot"
    assert controller_payload["controllerType"] == "kinematic_constraint_refinement"


def test_run_physics_simulation_emits_repo_motion_json(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names + [
            "left_foot",
            "right_foot",
            "left_hand",
            "right_hand",
            "left_elbow",
            "right_elbow",
            "left_knee",
            "right_knee",
            "head",
        ],
        frames=[
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    **frame.joints,
                    "pelvis": (0.0 + frame.time_sec * 0.1, 0.8, 0.0),
                    "left_foot": (-0.1, 0.0, -0.2),
                    "right_foot": (0.1, 0.0, -0.2),
                    "left_hand": (-0.2, 0.8, -0.1),
                    "right_hand": (0.2, 0.8, -0.1),
                    "left_elbow": (-0.15, 0.6, -0.05),
                    "right_elbow": (0.15, 0.6, -0.05),
                    "left_knee": (-0.1, 0.3, -0.15),
                    "right_knee": (0.1, 0.3, -0.15),
                    "head": (0.0, 1.1, 0.0),
                },
            )
            for frame in clip.frames
        ],
        source=clip.source,
        metadata={
            "cleanup": {
                "supportGroundY": 0.0,
                "footContacts": [
                    {
                        "frameIndex": index,
                        "supportJoint": "left_foot",
                        "state": "double_support",
                    }
                    for index, _ in enumerate(clip.frames)
                ],
            }
        },
    )
    bundle = write_physics_bundle(clip=clip, out_dir=tmp_path / "physics")
    result = run_physics_simulation(
        bundle_dir=bundle.out_dir,
        output_motion_json=bundle.out_dir / "simulated_motion.json",
    )

    simulated_clip = load_motion_json(result.simulated_motion_json_path)
    summary_payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert simulated_clip.frame_count == clip.frame_count
    assert simulated_clip.metadata["physicsSim"]["backend"] == "kinematic"
    assert summary_payload["backend"] == "kinematic"
    assert simulated_clip.frames[0].joints["left_foot"][1] == pytest.approx(0.0)
    first_frame = simulated_clip.frames[0].joints
    second_frame = simulated_clip.frames[1].joints
    first_leg_length = math.dist(first_frame["left_knee"], first_frame["left_foot"])
    second_leg_length = math.dist(second_frame["left_knee"], second_frame["left_foot"])
    assert second_leg_length == pytest.approx(first_leg_length, rel=0.05)


def test_run_physics_simulation_prototype_backend_smoke(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names + [
            "left_foot",
            "right_foot",
            "left_hand",
            "right_hand",
            "left_elbow",
            "right_elbow",
            "left_knee",
            "right_knee",
            "head",
        ],
        frames=[
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    **frame.joints,
                    "pelvis": (0.0, 0.8, 0.0),
                    "left_foot": (-0.1, 0.0, -0.2),
                    "right_foot": (0.1, 0.0, 0.2),
                    "left_hand": (-0.2, 0.8, -0.1),
                    "right_hand": (0.2, 0.8, 0.1),
                    "left_elbow": (-0.15, 0.6, -0.05),
                    "right_elbow": (0.15, 0.6, 0.05),
                    "left_knee": (-0.1, 0.3, -0.15),
                    "right_knee": (0.1, 0.3, 0.15),
                    "head": (0.0, 1.1, 0.0),
                },
            )
            for frame in clip.frames
        ],
        source=clip.source,
        metadata={
            "cleanup": {
                "supportGroundY": 0.0,
                "footContacts": [
                    {
                        "frameIndex": index,
                        "supportJoint": "left_foot",
                        "state": "double_support",
                    }
                    for index, _ in enumerate(clip.frames)
                ],
            }
        },
    )
    bundle = write_physics_bundle(clip=clip, out_dir=tmp_path / "physics")
    result = run_physics_simulation(
        bundle_dir=bundle.out_dir,
        output_motion_json=bundle.out_dir / "simulated_motion_prototype.json",
        config=PhysicsSimulationConfig(backend="prototype"),
    )

    simulated_clip = load_motion_json(result.simulated_motion_json_path)
    summary_payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert simulated_clip.frame_count == clip.frame_count
    assert simulated_clip.metadata["physicsSim"]["backend"] == "prototype"
    assert summary_payload["backend"] == "prototype"
    assert simulated_clip.frames[0].joints["left_foot"][1] == pytest.approx(0.0)


def test_normalize_window_relative_seconds_accepts_relative_values() -> None:
    window = DetectionWindow(index=7, start_seconds=28.0, end_seconds=34.28425)

    assert normalize_window_relative_seconds(2.5, window=window) == 2.5


def test_normalize_window_relative_seconds_converts_global_values() -> None:
    window = DetectionWindow(index=7, start_seconds=28.0, end_seconds=34.28425)

    assert normalize_window_relative_seconds(28.0, window=window) == 0.0
    assert math.isclose(
        normalize_window_relative_seconds(34.28, window=window),
        6.28,
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def test_trim_video_creates_expected_subclip(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")

    source_path = tmp_path / "source.mp4"
    fps = 10.0
    frame_size = (32, 24)
    writer = cv2.VideoWriter(
        str(source_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        frame_size,
    )
    assert writer.isOpened()
    try:
        for index in range(20):
            frame = cv2.cvtColor(
                (index * 10 % 255) * np.ones((frame_size[1], frame_size[0]), dtype=np.uint8),
                cv2.COLOR_GRAY2BGR,
            )
            writer.write(frame)
    finally:
        writer.release()

    trimmed_path = tmp_path / "trimmed.mp4"
    trim_video(
        source_path=source_path,
        output_path=trimmed_path,
        start_seconds=0.5,
        end_seconds=1.3,
    )

    metadata = read_basic_video_metadata(trimmed_path)
    assert metadata.fps > 0
    assert 7 <= metadata.frame_count <= 9

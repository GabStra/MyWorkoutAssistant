from __future__ import annotations

import json
import math
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np
import pytest

import exercise_motion_pkg.bake_and_rank as bake_and_rank_module
from exercise_motion_pkg.cleanup import (
    CleanupStats,
    choose_anchor_foot,
    cleanup_motion_clip,
    detect_support_contact_states,
    estimate_support_ground_height,
    lift_clip_above_support_ground,
    micro_movement_tolerance_for_joint,
    stabilize_multi_contact_support,
    suppress_micro_movements,
)
from exercise_motion_pkg.bake_and_rank import (
    BakedLoopArtifact,
    BakeAndRankRequest,
    LoopRanking,
    RankedCandidate,
    ReviewItem,
    apply_loop_continuity_adjustment,
    choose_best_review_item,
    compute_kinematic_plausibility_metrics,
    compute_hand_lock_arm_distortion_metrics,
    compute_loop_bridge_quality_metrics,
    compute_loop_continuity_metrics,
    compute_motion_strength_metrics,
    compute_paired_hands_preservation_metrics,
    compute_preview_readability_metrics,
    dense_loop_review_video_frame_indices,
    load_ranked_candidates_manifest,
    parse_loop_ranking_response,
    parse_ranked_candidates_manifest,
    parse_export_fps,
    parse_top_ranked_candidates_manifest,
    repeated_review_frame_data_urls,
    run_bake_and_rank_pipeline,
    sample_review_frame_indices,
    split_loops_by_duration,
    preview_settings_variants,
)
from exercise_motion_pkg.ground import (
    PlaneEstimate,
    adjust_render_ground_height_to_clip,
    estimate_motion_ground_origin,
    estimate_motion_ground_plane,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, GenerateResult, run_generation_pipeline
import exercise_motion_pkg.pipeline as pipeline
from exercise_motion_pkg.pose_prefilter import (
    PoseDetection,
    PosePrefilterSettings,
    PoseSample,
    resolve_pose_model_path,
    score_pose_samples,
)
import exercise_motion_pkg.pose_prefilter as pose_prefilter_module
from exercise_motion_pkg.physics_bundle import write_physics_bundle
from exercise_motion_pkg.physics_sim import PhysicsSimulationConfig, run_physics_simulation
from exercise_motion_pkg.structural_refinement import refine_motion_clip_structurally
from exercise_motion_pkg.preview import (
    _aligned_body_points_down,
    _apply_rotations_to_point,
    _build_preview_translation_track,
    _center_preview_clip_for_render,
    _compute_preview_auto_alignment,
    _detect_preview_loops,
    _build_capsules,
    _prepare_preview_clip,
    build_wear_skeleton_payload,
    refine_motion_clip_for_preview,
    write_preview_debug_json,
    write_preview_html,
    write_wear_skeleton_json,
)
from exercise_motion_pkg.segment_detection import (
    CandidateExecution,
    DetectionResult,
    DetectionWindow,
    DetectedSpan,
    MotionInterval,
    SupportDominanceResult,
    WindowDetection,
    build_window_prompt,
    choose_detected_span,
    detection_to_interval,
    iter_detection_windows,
    merge_detection_intervals,
    normalize_window_relative_seconds,
    parse_detection_payload,
)
from exercise_motion_pkg.video_utils import BasicVideoMetadata, read_basic_video_metadata, trim_video
from exercise_motion_pkg.wham_runner import WhamRunResult, build_wham_command, run_wham_locally
from exercise_motion_pkg.wham_smpl_preview import (
    WhamSmplMeshSequence,
    build_baked_wham_smpl_preview_payload,
)
from exercise_motion_pkg.paths import PipelinePaths
from exercise_motion_pkg.youtube import (
    ExerciseEntry,
    PreparedVisionReview,
    PreparedReviewWindow,
    YouTubeCandidate,
    YouTubeRankingSettings,
    apply_source_quality_caps,
    apply_vision_score,
    build_candidate_vision_prompt,
    DeepSeekYouTubeQueryPlanner,
    build_youtube_queries,
    candidate_passes_vision_hard_gates,
    compose_final_score,
    discover_and_rank_youtube_candidates,
    extract_workout_plan_exercises,
    merge_youtube_queries,
    parse_deepseek_query_payload,
    parse_yt_dlp_search_results,
    prepare_vision_review,
    rank_candidates_with_prepared_vision_reviews,
    score_candidate_vision_payload,
    score_prepared_vision_review,
    score_candidate_metadata,
    semantic_gate_subprocess_timeout,
    semantic_gate_text_conflict_reasons,
    select_evenly_spaced_review_windows,
    vision_review_priority_score,
    build_youtube_download_options,
)


def make_candidate_execution(**overrides: object) -> CandidateExecution:
    payload: dict[str, object] = {
        "start_seconds": 0.0,
        "end_seconds": 1.0,
        "complete": True,
        "single_execution": True,
        "normal_speed": True,
        "not_broken_into_steps": True,
        "fixed_camera": True,
        "single_person": True,
        "fully_in_frame": True,
        "unobstructed": True,
        "extra_motion_before": False,
        "extra_motion_after": False,
        "partial_movement": False,
        "full_movement_coverage": 1.0,
        "start_posture_visible": True,
        "full_action_path_visible": True,
        "end_posture_visible": True,
        "target_exercise_match": 1.0,
        "wrong_exercise_or_unrelated_movement": False,
        "loop_quality": 0.8,
        "suggested_loop_start_seconds": None,
        "suggested_loop_end_seconds": None,
        "actual_demonstration": True,
        "title_or_instruction_screen": False,
        "screen_with_embedded_video": False,
        "contains_multiple_executions": False,
        "contains_idle_or_reset": False,
        "confidence": 0.8,
        "quality": 0.8,
        "reason": "",
        "source_window_index": None,
    }
    payload.update(overrides)
    return CandidateExecution(**payload)


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

    cleaned, stats = cleanup_motion_clip(clip, motion_threshold=0.03, padding_frames=1)

    assert stats.trimmed_start_frames == 1
    assert stats.trimmed_end_frames == 0
    assert cleaned.frame_count == 6
    assert min(frame.joints["left_ankle"][1] for frame in cleaned.frames) >= 0.0
    cleaned_pelvis_xs = [frame.joints["pelvis"][0] for frame in cleaned.frames]
    cleaned_root_span = max(cleaned_pelvis_xs) - min(cleaned_pelvis_xs)
    assert cleaned_root_span < raw_trimmed_root_span
    assert cleaned.metadata["cleanup"]["rootJoint"] == "pelvis"
    assert cleaned.metadata["cleanup"]["smoothingMethod"] == "one_euro_root_translation_xz"
    assert cleaned.metadata["cleanup"]["reviewStatus"] == "needs_manual_review"


def test_cleanup_motion_clip_preserves_slow_cumulative_motion_after_initial_move() -> None:
    frames = []
    pelvis_x = 0.0
    for index in range(24):
        if index == 1:
            pelvis_x += 0.02
        elif index > 1:
            pelvis_x += 0.004
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (pelvis_x, 1.0, 0.0),
                    "head": (pelvis_x, 1.7, 0.0),
                },
            )
        )
    clip = MotionClip(fps=30.0, joint_names=["pelvis", "head"], frames=frames)

    cleaned, stats = cleanup_motion_clip(clip, motion_threshold=0.015, padding_frames=1)

    assert cleaned.frame_count >= 22
    assert stats.trimmed_end_frames <= 2


def test_cleanup_motion_clip_preserves_relative_joint_offsets() -> None:
    clip = build_fixture_clip()

    cleaned, _ = cleanup_motion_clip(clip, motion_threshold=0.03, padding_frames=1)

    trimmed_source_frames = clip.frames[1:]
    for source_frame, cleaned_frame in zip(trimmed_source_frames, cleaned.frames):
        source_root = source_frame.joints["pelvis"]
        cleaned_root = cleaned_frame.joints["pelvis"]
        for joint_name in ("left_ankle", "right_ankle", "left_knee", "right_knee"):
            source_joint = source_frame.joints[joint_name]
            cleaned_joint = cleaned_frame.joints[joint_name]
            source_relative = tuple(source_joint[axis] - source_root[axis] for axis in range(3))
            cleaned_relative = tuple(cleaned_joint[axis] - cleaned_root[axis] for axis in range(3))
            assert cleaned_relative == pytest.approx(source_relative, abs=1e-6)


def test_cleanup_motion_clip_preserves_jump_travel_when_feet_leave_ground() -> None:
    clip = build_jump_fixture_clip()

    cleaned, stats = cleanup_motion_clip(clip, motion_threshold=0.01, padding_frames=0)

    trimmed_source_frames = clip.frames[stats.trimmed_start_frames : stats.trimmed_start_frames + cleaned.frame_count]
    for source_frame, cleaned_frame in zip(trimmed_source_frames, cleaned.frames):
        source_root = source_frame.joints["pelvis"]
        cleaned_root = cleaned_frame.joints["pelvis"]
        source_relative = tuple(
            source_frame.joints["left_ankle"][axis] - source_root[axis]
            for axis in range(3)
        )
        cleaned_relative = tuple(
            cleaned_frame.joints["left_ankle"][axis] - cleaned_root[axis]
            for axis in range(3)
        )
        assert cleaned_relative == pytest.approx(source_relative, abs=1e-6)


def test_stabilize_multi_contact_support_resets_anchor_after_airborne_phase() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "left_foot": (0.0, 0.0, 0.0),
                    "right_foot": (0.4, 0.4, 0.0),
                },
            ),
            MotionFrame(
                time_sec=1.0 / 30.0,
                joints={
                    "pelvis": (1.0, 1.0, 0.0),
                    "left_foot": (1.0, 0.4, 0.0),
                    "right_foot": (1.4, 0.4, 0.0),
                },
            ),
            MotionFrame(
                time_sec=2.0 / 30.0,
                joints={
                    "pelvis": (2.0, 1.0, 0.0),
                    "left_foot": (2.0, 0.0, 0.0),
                    "right_foot": (2.4, 0.4, 0.0),
                },
            ),
        ],
        source="unit-test",
    )
    contact_states = [
        {"state": "left_planted", "leftInContact": True, "rightInContact": False},
        {"state": "airborne", "leftInContact": False, "rightInContact": False},
        {"state": "left_planted", "leftInContact": True, "rightInContact": False},
    ]

    stabilized = stabilize_multi_contact_support(
        clip,
        contact_states=contact_states,
        support_ground_y=0.0,
    )

    assert stabilized.frames[0].joints["left_foot"] == (0.0, 0.0, 0.0)
    assert stabilized.frames[2].joints["left_foot"] == (2.0, 0.0, 0.0)
    assert stabilized.frames[2].joints["pelvis"] == (2.0, 1.0, 0.0)


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


def test_micro_movement_tolerance_for_joint_is_stronger_for_torso_than_feet() -> None:
    pelvis_tolerance = micro_movement_tolerance_for_joint("pelvis", default=0.015)
    foot_tolerance = micro_movement_tolerance_for_joint("left_foot", default=0.015)
    hand_tolerance = micro_movement_tolerance_for_joint("right_hand", default=0.015)

    assert pelvis_tolerance > foot_tolerance
    assert hand_tolerance > 0.015


def test_structural_refinement_preserves_root_vertical_motion_for_leg_dominant_transfer() -> None:
    frames: list[MotionFrame] = []
    for index in range(12):
        phase = index / 11.0
        pelvis_y = 1.0 - 0.18 * math.sin(math.pi * phase)
        leg_drive = 0.45 * math.sin(math.pi * phase)
        leg_swing = 0.35 * math.sin(2.0 * math.pi * phase)
        joints = {
            "pelvis": (0.0, pelvis_y, 0.0),
            "spine1": (0.0, pelvis_y + 0.22, 0.0),
            "spine2": (0.0, pelvis_y + 0.42, 0.0),
            "spine3": (0.0, pelvis_y + 0.62, 0.0),
            "neck": (0.0, pelvis_y + 0.78, 0.0),
            "head": (0.0, pelvis_y + 0.92, 0.0),
            "left_collar": (-0.08, pelvis_y + 0.72, 0.0),
            "right_collar": (0.08, pelvis_y + 0.72, 0.0),
            "left_shoulder": (-0.24, pelvis_y + 0.70, 0.0),
            "right_shoulder": (0.24, pelvis_y + 0.70, 0.0),
            "left_elbow": (-0.34, pelvis_y + 0.48, 0.0),
            "right_elbow": (0.34, pelvis_y + 0.48, 0.0),
            "left_wrist": (-0.38, pelvis_y + 0.25, 0.0),
            "right_wrist": (0.38, pelvis_y + 0.25, 0.0),
            "left_hand": (-0.40, pelvis_y + 0.18, 0.0),
            "right_hand": (0.40, pelvis_y + 0.18, 0.0),
            "left_hip": (-0.13, pelvis_y - 0.08, 0.0),
            "right_hip": (0.13, pelvis_y - 0.08, 0.0),
            "left_knee": (-0.16, pelvis_y - 0.52 + leg_drive, 0.08 + leg_swing),
            "right_knee": (0.16, pelvis_y - 0.52 + 0.25 * leg_drive, -0.08 - leg_swing),
            "left_ankle": (-0.18, pelvis_y - 0.92 + 0.20 * leg_drive, 0.12 + leg_swing * 1.4),
            "right_ankle": (0.18, pelvis_y - 0.92 + 0.70 * leg_drive, -0.12 - leg_swing * 1.4),
            "left_foot": (-0.18, pelvis_y - 1.00 + 0.12 * leg_drive, 0.28 + leg_swing * 1.4),
            "right_foot": (0.18, pelvis_y - 1.00 + 0.70 * leg_drive, -0.28 - leg_swing * 1.4),
        }
        frames.append(MotionFrame(time_sec=index / 30.0, joints=joints))
    clip = MotionClip(fps=30.0, joint_names=list(frames[0].joints), frames=frames)

    refined = refine_motion_clip_structurally(clip)
    metadata = refined.metadata["structuralRefinement"]

    assert metadata["strategy"] == "canonical_body_selected_motion_transfer"
    assert metadata["dominantProfile"]["dominantGroups"] == ["legs"]
    assert metadata["rootVerticalMotionPreservation"]["applied"] is True
    source_pelvis_y = [frame.joints["pelvis"][1] for frame in clip.frames]
    refined_pelvis_y = [frame.joints["pelvis"][1] for frame in refined.frames]
    assert max(refined_pelvis_y) - min(refined_pelvis_y) == pytest.approx(
        max(source_pelvis_y) - min(source_pelvis_y)
    )
    assert refined_pelvis_y == pytest.approx(source_pelvis_y)


def test_structural_refinement_keeps_slow_large_leg_articulation_when_arms_move_faster() -> None:
    frames: list[MotionFrame] = []
    for index in range(72):
        phase = index / 71.0
        slow_leg = 0.42 * math.sin(math.pi * phase)
        quick_arm = 0.05 * math.sin(10.0 * math.pi * phase)
        pelvis_y = 1.0 - 0.16 * math.sin(math.pi * phase)
        joints = {
            "pelvis": (0.0, pelvis_y, 0.0),
            "spine1": (0.0, pelvis_y + 0.22, 0.0),
            "spine2": (0.0, pelvis_y + 0.42, 0.0),
            "spine3": (0.0, pelvis_y + 0.62, 0.0),
            "neck": (0.0, pelvis_y + 0.78, 0.0),
            "head": (0.0, pelvis_y + 0.92, 0.0),
            "left_collar": (-0.08, pelvis_y + 0.72, 0.0),
            "right_collar": (0.08, pelvis_y + 0.72, 0.0),
            "left_shoulder": (-0.24, pelvis_y + 0.70, 0.0),
            "right_shoulder": (0.24, pelvis_y + 0.70, 0.0),
            "left_elbow": (-0.34, pelvis_y + 0.48 + quick_arm, 0.0),
            "right_elbow": (0.34, pelvis_y + 0.48 - quick_arm, 0.0),
            "left_wrist": (-0.38, pelvis_y + 0.25 + quick_arm, 0.0),
            "right_wrist": (0.38, pelvis_y + 0.25 - quick_arm, 0.0),
            "left_hand": (-0.40, pelvis_y + 0.18 + quick_arm, 0.0),
            "right_hand": (0.40, pelvis_y + 0.18 - quick_arm, 0.0),
            "left_hip": (-0.13, pelvis_y - 0.08, 0.0),
            "right_hip": (0.13, pelvis_y - 0.08, 0.0),
            "left_knee": (-0.16, pelvis_y - 0.52 + slow_leg, 0.08),
            "right_knee": (0.16, pelvis_y - 0.52 + slow_leg * 0.35, -0.08),
            "left_ankle": (-0.18, pelvis_y - 0.92 + slow_leg * 0.95, 0.12),
            "right_ankle": (0.18, pelvis_y - 0.92 + slow_leg * 0.75, -0.12),
            "left_foot": (-0.18, pelvis_y - 1.00 + slow_leg * 0.80, 0.28),
            "right_foot": (0.18, pelvis_y - 1.00 + slow_leg * 0.65, -0.28),
        }
        frames.append(MotionFrame(time_sec=index / 30.0, joints=joints))
    clip = MotionClip(fps=30.0, joint_names=list(frames[0].joints), frames=frames)

    refined = refine_motion_clip_structurally(clip)
    metadata = refined.metadata["structuralRefinement"]

    assert metadata["dominantProfile"]["motionDominantGroups"] == ["arms"]
    assert "legs" in metadata["dominantProfile"]["rangeDominantGroups"]
    assert "legs" in metadata["dominantProfile"]["dominantGroups"]
    source_left_ankle = [
        frame.joints["left_ankle"][1] - frame.joints["pelvis"][1]
        for frame in clip.frames
    ]
    refined_left_ankle = [
        frame.joints["left_ankle"][1] - frame.joints["pelvis"][1]
        for frame in refined.frames
    ]
    assert max(refined_left_ankle) - min(refined_left_ankle) > 0.75 * (
        max(source_left_ankle) - min(source_left_ankle)
    )


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

    cleaned, _ = cleanup_motion_clip(clip, motion_threshold=0.0, padding_frames=0)

    assert min(frame.joints["left_foot"][1] for frame in cleaned.frames) >= 0.0
    assert min(frame.joints["right_foot"][1] for frame in cleaned.frames) >= 0.0


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
    assert "\"defaultFixedRoot\": true" in text
    assert "\"defaultSceneInverted\": false" in text
    assert "\"defaultAutoWorldAlignment\":" in text
    assert "<button id=\"pauseToggle\" type=\"button\">Pause</button>" in text
    assert "const cameraTarget = new THREE.Vector3();" in text
    assert "overflow-y: auto;" in text
    assert "function estimateSceneOrigin(currentFixedRoot)" in text
    assert "function refreshCameraTarget()" in text
    assert "let playbackState = buildPlaybackState(payload.frames, currentLoop);" in text
    assert "const detectedLoops = Array.isArray(payload.detectedLoops) ? payload.detectedLoops : [];" in text
    assert "<select id=\"loopSelect\"></select>" in text
    assert "Root lock" in text
    assert "Lock root Y drift" in text
    assert "Lock planted feet" in text
    assert "Lock planted hands" in text
    assert "<input id=\"lockYRoot\" type=\"checkbox\" />" in text
    assert "<input id=\"lockPlantedFeet\" type=\"checkbox\" />" in text
    assert "<input id=\"lockPlantedHands\" type=\"checkbox\" />" in text
    assert "Ankle lock target offset" not in text
    assert "ankleOffsetForward" not in text
    assert "ankleOffsetLateral" not in text
    assert "ankleOffsetUp" not in text
    assert "Download baked Wear skeleton" in text
    assert "<input id=\"autoWorldAlignment\" type=\"checkbox\"" in text
    assert "<input id=\"sceneInverted\" type=\"checkbox\"" in text
    assert "function populateLoopSelect()" in text
    assert "function setSelectedLoop(nextIndex)" in text
    assert "function buildBakedWearSkeletonPayload()" in text
    assert "function downloadBakedWearSkeleton()" in text
    assert "lockYDrift" in text
    assert "function getFrameTranslation(frame)" in text
    assert "function getFrameBakeTranslation(frame, lockYDrift)" in text
    assert "function toRootAdjustedPoint(point, frameTranslation)" in text
    assert "function applySceneTransform(point)" in text
    assert "function getFrameTranslation(frame) {\n      if (lockPlantedHands" not in text
    assert "function getFrameBakeTranslation(frame, lockYDrift) {\n      if (lockPlantedHands" not in text
    assert "const targetPoint = applyAutoAlignment(anchor);" not in text
    assert "lockYRootInput.addEventListener(\"change\"" in text
    assert "lockPlantedFeetInput.addEventListener(\"change\"" in text
    assert "lockPlantedHandsInput.addEventListener(\"change\"" in text
    assert "const leftHipJoint = getFrameJointWorld(frame, frameTranslation, \"left_hip\");" in text
    assert "function computeFootLockCorrections()" in text
    assert "function computeLockedJointPositions(frame, frameTranslation)" in text
    assert "function solveLegIkChain(points, target)" in text
    assert "const lockedPosition = typeof jointName === \"string\" && lockedPositions.has(jointName)" in text
    assert "const verticalCorrection = lockedPosition" in text
    assert "sourceIndexA: frameSourceIndexForMotionTuning(startFrame)" in text
    assert "sourceIndexB: frameSourceIndexForMotionTuning(endFrame)" in text
    assert "function interpolateFrameSourceMapping(current, next, baseIndex, nextIndex, alpha)" in text
    assert "value.startsWith(\"bridge-\")" not in text
    assert "const upperLength = Math.max(root.distanceTo(originalKnee), 1e-6);" in text
    assert "const sourceBendDirection = sourceKneeOffset" in text
    assert "const maxReach = Math.max(upperLength + lowerLength - 1e-4, 1e-6);" in text
    assert "ankleLockTargetOffset" not in text
    assert "const loopTargets = []" in text
    assert "${lockYRoot}" in text
    assert "${lockPlantedFeet}" in text
    assert "${lockPlantedHands}" in text
    assert "let activeRootAnchor = null;" in text
    assert "function computeActiveRootAnchor(frames)" in text
    assert "activeRootAnchor = computeActiveRootAnchor(playbackState.boundsFrames);" in text
    assert "function getFrameRootPoint(frame, preferredRootJoint)" in text
    assert "function getCachedSceneBounds(currentFixedRoot)" in text
    assert "function invalidateSceneBoundsCache()" in text
    assert "function recalculateSceneBoundsAndFrame()" in text
    assert "boundsFrames: activeFrames" in text
    assert "function buildSceneBoundsCacheKey(currentFixedRoot)" in text
    assert "|${sceneInverted}|" in text
    assert "tempBoundsBox.setFromObject(object);" in text
    assert "transformedPoint.applyAxisAngle(axisX, Math.PI);" in text
    assert "type=\"module\"" in text
    assert "new THREE.WebGLRenderer" in text
    assert "new THREE.PerspectiveCamera" in text
    assert "new THREE.GridHelper" in text
    assert "new THREE.LineSegments(" in text
    assert "new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1))" in text
    assert "new THREE.DirectionalLight" in text
    assert "\"capsules\"" in text
    assert "drawTorsoFacingMarker(frame, frameTranslation);" not in text
    assert ".filter((capsule) => !isTorsoCapsule(capsule))" in text
    assert "function attachOutline(mesh, outlineMaterial)" in text
    assert "mesh.userData.outline = outline;" in text
    assert "function createStackedPrismGeometry(levels)" in text
    assert "const bevelWidth = halfWidth * 0.72;" in text
    assert "for (let side = 0; side < 8; side += 1)" in text
    assert "function createFacetedHeadGeometry()" in text
    assert "function limbProfileForCapsule(capsule, radius)" in text
    assert "const pelvisMesh = attachOutline(new THREE.Mesh(pelvisGeometry, torsoMaterial), torsoOutlineMaterial);" in text
    assert "const coreShellMesh = attachOutline(new THREE.Mesh(torsoSegmentGeometry.clone(), torsoMaterial), torsoOutlineMaterial);" in text
    assert "coreShellMesh.visible = false;" in text
    assert "const spineMeshes = [0, 1, 2].map(() => attachOutline(new THREE.Mesh(spineGeometry, torsoMaterial), torsoOutlineMaterial));" in text
    assert "function updateCamera()" in text
    assert "perspectiveCamera.lookAt(cameraTarget);" in text
    assert "function refreshMergedBoundsHelper()" in text
    assert "function getFrameFloorMotionPoint(frame)" in text
    assert "function refreshSceneBasis()" in text
    assert "sceneRotationQuaternion.identity();" in text
    assert "const floorPoint = getFrameFloorMotionPoint(frame);" not in text
    assert "const horizontalPadding = 0.08;" in text
    assert "mergedBoundsHelper.quaternion.copy(sceneRotationQuaternion);" in text or "grid.quaternion.copy(sceneRotationQuaternion);" in text
    assert "const bounds = getCachedSceneBounds(fixedRoot);" in text
    assert "function computeOrientedSceneBounds(currentFixedRoot)" in text
    assert "function getInterpolatedFrame()" in text
    assert "function updateSceneForFrame(frame)" in text
    assert "function setOrientedCylinder(mesh, start, end, radius, lateralAxis = null)" in text
    assert "function chooseRollStableQuaternion(previousQuaternion, xDir, yDir, zDir)" in text
    assert "function applyStableMeshOrientation(mesh, xDir, yDir, zDir)" in text
    assert "function setOrientedEllipsoid(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "function setOrientedCylinder(mesh, start, end, radius, lateralAxis = null)" in text
    assert "function setOrientedFrameVolume(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "function setOrientedBar(mesh, center, xAxis, yAxis, width, height, depth)" in text
    assert "const ribcageGeometry = createStackedPrismGeometry([" in text
    assert "const spineGeometry = createStackedPrismGeometry([" in text
    assert "const limbGeometry = createStackedPrismGeometry([" in text
    assert "const limbProfile = limbProfileForCapsule(node.capsule, radius);" in text
    assert "if (shoulderAxis && isArmCapsule(node.capsule))" in text
    assert "const abdomenWidth = Math.max(0.11, shoulderAxis.length() * 0.28);" in text
    assert "let coreShellVisible = false;" in text
    assert "const torsoCenter = hipCenter.clone().lerp(shoulderCenter, 0.54);" in text
    assert "const torsoHeight = Math.max(0.24, hipCenter.distanceTo(shoulderCenter));" in text
    assert "setOrientedFrameVolume(\n              coreShellMesh," in text
    assert "const spineSegments = [" in text
    assert "spineSegments.forEach((segment, index) => {" in text
    assert "new THREE.ExtrudeGeometry(new THREE.Shape(), { steps: 1, depth: 0.01, bevelEnabled: false })" in text
    assert "const jointNodeGeometry = new THREE.SphereGeometry(1, 7, 6);" in text
    assert "const skeletonSurfaces = skeletonChains.map((jointNames) => {" in text
    assert "const jointNodeMeshes = jointNodeNames.map((jointName) => {" in text
    assert "function buildProfileShape(width, depth)" in text
    assert "function chainProfileDimensions(jointNames)" in text
    assert "const headCenter = neckSourceJoint" in text
    assert "Math.max(0.115, Math.min(0.165, headJoint.distanceTo(neckSourceJoint) * 0.68))" in text
    assert "let paused = false;" in text
    assert "\"previewMaxRenderFps\": 30.0" in text
    assert "const previewMaxRenderFps = Math.max(12, Math.min(30, Number(payload.previewMaxRenderFps) || Number(payload.fps) || 30));" in text
    assert "let lastDrawTimestamp = null;" in text
    assert "let forceNextDraw = true;" in text
    assert "function requestPreviewRedraw()" in text
    assert "function applyUrlPreviewParameters()" in text
    assert "new URLSearchParams(window.location.search)" in text
    assert "selectCustomTimeRange(startSeconds, endSeconds);" in text
    assert "applyAutomationSettings(options);" in text
    assert "function parseUrlPreviewOption(value, type)" in text
    assert "applyUrlPreviewParameters();" in text
    assert "renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));" in text
    assert "const cursorAdvanced = !paused && playbackState.frames.length > 0;" in text
    assert "cursorAdvanced && timeSinceLastDraw >= previewMinRenderIntervalMs" in text
    assert "function ensureSmplMeshGeometry(meshPayload, vertexCount)" in text
    assert "smplMeshPositionAttribute.setUsage(THREE.DynamicDrawUsage);" in text
    assert "let cameraTouched = false;" in text
    assert "function refreshPauseLabel()" in text
    assert "function resetCameraOrbitFromBounds()" in text
    assert "const boundingRadius = Math.sqrt(width * width + height * height + depth * depth) * 0.5;" in text
    assert "const distance = getCameraFitDistance() * zoomScale * 1.28;" in text
    assert "yaw -= deltaX * 0.01;" in text
    assert "let playbackDirection = 1;" in text
    assert "<select id=\"cameraMode\">" not in text
    assert "<input id=\"pitch\" type=\"range\"" not in text
    assert "<input id=\"rotateX\" type=\"range\"" not in text
    assert "<input id=\"translateX\" type=\"range\"" not in text
    assert "World rotation:" not in text
    assert "World translation:" not in text
    assert "<button id=\"resetTransform\" type=\"button\">Reset world transform</button>" not in text
    assert "new THREE.OrthographicCamera" not in text
    assert "playbackDirection = -1;" not in text
    assert "deltaSeconds * payload.fps * speed" in text


def test_center_preview_clip_for_render_removes_camera_space_offset() -> None:
    clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "head", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (10.0, 1.0, 20.0),
                    "head": (10.0, 2.0, 20.0),
                    "left_foot": (9.8, 0.0, 20.0),
                    "right_foot": (10.2, 0.0, 20.0),
                },
            ),
            MotionFrame(
                time_sec=1.0 / 30.0,
                joints={
                    "pelvis": (10.5, 1.0, 20.4),
                    "head": (10.5, 2.0, 20.4),
                    "left_foot": (10.3, 0.0, 20.4),
                    "right_foot": (10.7, 0.0, 20.4),
                },
            ),
        ],
        metadata={"upstream": "wham"},
    )

    centered = _center_preview_clip_for_render(clip)
    translation_track = _build_preview_translation_track(centered.frames, "pelvis")
    rendered_points = []
    for index, frame in enumerate(centered.frames):
        translation = translation_track[index]
        rendered_points.extend(
            (
                point[0] - translation[0],
                point[1] - translation[1],
                point[2] - translation[2],
            )
            for point in frame.joints.values()
        )

    center = tuple(
        (min(point[axis] for point in rendered_points) + max(point[axis] for point in rendered_points)) * 0.5
        for axis in range(3)
    )
    assert center == pytest.approx((0.0, 0.0, 0.0))
    assert centered.metadata["previewCenterOffset"]["point"] == pytest.approx([10.0, 1.0, 20.0])


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


def test_compute_preview_auto_alignment_levels_tilted_support_plane() -> None:
    angle = math.radians(28.0)

    def tilt(point: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = point
        return (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
            z,
        )

    frames = [
        MotionFrame(
            time_sec=index / 30.0,
            joints={
                "pelvis": tilt((0.0, 1.0, 0.0)),
                "neck": tilt((0.0, 1.85, 0.0)),
                "head": tilt((0.0, 2.1, 0.0)),
                "left_shoulder": tilt((-0.28, 1.72, 0.0)),
                "right_shoulder": tilt((0.28, 1.72, 0.0)),
                "left_ankle": tilt((-0.12, 0.0, 0.0)),
                "right_ankle": tilt((0.12, 0.0, 0.0)),
                "left_foot": tilt((-0.16, 0.0, 0.08)),
                "right_foot": tilt((0.16, 0.0, 0.08)),
            },
        )
        for index in range(4)
    ]

    rotations = _compute_preview_auto_alignment(frames)

    aligned_left_foot = _apply_rotations_to_point(frames[0].joints["left_foot"], rotations)
    aligned_right_foot = _apply_rotations_to_point(frames[0].joints["right_foot"], rotations)
    aligned_left_ankle = _apply_rotations_to_point(frames[0].joints["left_ankle"], rotations)
    aligned_right_ankle = _apply_rotations_to_point(frames[0].joints["right_ankle"], rotations)
    support_y_values = (
        aligned_left_foot[1],
        aligned_right_foot[1],
        aligned_left_ankle[1],
        aligned_right_ankle[1],
    )

    assert max(support_y_values) - min(support_y_values) < 0.08


def test_compute_preview_auto_alignment_aligns_support_lateral_axis_to_scene_x() -> None:
    yaw = math.radians(42.0)

    def rotate_y(point: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = point
        return (
            x * math.cos(yaw) + z * math.sin(yaw),
            y,
            -x * math.sin(yaw) + z * math.cos(yaw),
        )

    frames = [
        MotionFrame(
            time_sec=index / 30.0,
            joints={
                "pelvis": rotate_y((0.0, 1.0, 0.0)),
                "neck": rotate_y((0.0, 1.9, 0.0)),
                "left_shoulder": rotate_y((-0.3, 1.72, 0.0)),
                "right_shoulder": rotate_y((0.3, 1.72, 0.0)),
                "left_ankle": rotate_y((-0.12, 0.0, 0.0)),
                "right_ankle": rotate_y((0.12, 0.0, 0.0)),
                "left_foot": rotate_y((-0.16, 0.0, 0.08)),
                "right_foot": rotate_y((0.16, 0.0, 0.08)),
            },
        )
        for index in range(6)
    ]

    rotations = _compute_preview_auto_alignment(frames)

    aligned_left = _apply_rotations_to_point(frames[0].joints["left_ankle"], rotations)
    aligned_right = _apply_rotations_to_point(frames[0].joints["right_ankle"], rotations)
    aligned_axis = (
        aligned_right[0] - aligned_left[0],
        aligned_right[1] - aligned_left[1],
        aligned_right[2] - aligned_left[2],
    )
    axis_length = math.sqrt(sum(component * component for component in aligned_axis))

    assert axis_length > 0.0
    assert aligned_axis[0] / axis_length > 0.98
    assert abs(aligned_axis[2] / axis_length) < 0.05


def test_compute_preview_auto_alignment_aligns_upright_spine_to_scene_y() -> None:
    frames = [
        MotionFrame(
            time_sec=index / 30.0,
            joints={
                "pelvis": (0.0, 1.0, 0.0),
                "neck": (0.04, 0.08, -0.03),
                "head": (0.05, -0.12, -0.04),
                "left_foot": (-0.18, 0.0, 0.08),
                "right_foot": (0.18, 0.0, 0.08),
                "left_hand": (-0.24, 1.1, -0.02),
                "right_hand": (0.24, 1.1, -0.02),
            },
        )
        for index in range(6)
    ]

    rotations = _compute_preview_auto_alignment(frames)
    aligned_pelvis = _apply_rotations_to_point(frames[0].joints["pelvis"], rotations)
    aligned_neck = _apply_rotations_to_point(frames[0].joints["neck"], rotations)
    aligned_spine = (
        aligned_neck[0] - aligned_pelvis[0],
        aligned_neck[1] - aligned_pelvis[1],
        aligned_neck[2] - aligned_pelvis[2],
    )
    spine_length = math.sqrt(sum(component * component for component in aligned_spine))

    assert spine_length > 0.0
    assert aligned_spine[1] / spine_length > 0.98


def test_compute_preview_auto_alignment_aligns_diagonal_dominant_motion_to_nearest_axis() -> None:
    frames = []
    for index in range(8):
        progress = index / 7.0
        hand = (0.22 + progress * 0.16, 1.12 + progress * 0.42, -0.08 + progress * 0.18)
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "neck": (0.0, 1.86, 0.0),
                    "head": (0.0, 2.08, 0.0),
                    "left_shoulder": (-0.28, 1.72, 0.0),
                    "right_shoulder": (0.28, 1.72, 0.0),
                    "left_ankle": (-0.12, 0.0, 0.0),
                    "right_ankle": (0.12, 0.0, 0.0),
                    "left_foot": (-0.16, 0.0, 0.08),
                    "right_foot": (0.16, 0.0, 0.08),
                    "left_hand": (-0.24, 1.1, -0.02),
                    "right_hand": hand,
                },
            )
        )

    rotations = _compute_preview_auto_alignment(frames)

    first_hand_relative = (
        frames[0].joints["right_hand"][0] - frames[0].joints["pelvis"][0],
        frames[0].joints["right_hand"][1] - frames[0].joints["pelvis"][1],
        frames[0].joints["right_hand"][2] - frames[0].joints["pelvis"][2],
    )
    last_hand_relative = (
        frames[-1].joints["right_hand"][0] - frames[-1].joints["pelvis"][0],
        frames[-1].joints["right_hand"][1] - frames[-1].joints["pelvis"][1],
        frames[-1].joints["right_hand"][2] - frames[-1].joints["pelvis"][2],
    )
    aligned_first_hand = _apply_rotations_to_point(first_hand_relative, rotations)
    aligned_last_hand = _apply_rotations_to_point(last_hand_relative, rotations)
    horizontal_delta = (
        aligned_last_hand[0] - aligned_first_hand[0],
        aligned_last_hand[2] - aligned_first_hand[2],
    )
    horizontal_length = math.hypot(horizontal_delta[0], horizontal_delta[1])
    vertical_delta = aligned_last_hand[1] - aligned_first_hand[1]
    aligned_pelvis = _apply_rotations_to_point(frames[0].joints["pelvis"], rotations)
    aligned_neck = _apply_rotations_to_point(frames[0].joints["neck"], rotations)
    aligned_spine = (
        aligned_neck[0] - aligned_pelvis[0],
        aligned_neck[1] - aligned_pelvis[1],
        aligned_neck[2] - aligned_pelvis[2],
    )
    spine_length = math.sqrt(sum(component * component for component in aligned_spine))

    assert abs(vertical_delta) > 0.0
    assert abs(vertical_delta) > horizontal_length
    assert spine_length > 0.0
    assert aligned_spine[1] / spine_length > 0.98


def test_compute_preview_auto_alignment_does_not_tilt_body_to_fix_misleading_support_plane() -> None:
    frames = []
    for index in range(8):
        progress = index / 7.0
        hand_y = 1.05 + progress * 0.38
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "neck": (0.0, 1.86, 0.0),
                    "head": (0.0, 2.08, 0.0),
                    "left_shoulder": (-0.28, 1.72, 0.0),
                    "right_shoulder": (0.28, 1.72, 0.0),
                    "left_hip": (-0.16, 0.92, 0.0),
                    "right_hip": (0.16, 0.92, 0.0),
                    "left_ankle": (-0.35, 0.08, -0.30),
                    "right_ankle": (0.35, -0.18, 0.30),
                    "left_foot": (-0.40, 0.10, -0.34),
                    "right_foot": (0.40, -0.20, 0.34),
                    "left_wrist": (-0.24, hand_y, -0.02),
                    "right_wrist": (0.24, hand_y, -0.02),
                    "left_hand": (-0.24, hand_y - 0.03, -0.02),
                    "right_hand": (0.24, hand_y - 0.03, -0.02),
                },
            )
        )

    rotations = _compute_preview_auto_alignment(frames)

    aligned_pelvis = _apply_rotations_to_point(frames[0].joints["pelvis"], rotations)
    aligned_neck = _apply_rotations_to_point(frames[0].joints["neck"], rotations)
    aligned_spine = (
        aligned_neck[0] - aligned_pelvis[0],
        aligned_neck[1] - aligned_pelvis[1],
        aligned_neck[2] - aligned_pelvis[2],
    )
    spine_length = math.sqrt(sum(component * component for component in aligned_spine))
    aligned_first_hand = _apply_rotations_to_point(frames[0].joints["right_hand"], rotations)
    aligned_last_hand = _apply_rotations_to_point(frames[-1].joints["right_hand"], rotations)
    hand_delta = (
        aligned_last_hand[0] - aligned_first_hand[0],
        aligned_last_hand[1] - aligned_first_hand[1],
        aligned_last_hand[2] - aligned_first_hand[2],
    )
    hand_delta_length = math.sqrt(sum(component * component for component in hand_delta))

    assert spine_length > 0.0
    assert aligned_spine[1] / spine_length > 0.98
    assert hand_delta_length > 0.0
    assert abs(hand_delta[1]) / hand_delta_length > 0.95


def test_preview_default_scene_inversion_detects_upside_down_auto_alignment() -> None:
    rotations = [((1.0, 0.0, 0.0), math.pi)]
    frames = [
        MotionFrame(
            time_sec=index / 30.0,
            joints={
                "pelvis": (0.0, 1.0, 0.0),
                "neck": (0.0, 1.8, 0.0),
                "head": (0.0, 2.0, 0.0),
            },
        )
        for index in range(4)
    ]

    assert _aligned_body_points_down(frames, rotations) is True
    assert _aligned_body_points_down(frames, []) is False


def test_compute_preview_auto_alignment_yaws_horizontal_dominant_motion_to_nearest_axis() -> None:
    frames = []
    for index in range(8):
        progress = index / 7.0
        hand = (0.22 + progress * 0.42, 1.12, -0.08 + progress * 0.42)
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (0.0, 1.0, 0.0),
                    "neck": (0.0, 1.86, 0.0),
                    "head": (0.0, 2.08, 0.0),
                    "left_shoulder": (-0.28, 1.72, 0.0),
                    "right_shoulder": (0.28, 1.72, 0.0),
                    "left_ankle": (-0.12, 0.0, 0.0),
                    "right_ankle": (0.12, 0.0, 0.0),
                    "left_foot": (-0.16, 0.0, 0.08),
                    "right_foot": (0.16, 0.0, 0.08),
                    "left_hand": (-0.24, 1.1, -0.02),
                    "right_hand": hand,
                },
            )
        )

    rotations = _compute_preview_auto_alignment(frames)

    first_hand_relative = (
        frames[0].joints["right_hand"][0] - frames[0].joints["pelvis"][0],
        frames[0].joints["right_hand"][1] - frames[0].joints["pelvis"][1],
        frames[0].joints["right_hand"][2] - frames[0].joints["pelvis"][2],
    )
    last_hand_relative = (
        frames[-1].joints["right_hand"][0] - frames[-1].joints["pelvis"][0],
        frames[-1].joints["right_hand"][1] - frames[-1].joints["pelvis"][1],
        frames[-1].joints["right_hand"][2] - frames[-1].joints["pelvis"][2],
    )
    aligned_first_hand = _apply_rotations_to_point(first_hand_relative, rotations)
    aligned_last_hand = _apply_rotations_to_point(last_hand_relative, rotations)
    horizontal_delta = (
        aligned_last_hand[0] - aligned_first_hand[0],
        aligned_last_hand[2] - aligned_first_hand[2],
    )
    horizontal_length = math.hypot(horizontal_delta[0], horizontal_delta[1])
    aligned_pelvis = _apply_rotations_to_point(frames[0].joints["pelvis"], rotations)
    aligned_neck = _apply_rotations_to_point(frames[0].joints["neck"], rotations)
    aligned_spine = (
        aligned_neck[0] - aligned_pelvis[0],
        aligned_neck[1] - aligned_pelvis[1],
        aligned_neck[2] - aligned_pelvis[2],
    )
    spine_length = math.sqrt(sum(component * component for component in aligned_spine))

    assert horizontal_length > 0.0
    assert abs(horizontal_delta[0]) / horizontal_length > 0.98
    assert abs(horizontal_delta[1]) / horizontal_length < 0.05
    assert spine_length > 0.0
    assert aligned_spine[1] / spine_length > 0.98


def test_compute_preview_auto_alignment_prefers_coherent_arm_motion_over_root_drift() -> None:
    frames = []
    for index in range(10):
        progress = index / 9.0
        root_drift = progress * 0.62
        arm_press = progress * 0.38
        pelvis = (root_drift, 1.0, root_drift * 0.18)
        hand = (pelvis[0] + 0.18 + arm_press, 1.12, pelvis[2] - 0.08 + arm_press)
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": pelvis,
                    "neck": (pelvis[0], 1.86, pelvis[2]),
                    "head": (pelvis[0], 2.08, pelvis[2]),
                    "left_shoulder": (pelvis[0] - 0.28, 1.72, pelvis[2]),
                    "right_shoulder": (pelvis[0] + 0.28, 1.72, pelvis[2]),
                    "left_ankle": (pelvis[0] - 0.12, 0.0, pelvis[2]),
                    "right_ankle": (pelvis[0] + 0.12, 0.0, pelvis[2]),
                    "left_foot": (pelvis[0] - 0.16, 0.0, pelvis[2] + 0.08),
                    "right_foot": (pelvis[0] + 0.16, 0.0, pelvis[2] + 0.08),
                    "left_hand": (pelvis[0] - 0.24, 1.1, pelvis[2] - 0.02),
                    "right_hand": hand,
                },
            )
        )

    rotations = _compute_preview_auto_alignment(frames)

    first_hand_relative = (
        frames[0].joints["right_hand"][0] - frames[0].joints["pelvis"][0],
        frames[0].joints["right_hand"][1] - frames[0].joints["pelvis"][1],
        frames[0].joints["right_hand"][2] - frames[0].joints["pelvis"][2],
    )
    last_hand_relative = (
        frames[-1].joints["right_hand"][0] - frames[-1].joints["pelvis"][0],
        frames[-1].joints["right_hand"][1] - frames[-1].joints["pelvis"][1],
        frames[-1].joints["right_hand"][2] - frames[-1].joints["pelvis"][2],
    )
    aligned_first_hand = _apply_rotations_to_point(first_hand_relative, rotations)
    aligned_last_hand = _apply_rotations_to_point(last_hand_relative, rotations)
    horizontal_delta = (
        aligned_last_hand[0] - aligned_first_hand[0],
        aligned_last_hand[2] - aligned_first_hand[2],
    )
    horizontal_length = math.hypot(horizontal_delta[0], horizontal_delta[1])

    assert horizontal_length > 0.0
    assert max(abs(horizontal_delta[0]), abs(horizontal_delta[1])) / horizontal_length > 0.98
    assert min(abs(horizontal_delta[0]), abs(horizontal_delta[1])) / horizontal_length < 0.05


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


def test_write_preview_html_marks_motion_tuning_disabled_as_raw_passthrough(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    clip = MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=clip.frames,
        source=clip.source,
        metadata={"upstream": "wham", "motionTuning": {"enabled": False}},
    )
    output = tmp_path / "preview-raw-wham.html"

    write_preview_html(output, clip, title="raw-wham")

    text = output.read_text(encoding="utf-8")
    assert "\"motionTuningEnabled\": false" in text
    assert "\"rawWhamPassthrough\": true" in text


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


def test_write_preview_html_does_not_embed_smpl_mesh_payload(tmp_path: Path) -> None:
    clip = build_fixture_clip()
    output = tmp_path / "preview-smpl.html"

    write_preview_html(output, clip, title="smpl-preview")

    text = output.read_text(encoding="utf-8")
    assert '"smplMesh":' not in text
    assert "Show WHAM SMPL mesh" in text
    assert "updateSmplMeshForFrame" in text


def test_baked_wham_smpl_preview_applies_cleanup_delta_and_exports_loop_metadata() -> None:
    raw_clip = MotionClip(
        fps=30.0,
        joint_names=["pelvis", "left_foot", "right_foot"],
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (1.0, 1.0, 1.0),
                    "left_foot": (0.9, 0.0, 1.0),
                    "right_foot": (1.1, 0.0, 1.0),
                },
            )
        ],
        metadata={"upstream": "wham"},
    )
    cleaned_clip = MotionClip(
        fps=30.0,
        joint_names=raw_clip.joint_names,
        frames=[
            MotionFrame(
                time_sec=0.0,
                joints={
                    "pelvis": (1.25, 1.2, 0.75),
                    "left_foot": (1.15, 0.2, 0.75),
                    "right_foot": (1.35, 0.2, 0.75),
                },
            )
        ],
        metadata={
            "upstream": "wham",
            "cleanup": {
                "trimmedStartFrames": 0,
                "trimmedEndFrames": 0,
            },
        },
    )
    sequence = WhamSmplMeshSequence(
        fps=30.0,
        subject_id="0",
        coordinate_space="camera",
        frame_ids=[0],
        faces=[[0, 1, 2]],
        vertices=[
            [
                (1.0, 1.0, 1.0),
                (1.1, 1.0, 1.0),
                (1.0, 1.1, 1.0),
            ]
        ],
    )

    payload = build_baked_wham_smpl_preview_payload(
        sequence=sequence,
        raw_clip=raw_clip,
        cleaned_clip=cleaned_clip,
        title="smpl-preview",
        selected_loop_index=-1,
    )

    assert payload["kind"] == "whamBakedSmplMeshPreview"
    assert payload["bodyModel"] == "smpl"
    assert payload["faces"] == [[0, 1, 2]]
    assert payload["loop"]["enabled"] is False
    assert "cleanup_global_translation_delta" in payload["bakedPreviewConfiguration"]["postProcessingApplied"]
    first_frame = payload["frames"][0]
    assert first_frame["cleanupDeltaApplied"] == pytest.approx([0.25, 0.2, -0.25])


def test_wham_smpl_loader_applies_legacy_compat_before_smplx_import() -> None:
    text = Path("exercise_motion_pkg/wham_smpl_preview.py").read_text(encoding="utf-8")
    function_start = text.index("def load_wham_smpl_mesh_sequence")
    compat_call = text.index("ensure_legacy_smpl_runtime_compat()", function_start)
    smplx_import = text.index("import smplx", function_start)

    assert compat_call < smplx_import


def test_wear_skeleton_payload_bakes_preview_alignment_root_lock_and_centering() -> None:
    clip = build_fixture_clip()

    payload = build_wear_skeleton_payload(clip, title="squat-wear")

    assert payload["kind"] == "wearPreviewSkeleton"
    assert payload["title"] == "squat-wear"
    assert payload["bakedPreviewConfiguration"] == {
        "autoWorldAlignment": True,
        "lockGlobalRootDrift": True,
        "lockYDrift": False,
        "invertScene": False,
        "selectedLoopIndex": -1,
        "rawWhamPassthrough": False,
    }
    assert payload["frameCount"] == clip.frame_count
    assert payload["loop"]["enabled"] is False
    assert payload["bounds"]["center"] == pytest.approx([0.0, 0.0, 0.0])
    assert "skeletonChains" in payload["topology"]
    assert "capsules" in payload["topology"]
    assert payload["geometry"]["style"] == "low_poly_block_humanoid"

    pelvis_points = [
        frame["joints"]["pelvis"]
        for frame in payload["frames"]
    ]
    assert max(point[0] for point in pelvis_points) - min(point[0] for point in pelvis_points) < 1e-9
    assert max(point[2] for point in pelvis_points) - min(point[2] for point in pelvis_points) < 1e-9


def test_write_wear_skeleton_json_exports_baked_preview_payload(tmp_path: Path) -> None:
    output = tmp_path / "wear" / "skeleton.preview.json"

    write_wear_skeleton_json(output, build_fixture_clip(), title="wear-preview")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["title"] == "wear-preview"
    assert payload["bakedPreviewConfiguration"]["autoWorldAlignment"] is True
    assert payload["bakedPreviewConfiguration"]["lockGlobalRootDrift"] is True
    assert payload["bakedPreviewConfiguration"]["lockYDrift"] is False
    assert payload["bakedPreviewConfiguration"]["invertScene"] is False
    assert len(payload["frames"]) == payload["frameCount"]


def test_wear_skeleton_payload_can_bake_selected_loop_and_y_drift_lock() -> None:
    clip = build_loop_fixture_clip()

    payload = build_wear_skeleton_payload(
        clip,
        title="looped-wear",
        selected_loop_index=0,
        lock_y_drift=True,
    )

    assert payload["bakedPreviewConfiguration"]["selectedLoopIndex"] == 0
    assert payload["bakedPreviewConfiguration"]["lockYDrift"] is True
    assert payload["loop"]["enabled"] is True
    assert payload["source"]["activeStartFrame"] == payload["loop"]["sourceStartFrame"]
    assert payload["source"]["activeEndFrame"] == payload["loop"]["sourceEndFrame"]

    pelvis_y_values = [
        frame["joints"]["pelvis"][1]
        for frame in payload["frames"]
    ]
    assert max(pelvis_y_values) - min(pelvis_y_values) < 1e-9


def test_build_preview_translation_track_uses_root_joint_instead_of_joint_median() -> None:
    frames = [
        MotionFrame(
            time_sec=0.0,
            joints={
                "pelvis": (0.0, 1.0, 0.0),
                "head": (0.0, 2.0, 0.0),
                "left_hand": (-0.5, 1.5, 0.0),
                "right_hand": (0.5, 1.5, 0.0),
            },
        ),
        MotionFrame(
            time_sec=1 / 30.0,
            joints={
                "pelvis": (0.1, 1.4, 0.0),
                "head": (0.1, 2.4, 0.0),
                "left_hand": (2.5, 1.9, 0.0),
                "right_hand": (3.5, 1.9, 0.0),
            },
        ),
    ]

    track = _build_preview_translation_track(frames, "pelvis")

    assert track[0] == pytest.approx((0.0, 0.0, 0.0))
    assert track[1] == pytest.approx((0.1, 0.0, 0.0))


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
            motion_threshold=0.03,
            padding_frames=1,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["previewHtmlPath"]).exists()
    assert Path(manifest["wearSkeletonJsonPath"]).exists()
    assert Path(manifest["cleanedMotionJsonPath"]).exists()
    assert Path(manifest["groundMetadataPath"]).exists()
    assert Path(manifest["targetRigContractPath"]).exists()
    assert manifest["retargetSourcePath"] is None
    assert manifest["whamRetargetSourcePath"] is None
    assert manifest["whamSmplPreviewJsonPath"] is None
    assert manifest["whamResultsPkl"] is None
    assert manifest["whamCacheStatus"] == "not_used_normalized_motion"
    assert manifest["groundMetadata"]["renderGroundPlane"]["space"] == "motion"
    assert manifest["groundMetadata"]["renderGroundOrigin"]["space"] == "motion"
    assert manifest["postProcessing"]["steps"] == [
        "ground_plane_fitting",
        "root_translation_one_euro_xz",
        "structural_ik_refinement",
    ]
    assert manifest["nextStage"]["status"] == "wear_preview_skeleton_ready"
    assert Path(manifest["nextStage"]["wearSkeletonJsonPath"]).exists()
    assert manifest["nextStage"]["retargetSourcePath"] is None
    assert manifest["nextStage"]["whamRetargetSourcePath"] is None
    assert manifest["nextStage"]["whamSmplPreviewJsonPath"] is None

    cleaned_clip = load_motion_json(result.cleaned_motion_json_path)
    assert cleaned_clip.metadata["ground"]["renderGroundPlane"]["space"] == "motion"
    assert cleaned_clip.metadata["ground"]["renderGroundOrigin"]["space"] == "motion"
    assert cleaned_clip.metadata["cleanup"]["appliedPostProcessingSteps"] == [
        "ground_plane_fitting",
        "root_translation_one_euro_xz",
        "support_contact_detection",
    ]

    preview_html = result.preview_html_path.read_text(encoding="utf-8")
    assert "\"renderGroundPlane\"" in preview_html
    assert "\"renderGroundOrigin\"" in preview_html


def test_resolve_wham_results_source_reuses_default_cache(tmp_path: Path) -> None:
    input_video = tmp_path / "input" / "selected_segment.mp4"
    input_video.parent.mkdir(parents=True)
    input_video.write_bytes(b"video")
    wham_output_dir = tmp_path / "raw" / "wham"
    cached_pkl = wham_output_dir / "selected_segment" / "wham_output.pkl"
    cached_pkl.parent.mkdir(parents=True)
    cached_pkl.write_bytes(b"pkl")

    source = pipeline.resolve_wham_results_source(
        explicit_results_pkl=None,
        wham_output_dir=wham_output_dir,
        input_video_path=input_video,
        reuse_wham_cache=True,
    )

    assert source.path == cached_pkl
    assert source.cache_status == "reused"
    assert source.should_run_wham is False


def test_resolve_wham_results_source_can_force_regeneration(tmp_path: Path) -> None:
    input_video = tmp_path / "input" / "selected_segment.mp4"
    input_video.parent.mkdir(parents=True)
    input_video.write_bytes(b"video")
    wham_output_dir = tmp_path / "raw" / "wham"
    cached_pkl = wham_output_dir / "selected_segment" / "wham_output.pkl"
    cached_pkl.parent.mkdir(parents=True)
    cached_pkl.write_bytes(b"pkl")

    source = pipeline.resolve_wham_results_source(
        explicit_results_pkl=None,
        wham_output_dir=wham_output_dir,
        input_video_path=input_video,
        reuse_wham_cache=False,
    )

    assert source.path == cached_pkl
    assert source.cache_status == "generated"
    assert source.should_run_wham is True


def test_resolve_wham_results_source_prefers_explicit_pkl(tmp_path: Path) -> None:
    input_video = tmp_path / "input" / "selected_segment.mp4"
    input_video.parent.mkdir(parents=True)
    input_video.write_bytes(b"video")
    explicit_pkl = tmp_path / "external" / "wham_output.pkl"
    explicit_pkl.parent.mkdir(parents=True)
    explicit_pkl.write_bytes(b"pkl")

    source = pipeline.resolve_wham_results_source(
        explicit_results_pkl=explicit_pkl,
        wham_output_dir=tmp_path / "raw" / "wham",
        input_video_path=input_video,
        reuse_wham_cache=False,
    )

    assert source.path == explicit_pkl.resolve()
    assert source.cache_status == "explicit"
    assert source.should_run_wham is False


def test_prepare_input_video_trims_source_segment_for_generate_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    paths = PipelinePaths.create(tmp_path / "workspace", "squat")
    captured: dict[str, float | str] = {}

    def fake_sanitize(path: Path) -> Path:
        captured["sanitized_input"] = str(path)
        return path

    def fake_trim_video(
        *,
        source_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        captured["trim_source"] = str(source_path)
        captured["trim_output"] = str(output_path)
        captured["trim_start"] = start_seconds
        captured["trim_end"] = end_seconds
        output_path.write_bytes(b"trimmed")
        return output_path

    monkeypatch.setattr("exercise_motion_pkg.pipeline.sanitize_video_for_processing", fake_sanitize)
    monkeypatch.setattr("exercise_motion_pkg.pipeline.trim_video", fake_trim_video)

    output = pipeline.prepare_input_video(
        GenerateRequest(
            exercise_slug="squat",
            workspace=tmp_path / "workspace",
            video_path=source,
            source_start_seconds=1.5,
            source_end_seconds=4.0,
        ),
        paths,
    )

    assert output == paths.input_dir / "selected_segment.mp4"
    assert captured["trim_source"] == str(paths.input_dir / source.name)
    assert captured["trim_output"] == str(output)
    assert captured["trim_start"] == pytest.approx(1.5)
    assert captured["trim_end"] == pytest.approx(4.0)


def test_prepare_input_video_rejects_invalid_segment_bounds(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    with pytest.raises(ValueError, match="greater than"):
        pipeline.prepare_input_video(
            GenerateRequest(
                exercise_slug="squat",
                workspace=tmp_path / "workspace",
                video_path=source,
                source_start_seconds=3.0,
                source_end_seconds=2.0,
            ),
            PipelinePaths.create(tmp_path / "workspace", "squat-invalid"),
        )


def test_prepare_input_video_trims_youtube_downloaded_source_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PipelinePaths.create(tmp_path / "workspace", "squat")
    downloaded = paths.input_dir / "source.mp4"
    downloaded.write_bytes(b"video")

    captured: dict[str, float | str] = {}

    def fake_download_youtube(url: str, output_dir: Path, cookies_path: Path | None = None) -> Path:
        captured["downloaded_from"] = url
        captured["download_output_dir"] = str(output_dir)
        captured["cookies_path"] = str(cookies_path) if cookies_path is not None else ""
        return downloaded

    def fake_trim_video(
        *,
        source_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        captured["trim_source"] = str(source_path)
        captured["trim_output"] = str(output_path)
        captured["trim_start"] = start_seconds
        captured["trim_end"] = end_seconds
        output_path.write_bytes(b"trimmed")
        return output_path

    monkeypatch.setattr("exercise_motion_pkg.pipeline.download_youtube", fake_download_youtube)
    monkeypatch.setattr("exercise_motion_pkg.pipeline.trim_video", fake_trim_video)

    output = pipeline.prepare_input_video(
        GenerateRequest(
            exercise_slug="squat",
            workspace=tmp_path / "workspace",
            youtube_url="https://www.youtube.com/watch?v=SCVCLChPQFY",
            source_start_seconds=1.0,
            source_end_seconds=5.0,
        ),
        paths,
    )

    assert output == paths.input_dir / "selected_segment.mp4"
    assert captured["downloaded_from"] == "https://www.youtube.com/watch?v=SCVCLChPQFY"
    assert captured["download_output_dir"] == str(paths.input_dir)
    assert captured["cookies_path"] == ""
    assert captured["trim_source"] == str(downloaded)
    assert captured["trim_output"] == str(output)
    assert captured["trim_start"] == pytest.approx(1.0)
    assert captured["trim_end"] == pytest.approx(5.0)


def test_prepare_input_video_passes_youtube_cookies_to_downloader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PipelinePaths.create(tmp_path / "workspace", "squat")
    downloaded = paths.input_dir / "source.mp4"
    downloaded.write_bytes(b"video")
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("NetscapeCookie", encoding="utf-8")

    captured: dict[str, str] = {}

    def fake_download_youtube(url: str, output_dir: Path, cookies_path: Path | None = None) -> Path:
        captured["downloaded_from"] = url
        captured["download_output_dir"] = str(output_dir)
        captured["cookies_path"] = str(cookies_path) if cookies_path is not None else ""
        return downloaded

    def fake_trim_video(
        *,
        source_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        output_path.write_bytes(b"trimmed")
        return output_path

    monkeypatch.setattr("exercise_motion_pkg.pipeline.download_youtube", fake_download_youtube)
    monkeypatch.setattr("exercise_motion_pkg.pipeline.trim_video", fake_trim_video)

    output = pipeline.prepare_input_video(
        GenerateRequest(
            exercise_slug="squat",
            workspace=tmp_path / "workspace",
            youtube_url="https://www.youtube.com/watch?v=SCVCLChPQFY",
            source_start_seconds=1.0,
            source_end_seconds=5.0,
            youtube_cookies=cookies_path,
        ),
        paths,
    )

    assert output == paths.input_dir / "selected_segment.mp4"
    assert captured["downloaded_from"] == "https://www.youtube.com/watch?v=SCVCLChPQFY"
    assert captured["download_output_dir"] == str(paths.input_dir)
    assert captured["cookies_path"] == str(cookies_path.resolve())


def test_build_youtube_download_options_supports_cookies_path(tmp_path: Path) -> None:
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("NetscapeCookie", encoding="utf-8")

    options = build_youtube_download_options(
        outtmpl=str(tmp_path / "source.%(ext)s"),
        quiet=True,
        noprogress=True,
        retries=2,
        preview=True,
        cookies_path=cookies_path,
    )

    assert options["cookiefile"] == str(cookies_path)


def test_download_youtube_preview_passes_cookies_to_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("NetscapeCookie", encoding="utf-8")
    captured: dict[str, list[str]] = {}
    downloaded = tmp_path / "candidate.mp4"

    def fake_run(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        downloaded.write_bytes(b"video")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("exercise_motion_pkg.youtube.sanitize_downloaded_video", lambda path: path)

    from exercise_motion_pkg.youtube import download_youtube_preview

    result = download_youtube_preview("https://www.youtube.com/watch?v=test", tmp_path, cookies_path)

    assert result == downloaded
    assert captured["command"][captured["command"].index("--cookies") + 1] == str(cookies_path.resolve())


def test_build_youtube_download_options_prefers_low_resolution_video_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("exercise_motion_pkg.youtube.shutil.which", lambda _: "ffmpeg")

    options = build_youtube_download_options(
        outtmpl=str(tmp_path / "source.%(ext)s"),
        quiet=True,
        noprogress=True,
        retries=2,
        preview=False,
    )

    format_selector = options["format"]
    assert "bestvideo[height<=360]" in format_selector
    assert "bestvideo[height<=480]" in format_selector
    assert "bestaudio" not in format_selector
    assert "acodec" not in format_selector


def test_sanitize_downloaded_video_strips_audio_when_copying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    captured: dict[str, list[str]] = {}

    def fake_run_ffmpeg(args: list[str]) -> tuple[int, str]:
        captured["args"] = args
        return 0, ""

    def fake_finalize(temp_path: Path, final_path: Path, fallback_path: Path) -> Path:
        return final_path

    monkeypatch.setattr("exercise_motion_pkg.youtube.shutil.which", lambda _: "ffmpeg")
    monkeypatch.setattr("exercise_motion_pkg.youtube._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("exercise_motion_pkg.youtube._finalize_sanitized_video", fake_finalize)

    from exercise_motion_pkg.youtube import sanitize_downloaded_video

    result = sanitize_downloaded_video(source)

    args = captured["args"]
    assert result == tmp_path / "source_sanitized.mp4"
    assert "-an" in args
    assert "-c:v" in args
    assert "-c:a" not in args


def test_sanitize_downloaded_video_strips_audio_when_reencoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run_ffmpeg(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if len(calls) == 1:
            return 0, "Missing reference picture"
        return 0, ""

    def fake_finalize(temp_path: Path, final_path: Path, fallback_path: Path) -> Path:
        return final_path

    monkeypatch.setattr("exercise_motion_pkg.youtube.shutil.which", lambda _: "ffmpeg")
    monkeypatch.setattr("exercise_motion_pkg.youtube._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("exercise_motion_pkg.youtube._finalize_sanitized_video", fake_finalize)

    from exercise_motion_pkg.youtube import sanitize_downloaded_video

    result = sanitize_downloaded_video(source)

    reencode_args = calls[1]
    assert result == tmp_path / "source_sanitized.mp4"
    assert "-an" in reencode_args
    assert "-c:a" not in reencode_args


def test_download_youtube_preview_uses_low_resolution_video_only_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        encoding: str,
        errors: str,
        timeout: int,
    ) -> object:
        captured["command"] = command
        (tmp_path / "candidate.mp4").write_bytes(b"video")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("exercise_motion_pkg.youtube.subprocess.run", fake_run)
    monkeypatch.setattr("exercise_motion_pkg.youtube.sanitize_downloaded_video", lambda path: path)

    from exercise_motion_pkg.youtube import download_youtube_preview

    result = download_youtube_preview("https://www.youtube.com/watch?v=test", tmp_path)

    command = captured["command"]
    format_selector = command[command.index("--format") + 1]
    assert result == tmp_path / "candidate.mp4"
    assert "bestvideo[height<=360]" in format_selector
    assert "bestvideo[height<=480]" in format_selector
    assert "bestaudio" not in format_selector
    assert "acodec" not in format_selector


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
            motion_threshold=0.03,
            padding_frames=1,
        )
    )

    assert result.copied_input_video_path == source_video
    assert result.manifest_path.exists()


def test_build_wham_command_uses_local_paths() -> None:
    command = build_wham_command(
        wham_repo_path=Path("C:/WHAM"),
        input_video=Path("C:/videos/burpee.mp4"),
        output_root=Path("C:/out"),
        python_command="python",
        estimate_local_only=True,
        run_smplify=True,
    )

    assert command[:2] == ["python", "demo.py"]
    assert "C:\\videos\\burpee.mp4" in command
    assert "--output_pth" in command
    assert "C:\\out" in command
    assert "--estimate_local_only" in command
    assert "--run_smplify" in command


def test_build_wham_command_uses_docker_mounts() -> None:
    command = build_wham_command(
        wham_repo_path=Path("C:/WHAM"),
        input_video=Path("C:/videos/burpee.mp4"),
        output_root=Path("C:/out"),
        python_command="python",
        estimate_local_only=True,
        run_smplify=True,
        use_docker=True,
        docker_image="wham:test",
        docker_gpus="all",
        docker_shm_size="8g",
    )

    assert command[:2] == ["docker", "run"]
    assert "--gpus" in command
    assert "--shm-size" in command
    assert "wham:test" in command
    assert "/input/burpee.mp4" in command
    assert "--estimate_local_only" in command
    assert "--run_smplify" in command


def test_run_wham_locally_defaults_to_smplify() -> None:
    assert run_wham_locally.__kwdefaults__ is not None
    assert run_wham_locally.__kwdefaults__["run_smplify"] is True
    assert run_wham_locally.__kwdefaults__["estimate_local_only"] is True


def test_wham_run_result_timing_payload_records_runtime_mode(tmp_path: Path) -> None:
    result = WhamRunResult(
        output_dir=tmp_path / "out",
        results_pkl=tmp_path / "out" / "wham_output.pkl",
        stdout_log=tmp_path / "logs" / "stdout.log",
        stderr_log=tmp_path / "logs" / "stderr.log",
        command=["docker", "run", "wham:test"],
        elapsed_seconds=12.3456,
        returncode=0,
        use_docker=True,
        estimate_local_only=True,
        run_smplify=False,
        docker_image="wham:test",
    )

    payload = result.timing_payload()

    assert payload["elapsedSeconds"] == pytest.approx(12.346)
    assert payload["useDocker"] is True
    assert payload["estimateLocalOnly"] is True
    assert payload["runSmplify"] is False
    assert payload["dockerImage"] == "wham:test"


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


def test_choose_detected_span_prefers_complete_precise_interval_over_partial_cluster() -> None:
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
    assert span.start_seconds == 21.0
    assert span.end_seconds == 24.0
    assert span.contributing_windows == [3]


def test_choose_detected_span_rejects_too_short_precise_fragment() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=20.0, end_seconds=40.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=0.0,
            movement_end_seconds=0.9,
            confidence=0.95,
            summary="short fragment",
            reason="too short to contain a complete movement",
            camera_variation=0.01,
            frame_paths=[],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=30.0, end_seconds=46.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=0.0,
            movement_end_seconds=4.5,
            confidence=0.9,
            summary="complete execution",
            reason="contains the full movement execution",
            camera_variation=0.03,
            frame_paths=[],
        ),
    ]

    span = choose_detected_span(
        detections=detections,
        confidence_threshold=0.45,
        merge_gap_seconds=2.0,
        min_segment_seconds=2.0,
    )

    assert span is not None
    assert span.start_seconds == 30.0
    assert span.end_seconds == 34.5
    assert span.contributing_windows == [1]


def test_choose_detected_span_prefers_single_execution_candidate_over_broad_multi_execution() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=10.0, end_seconds=40.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=0.0,
            movement_end_seconds=28.0,
            confidence=0.96,
            summary="broad span includes multiple attempts",
            reason="model returned setup and two executions",
            camera_variation=0.02,
            frame_paths=[],
            executions=[
                    make_candidate_execution(
                    start_seconds=10.0,
                    end_seconds=38.0,
                    confidence=0.96,
                    quality=0.95,
                    complete=True,
                    single_execution=False,
                    contains_multiple_executions=True,
                    contains_idle_or_reset=True,
                    reason="contains more than one attempt",
                    source_window_index=0,
                )
            ],
        ),
        WindowDetection(
            window=DetectionWindow(index=1, start_seconds=30.0, end_seconds=50.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=1.5,
            movement_end_seconds=15.0,
            confidence=0.86,
            summary="one complete execution",
            reason="clean single execution",
            camera_variation=0.06,
            frame_paths=[],
            executions=[
                    make_candidate_execution(
                    start_seconds=31.5,
                    end_seconds=45.0,
                    confidence=0.86,
                    quality=0.88,
                    complete=True,
                    single_execution=True,
                    contains_multiple_executions=False,
                    contains_idle_or_reset=False,
                    reason="one complete execution reaches terminal position",
                    source_window_index=1,
                )
            ],
        ),
    ]

    span = choose_detected_span(
        detections=detections,
        confidence_threshold=0.45,
        merge_gap_seconds=2.0,
        min_segment_seconds=2.0,
        max_segment_seconds=20.0,
    )

    assert span is not None
    assert span.start_seconds == 31.5
    assert span.end_seconds == 45.0
    assert span.contributing_windows == [1]


def test_choose_detected_span_does_not_fallback_when_execution_candidates_are_invalid() -> None:
    detections = [
        WindowDetection(
            window=DetectionWindow(index=0, start_seconds=10.0, end_seconds=40.0),
            movement_present=True,
            contains_movement_start=True,
            contains_movement_end=True,
            movement_start_seconds=0.0,
            movement_end_seconds=28.0,
            confidence=0.96,
            summary="broad span includes multiple executions",
            reason="model emitted invalid candidate executions",
            camera_variation=0.02,
            frame_paths=[],
            executions=[
                    make_candidate_execution(
                    start_seconds=10.0,
                    end_seconds=38.0,
                    confidence=0.96,
                    quality=0.95,
                    complete=True,
                    single_execution=False,
                    contains_multiple_executions=True,
                    contains_idle_or_reset=True,
                    reason="contains more than one attempt",
                    source_window_index=0,
                )
            ],
        )
    ]

    span = choose_detected_span(
        detections=detections,
        confidence_threshold=0.45,
        merge_gap_seconds=2.0,
        min_segment_seconds=2.0,
        max_segment_seconds=20.0,
    )

    assert span is None


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
    assert len(payload["executions"]) == 1
    assert payload["executions"][0].start_seconds == 12.0
    assert payload["executions"][0].end_seconds == 20.0


def test_parse_detection_payload_accepts_execution_candidates_with_absolute_timestamps() -> None:
    payload = parse_detection_payload(
        json.dumps(
            {
                "movement_present": True,
                "executions": [
                    {
                        "start_seconds": 31.5,
                        "end_seconds": 45.2,
                        "complete": True,
                        "single_execution": True,
                        "contains_multiple_executions": False,
                        "contains_idle_or_reset": False,
                        "quality": 0.87,
                        "confidence": 0.91,
                        "reason": "one full execution reaches the terminal position",
                    },
                    {
                        "start_seconds": 30.0,
                        "end_seconds": 49.0,
                        "complete": True,
                        "single_execution": False,
                        "contains_multiple_executions": True,
                        "contains_idle_or_reset": True,
                        "quality": 0.2,
                        "confidence": 0.9,
                        "reason": "contains reset and multiple attempts",
                    },
                ],
                "movement_start_seconds": 31.5,
                "movement_end_seconds": 45.2,
                "confidence": 0.91,
                "summary": "full execution visible",
                "reason": "candidate is clear",
            }
        ),
        window=DetectionWindow(index=3, start_seconds=30.0, end_seconds=50.0),
    )

    executions = payload["executions"]

    assert len(executions) == 2
    assert executions[0].start_seconds == pytest.approx(31.5)
    assert executions[0].end_seconds == pytest.approx(45.2)
    assert executions[0].quality == pytest.approx(0.87)
    assert executions[0].source_window_index == 3
    assert executions[1].contains_multiple_executions is True
    assert executions[1].contains_idle_or_reset is True


def test_parse_detection_payload_accepts_malformed_confidence_without_timing() -> None:
    payload = parse_detection_payload(
        '{"movement_present": true, "confidence": 0.9.5, '
        '"summary": "The athlete is actively performing a front squat rep.", '
        '"reason": "The sampled frames show the exercise movement."}',
        window=DetectionWindow(index=0, start_seconds=12.0, end_seconds=20.0),
    )

    assert payload["movement_present"] is True
    assert payload["confidence"] == pytest.approx(0.95)
    assert payload["movement_start_seconds"] is None
    assert payload["movement_end_seconds"] is None


def test_build_window_prompt_rejects_setup_and_prefers_tight_full_rep() -> None:
    prompt = build_window_prompt(
        exercise_name="burpee",
        start_seconds=12.0,
        end_seconds=20.0,
    )

    assert "Goal: decide whether this window contains at least one complete target movement execution." in prompt
    assert "movement_present is true only when the full execution is visibly complete in this window." in prompt
    assert "movement_start_seconds and movement_end_seconds are coarse timing hints only" in prompt
    assert "read them in frame-number order, left-to-right within each row and then top-to-bottom across rows" in prompt
    assert "execution candidates, if provided, are optional and are hints, not hard boundaries." in prompt
    assert "Prefer classification." in prompt
    assert "contains_loop_anchor" not in prompt
    assert '"executions": [' in prompt
    assert '"movement_start_seconds": number|null' in prompt
    assert '"movement_end_seconds": number|null' in prompt


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


def test_extract_workout_plan_exercises_from_planner_json_dedupes_and_skips_disabled() -> None:
    payload = {
        "exercises": [
            {"id": "squat-a", "name": "Squat"},
            {"id": "squat-b", "exerciseName": " squat "},
            {"id": "pushup", "name": "Push Up", "enabled": False},
            {"id": "rest", "name": "Rest", "type": "rest"},
            {"id": "row", "exercise": {"name": "Bent Over Row"}},
        ]
    }

    exercises = extract_workout_plan_exercises(payload)

    assert [(item.exercise_id, item.name, item.slug) for item in exercises] == [
        ("squat-a", "Squat", "squat"),
        ("row", "Bent Over Row", "bent-over-row"),
    ]


def test_extract_workout_plan_exercises_from_final_package_and_nested_superset() -> None:
    payload = {
        "workouts": [
            {
                "workoutComponents": [
                    {
                        "type": "superset",
                        "name": "Upper superset",
                        "supersetExercises": [
                            {"exerciseId": "curl", "exerciseName": "Dumbbell Curl"},
                            {"exerciseId": "tri", "exerciseName": "Triceps Extension"},
                        ],
                    },
                    {"type": "rest", "exerciseName": "Rest"},
                ]
            }
        ]
    }

    exercises = extract_workout_plan_exercises(payload)

    assert [item.name for item in exercises] == [
        "Dumbbell Curl",
        "Triceps Extension",
    ]


def test_extract_workout_plan_exercises_can_include_disabled() -> None:
    payload = {"exercises": [{"id": "pushup", "name": "Push Up", "enabled": False}]}

    exercises = extract_workout_plan_exercises(payload, include_disabled=True)

    assert [item.name for item in exercises] == ["Push Up"]


def test_extract_workout_plan_exercises_from_workout_store_backup_root() -> None:
    payload = {
        "WorkoutStore": {
            "workouts": [
                {
                    "enabled": True,
                    "workoutComponents": [
                        {
                            "id": "warmup",
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Warm-Up",
                            "exerciseType": "COUNTDOWN",
                        },
                        {
                            "id": "bench",
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Bench Press",
                            "exerciseType": "WEIGHT",
                        },
                    ],
                },
                {
                    "enabled": False,
                    "workoutComponents": [
                        {
                            "id": "disabled",
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Disabled Workout Exercise",
                            "exerciseType": "WEIGHT",
                        }
                    ],
                },
            ]
        }
    }

    exercises = extract_workout_plan_exercises(payload)

    assert [(item.exercise_id, item.name) for item in exercises] == [("bench", "Bench Press")]


def test_parse_yt_dlp_search_results_normalizes_candidates() -> None:
    info = {
        "entries": [
            {
                "id": "abc123",
                "title": "Squat proper form tutorial",
                "channel": "Coach",
                "duration": "120",
                "view_count": "150000",
                "upload_date": "20240102",
                "description": "A full body side view squat demonstration.",
                "thumbnails": [{"url": "small.jpg"}, {"url": "large.jpg"}],
            }
        ]
    }

    candidates = parse_yt_dlp_search_results(info)

    assert len(candidates) == 1
    assert candidates[0].url == "https://www.youtube.com/watch?v=abc123"
    assert candidates[0].duration_seconds == 120
    assert candidates[0].view_count == 150000
    assert candidates[0].thumbnail == "large.jpg"


def test_build_youtube_queries_biases_motion_extraction_candidates() -> None:
    queries = build_youtube_queries("Bench Press")

    assert queries[:6] == [
        'Bench Press demonstration reps "same camera angle" -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine',
        'Bench Press "proper form" demo "single camera" -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine -mistakes -guide',
        "Bench Press execution demo full movement stable camera -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine -workout -program",
        "Bench Press exercise demonstration full rep single person -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine",
        "Bench Press full body demo reps side view -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine",
        "Bench Press technique demo complete repetition static camera -tutorial -shorts -record -competition -amrap -1rm -incline -decline -machine",
    ]
    assert any("-tutorial" in query for query in queries)
    assert all("-record" in query for query in queries)
    assert all("-decline" in query for query in queries)
    assert any("same camera angle" in query for query in queries)
    assert any("stable camera" in query for query in queries)
    assert any("single person" in query for query in queries)


def test_build_youtube_queries_adds_generic_equipment_stripped_alias() -> None:
    queries = build_youtube_queries("Barbell Bench Press")

    assert any(query.startswith("Bench Press exercise demonstration") for query in queries)
    assert any(query.startswith("Bench Press full body demo") for query in queries)
    assert not any(query.startswith("Panca piana ") for query in queries)


def test_select_evenly_spaced_review_windows_caps_without_front_loading() -> None:
    windows = list(range(10))

    assert select_evenly_spaced_review_windows(windows, 5) == [0, 2, 4, 7, 9]
    assert select_evenly_spaced_review_windows(windows, 1) == [5]
    assert select_evenly_spaced_review_windows(windows, None) == windows
    assert select_evenly_spaced_review_windows(windows, 0) == windows


def test_merge_youtube_queries_deduplicates_and_skips_urls() -> None:
    queries = merge_youtube_queries(
        [
            " Bench Press demo  ",
            "bench press demo",
            "https://www.youtube.com/watch?v=abc",
            "Bench Press side view -shorts",
        ],
    )

    assert queries == ["Bench Press demo", "Bench Press side view -shorts"]


def test_parse_deepseek_query_payload_accepts_json_object() -> None:
    queries = parse_deepseek_query_payload(
        json.dumps(
            {
                "queries": [
                    'Bench Press demo "same camera angle" -shorts',
                    "https://www.youtube.com/watch?v=abc",
                    "Bench Press demo \"same camera angle\" -shorts",
                    "Bench Press side view full rep",
                ]
            }
        ),
        max_queries=2,
    )

    assert queries == [
        'Bench Press demo "same camera angle" -shorts',
        "Bench Press side view full rep",
    ]


def test_deepseek_query_planner_calls_chat_completion_with_json_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"queries": ['Squat side view "single camera" -shorts']}
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = DeepSeekYouTubeQueryPlanner(
        YouTubeRankingSettings(deepseek_api_key="test-key"),
        client=client,
    )

    try:
        queries = planner(
            ExerciseEntry(exercise_id="squat", name="Squat", slug="squat"),
            build_youtube_queries("Squat"),
            YouTubeRankingSettings(deepseek_api_key="test-key"),
        )
    finally:
        planner.close()
        client.close()

    assert queries == ['Squat side view "single camera" -shorts']
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert str(requests[0].url) == "https://api.deepseek.com/chat/completions"


def test_candidate_vision_prompt_rejects_shaky_step_breakdown_videos() -> None:
    prompt = build_candidate_vision_prompt(
        "Bench Press",
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Bench Press Side View",
            channel=None,
            duration_seconds=None,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
    )

    assert "continuous uninterrupted repetitions" in prompt
    assert "Any angle is acceptable if it stays the same" in prompt
    assert "The whole relevant body and implement visible through the entire rep" in prompt
    assert "static_camera_throughout false" in prompt
    assert "shaky handheld video" in prompt
    assert "step-by-step demonstrations" in prompt
    assert "friendly for monocular human-pose extraction" in prompt
    assert "top-down" in prompt
    assert "Visible motion must come from the athlete body joints" in prompt
    assert "incline, decline, seated, supported, machine" in prompt
    assert "prefer clean repeatable demo repetitions over records" in prompt
    assert '"athlete_fully_in_frame_throughout": boolean' in prompt
    assert '"static_camera_throughout": boolean' in prompt
    assert '"continuous_motion": boolean' in prompt
    assert '"no_step_breakdown": boolean' in prompt
    assert '"no_camera_cuts": boolean' in prompt
    assert '"large_body_visible": boolean' in prompt
    assert '"pose_friendly_camera_angle": boolean' in prompt
    assert '"body_joint_motion_visible": boolean' in prompt
    assert '"low_equipment_occlusion": boolean' in prompt
    assert "Critical moving joints" in prompt
    assert "reconstruct into a usable 3D skeleton" in prompt
    assert '"critical_moving_joints_visible": boolean' in prompt
    assert '"low_critical_joint_occlusion": boolean' in prompt
    assert '"reconstruction_suitable": boolean' in prompt
    assert "critical_joint_occlusion" in prompt


def test_metadata_scoring_prefers_demo_duration_and_penalizes_shorts() -> None:
    exercise = ExerciseEntry(exercise_id="EXERCISE_0", name="Squat", slug="squat")
    good = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=good",
        video_id="good",
        title="Squat proper form demonstration full body side view",
        channel="Coach",
        duration_seconds=120,
        view_count=250000,
        upload_date=None,
        description_snippet="Squat exercise demonstration proper execution.",
        thumbnail=None,
    )
    bad = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=bad",
        video_id="bad",
        title="Squat shorts challenge music compilation",
        channel="Creator",
        duration_seconds=8,
        view_count=900,
        upload_date=None,
        description_snippet=None,
        thumbnail=None,
    )

    scored_good = score_candidate_metadata(
        exercise,
        good,
        min_duration_seconds=20,
        max_duration_seconds=480,
    )
    scored_bad = score_candidate_metadata(
        exercise,
        bad,
        min_duration_seconds=20,
        max_duration_seconds=480,
    )

    assert scored_good.metadata_score > scored_bad.metadata_score
    assert "exercise_name_match" in scored_good.score_reasons
    assert "usable_duration" in scored_good.score_reasons
    assert "too_short" in scored_bad.score_reasons
    assert "shorts_penalty" in scored_bad.score_reasons


def test_metadata_scoring_penalizes_bad_camera_angle_text() -> None:
    exercise = ExerciseEntry(exercise_id="EXERCISE_0", name="Clean and Jerk", slug="clean-and-jerk")
    candidate = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=camera",
        video_id="camera",
        title="Clean and Jerk technique",
        channel="Coach",
        duration_seconds=48,
        view_count=1000,
        upload_date=None,
        description_snippet="Technique is coming along. Sorry for the camera angles.",
        thumbnail=None,
    )

    scored = score_candidate_metadata(
        exercise,
        candidate,
        min_duration_seconds=20,
        max_duration_seconds=120,
    )

    assert "camera_angles_penalty" in scored.score_reasons
    assert scored.metadata_score < 0.69


def test_metadata_scoring_penalizes_unrequested_variants_and_max_attempts() -> None:
    exercise = ExerciseEntry(exercise_id="EXERCISE_0", name="Bench Press", slug="bench-press")
    clean_demo = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=demo",
        video_id="demo",
        title="Bench Press proper form demonstration side view",
        channel="Coach",
        duration_seconds=45,
        view_count=10_000,
        upload_date=None,
        description_snippet="Clean bench press demo with full repetition.",
        thumbnail=None,
    )
    decline_pr = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=decline",
        video_id="decline",
        title="275lbs decline bench press new personal record",
        channel="Lifter",
        duration_seconds=45,
        view_count=10_000,
        upload_date=None,
        description_snippet="PR max attempt.",
        thumbnail=None,
    )

    scored_clean = score_candidate_metadata(
        exercise,
        clean_demo,
        min_duration_seconds=20,
        max_duration_seconds=120,
    )
    scored_decline = score_candidate_metadata(
        exercise,
        decline_pr,
        min_duration_seconds=20,
        max_duration_seconds=120,
    )

    assert scored_clean.metadata_score > scored_decline.metadata_score
    assert "unrequested_decline_variant_penalty" in scored_decline.score_reasons
    assert "personal_record_penalty" in scored_decline.score_reasons


def test_vision_review_priority_prefers_source_quality_over_bare_metadata() -> None:
    exercise = ExerciseEntry(exercise_id="EXERCISE_0", name="Bench Press", slug="bench-press")
    source_like = score_candidate_metadata(
        exercise,
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=source",
            video_id="source",
            title="Bench Press technique full body side view",
            channel="Coach",
            duration_seconds=167,
            view_count=900,
            upload_date=None,
            description_snippet="Build strength with a clear bench press technique demonstration.",
            thumbnail=None,
        ),
        min_duration_seconds=20,
        max_duration_seconds=120,
    )
    bare_match = score_candidate_metadata(
        exercise,
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=bare",
            video_id="bare",
            title="75kg Bench Press",
            channel="Lifter",
            duration_seconds=34,
            view_count=10_000,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        min_duration_seconds=20,
        max_duration_seconds=120,
    )

    assert bare_match.metadata_score >= source_like.metadata_score
    assert vision_review_priority_score(
        source_like,
        min_duration_seconds=20,
        max_duration_seconds=120,
    ) > vision_review_priority_score(
        bare_match,
        min_duration_seconds=20,
        max_duration_seconds=120,
    )


def test_final_score_composes_with_and_without_vision() -> None:
    assert compose_final_score(0.7, None) == pytest.approx(0.7)
    assert compose_final_score(0.7, 0.9) == pytest.approx(0.88)


def test_prepare_vision_review_plans_motion_windows_without_eager_frame_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "preview.mp4"
    video_path.write_bytes(b"video")
    extraction_calls: list[object] = []

    class FakeMetadata:
        duration_seconds = 30.0
        fps = 30.0
        frame_count = 900
        width = 640
        height = 360

    monkeypatch.setattr("exercise_motion_pkg.youtube.download_youtube_preview", lambda *_: video_path)
    monkeypatch.setattr("exercise_motion_pkg.video_utils.read_basic_video_metadata", lambda _: FakeMetadata())
    captured_detection: dict[str, object] = {}

    def fake_detect_motion_candidate_intervals(**kwargs: object) -> list[MotionInterval]:
        captured_detection.update(kwargs)
        return [MotionInterval(start_seconds=4.0, end_seconds=10.0, score=2.0)]

    monkeypatch.setattr(
        "exercise_motion_pkg.segment_detection.detect_motion_candidate_intervals",
        fake_detect_motion_candidate_intervals,
    )
    monkeypatch.setattr(
        "exercise_motion_pkg.segment_detection.extract_window_frames",
        lambda **kwargs: extraction_calls.append(kwargs) or [],
    )

    prepared = prepare_vision_review(
        ExerciseEntry(exercise_id="bench", name="Bench Press", slug="bench-press"),
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Bench Press demo",
            channel=None,
            duration_seconds=30,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        YouTubeRankingSettings(
            vision_max_chunks_per_candidate=3,
            vision_motion_scan_sample_fps=0.25,
            vision_motion_scan_max_seconds=12.0,
        ),
    )

    try:
        detection_metadata = captured_detection["metadata"]
        detection_settings = captured_detection["settings"]
        assert prepared.video_path == video_path
        assert prepared.frame_path_chunks == []
        assert prepared.frame_paths == []
        assert extraction_calls == []
        assert detection_metadata.duration_seconds == pytest.approx(12.0)
        assert detection_settings.motion_sample_fps == pytest.approx(0.25)
        assert prepared.review_windows[0].source == "motion_interval"
        assert any(window.source == "coverage_probe" for window in prepared.review_windows)
        assert prepared.preview_download_elapsed_seconds >= 0.0
        assert prepared.motion_scan_elapsed_seconds >= 0.0
    finally:
        prepared.close()


def test_adaptive_vision_review_lazily_renders_only_diagnostic_bad_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    video_path = tmp_path / "preview.mp4"
    video_path.write_bytes(b"video")
    rendered_indexes: list[int] = []

    def fake_extract_window_frames(**kwargs: object) -> list[Path]:
        window = kwargs["window"]
        assert isinstance(window, DetectionWindow)
        rendered_indexes.append(window.index)
        frame_path = tmp_path / f"chunk-{window.index}.jpg"
        frame_path.write_bytes(b"frame")
        return [frame_path]

    monkeypatch.setattr("exercise_motion_pkg.segment_detection.extract_window_frames", fake_extract_window_frames)
    prepared = PreparedVisionReview(
        candidate=YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Bench Press demo",
            channel=None,
            duration_seconds=60,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        temp_dir=temp_dir,
        frame_paths=[],
        frame_path_chunks=[],
        chunk_windows=[(0.0, 4.0), (12.0, 16.0), (24.0, 28.0), (36.0, 40.0), (48.0, 52.0)],
        chunk_count=5,
        prompt="prompt",
        video_path=video_path,
        review_windows=[
            PreparedReviewWindow(index=0, start_seconds=0.0, end_seconds=4.0, source="motion_interval"),
            PreparedReviewWindow(index=1, start_seconds=12.0, end_seconds=16.0, source="coverage_probe"),
            PreparedReviewWindow(index=2, start_seconds=24.0, end_seconds=28.0, source="motion_interval"),
            PreparedReviewWindow(index=3, start_seconds=36.0, end_seconds=40.0, source="motion_interval"),
            PreparedReviewWindow(index=4, start_seconds=48.0, end_seconds=52.0, source="motion_interval"),
        ],
        frames_per_chunk=1,
    )

    def bad_caption_images(*, frame_paths: list[Path], prompt: str) -> str:
        return json.dumps(
            {
                "correct_exercise": False,
                "target_identity_match": False,
                "usable_for_motion_extraction": False,
                "complete_repetition_visible": False,
                "single_person_chunk": True,
                "target_match": 0.1,
                "complete_movement": 0.1,
                "capture_quality": 0.1,
                "execution_quality": 0.1,
                "source_score": 0.1,
                "blocking_issues": ["wrong_exercise"],
                "confidence": 1.0,
            }
        )

    try:
        score, reasons, payload = score_prepared_vision_review(
            prepared=prepared,
            settings=YouTubeRankingSettings(
                vision_initial_chunks_per_candidate=2,
                vision_expand_chunks_per_candidate=3,
            ),
            caption_images=bad_caption_images,
        )
    finally:
        prepared.close()

    assert score < 0.35
    assert rendered_indexes == [0, 1]
    assert payload is not None
    assert payload["adaptiveReviewPolicy"]["earlyStopReason"] == "all_diagnostic_chunks_bad"
    assert payload["adaptiveReviewPolicy"]["reviewedChunkCount"] == 2
    assert len(payload["reviewedChunks"]) == 2
    assert payload["totalChunkRenderElapsedSeconds"] >= 0.0
    assert payload["totalChunkVlmElapsedSeconds"] >= 0.0


def test_single_worker_vision_review_prepares_candidates_progressively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exercise = ExerciseEntry(exercise_id="bench", name="Bench Press", slug="bench-press")
    candidates = [
        YouTubeCandidate(
            url=f"https://www.youtube.com/watch?v=test{index}",
            video_id=f"test{index}",
            title=f"Bench candidate {index}",
            channel=None,
            duration_seconds=40,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
            metadata_score=0.7 - index * 0.01,
            final_score=0.7 - index * 0.01,
        )
        for index in range(5)
    ]
    prepared_calls: list[list[str]] = []
    temp_dirs: list[tempfile.TemporaryDirectory] = []

    def fake_prepare_parallel(**kwargs: object) -> dict[str, PreparedVisionReview]:
        batch = kwargs["candidates"]
        assert isinstance(batch, list)
        prepared_calls.append([candidate.video_id for candidate in batch])
        result: dict[str, PreparedVisionReview] = {}
        for candidate in batch:
            temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
            temp_dirs.append(temp_dir)
            result[candidate.key()] = PreparedVisionReview(
                candidate=candidate,
                temp_dir=temp_dir,
                frame_paths=[],
                frame_path_chunks=[],
                chunk_windows=[],
                chunk_count=0,
                prompt="",
            )
        return result

    class FakeRanker:
        def rank_prepared(
            self,
            prepared: PreparedVisionReview,
            settings: YouTubeRankingSettings,
        ) -> tuple[float, list[str], dict[str, object]]:
            return (
                1.0,
                [*VISION_HARD_GATE_REASONS_FOR_TEST, "source_score", "valid_motion_scene"],
                {
                    "correct_exercise": True,
                    "usable_for_motion_extraction": True,
                    "complete_repetition_visible": True,
                    "loopable_repetition_cycle": True,
                    "exercise_only_chunk": True,
                    "target_match": 1.0,
                    "complete_movement": 1.0,
                    "capture_quality": 1.0,
                    "execution_quality": 1.0,
                    "source_score": 1.0,
                },
            )

    monkeypatch.setattr("exercise_motion_pkg.youtube.prepare_vision_reviews_parallel", fake_prepare_parallel)

    try:
        ranked = rank_candidates_with_prepared_vision_reviews(
            exercise=exercise,
            ranked=candidates,
            settings=YouTubeRankingSettings(
                vision_candidates_per_exercise=5,
                vision_download_workers=2,
                vision_llm_workers=1,
            ),
            vision_ranker=FakeRanker(),
        )

        assert prepared_calls == [["test0", "test1"]]
        assert ranked[0].vision_score == pytest.approx(1.0)
        assert ranked[1].vision_score is None
    finally:
        for temp_dir in temp_dirs:
            temp_dir.cleanup()


def test_source_quality_caps_demote_variants_and_max_attempts_after_vision() -> None:
    variant_score, variant_reasons = apply_source_quality_caps(
        0.92,
        ["unrequested_decline_variant_penalty"],
    )
    attempt_score, attempt_reasons = apply_source_quality_caps(
        0.92,
        ["record_penalty", "pr_penalty"],
    )

    assert variant_score == pytest.approx(0.34)
    assert variant_reasons == ["unrequested_variant_source_cap"]
    assert attempt_score == pytest.approx(0.67)
    assert attempt_reasons == ["max_or_competition_attempt_source_cap"]


def test_vision_ranking_does_not_early_stop_on_metadata_demoted_sources() -> None:
    candidate = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=record",
        video_id="record",
        title="Bench Press record",
        channel=None,
        duration_seconds=45,
        view_count=None,
        upload_date=None,
        description_snippet=None,
        thumbnail=None,
        metadata_score=0.4,
        final_score=0.4,
        status="candidate",
        score_reasons=["record_penalty"],
    )
    reviewed = apply_vision_score(
        candidate,
        0.98,
        list(VISION_HARD_GATE_REASONS_FOR_TEST),
        {"source_score": 0.98},
    )

    assert reviewed.final_score == pytest.approx(0.67)
    assert reviewed.status == "candidate"
    assert "max_or_competition_attempt_source_cap" in reviewed.score_reasons
    assert candidate_passes_vision_hard_gates(reviewed, YouTubeRankingSettings()) is False


def test_vision_ranking_does_not_early_stop_without_valid_chunk_evidence() -> None:
    candidate = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=overconfident",
        video_id="overconfident",
        title="Bench Press demo",
        channel=None,
        duration_seconds=45,
        view_count=None,
        upload_date=None,
        description_snippet=None,
        thumbnail=None,
        metadata_score=0.8,
        final_score=0.8,
        status="recommended",
        score_reasons=[],
    )
    reviewed = apply_vision_score(
        candidate,
        0.98,
        list(VISION_HARD_GATE_REASONS_FOR_TEST),
        {
            "source_score": 1.0,
            "bestChunkScore": 0.49,
            "validChunkCount": 0,
            "chunkEvidenceCapApplied": True,
        },
    )

    assert candidate_passes_vision_hard_gates(reviewed, YouTubeRankingSettings()) is False


VISION_HARD_GATE_REASONS_FOR_TEST = (
    "correct_exercise",
    "usable_for_motion_extraction",
    "complete_repetition_visible",
    "loopable_repetition_cycle",
    "exercise_only_chunk",
    "normal_speed_execution",
    "not_broken_into_steps",
    "continuous_motion",
    "athlete_fully_in_frame_throughout",
    "static_camera_throughout",
    "single_camera_angle",
    "no_step_breakdown",
    "no_camera_cuts",
    "unobstructed_motion",
    "key_joints_visible",
    "large_body_visible",
    "pose_friendly_camera_angle",
    "body_joint_motion_visible",
    "low_equipment_occlusion",
    "critical_moving_joints_visible",
    "low_critical_joint_occlusion",
    "reconstruction_suitable",
    "single_person_chunk",
)


def test_vision_scoring_penalizes_moving_camera_and_incomplete_framing(
    tmp_path: Path,
) -> None:
    temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")
    prepared = PreparedVisionReview(
        candidate=YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Clean and Jerk demo",
            channel=None,
            duration_seconds=40,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        temp_dir=temp_dir,
        frame_paths=[frame_path],
        frame_path_chunks=[[frame_path]],
        chunk_windows=[(0.0, 4.0)],
        chunk_count=1,
        prompt="prompt",
    )

    try:
        score, reasons, payload = score_prepared_vision_review(
            prepared=prepared,
            settings=YouTubeRankingSettings(),
            caption_images=lambda *, frame_paths, prompt: json.dumps(
                {
                    "correct_exercise": True,
                    "full_body_visible": True,
                    "athlete_fully_in_frame_throughout": False,
                    "stable_camera": True,
                    "static_camera_throughout": False,
                    "repeated_reps": True,
                    "low_obstruction": True,
                    "usable_for_motion_extraction": True,
                    "continuous_motion": True,
                    "single_camera_angle": False,
                    "no_step_breakdown": True,
                    "no_camera_cuts": True,
                    "unobstructed_motion": True,
                    "key_joints_visible": True,
                    "implement_path_visible": False,
                    "single_primary_subject": True,
                    "clean_scene": True,
                    "no_nearby_people": True,
                    "confidence": 1.0,
                    "reason": "camera follows the athlete and implement leaves frame",
                }
            ),
        )
    finally:
        prepared.close()

    assert score < 0.50
    assert "athlete_or_implement_out_of_frame_penalty" in reasons
    assert "moving_or_reframing_camera_penalty" in reasons
    assert payload is not None
    assert payload["static_camera_throughout"] is False


def test_vision_scoring_penalizes_pose_extraction_unfriendly_source() -> None:
    score, reasons = score_candidate_vision_payload(
        {
            "correct_exercise": True,
            "target_identity_match": True,
            "usable_for_motion_extraction": True,
            "complete_repetition_visible": True,
            "loopable_repetition_cycle": True,
            "exercise_only_chunk": True,
            "normal_speed_execution": True,
            "not_broken_into_steps": True,
            "continuous_motion": True,
            "athlete_fully_in_frame_throughout": True,
            "static_camera_throughout": True,
            "single_camera_angle": True,
            "no_step_breakdown": True,
            "no_camera_cuts": True,
            "unobstructed_motion": True,
            "key_joints_visible": True,
            "large_body_visible": False,
            "pose_friendly_camera_angle": False,
            "body_joint_motion_visible": False,
            "low_equipment_occlusion": True,
            "single_person_chunk": True,
            "target_match": 1.0,
            "complete_movement": 1.0,
            "capture_quality": 1.0,
            "execution_quality": 1.0,
            "source_score": 1.0,
            "blocking_issues": ["small_body", "bad_pose_angle", "weak_body_joint_motion"],
            "confidence": 1.0,
            "reason": "Top-down instructional bench clip where the bar moves but the body is tiny.",
        }
    )

    assert score <= 0.49
    assert "small_body_pose_extraction_penalty" in reasons
    assert "bad_pose_camera_angle_penalty" in reasons
    assert "weak_body_joint_motion_penalty" in reasons
    assert "small_body_penalty" in reasons
    assert "bad_pose_angle_penalty" in reasons
    assert "weak_body_joint_motion_penalty" in reasons


def test_vision_scoring_penalizes_equipment_occluding_body_joints() -> None:
    score, reasons = score_candidate_vision_payload(
        {
            "correct_exercise": True,
            "target_identity_match": True,
            "usable_for_motion_extraction": True,
            "complete_repetition_visible": True,
            "loopable_repetition_cycle": True,
            "exercise_only_chunk": True,
            "normal_speed_execution": True,
            "not_broken_into_steps": True,
            "continuous_motion": True,
            "athlete_fully_in_frame_throughout": True,
            "static_camera_throughout": True,
            "single_camera_angle": True,
            "no_step_breakdown": True,
            "no_camera_cuts": True,
            "unobstructed_motion": True,
            "key_joints_visible": False,
            "large_body_visible": True,
            "pose_friendly_camera_angle": True,
            "body_joint_motion_visible": True,
            "low_equipment_occlusion": False,
            "single_person_chunk": True,
            "target_match": 1.0,
            "complete_movement": 1.0,
            "capture_quality": 1.0,
            "execution_quality": 1.0,
            "source_score": 1.0,
            "blocking_issues": ["equipment_occlusion"],
            "confidence": 1.0,
            "reason": "Plates and bench obscure shoulders, elbows, and torso through the press.",
        }
    )

    assert score <= 0.49
    assert "key_joints_visible_failed" in reasons
    assert "equipment_occlusion_penalty" in reasons


def test_vision_scoring_caps_hidden_critical_moving_joints() -> None:
    score, reasons = score_candidate_vision_payload(
        {
            "correct_exercise": True,
            "target_identity_match": True,
            "usable_for_motion_extraction": True,
            "complete_repetition_visible": True,
            "loopable_repetition_cycle": True,
            "exercise_only_chunk": True,
            "normal_speed_execution": True,
            "not_broken_into_steps": True,
            "continuous_motion": True,
            "athlete_fully_in_frame_throughout": True,
            "static_camera_throughout": True,
            "single_camera_angle": True,
            "no_step_breakdown": True,
            "no_camera_cuts": True,
            "unobstructed_motion": True,
            "key_joints_visible": True,
            "large_body_visible": True,
            "pose_friendly_camera_angle": True,
            "body_joint_motion_visible": True,
            "low_equipment_occlusion": True,
            "critical_moving_joints_visible": False,
            "low_critical_joint_occlusion": False,
            "reconstruction_suitable": False,
            "single_person_chunk": True,
            "target_match": 1.0,
            "complete_movement": 1.0,
            "capture_quality": 1.0,
            "execution_quality": 1.0,
            "source_score": 1.0,
            "blocking_issues": ["critical_joint_occlusion", "poor_reconstruction_suitability"],
            "confidence": 1.0,
            "reason": "One moving elbow is hidden behind the torso and plates for most of the press.",
        }
    )

    assert score <= 0.34
    assert "critical_moving_joints_visible_failed" in reasons
    assert "low_critical_joint_occlusion_failed" in reasons
    assert "reconstruction_suitable_failed" in reasons
    assert "critical_joint_visibility_penalty" in reasons
    assert "critical_joint_occlusion_penalty" in reasons
    assert "poor_reconstruction_suitability_penalty" in reasons


def test_vision_scoring_caps_isolated_valid_chunk_evidence(
    tmp_path: Path,
) -> None:
    temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")
    prepared = PreparedVisionReview(
        candidate=YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Exercise demo",
            channel=None,
            duration_seconds=60,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        temp_dir=temp_dir,
        frame_paths=[frame_path] * 5,
        frame_path_chunks=[[frame_path] for _ in range(5)],
        chunk_windows=[(float(index * 4), float(index * 4 + 4)) for index in range(5)],
        chunk_count=5,
        prompt="prompt",
    )

    def fake_caption_images(*, frame_paths: list[Path], prompt: str) -> str:
        is_first_chunk = "chunk 1 of 5" in prompt
        return json.dumps(
            {
                "correct_exercise": is_first_chunk,
                "target_identity_match": is_first_chunk,
                "usable_for_motion_extraction": is_first_chunk,
                "complete_repetition_visible": is_first_chunk,
                "loopable_repetition_cycle": is_first_chunk,
                "exercise_only_chunk": is_first_chunk,
                "normal_speed_execution": is_first_chunk,
                "not_broken_into_steps": is_first_chunk,
                "continuous_motion": is_first_chunk,
                "athlete_fully_in_frame_throughout": is_first_chunk,
                "static_camera_throughout": is_first_chunk,
                "single_camera_angle": is_first_chunk,
                "no_step_breakdown": is_first_chunk,
                "no_camera_cuts": is_first_chunk,
                "unobstructed_motion": is_first_chunk,
                "key_joints_visible": is_first_chunk,
                "single_person_chunk": True,
                "target_match": 1.0 if is_first_chunk else 0.2,
                "complete_movement": 1.0 if is_first_chunk else 0.2,
                "capture_quality": 1.0 if is_first_chunk else 0.2,
                "execution_quality": 1.0 if is_first_chunk else 0.2,
                "source_score": 1.0 if is_first_chunk else 0.2,
                "blocking_issues": ["none"] if is_first_chunk else ["partial_movement"],
                "confidence": 1.0,
                "reason": "test chunk",
            }
        )

    try:
        score, reasons, payload = score_prepared_vision_review(
            prepared=prepared,
            settings=YouTubeRankingSettings(),
            caption_images=fake_caption_images,
        )
    finally:
        prepared.close()

    assert score <= 0.49
    assert "low_source_evidence_coverage" in reasons
    assert payload is not None
    assert payload["validChunkCount"] == 1
    assert payload["validChunkRatio"] == pytest.approx(0.2)
    assert payload["chunkEvidenceCapApplied"] is True


def test_vision_scoring_allows_non_loopable_clean_movement_chunk(
    tmp_path: Path,
) -> None:
    temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")
    prepared = PreparedVisionReview(
        candidate=YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Exercise demo",
            channel=None,
            duration_seconds=60,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        temp_dir=temp_dir,
        frame_paths=[frame_path] * 2,
        frame_path_chunks=[[frame_path], [frame_path]],
        chunk_windows=[(0.0, 4.0), (12.0, 16.0)],
        chunk_count=2,
        prompt="prompt",
    )

    def fake_caption_images(*, frame_paths: list[Path], prompt: str) -> str:
        is_first_chunk = "chunk 1 of 2" in prompt
        return json.dumps(
            {
                "correct_exercise": is_first_chunk,
                "target_identity_match": is_first_chunk,
                "usable_for_motion_extraction": is_first_chunk,
                "complete_repetition_visible": is_first_chunk,
                "loopable_repetition_cycle": False,
                "exercise_only_chunk": is_first_chunk,
                "normal_speed_execution": is_first_chunk,
                "not_broken_into_steps": is_first_chunk,
                "continuous_motion": is_first_chunk,
                "athlete_fully_in_frame_throughout": is_first_chunk,
                "static_camera_throughout": is_first_chunk,
                "single_camera_angle": is_first_chunk,
                "no_step_breakdown": is_first_chunk,
                "no_camera_cuts": is_first_chunk,
                "unobstructed_motion": is_first_chunk,
                "key_joints_visible": is_first_chunk,
                "single_person_chunk": True,
                "target_match": 1.0 if is_first_chunk else 0.2,
                "complete_movement": 1.0 if is_first_chunk else 0.2,
                "capture_quality": 1.0 if is_first_chunk else 0.2,
                "execution_quality": 1.0 if is_first_chunk else 0.2,
                "source_score": 1.0 if is_first_chunk else 0.2,
                "blocking_issues": ["none"] if is_first_chunk else ["partial_movement"],
                "confidence": 1.0,
                "reason": "test chunk",
            }
        )

    try:
        score, reasons, payload = score_prepared_vision_review(
            prepared=prepared,
            settings=YouTubeRankingSettings(
                vision_initial_chunks_per_candidate=2,
                vision_expand_chunks_per_candidate=3,
            ),
            caption_images=fake_caption_images,
        )
    finally:
        prepared.close()

    assert score <= 0.49
    assert "no_valid_source_chunk_evidence" not in reasons
    assert "low_source_evidence_coverage" in reasons
    assert payload is not None
    assert payload["validChunkCount"] == 1
    assert payload["validChunkRatio"] == pytest.approx(0.5)
    assert payload["bestChunkScore"] >= 0.50
    assert payload["adaptiveReviewPolicy"]["earlyStopReason"] == "max_budget_reached"
    assert payload["chunkEvidenceCapApplied"] is True


def test_vision_scoring_caps_single_valid_chunk_evidence(
    tmp_path: Path,
) -> None:
    temp_dir = tempfile.TemporaryDirectory(dir=tmp_path)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")
    prepared = PreparedVisionReview(
        candidate=YouTubeCandidate(
            url="https://www.youtube.com/watch?v=test",
            video_id="test",
            title="Exercise demo",
            channel=None,
            duration_seconds=60,
            view_count=None,
            upload_date=None,
            description_snippet=None,
            thumbnail=None,
        ),
        temp_dir=temp_dir,
        frame_paths=[frame_path] * 2,
        frame_path_chunks=[[frame_path], [frame_path]],
        chunk_windows=[(0.0, 4.0), (12.0, 16.0)],
        chunk_count=2,
        prompt="prompt",
    )

    def fake_caption_images(*, frame_paths: list[Path], prompt: str) -> str:
        is_first_chunk = "chunk 1 of 2" in prompt
        return json.dumps(
            {
                "correct_exercise": is_first_chunk,
                "target_identity_match": True,
                "usable_for_motion_extraction": is_first_chunk,
                "complete_repetition_visible": is_first_chunk,
                "loopable_repetition_cycle": is_first_chunk,
                "exercise_only_chunk": is_first_chunk,
                "normal_speed_execution": is_first_chunk,
                "not_broken_into_steps": is_first_chunk,
                "continuous_motion": is_first_chunk,
                "athlete_fully_in_frame_throughout": is_first_chunk,
                "static_camera_throughout": is_first_chunk,
                "single_camera_angle": is_first_chunk,
                "no_step_breakdown": is_first_chunk,
                "no_camera_cuts": is_first_chunk,
                "unobstructed_motion": is_first_chunk,
                "key_joints_visible": is_first_chunk,
                "large_body_visible": is_first_chunk,
                "pose_friendly_camera_angle": is_first_chunk,
                "body_joint_motion_visible": is_first_chunk,
                "low_equipment_occlusion": is_first_chunk,
                "critical_moving_joints_visible": is_first_chunk,
                "low_critical_joint_occlusion": is_first_chunk,
                "reconstruction_suitable": is_first_chunk,
                "single_person_chunk": True,
                "target_match": 1.0 if is_first_chunk else 0.2,
                "complete_movement": 1.0 if is_first_chunk else 0.2,
                "capture_quality": 1.0 if is_first_chunk else 0.2,
                "execution_quality": 1.0 if is_first_chunk else 0.2,
                "source_score": 1.0 if is_first_chunk else 0.2,
                "blocking_issues": ["none"] if is_first_chunk else ["partial_movement"],
                "confidence": 1.0,
                "reason": "test chunk",
            }
        )

    try:
        score, reasons, payload = score_prepared_vision_review(
            prepared=prepared,
            settings=YouTubeRankingSettings(
                vision_initial_chunks_per_candidate=2,
                vision_expand_chunks_per_candidate=3,
            ),
            caption_images=fake_caption_images,
        )
    finally:
        prepared.close()

    assert score <= 0.49
    assert "low_source_evidence_coverage" in reasons
    assert payload is not None
    assert payload["validChunkCount"] == 1
    assert payload["validChunkRatio"] == pytest.approx(0.5)
    assert payload["chunkEvidenceCapApplied"] is True


def test_discover_and_rank_youtube_candidates_writes_manifest_with_mocked_search_and_vision(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {"name": "Squat"},
                    {"name": "Push Up"},
                ]
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        calls.append(query)
        exercise_name = "Push Up" if "Push Up" in query else "Squat"
        video_id = "push" if exercise_name == "Push Up" else "squat"
        return [
            YouTubeCandidate(
                url=f"https://www.youtube.com/watch?v={video_id}",
                video_id=video_id,
                title=f"{exercise_name} proper form demonstration full body side view",
                channel="Coach",
                duration_seconds=90,
                view_count=100000,
                upload_date=None,
                description_snippet=f"{exercise_name} demonstration.",
                thumbnail=None,
            )
        ]

    def fake_vision(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        return 0.9, ["full_body_visible"], {"full_body_visible": True}

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=5,
            max_candidates=3,
            rank_with_litert=True,
            vision_candidates_per_exercise=1,
        ),
        search_fn=fake_search,
        vision_ranker=fake_vision,
    )

    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert manifest == saved
    assert saved["sourcePlanPath"] == str(plan_path)
    assert saved["ranking"] | {"timing": None} == {
        "metadataEnabled": True,
        "maxCandidates": 3,
        "metadataCandidatePoolSize": 24,
        "queryPlanningEnabled": False,
        "queryPlannerBackend": None,
        "visionEnabled": True,
        "visionBackend": "llama-cpp-server",
        "visionCandidatesPerExercise": 1,
        "semanticGateEnabled": False,
        "semanticGateBackend": None,
        "semanticGateModel": None,
        "semanticGateCandidatesPerExercise": None,
        "semanticGateMinScore": None,
        "posePrefilterEnabled": False,
        "posePrefilterBackend": None,
        "posePrefilterModel": None,
        "posePrefilterCandidatesPerExercise": None,
        "timing": None,
    }
    assert saved["ranking"]["timing"]["totalElapsedSeconds"] >= 0.0
    assert saved["ranking"]["timing"]["searchElapsedSeconds"] >= 0.0
    assert saved["ranking"]["timing"]["metadataRankingElapsedSeconds"] >= 0.0
    assert saved["ranking"]["timing"]["semanticGateElapsedSeconds"] >= 0.0
    assert saved["ranking"]["timing"]["posePrefilterElapsedSeconds"] >= 0.0
    assert saved["ranking"]["timing"]["visionScoringElapsedSeconds"] >= 0.0
    assert len(saved["exercises"]) == 2
    assert len(calls) == 12
    assert saved["exercises"][0]["queries"] == build_youtube_queries("Squat")
    assert saved["exercises"][0]["queryPlanning"] == {
        "enabled": False,
        "backend": None,
        "status": "skipped",
        "addedQueries": [],
    }
    first_candidate = saved["exercises"][0]["candidates"][0]
    assert first_candidate["visionScore"] == 0.9
    assert first_candidate["visionPayload"] == {"full_body_visible": True}
    assert first_candidate["status"] == "recommended"
    assert "full_body_visible" in first_candidate["scoreReasons"]


def test_discover_and_rank_youtube_candidates_reviews_broader_metadata_pool(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Squat"}]}), encoding="utf-8")
    search_calls = 0

    def make_candidate(index: int, *, title: str, view_count: int) -> YouTubeCandidate:
        return YouTubeCandidate(
            url=f"https://www.youtube.com/watch?v=candidate-{index}",
            video_id=f"candidate-{index}",
            title=title,
            channel="Coach",
            duration_seconds=70,
            view_count=view_count,
            upload_date=None,
            description_snippet="Squat exercise.",
            thumbnail=None,
        )

    metadata_favorites = [
        make_candidate(index, title=f"Squat proper form demonstration full body demo {index}", view_count=250_000)
        for index in range(1, 4)
    ]
    lower_metadata_visual_winner = make_candidate(
        7,
        title="Squat full rep side view single person",
        view_count=500,
    )
    lower_metadata_candidates = [
        make_candidate(index, title=f"Squat quiet source {index}", view_count=500)
        for index in range(4, 7)
    ]

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        nonlocal search_calls
        search_calls += 1
        if search_calls > 1:
            return []
        return [*metadata_favorites, *lower_metadata_candidates, lower_metadata_visual_winner]

    def fake_vision(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        if candidate.video_id == lower_metadata_visual_winner.video_id:
            return 0.96, ["complete_repetition_visible"], {"bestChunkScore": 0.96}
        return 0.12, ["weak_visual_match"], {"bestChunkScore": 0.12}

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=8,
            max_candidates=3,
            metadata_candidate_pool_size=8,
            rank_with_litert=True,
            vision_candidates_per_exercise=8,
        ),
        search_fn=fake_search,
        vision_ranker=fake_vision,
    )

    candidates = manifest["exercises"][0]["candidates"]
    assert candidates[0]["videoId"] == lower_metadata_visual_winner.video_id
    assert candidates[0]["visionScore"] == pytest.approx(0.96)
    assert len(candidates) == 3


def test_discover_and_rank_youtube_candidates_does_not_prefilter_by_metadata(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Barbell Bench Press"}]}), encoding="utf-8")
    reviewed: list[str] = []
    candidates = [
        YouTubeCandidate(
            url=f"https://www.youtube.com/watch?v=good-low-metadata",
            video_id="good-low-metadata",
            title="Panca piana - day20",
            channel="Coach",
            duration_seconds=42,
            view_count=3,
            upload_date=None,
            description_snippet="",
            thumbnail=None,
        ),
        *[
            YouTubeCandidate(
                url=f"https://www.youtube.com/watch?v=token-match-{index}",
                video_id=f"token-match-{index}",
                title=f"Barbell bench press unrelated token match {index}",
                channel="Coach",
                duration_seconds=45,
                view_count=500,
                upload_date=None,
                description_snippet="",
                thumbnail=None,
            )
            for index in range(6)
        ],
    ]

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        return candidates if "Barbell Bench Press" in query else []

    def fake_vision(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        reviewed.append(candidate.video_id or "")
        if candidate.video_id == "good-low-metadata":
            return 0.96, ["complete_repetition_visible"], {"bestChunkScore": 0.96}
        return 0.1, ["weak_visual_match"], {"bestChunkScore": 0.1}

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=8,
            max_candidates=3,
            metadata_candidate_pool_size=3,
            rank_with_litert=True,
            vision_candidates_per_exercise=3,
        ),
        search_fn=fake_search,
        vision_ranker=fake_vision,
    )

    result_candidates = manifest["exercises"][0]["candidates"]

    assert "good-low-metadata" in reviewed
    assert result_candidates[0]["videoId"] == "good-low-metadata"
    assert result_candidates[0]["metadataScore"] < result_candidates[1]["metadataScore"]
    assert result_candidates[0]["visionScore"] == pytest.approx(0.96)


def test_discover_and_rank_youtube_candidates_retries_empty_search_results(
    tmp_path: Path,
) -> None:
    assert YouTubeRankingSettings().youtube_search_empty_retries == 5

    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Bench Press"}]}), encoding="utf-8")
    calls_by_query: dict[str, int] = {}

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        calls_by_query[query] = calls_by_query.get(query, 0) + 1
        if calls_by_query[query] == 1:
            return []
        return [
            YouTubeCandidate(
                url="https://www.youtube.com/watch?v=recovered",
                video_id="recovered",
                title="Bench Press recovered search result",
                channel="Coach",
                duration_seconds=42,
                view_count=100,
                upload_date=None,
                description_snippet="",
                thumbnail=None,
            )
        ]

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=3,
            max_candidates=1,
            youtube_search_empty_retries=2,
        ),
        search_fn=fake_search,
    )

    exercise = manifest["exercises"][0]

    assert exercise["candidates"][0]["videoId"] == "recovered"
    assert any(item["attempts"] == 2 and item["resultCount"] == 1 for item in exercise["searchAttempts"])


def test_semantic_gate_default_has_no_subprocess_timeout() -> None:
    assert YouTubeRankingSettings().semantic_gate_timeout_seconds == 0.0
    assert semantic_gate_subprocess_timeout(YouTubeRankingSettings()) is None
    assert semantic_gate_subprocess_timeout(YouTubeRankingSettings(semantic_gate_timeout_seconds=30.0)) == pytest.approx(30.0)


def test_pose_prefilter_scores_clean_single_person_motion_window() -> None:
    metadata = BasicVideoMetadata(fps=2.0, frame_count=12, width=640, height=480)
    samples: list[PoseSample] = []
    for index in range(12):
        motion = math.sin(index / 11.0 * math.pi) * 42.0
        keypoints = {
            "left_shoulder": (250.0, 145.0, 0.9),
            "right_shoulder": (390.0, 145.0, 0.9),
            "left_elbow": (230.0, 220.0 - motion * 0.35, 0.9),
            "right_elbow": (410.0, 220.0 - motion * 0.35, 0.9),
            "left_wrist": (220.0, 295.0 - motion, 0.9),
            "right_wrist": (420.0, 295.0 - motion, 0.9),
            "left_hip": (275.0, 310.0, 0.9),
            "right_hip": (365.0, 310.0, 0.9),
            "left_knee": (270.0, 395.0, 0.9),
            "right_knee": (370.0, 395.0, 0.9),
            "left_ankle": (265.0, 455.0, 0.9),
            "right_ankle": (375.0, 455.0, 0.9),
        }
        samples.append(
            PoseSample(
                time_seconds=index / metadata.fps,
                detections=[
                    PoseDetection(
                        keypoints=keypoints,
                        bbox=(205.0, 120.0, 435.0, 468.0),
                        confidence=0.95,
                    )
                ],
            )
        )

    result = score_pose_samples(
        samples,
        metadata=metadata,
        settings=PosePrefilterSettings(
            window_seconds=6.0,
            overlap_seconds=3.0,
            min_score=0.45,
            min_body_scale=0.18,
        ),
    )

    assert result.passed is True
    assert result.score >= 0.70
    assert result.payload["singlePersonRatio"] == pytest.approx(1.0)
    assert result.payload["keypointCoverage"] == pytest.approx(1.0)
    assert result.payload["motionStrength"] > 0.2
    assert result.payload["blockingIssues"] == []


def test_pose_prefilter_rejects_multiple_people_and_cropped_body() -> None:
    metadata = BasicVideoMetadata(fps=2.0, frame_count=6, width=640, height=480)
    samples: list[PoseSample] = []
    partial_keypoints = {
        "left_shoulder": (4.0, 90.0, 0.9),
        "right_shoulder": (120.0, 90.0, 0.9),
        "left_elbow": (5.0, 160.0, 0.9),
        "right_elbow": (145.0, 160.0, 0.9),
        "left_wrist": (4.0, 230.0, 0.9),
        "right_wrist": (150.0, 230.0, 0.9),
    }
    other_keypoints = {
        **partial_keypoints,
        "left_shoulder": (420.0, 100.0, 0.9),
        "right_shoulder": (520.0, 100.0, 0.9),
    }
    for index in range(6):
        samples.append(
            PoseSample(
                time_seconds=index / metadata.fps,
                detections=[
                    PoseDetection(keypoints=partial_keypoints, bbox=(0.0, 80.0, 160.0, 260.0), confidence=0.9),
                    PoseDetection(keypoints=other_keypoints, bbox=(390.0, 80.0, 550.0, 260.0), confidence=0.8),
                ],
            )
        )

    result = score_pose_samples(
        samples,
        metadata=metadata,
        settings=PosePrefilterSettings(window_seconds=3.0, overlap_seconds=1.0, min_score=0.45),
    )

    assert result.passed is False
    assert "multiple_people" in result.payload["blockingIssues"]
    assert "low_keypoint_coverage" in result.payload["blockingIssues"]
    assert "cropped_body" in result.payload["blockingIssues"]


def test_pose_prefilter_rejects_active_chain_with_missing_moving_joint() -> None:
    metadata = BasicVideoMetadata(fps=2.0, frame_count=12, width=640, height=480)
    samples: list[PoseSample] = []
    for index in range(12):
        motion = math.sin(index / 11.0 * math.pi) * 42.0
        keypoints = {
            "left_shoulder": (250.0, 145.0, 0.9),
            "right_shoulder": (390.0, 145.0, 0.9),
            "left_elbow": (230.0, 220.0 - motion * 0.35, 0.9),
            "left_wrist": (220.0, 295.0 - motion, 0.9),
            "right_wrist": (420.0, 295.0 - motion, 0.9),
            "left_hip": (275.0, 310.0, 0.9),
            "right_hip": (365.0, 310.0, 0.9),
            "left_knee": (270.0, 395.0, 0.9),
            "right_knee": (370.0, 395.0, 0.9),
            "left_ankle": (265.0, 455.0, 0.9),
            "right_ankle": (375.0, 455.0, 0.9),
        }
        samples.append(
            PoseSample(
                time_seconds=index / metadata.fps,
                detections=[
                    PoseDetection(
                        keypoints=keypoints,
                        bbox=(205.0, 120.0, 435.0, 468.0),
                        confidence=0.95,
                    )
                ],
            )
        )

    result = score_pose_samples(
        samples,
        metadata=metadata,
        settings=PosePrefilterSettings(
            window_seconds=6.0,
            overlap_seconds=3.0,
            min_score=0.45,
            min_body_scale=0.18,
        ),
    )

    assert result.passed is False
    assert "low_active_chain_visibility" in result.payload["blockingIssues"]
    assert "right_arm" in result.payload["activeChains"]
    assert result.payload["activeChainVisibility"] < 0.68


def test_pose_model_alias_resolves_to_shared_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "pose-model-cache"
    downloads: list[tuple[str, Path]] = []

    def fake_urlretrieve(url: str, filename: Path) -> tuple[str, object | None]:
        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"model")
        downloads.append((url, output_path))
        return str(output_path), None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pose_prefilter_module, "POSE_MODEL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(pose_prefilter_module, "urlretrieve", fake_urlretrieve)

    first = resolve_pose_model_path("yolo26x-pose.pt")
    second = resolve_pose_model_path("yolo26x-pose.pt")

    assert Path(first) == cache_dir / "yolo26x-pose.pt"
    assert second == first
    assert Path(first).read_bytes() == b"model"
    assert len(downloads) == 1


def test_pose_model_alias_seeds_shared_cache_from_existing_local_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "pose-model-cache"
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "yolo26x-pose.pt").write_bytes(b"seed-model")

    def fail_urlretrieve(url: str, filename: Path) -> tuple[str, object | None]:
        raise AssertionError("existing local model should seed the shared cache")

    monkeypatch.chdir(local_dir)
    monkeypatch.setattr(pose_prefilter_module, "POSE_MODEL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(pose_prefilter_module, "urlretrieve", fail_urlretrieve)

    resolved = resolve_pose_model_path("yolo26x-pose.pt")

    assert Path(resolved) == cache_dir / "yolo26x-pose.pt"
    assert Path(resolved).read_bytes() == b"seed-model"


def test_discover_and_rank_youtube_candidates_pose_prefilter_reduces_pool_before_vision(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Bench Press"}]}), encoding="utf-8")
    candidates = [
        YouTubeCandidate(
            url=f"https://www.youtube.com/watch?v=bench-{index}",
            video_id=f"bench-{index}",
            title=f"Bench press candidate {index}",
            channel="Coach",
            duration_seconds=70,
            view_count=10_000 - index,
            upload_date=None,
            description_snippet="Bench press demonstration.",
            thumbnail=None,
        )
        for index in range(5)
    ]
    pose_reviewed: list[str] = []
    vision_reviewed: list[str] = []

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        return candidates if "Bench Press" in query else []

    def fake_pose(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        pose_reviewed.append(candidate.video_id or "")
        score = 0.92 if candidate.video_id in {"bench-2", "bench-4"} else 0.18
        return (
            score,
            ["pose_good_motion_source"] if score > 0.5 else ["pose_weak_body_joint_motion"],
            {
                "enabled": True,
                "passed": score > 0.5,
                "score": score,
                "bestChunkStartSeconds": 4.0,
                "bestChunkEndSeconds": 12.0,
                "blockingIssues": [] if score > 0.5 else ["weak_body_joint_motion"],
            },
        )

    def fake_vision(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        vision_reviewed.append(candidate.video_id or "")
        return 0.8, ["complete_repetition_visible"], {"bestChunkScore": 0.8}

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=5,
            max_candidates=3,
            metadata_candidate_pool_size=5,
            pose_prefilter_enabled=True,
            pose_prefilter_candidates_per_exercise=5,
            rank_with_litert=True,
            vision_candidates_per_exercise=2,
        ),
        search_fn=fake_search,
        pose_ranker=fake_pose,
        vision_ranker=fake_vision,
    )

    result_candidates = manifest["exercises"][0]["candidates"]

    assert set(pose_reviewed) == {candidate.video_id for candidate in candidates}
    assert set(vision_reviewed) == {"bench-2", "bench-4"}
    assert result_candidates[0]["visionPayload"]["posePrefilter"]["passed"] is True
    assert result_candidates[0]["visionPayload"]["posePrefilter"]["bestChunkStartSeconds"] == pytest.approx(4.0)
    assert manifest["ranking"]["posePrefilterEnabled"] is True
    assert manifest["ranking"]["posePrefilterModel"] == "yolo26x-pose.pt"
    assert manifest["ranking"]["timing"]["posePrefilterElapsedSeconds"] >= 0.0


def test_discover_and_rank_youtube_candidates_semantic_gate_ranks_fallbacks_before_pose(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Barbell Bench Press"}]}), encoding="utf-8")
    candidates = [
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=bench",
            video_id="bench",
            title="Barbell bench press exercise demo",
            channel="Coach",
            duration_seconds=45,
            view_count=10_000,
            upload_date=None,
            description_snippet="Flat barbell bench press demonstration.",
            thumbnail=None,
        ),
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=power-clean",
            video_id="power-clean",
            title="Power Clean",
            channel="Coach",
            duration_seconds=45,
            view_count=9_000,
            upload_date=None,
            description_snippet="Explosive Olympic lift demo.",
            thumbnail=None,
        ),
        YouTubeCandidate(
            url="https://www.youtube.com/watch?v=step-up",
            video_id="step-up",
            title="DB Suitcase Box Step Up",
            channel="Coach",
            duration_seconds=45,
            view_count=8_000,
            upload_date=None,
            description_snippet="Step up exercise demo.",
            thumbnail=None,
        ),
    ]
    semantic_reviewed: list[str] = []
    pose_reviewed: list[str] = []

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        return candidates if "Bench Press" in query else []

    def fake_semantic_gate(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        semantic_reviewed.append(candidate.video_id or "")
        passed = candidate.video_id == "bench"
        return (
            0.93 if passed else 0.08,
            ["semantic_text_match"] if passed else ["semantic_text_mismatch", "semantic_wrong_exercise"],
            {
                "enabled": True,
                "passed": passed,
                "score": 0.93 if passed else 0.08,
                "wrongExercise": not passed,
                "wrongEquipment": False,
                "matchedExercise": "barbell bench press" if passed else "other exercise",
                "reason": "text match" if passed else "wrong exercise",
            },
        )

    def fake_pose(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        pose_reviewed.append(candidate.video_id or "")
        return (
            0.91,
            ["pose_good_motion_source"],
            {
                "enabled": True,
                "passed": True,
                "score": 0.91,
                "bestChunkStartSeconds": 3.0,
                "bestChunkEndSeconds": 11.0,
            },
        )

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=5,
            max_candidates=3,
            metadata_candidate_pool_size=5,
            semantic_gate_enabled=True,
            semantic_gate_candidates_per_exercise=3,
            pose_prefilter_enabled=True,
            pose_prefilter_candidates_per_exercise=3,
        ),
        search_fn=fake_search,
        semantic_gate=fake_semantic_gate,
        pose_ranker=fake_pose,
    )

    result_candidates = manifest["exercises"][0]["candidates"]

    assert set(semantic_reviewed) == {"bench", "power-clean", "step-up"}
    assert set(pose_reviewed) == {"bench", "power-clean", "step-up"}
    assert [candidate["videoId"] for candidate in result_candidates] == ["bench", "power-clean", "step-up"]
    assert result_candidates[0]["visionPayload"]["semanticGate"]["passed"] is True
    assert result_candidates[1]["visionPayload"]["semanticGate"]["passed"] is False
    assert result_candidates[0]["visionPayload"]["posePrefilter"]["passed"] is True
    assert manifest["ranking"]["semanticGateEnabled"] is True
    assert manifest["ranking"]["semanticGateBackend"] == "litert-lm"
    assert manifest["ranking"]["semanticGateModel"] == "gemma-4-E4B-it"
    assert manifest["ranking"]["timing"]["semanticGateElapsedSeconds"] >= 0.0


def test_semantic_gate_keeps_candidate_when_pose_prefilter_fails_visibility(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Barbell Bench Press"}]}), encoding="utf-8")
    candidate = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=panca",
        video_id="panca",
        title="Panca piana - #day20",
        channel="Coach",
        duration_seconds=42,
        view_count=500,
        upload_date=None,
        description_snippet="Panca piana con bilanciere.",
        thumbnail=None,
    )
    vision_reviewed: list[str] = []

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        return [candidate] if "Bench Press" in query else []

    def fake_semantic_gate(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        return (
            1.0,
            ["semantic_text_match"],
            {
                "enabled": True,
                "passed": True,
                "score": 1.0,
                "wrongExercise": False,
                "wrongEquipment": False,
                "matchedExercise": "Barbell Bench Press",
                "reason": "Italian panca piana with barbell.",
            },
        )

    def fake_pose(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        return (
            0.89,
            ["pose_low_active_chain_visibility"],
            {
                "enabled": True,
                "passed": False,
                "score": 0.89,
                "blockingIssues": ["low_active_chain_visibility"],
            },
        )

    def fake_vision(
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str], dict[str, object]]:
        vision_reviewed.append(candidate.video_id or "")
        return (
            0.91,
            ["correct_exercise", "usable_for_motion_extraction"],
            {
                "bestChunkScore": 1.0,
                "bestChunkStartSeconds": 15.5,
                "bestChunkEndSeconds": 25.5,
                "correct_exercise": True,
                "usable_for_motion_extraction": True,
            },
        )

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=5,
            max_candidates=3,
            metadata_candidate_pool_size=5,
            semantic_gate_enabled=True,
            semantic_gate_candidates_per_exercise=3,
            pose_prefilter_enabled=True,
            pose_prefilter_candidates_per_exercise=3,
            rank_with_litert=True,
            vision_candidates_per_exercise=3,
        ),
        search_fn=fake_search,
        semantic_gate=fake_semantic_gate,
        pose_ranker=fake_pose,
        vision_ranker=fake_vision,
    )

    result_candidates = manifest["exercises"][0]["candidates"]

    assert vision_reviewed == ["panca"]
    assert result_candidates[0]["videoId"] == "panca"
    assert result_candidates[0]["status"] in {"candidate", "recommended"}
    assert result_candidates[0]["visionPayload"]["semanticGate"]["passed"] is True
    assert result_candidates[0]["visionPayload"]["posePrefilter"]["passed"] is False
    assert result_candidates[0]["visionPayload"]["bestChunkScore"] == pytest.approx(1.0)


def test_semantic_gate_text_conflicts_reject_broad_or_multi_lift_bench_sources() -> None:
    exercise = ExerciseEntry(exercise_id="bench", name="Barbell Bench Press", slug="barbell-bench-press")

    multi_lift = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=multi",
        video_id="multi",
        title="Watch a Coach Do Form Checks | Squat | Deadlift | Bench | Press",
        channel="Coach",
        duration_seconds=60,
        view_count=10_000,
        upload_date=None,
        description_snippet="Includes bench press form checks.",
        thumbnail=None,
    )
    description_only = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=chest",
        video_id="chest",
        title="Why Your Chest Is Not Growing",
        channel="Coach",
        duration_seconds=60,
        view_count=10_000,
        upload_date=None,
        description_snippet="Includes flat bench and bench press advice.",
        thumbnail=None,
    )
    direct_alias = YouTubeCandidate(
        url="https://www.youtube.com/watch?v=panca",
        video_id="panca",
        title="Panca piana - day 20",
        channel="Coach",
        duration_seconds=60,
        view_count=10_000,
        upload_date=None,
        description_snippet="Italian flat bench press set.",
        thumbnail=None,
    )

    assert "semantic_title_mentions_other_exercise" in semantic_gate_text_conflict_reasons(exercise, multi_lift)
    assert "semantic_target_only_in_description" in semantic_gate_text_conflict_reasons(exercise, description_only)
    assert semantic_gate_text_conflict_reasons(exercise, direct_alias) == []


def test_discover_and_rank_youtube_candidates_uses_query_planner(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "youtube_candidates.json"
    plan_path.write_text(json.dumps({"exercises": [{"name": "Squat"}]}), encoding="utf-8")
    searched_queries: list[str] = []

    def fake_query_planner(
        exercise: ExerciseEntry,
        base_queries: list[str],
        settings: YouTubeRankingSettings,
    ) -> list[str]:
        assert exercise.name == "Squat"
        assert base_queries == build_youtube_queries("Squat")
        assert settings.deepseek_max_queries == 2
        return [
            'Squat side view "single camera" -shorts',
            "Squat execution demo full rep -tutorial",
        ]

    def fake_search(query: str, results_per_query: int) -> list[YouTubeCandidate]:
        searched_queries.append(query)
        return [
            YouTubeCandidate(
                url=f"https://www.youtube.com/watch?v={len(searched_queries)}",
                video_id=str(len(searched_queries)),
                title=f"Squat demo {len(searched_queries)}",
                channel="Coach",
                duration_seconds=60,
                view_count=10_000,
                upload_date=None,
                description_snippet="Squat demonstration.",
                thumbnail=None,
            )
        ]

    manifest = discover_and_rank_youtube_candidates(
        workout_plan_json=plan_path,
        out_json=out_path,
        settings=YouTubeRankingSettings(
            results_per_query=3,
            max_candidates=5,
            use_deepseek_query_planner=True,
            deepseek_max_queries=2,
        ),
        search_fn=fake_search,
        query_planner=fake_query_planner,
    )

    exercise = manifest["exercises"][0]
    assert searched_queries == [
        *build_youtube_queries("Squat"),
        'Squat side view "single camera" -shorts',
        "Squat execution demo full rep -tutorial",
    ]
    assert exercise["queryPlanning"] == {
        "enabled": True,
        "backend": "custom",
        "status": "completed",
        "addedQueries": [
            'Squat side view "single camera" -shorts',
            "Squat execution demo full rep -tutorial",
        ],
    }
    assert manifest["ranking"]["queryPlanningEnabled"] is True
    assert manifest["ranking"]["queryPlannerBackend"] == "deepseek"


def test_bake_and_rank_manifest_parser_uses_top_candidate_per_exercise() -> None:
    payload = {
        "exercises": [
            {
                "exerciseId": "squat",
                "exerciseName": "Squat",
                "slug": "squat",
                "candidates": [
                    {"videoId": "top", "url": "https://www.youtube.com/watch?v=top", "title": "Top"},
                    {"videoId": "second", "url": "https://www.youtube.com/watch?v=second", "title": "Second"},
                ],
            },
            {
                "exerciseId": "row",
                "exerciseName": "Row",
                "slug": "row",
                "candidates": [
                    {"videoId": "row-top", "url": "https://www.youtube.com/watch?v=row-top", "title": "Row Top"},
                ],
            },
        ]
    }

    all_candidates = parse_ranked_candidates_manifest(payload)
    top_candidates = parse_top_ranked_candidates_manifest(payload)

    assert [candidate.video_id for candidate in all_candidates] == ["top", "second", "row-top"]
    assert [candidate.video_id for candidate in top_candidates] == ["top", "row-top"]
    assert [candidate.candidate_rank for candidate in top_candidates] == [0, 0]


def test_bake_and_rank_loader_skips_unreviewed_candidates_when_reviewed_sources_exist(tmp_path: Path) -> None:
    candidates_path = tmp_path / "youtube_candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "bench",
                        "exerciseName": "Bench Press",
                        "slug": "bench-press",
                        "candidates": [
                            {
                                "videoId": "reviewed",
                                "url": "https://www.youtube.com/watch?v=reviewed",
                                "title": "Reviewed source",
                                "status": "recommended",
                                "visionPayload": {"source_score": 1.0},
                            },
                            {
                                "videoId": "unreviewed",
                                "url": "https://www.youtube.com/watch?v=unreviewed",
                                "title": "Unreviewed fallback",
                                "status": "candidate",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    candidates = load_ranked_candidates_manifest(candidates_path)

    assert [candidate.video_id for candidate in candidates] == ["reviewed"]


def test_ranked_candidate_source_chunk_hint_reads_pose_prefilter_payload() -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="bench",
        exercise_name="Bench Press",
        exercise_slug="bench-press",
        candidate={
            "videoId": "pose",
            "url": "https://www.youtube.com/watch?v=pose",
            "title": "Pose-selected source",
            "visionPayload": {
                "posePrefilter": {
                    "passed": True,
                    "score": 0.82,
                    "bestChunkStartSeconds": 4.25,
                    "bestChunkEndSeconds": 12.75,
                }
            },
        },
    )

    hint = candidate.source_chunk_hint

    assert hint is not None
    assert hint.start_seconds == pytest.approx(4.25)
    assert hint.end_seconds == pytest.approx(12.75)
    assert hint.score == pytest.approx(0.82)


def test_ranked_candidate_source_chunk_hint_prefers_pose_when_vlm_chunk_has_no_valid_evidence() -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="bench",
        exercise_name="Bench Press",
        exercise_slug="bench-press",
        candidate={
            "videoId": "pose",
            "url": "https://www.youtube.com/watch?v=pose",
            "title": "Pose-selected source",
            "visionPayload": {
                "bestChunkStartSeconds": 0.0,
                "bestChunkEndSeconds": 10.0,
                "bestChunkScore": 0.49,
                "validChunkCount": 0,
                "posePrefilter": {
                    "passed": True,
                    "score": 0.97,
                    "bestChunkStartSeconds": 12.0,
                    "bestChunkEndSeconds": 20.0,
                },
            },
        },
    )

    hint = candidate.source_chunk_hint

    assert hint is not None
    assert hint.start_seconds == pytest.approx(12.0)
    assert hint.end_seconds == pytest.approx(20.0)
    assert hint.score == pytest.approx(0.97)


def test_bake_and_rank_rejects_loops_over_max_duration() -> None:
    eligible, rejected = split_loops_by_duration(
        [
            {"startFrame": 0, "endFrame": 30, "durationSec": 3.0},
            {"startFrame": 0, "endFrame": 120, "durationSec": 12.0},
        ],
        max_loop_seconds=10.0,
    )

    assert [item.loop_index for item in eligible] == [0]
    assert [item.loop_index for item in rejected] == [1]
    assert rejected[0].reason == "loop_too_long"


def test_bake_and_rank_records_top_candidate_with_no_eligible_loops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_path = tmp_path / "youtube_candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "squat",
                        "exerciseName": "Squat",
                        "slug": "squat",
                        "candidates": [
                            {"videoId": "top", "url": "https://www.youtube.com/watch?v=top", "title": "Top"},
                            {"videoId": "second", "url": "https://www.youtube.com/watch?v=second", "title": "Second"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_generate(ranked_candidate: RankedCandidate, *, request: BakeAndRankRequest) -> GenerateResult:
        root = request.workspace / ranked_candidate.workspace_slug
        for directory in ("cleaned", "preview", "raw", "retarget", "wear", "input", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        loop_clip = build_loop_fixture_clip()
        long_loop_frames = loop_clip.frames * 4
        long_loop = MotionClip(
            fps=loop_clip.fps,
            joint_names=loop_clip.joint_names,
            frames=long_loop_frames,
            source=loop_clip.source,
            metadata=loop_clip.metadata,
        )
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        save_motion_json(cleaned_motion_json, long_loop)
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.write_text("<html></html>", encoding="utf-8")
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "source.mp4",
            cleanup_stats=CleanupStats(
                input_frames=1,
                output_frames=1,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fake_generate)
    artifact = BakedLoopArtifact(
        loop_index=-1,
        skeleton_path=tmp_path / "build" / "squat-001-top" / "wear" / "skeleton.baked.full-clip.no-foot-lock.json",
        skeleton_path_no_feet_lock=tmp_path / "build" / "squat-001-top" / "wear" / "skeleton.baked.full-clip.no-foot-lock.json",
        skeleton_path_no_hand_lock=tmp_path / "build" / "squat-001-top" / "wear" / "skeleton.baked.full-clip.no-hand-lock.json",
        review_video_path=tmp_path / "build" / "squat-001-top" / "review" / "full-clip.webm",
        export_payload={},
    )
    artifact.skeleton_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.skeleton_path.write_text("{}", encoding="utf-8")
    artifact.review_video_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.review_video_path.write_text("video-bytes", encoding="utf-8")

    def fake_bake_preview_loops_with_playwright(*args: object, **kwargs: object) -> list[BakedLoopArtifact]:
        artifact.skeleton_path.write_text(json.dumps({"frames": []}, ensure_ascii=False), encoding="utf-8")
        return [artifact]

    def fail_ranker(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("Ranker should not run without review items.")

    manifest = run_bake_and_rank_pipeline(
        BakeAndRankRequest(
            candidates_json=candidates_path,
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            fallback_candidates=1,
            classify_support_dominance=False,
        ),
        preview_baker=fake_bake_preview_loops_with_playwright,
        loop_ranker=fail_ranker,
    )

    assert manifest["candidateSelectionPolicy"] == "ranked_source_video_fallback_then_materialized_section_validation"
    assert len(manifest["candidateResults"]) == 1
    candidate_result = manifest["candidateResults"][0]
    assert candidate_result["candidate"]["videoId"] == "top"
    assert candidate_result["status"] == "ready_for_selection"
    assert manifest["selected"] is not None


def test_launch_chromium_browser_falls_back_to_system_executable(tmp_path: Path) -> None:
    fallback_executable = tmp_path / "chrome.exe"
    fallback_executable.write_text("", encoding="utf-8")

    class FakeChromium:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def launch(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            if "executable_path" not in kwargs:
                raise RuntimeError("bundled browser is missing")
            return {"browser": kwargs["executable_path"]}

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

    playwright = FakePlaywright()

    browser = bake_and_rank_module.launch_chromium_browser(
        playwright,
        fallback_executables=[fallback_executable],
    )

    assert browser == {"browser": str(fallback_executable)}
    assert playwright.chromium.calls == [
        {"headless": True},
        {"headless": True, "executable_path": str(fallback_executable)},
    ]


def test_process_ranked_candidate_stores_support_dominance_from_preview_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="pull-up",
        exercise_name="Pull Up",
        exercise_slug="pull-up",
        candidate={
            "videoId": "vid123",
            "url": "https://www.youtube.com/watch?v=vid123",
            "title": "Pull Up Demo",
        },
    )
    workspace_root = tmp_path / "build" / candidate.workspace_slug

    def fake_generate_candidate_motion(
        ranked_candidate: RankedCandidate,
        *,
        request: BakeAndRankRequest,
    ) -> GenerateResult:
        assert ranked_candidate.exercise_slug == candidate.exercise_slug
        root = request.workspace / ranked_candidate.workspace_slug
        root.mkdir(parents=True, exist_ok=True)
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.parent.mkdir(parents=True, exist_ok=True)
        preview_html.write_text("<html></html>", encoding="utf-8")
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        cleaned_motion_json.parent.mkdir(parents=True, exist_ok=True)
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=10,
                output_frames=10,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    artifact = BakedLoopArtifact(
        loop_index=-1,
        skeleton_path=workspace_root / "wear" / "skeleton.baked.full-clip.json",
        skeleton_path_no_feet_lock=workspace_root / "wear" / "skeleton.baked.full-clip.no-foot-lock.json",
        skeleton_path_no_hand_lock=workspace_root / "wear" / "skeleton.baked.full-clip.no-hand-lock.json",
        review_video_path=workspace_root / "review" / "full-clip.webm",
        export_payload={},
    )
    artifact.skeleton_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.skeleton_path.write_text("{}", encoding="utf-8")
    artifact.review_video_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.review_video_path.write_bytes(b"fake-video")

    def fake_preview_baker(
        preview_html_path: Path,
        eligible_loops: list[bake_and_rank_module.EligibleLoop],
        candidate_workspace: Path,
        review_frames: int,
    ) -> list[BakedLoopArtifact]:
        return [artifact]

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fake_generate_candidate_motion)
    monkeypatch.setattr(bake_and_rank_module, "bake_preview_loops_with_playwright", fake_preview_baker)
    monkeypatch.setattr(
        bake_and_rank_module,
        "classify_support_dominance_for_review_loop",
        lambda **_: SupportDominanceResult(
            support_dominance="hand_dominant",
            confidence=0.91,
            reason="Hands are used to pull the body upward.",
            exercise_name="Pull Up",
            uncertain=False,
            model_output={"supportDominance": "hand_dominant"},
        ),
    )

    review_items: list[ReviewItem] = []
    review_entries: list[dict[str, Any]] = []
    result = bake_and_rank_module.process_ranked_candidate(
        candidate,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            detect_source_segment=False,
            classify_support_dominance=False,
        ),
        preview_baker=fake_preview_baker,
        review_items=review_items,
        review_item_entries=review_entries,
        support_dominance_classifier=lambda frame_paths, prompt: "",
    )

    assert result["status"] == "ready_for_selection"
    assert len(review_items) == 1
    assert review_items[0].support_dominance == "hand_dominant"
    assert review_items[0].support_dominance_confidence == pytest.approx(0.91)
    assert review_items[0].support_dominance_uncertain is False
    assert review_items[0].support_dominance_model_output == {"supportDominance": "hand_dominant"}
    assert review_entries[0]["supportDominance"] == "hand_dominant"
    assert review_entries[0]["supportDominanceConfidence"] == pytest.approx(0.91)
    assert review_entries[0]["supportDominanceUncertain"] is False
    assert review_entries[0]["supportDominanceModelOutput"] == {"supportDominance": "hand_dominant"}


def test_parallel_candidate_processing_does_not_speculate_beyond_ready_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [
        RankedCandidate(
            exercise_index=0,
            candidate_rank=index,
            exercise_id="bench-press",
            exercise_name="Bench Press",
            exercise_slug="bench-press",
            candidate={"videoId": f"candidate-{index}", "title": f"Candidate {index}"},
        )
        for index in range(3)
    ]
    processed_ranks: list[int] = []

    def fake_process_ranked_candidate_isolated(
        ranked_candidate: RankedCandidate,
        request: BakeAndRankRequest,
        preview_baker,
        support_dominance_classifier,
    ):
        processed_ranks.append(ranked_candidate.candidate_rank)
        if ranked_candidate.candidate_rank == 1:
            time.sleep(0.05)
        return ({"status": "ready_for_selection"}, [], [])

    monkeypatch.setattr(
        bake_and_rank_module,
        "process_ranked_candidate_isolated",
        fake_process_ranked_candidate_isolated,
    )

    candidate_results, review_items, review_item_entries = bake_and_rank_module.process_ranked_candidates_for_selection(
        candidates,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            fallback_candidates=2,
            candidate_workers=2,
        ),
        preview_baker=None,
        support_dominance_classifier=None,
    )

    assert [result["status"] for result in candidate_results] == ["ready_for_selection", "ready_for_selection"]
    assert review_items == []
    assert review_item_entries == []
    assert processed_ranks == [0, 1]


def test_process_ranked_candidate_skips_clear_source_vision_gate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="bulgarian-split-squat",
        exercise_name="Bulgarian Split Squat",
        exercise_slug="bulgarian-split-squat",
        candidate={
            "videoId": "bad",
            "url": "https://www.youtube.com/watch?v=bad",
            "title": "Bad source",
            "visionPayload": {
                "bestChunkScore": 0.2,
                "static_camera_throughout": False,
                "single_person_chunk": True,
            },
        },
    )

    def fail_generate(*args: object, **kwargs: object) -> GenerateResult:
        raise AssertionError("Unusable vision-gated sources should not run WHAM.")

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fail_generate)

    result = bake_and_rank_module.process_ranked_candidate(
        candidate,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            classify_support_dominance=False,
        ),
        preview_baker=lambda *args, **kwargs: [],
        review_items=[],
        review_item_entries=[],
        support_dominance_classifier=None,
    )

    assert result["status"] == "skipped_source_gate"
    assert result["sourceGate"]["passed"] is False
    assert "low_ranked_source_chunk_score" in result["sourceGate"]["reasons"]
    assert "static_camera_throughout" in result["sourceGate"]["hardGateFailures"]


def test_process_ranked_candidate_skips_low_source_evidence_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="movement",
        exercise_name="Movement",
        exercise_slug="movement",
        candidate={
            "videoId": "thin-evidence",
            "url": "https://www.youtube.com/watch?v=thin",
            "title": "Movement source",
            "visionPayload": {
                "bestChunkScore": 0.6,
                "validChunkCount": 1,
                "validChunkRatio": 0.2,
                "scoredChunkCount": 5,
            },
        },
    )

    def fail_generate(*args: object, **kwargs: object) -> GenerateResult:
        raise AssertionError("Low source-evidence coverage should not run WHAM.")

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fail_generate)

    result = bake_and_rank_module.process_ranked_candidate(
        candidate,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            classify_support_dominance=False,
        ),
        preview_baker=lambda *args, **kwargs: [],
        review_items=[],
        review_item_entries=[],
        support_dominance_classifier=None,
    )

    assert result["status"] == "skipped_source_gate"
    assert "low_source_evidence_coverage" in result["sourceGate"]["reasons"]
    assert result["sourceGate"]["validChunkCount"] == 1
    assert result["sourceGate"]["validChunkRatio"] == pytest.approx(0.2)


def test_process_ranked_candidate_skips_zero_valid_source_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="movement",
        exercise_name="Movement",
        exercise_slug="movement",
        candidate={
            "videoId": "zero-valid",
            "url": "https://www.youtube.com/watch?v=zero",
            "title": "Movement source",
            "visionPayload": {
                "bestChunkScore": 0.49,
                "validChunkCount": 0,
                "validChunkRatio": 0.0,
                "scoredChunkCount": 2,
            },
        },
    )

    def fail_generate(*args: object, **kwargs: object) -> GenerateResult:
        raise AssertionError("A source with no valid reviewed chunks should not run WHAM.")

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fail_generate)

    result = bake_and_rank_module.process_ranked_candidate(
        candidate,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            classify_support_dominance=False,
        ),
        preview_baker=lambda *args, **kwargs: [],
        review_items=[],
        review_item_entries=[],
        support_dominance_classifier=None,
    )

    assert result["status"] == "skipped_source_gate"
    assert "no_valid_source_chunk_evidence" in result["sourceGate"]["reasons"]
    assert result["sourceGate"]["validChunkCount"] == 0


def test_source_gate_allows_strong_single_chunk_source() -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="movement",
        exercise_name="Movement",
        exercise_slug="movement",
        candidate={
            "videoId": "strong-chunk",
            "url": "https://www.youtube.com/watch?v=strong",
            "title": "Movement source",
            "visionPayload": {
                "bestChunkScore": 1.0,
                "validChunkCount": 1,
                "validChunkRatio": 0.2,
                "scoredChunkCount": 5,
                "target_identity_match": True,
            },
        },
    )

    source_gate = bake_and_rank_module.evaluate_source_candidate_gate(candidate)

    assert source_gate["passed"] is True
    assert "low_source_evidence_coverage" not in source_gate["reasons"]


def test_bake_and_rank_pipeline_wires_support_dominance_classifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_path = tmp_path / "youtube_candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "pull-up",
                        "exerciseName": "Pull Up",
                        "slug": "pull-up",
                        "candidates": [
                            {"videoId": "top", "url": "https://www.youtube.com/watch?v=top", "title": "Top"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def caption_images(self, **kwargs: object) -> str:
            return "support-classifier-output"

    class FakeLlamaCppVisionRanker:
        closed = 0

        def __init__(self, settings: object) -> None:
            self.client = FakeClient()

        def close(self) -> None:
            FakeLlamaCppVisionRanker.closed += 1

    def fake_generate_candidate_motion(
        ranked_candidate: RankedCandidate,
        *,
        request: BakeAndRankRequest,
    ) -> GenerateResult:
        root = request.workspace / ranked_candidate.workspace_slug
        root.mkdir(parents=True, exist_ok=True)
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.parent.mkdir(parents=True, exist_ok=True)
        preview_html.write_text("<html></html>", encoding="utf-8")
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        cleaned_motion_json.parent.mkdir(parents=True, exist_ok=True)
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=10,
                output_frames=10,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    def fake_preview_baker(
        preview_html_path: Path,
        eligible_loops: list[bake_and_rank_module.EligibleLoop],
        candidate_workspace: Path,
        review_frames: int,
    ) -> list[BakedLoopArtifact]:
        wear_dir = candidate_workspace / "wear"
        review_dir = candidate_workspace / "review"
        wear_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        skeleton_path = wear_dir / "skeleton.baked.full-clip.json"
        review_video_path = review_dir / "full-clip.webm"
        skeleton_path.write_text("{}", encoding="utf-8")
        review_video_path.write_bytes(b"video")
        return [
            BakedLoopArtifact(
                loop_index=-1,
                skeleton_path=skeleton_path,
                review_video_path=review_video_path,
                export_payload={},
            )
        ]

    def fake_classify_support_dominance_for_review_loop(**kwargs: object) -> SupportDominanceResult:
        classifier = kwargs["classifier"]
        assert callable(classifier)
        assert classifier(frame_paths=[], prompt="support prompt") == "support-classifier-output"
        return SupportDominanceResult(
            support_dominance="hand_dominant",
            confidence=0.93,
            reason="The hands are the stable contact points.",
            exercise_name="Pull Up",
            uncertain=False,
            model_output={"supportDominance": "hand_dominant"},
        )

    monkeypatch.setattr(bake_and_rank_module, "LlamaCppVisionRanker", FakeLlamaCppVisionRanker)
    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fake_generate_candidate_motion)
    monkeypatch.setattr(
        bake_and_rank_module,
        "classify_support_dominance_for_review_loop",
        fake_classify_support_dominance_for_review_loop,
    )

    manifest = run_bake_and_rank_pipeline(
        BakeAndRankRequest(
            candidates_json=candidates_path,
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            detect_source_segment=False,
            classify_support_dominance=True,
        ),
        preview_baker=fake_preview_baker,
    )

    assert FakeLlamaCppVisionRanker.closed == 1
    assert manifest["selected"]["supportDominance"] == "hand_dominant"
    assert manifest["selected"]["supportDominanceConfidence"] == pytest.approx(0.93)


def test_bake_and_rank_can_select_best_preview_settings_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_path = tmp_path / "youtube_candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "squat",
                        "exerciseName": "Squat",
                        "slug": "squat",
                        "candidates": [
                            {"videoId": "top", "url": "https://www.youtube.com/watch?v=top", "title": "Top"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_generate_candidate_motion(
        ranked_candidate: RankedCandidate,
        *,
        request: BakeAndRankRequest,
    ) -> GenerateResult:
        root = request.workspace / ranked_candidate.workspace_slug
        root.mkdir(parents=True, exist_ok=True)
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.parent.mkdir(parents=True, exist_ok=True)
        preview_html.write_text("<html></html>", encoding="utf-8")
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        cleaned_motion_json.parent.mkdir(parents=True, exist_ok=True)
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=10,
                output_frames=10,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    def fake_preview_baker(
        preview_html_path: Path,
        eligible_loops: list[bake_and_rank_module.EligibleLoop],
        candidate_workspace: Path,
        review_frames: int,
    ) -> list[BakedLoopArtifact]:
        wear_dir = candidate_workspace / "wear"
        review_dir = candidate_workspace / "review"
        wear_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        default_skeleton = wear_dir / "skeleton.baked.full-clip.json"
        no_lock_skeleton = wear_dir / "skeleton.baked.full-clip.no-support-lock.json"
        default_skeleton.write_text("{}", encoding="utf-8")
        no_lock_skeleton.write_text("{}", encoding="utf-8")
        default_video = review_dir / "full-clip.lock-feet-hands.webm"
        no_lock_video = review_dir / "full-clip.no-support-lock.webm"
        default_video.write_bytes(b"default")
        no_lock_video.write_bytes(b"no-lock")
        return [
            BakedLoopArtifact(
                loop_index=-1,
                skeleton_path=default_skeleton,
                skeleton_path_no_feet_lock=no_lock_skeleton,
                review_video_path=default_video,
                export_payload={},
                settings_variant_id="lock-feet-hands",
                settings_variant_label="Lock feet and hands",
                settings_options={"lockPlantedFeet": True, "lockPlantedHands": True},
            ),
            BakedLoopArtifact(
                loop_index=-1,
                skeleton_path=no_lock_skeleton,
                skeleton_path_no_feet_lock=no_lock_skeleton,
                review_video_path=no_lock_video,
                export_payload={},
                settings_variant_id="no-support-lock",
                settings_variant_label="No support lock",
                settings_options={"lockPlantedFeet": False, "lockPlantedHands": False},
            ),
        ]

    def fake_ranker(items: list[ReviewItem], request: BakeAndRankRequest) -> list[LoopRanking]:
        assert [item.settings_variant_id for item in items] == ["lock-feet-hands", "no-support-lock"]
        return [
            LoopRanking(score=0.25, reasons=["too rigid"]),
            LoopRanking(score=0.91, reasons=["clearer motion"]),
        ]

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fake_generate_candidate_motion)

    manifest = run_bake_and_rank_pipeline(
        BakeAndRankRequest(
            candidates_json=candidates_path,
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            detect_source_segment=False,
            rank_preview_variants=True,
            classify_support_dominance=False,
        ),
        preview_baker=fake_preview_baker,
        loop_ranker=fake_ranker,
    )

    assert manifest["previewSettingsVariantRankingEnabled"] is True
    assert manifest["selected"]["settingsVariantId"] == "no-support-lock"
    assert manifest["selected"]["ranking"]["score"] == pytest.approx(0.91)
    assert manifest["selected"]["selectedWearSkeletonPath"].endswith("skeleton.baked.full-clip.no-support-lock.json")


def test_materialize_llm_recommended_settings_without_time_cut_rebakes_selected_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Squat",
        candidate_title="Squat demo",
        candidate_workspace=tmp_path / "candidate",
        preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
        skeleton_path=tmp_path / "candidate" / "wear" / "selected.json",
        review_video_path=tmp_path / "candidate" / "review" / "selected.webm",
        duration_sec=4.0,
        loop_start_seconds=1.0,
        loop_end_seconds=5.0,
        candidate={"videoId": "abc"},
        settings_variant_id="lock-feet-hands",
        settings_variant_label="Lock feet and hands",
        settings_options={
            "lockPlantedFeet": True,
            "lockPlantedHands": True,
            "autoWorldAlignment": True,
        },
    )
    calls = []

    def fake_bake_preview_time_range_with_playwright(**kwargs):
        calls.append(kwargs)
        skeleton_path = tmp_path / "candidate" / "wear" / "llm-recommended-settings.json"
        review_video_path = tmp_path / "candidate" / "review" / "llm-recommended-settings.webm"
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": kwargs["end_seconds"] - kwargs["start_seconds"],
            },
            settings_variant_id=kwargs["artifact_id"],
            settings_variant_label=kwargs["artifact_label"],
            settings_options=kwargs["options"],
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    materialized_item, _ = bake_and_rank_module.materialize_llm_selected_time_range(
        (
            item,
            LoopRanking(
                score=0.83,
                reasons=["hands should stay free"],
                payload={"recommended_settings": {"lockPlantedHands": False}},
            ),
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=7,
        ),
    )

    assert len(calls) == 1
    assert calls[0]["artifact_id"] == "llm-recommended-settings"
    assert calls[0]["start_seconds"] == pytest.approx(1.0)
    assert calls[0]["end_seconds"] == pytest.approx(5.0)
    assert calls[0]["review_frames"] == 7
    assert calls[0]["options"]["lockPlantedFeet"] is True
    assert calls[0]["options"]["lockPlantedHands"] is False
    assert materialized_item.settings_variant_id == "llm-recommended-settings"
    assert materialized_item.settings_options["lockPlantedHands"] is False
    assert materialized_item.llm_time_range_cut_applied is False
    assert materialized_item.source_review_video_path == item.review_video_path
    assert materialized_item.source_skeleton_path == item.skeleton_path
    assert materialized_item.loop_start_seconds == pytest.approx(1.0)
    assert materialized_item.loop_end_seconds == pytest.approx(5.0)


def test_materialize_llm_selected_time_range_rebakes_with_recommended_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Pull Up",
        candidate_title="Pull up demo",
        candidate_workspace=tmp_path / "candidate",
        preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
        skeleton_path=tmp_path / "candidate" / "wear" / "selected.json",
        review_video_path=tmp_path / "candidate" / "review" / "selected.webm",
        duration_sec=4.0,
        loop_start_seconds=1.0,
        loop_end_seconds=5.0,
        candidate={"videoId": "abc"},
        settings_variant_id="lock-feet-hands",
        settings_variant_label="Lock feet and hands",
        settings_options={
            "lockPlantedFeet": True,
            "lockPlantedHands": True,
            "autoWorldAlignment": True,
        },
    )
    calls = []

    def fake_bake_preview_time_range_with_playwright(**kwargs):
        calls.append(kwargs)
        skeleton_path = tmp_path / "candidate" / "wear" / "llm-selected-section.json"
        review_video_path = tmp_path / "candidate" / "review" / "llm-selected-section.webm"
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": kwargs["end_seconds"] - kwargs["start_seconds"],
            },
            settings_variant_id=kwargs["artifact_id"],
            settings_variant_label=kwargs["artifact_label"],
            settings_options=kwargs["options"],
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    materialized_item, _ = bake_and_rank_module.materialize_llm_selected_time_range(
        (
            item,
            LoopRanking(
                score=0.91,
                reasons=["best middle rep"],
                payload={
                    "selected_section_start_seconds": 2.25,
                    "selected_section_end_seconds": 3.75,
                    "recommended_settings": {"lockPlantedFeet": False},
                },
            ),
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=5,
        ),
    )

    assert len(calls) == 1
    assert calls[0]["artifact_id"] == "llm-selected-section"
    assert calls[0]["start_seconds"] == pytest.approx(2.25)
    assert calls[0]["end_seconds"] == pytest.approx(3.75)
    assert calls[0]["options"]["lockPlantedFeet"] is False
    assert calls[0]["options"]["lockPlantedHands"] is True
    assert materialized_item.settings_variant_id == "llm-selected-section"
    assert materialized_item.settings_options["lockPlantedFeet"] is False
    assert materialized_item.llm_time_range_cut_applied is True
    assert materialized_item.loop_start_seconds == pytest.approx(2.25)
    assert materialized_item.loop_end_seconds == pytest.approx(3.75)


def test_materialize_llm_selected_full_span_still_rebakes_final_review_with_current_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bench Press",
        candidate_title="Bench press demo",
        candidate_workspace=tmp_path / "candidate",
        preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
        skeleton_path=tmp_path / "candidate" / "wear" / "selected.json",
        review_video_path=tmp_path / "candidate" / "review" / "selected.webm",
        duration_sec=4.0,
        loop_start_seconds=1.0,
        loop_end_seconds=5.0,
        candidate={"videoId": "abc"},
        settings_variant_id="adaptive-baseline",
        settings_variant_label="Adaptive baseline",
        settings_options={
            "fixedRoot": True,
            "autoWorldAlignment": True,
            "sceneInverted": True,
            "cameraPitchDegrees": 30.0,
        },
    )
    calls = []

    def fake_bake_preview_time_range_with_playwright(**kwargs):
        calls.append(kwargs)
        skeleton_path = tmp_path / "candidate" / "wear" / "llm-selected-section.json"
        review_video_path = tmp_path / "candidate" / "review" / "llm-selected-section.webm"
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": kwargs["end_seconds"] - kwargs["start_seconds"],
            },
            settings_variant_id=kwargs["artifact_id"],
            settings_variant_label=kwargs["artifact_label"],
            settings_options=kwargs["options"],
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    materialized_item, _ = bake_and_rank_module.materialize_llm_selected_time_range(
        (
            item,
            LoopRanking(
                score=0.91,
                reasons=["whole chunk is the movement"],
                payload={
                    "selected_section_start_seconds": 1.0,
                    "selected_section_end_seconds": 5.0,
                    "recommended_settings": {},
                },
            ),
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=5,
        ),
    )

    assert len(calls) == 1
    assert calls[0]["artifact_id"] == "llm-selected-section"
    assert calls[0]["start_seconds"] == pytest.approx(1.0)
    assert calls[0]["end_seconds"] == pytest.approx(5.0)
    expected_options = bake_and_rank_module.effective_review_item_preview_options(
        item,
        motion_tuning_enabled=True,
    )
    assert calls[0]["options"] == expected_options
    assert materialized_item.settings_variant_id == "llm-selected-section"
    assert materialized_item.settings_options == expected_options
    assert materialized_item.source_review_video_path == item.review_video_path
    assert materialized_item.llm_time_range_cut_applied is True


def test_materialized_time_range_rebakes_without_support_locks_when_locking_damages_kinematics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squats",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=candidate_workspace / "wear" / "selected.json",
        review_video_path=candidate_workspace / "review" / "selected.webm",
        duration_sec=4.0,
        loop_start_seconds=1.0,
        loop_end_seconds=5.0,
        candidate={"videoId": "abc"},
        settings_options={
            "lockPlantedFeet": True,
            "lockPlantedHands": False,
            "autoWorldAlignment": True,
        },
    )
    calls: list[dict[str, object]] = []

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        calls.append(dict(kwargs))
        artifact_id = str(kwargs["artifact_id"])
        options = dict(kwargs["options"])
        skeleton_path = candidate_workspace / "wear" / f"{artifact_id}.json"
        review_video_path = candidate_workspace / "review" / f"{artifact_id}.webm"
        if options.get("lockPlantedFeet"):
            write_leg_kinematic_artifact_skeleton(skeleton_path)
        else:
            write_motion_strength_skeleton(skeleton_path, [0.0, 0.30, 0.0])
        review_video_path.parent.mkdir(parents=True, exist_ok=True)
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": float(kwargs["end_seconds"]) - float(kwargs["start_seconds"]),
            },
            settings_variant_id=artifact_id,
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=options,
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    materialized_item, materialized_ranking = bake_and_rank_module.materialize_llm_selected_time_range(
        (
            item,
            LoopRanking(
                score=0.88,
                reasons=["best section"],
                payload={
                    "selected_section_start_seconds": 2.0,
                    "selected_section_end_seconds": 4.0,
                    "recommended_settings": {"lockPlantedFeet": True},
                },
            ),
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=5,
        ),
    )

    assert len(calls) == 2
    assert calls[0]["artifact_id"] == "llm-selected-section"
    assert calls[0]["options"]["lockPlantedFeet"] is True
    assert calls[1]["artifact_id"] == "llm-selected-section-no-support-lock"
    assert calls[1]["options"]["lockPlantedFeet"] is False
    assert calls[1]["options"]["lockPlantedHands"] is False
    assert materialized_item.settings_variant_id == "llm-selected-section-no-support-lock"
    assert materialized_item.settings_options["lockPlantedFeet"] is False
    assert materialized_ranking is not None
    assert "support_lock_safe_rebake" in materialized_ranking.reasons
    assert materialized_ranking.payload is not None
    assert materialized_ranking.payload["supportLockSafeRebakeApplied"] is True
    assert materialized_ranking.payload["supportLockSafeRebakeOriginalKinematicMetrics"]["severeArtifact"] is True
    assert materialized_ranking.payload["supportLockSafeRebakeKinematicMetrics"]["severeArtifact"] is False


def test_materialized_time_range_rebakes_without_support_locks_when_locking_damages_loop_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squats",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=candidate_workspace / "wear" / "selected.json",
        review_video_path=candidate_workspace / "review" / "selected.webm",
        duration_sec=4.0,
        loop_start_seconds=1.0,
        loop_end_seconds=5.0,
        candidate={"videoId": "abc"},
        settings_options={
            "lockPlantedFeet": True,
            "lockPlantedHands": False,
            "autoWorldAlignment": True,
        },
    )
    calls: list[dict[str, object]] = []

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        calls.append(dict(kwargs))
        artifact_id = str(kwargs["artifact_id"])
        options = dict(kwargs["options"])
        skeleton_path = candidate_workspace / "wear" / f"{artifact_id}.json"
        review_video_path = candidate_workspace / "review" / f"{artifact_id}.webm"
        if options.get("lockPlantedFeet"):
            write_loop_bridge_mismatch_skeleton(skeleton_path)
        else:
            write_motion_strength_skeleton(skeleton_path, [0.0, 0.30, 0.0])
        review_video_path.parent.mkdir(parents=True, exist_ok=True)
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": float(kwargs["end_seconds"]) - float(kwargs["start_seconds"]),
            },
            settings_variant_id=artifact_id,
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=options,
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    materialized_item, materialized_ranking = bake_and_rank_module.materialize_llm_selected_time_range(
        (
            item,
            LoopRanking(
                score=0.88,
                reasons=["best section"],
                payload={
                    "selected_section_start_seconds": 2.0,
                    "selected_section_end_seconds": 4.0,
                    "recommended_settings": {"lockPlantedFeet": True},
                },
            ),
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=5,
        ),
    )

    assert len(calls) == 2
    assert calls[0]["artifact_id"] == "llm-selected-section"
    assert calls[1]["artifact_id"] == "llm-selected-section-no-support-lock"
    assert materialized_item.settings_variant_id == "llm-selected-section-no-support-lock"
    assert materialized_ranking is not None
    assert "support_lock_safe_rebake" in materialized_ranking.reasons
    assert "support_lock_loop_bridge_rebake" in materialized_ranking.reasons
    assert materialized_ranking.payload is not None
    assert materialized_ranking.payload["supportLockSafeRebakeApplied"] is True
    assert materialized_ranking.payload["supportLockSafeRebakeOriginalKinematicMetrics"]["severeArtifact"] is False
    assert materialized_ranking.payload["supportLockSafeRebakeOriginalLoopBridgeQualityMetrics"]["severeLoopMismatch"] is True
    assert materialized_ranking.payload["supportLockSafeRebakeLoopBridgeQualityMetrics"]["severeLoopMismatch"] is False


def test_materialized_llm_section_can_pass_after_full_preview_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    preview_html = candidate_workspace / "preview" / "motion_preview.html"
    preview_html.parent.mkdir(parents=True)
    preview_html.write_text("<html></html>", encoding="utf-8")
    source_skeleton = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
    source_skeleton.parent.mkdir(parents=True)
    source_skeleton.write_text("{}", encoding="utf-8")
    source_review = candidate_workspace / "review" / "full-input.webm"
    source_review.parent.mkdir(parents=True)
    source_review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squats",
        candidate_workspace=candidate_workspace,
        preview_html_path=preview_html,
        skeleton_path=source_skeleton,
        review_video_path=source_review,
        duration_sec=9.3,
        loop_start_seconds=0.0,
        loop_end_seconds=9.3,
        candidate={"videoId": "I1Ee3M6SDgQ"},
    )
    original_ranking = LoopRanking(
        score=0.35,
        reasons=["good section", "loop_restart_discontinuity_penalty"],
        payload={
            "selected_section_start_seconds": 3.25,
            "selected_section_end_seconds": 7.32,
            "recommended_settings": {"lockPlantedFeet": True, "fixedRoot": True},
            "modelScore": 0.7,
        },
        model_score=0.7,
        continuity_score=0.0,
    )
    calls: list[dict[str, object]] = []

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        calls.append(dict(kwargs))
        skeleton_path = candidate_workspace / "wear" / "skeleton.baked.llm-selected-section.json"
        review_video_path = candidate_workspace / "review" / "llm-selected-section.webm"
        skeleton_path.write_text("{}", encoding="utf-8")
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": float(kwargs["end_seconds"]) - float(kwargs["start_seconds"]),
            },
            settings_variant_id=str(kwargs["artifact_id"]),
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=dict(kwargs["options"]),
        )

    def fake_apply_loop_continuity_adjustment(review_item: ReviewItem, ranking: LoopRanking) -> LoopRanking:
        assert review_item.settings_variant_id == "llm-selected-section"
        assert ranking.score == pytest.approx(0.7)
        return LoopRanking(
            score=0.65,
            reasons=[*ranking.reasons, "continuity_recomputed_for_materialized_section"],
            raw_response=ranking.raw_response,
            payload={
                **dict(ranking.payload or {}),
                "modelScore": ranking.score,
                "continuityScore": 0.6,
            },
            model_score=ranking.score,
            continuity_score=0.6,
            continuity_metrics={"continuityScore": 0.6},
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )
    monkeypatch.setattr(
        bake_and_rank_module,
        "apply_loop_continuity_adjustment",
        fake_apply_loop_continuity_adjustment,
    )

    selected, rejected_best = bake_and_rank_module.choose_best_materialized_review_item(
        [item],
        [original_ranking],
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            min_selected_score=0.55,
        ),
    )

    assert rejected_best is None
    assert selected is not None
    selected_item, selected_ranking = selected
    assert len(calls) == 1
    assert calls[0]["start_seconds"] == pytest.approx(3.25)
    assert calls[0]["end_seconds"] == pytest.approx(7.32)
    assert selected_item.llm_time_range_cut_applied is True
    assert selected_item.settings_options["lockPlantedFeet"] is True
    assert selected_item.source_skeleton_path == source_skeleton
    assert selected_ranking is not None
    assert selected_ranking.score == pytest.approx(0.65)
    assert "llm_materialized_before_threshold" in selected_ranking.reasons


def test_rank_review_items_with_llama_cpp_accepts_bake_request_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skeleton_path = tmp_path / "skeleton.json"
    skeleton_path.write_text("{}", encoding="utf-8")
    review_video_path = tmp_path / "review.webm"
    review_video_path.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Squat",
        candidate_title="Squat demo",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "motion_preview.html",
        skeleton_path=skeleton_path,
        review_video_path=review_video_path,
        duration_sec=3.0,
        loop_start_seconds=0.0,
        loop_end_seconds=3.0,
        candidate={"videoId": "abc"},
    )

    class FakeClient:
        def caption_images(self, **kwargs: object) -> str:
            return "caption"

    class FakeLlamaCppVisionRanker:
        closed = 0

        def __init__(self, settings: object) -> None:
            self.settings = settings
            self.client = FakeClient()

        def close(self) -> None:
            FakeLlamaCppVisionRanker.closed += 1

    def fake_rank_review_item_with_caption_images(
        review_item: ReviewItem,
        request: BakeAndRankRequest,
        caption_images: object,
    ) -> LoopRanking:
        assert review_item == item
        assert request.llama_cpp_base_url == "http://127.0.0.1:8090"
        assert request.llama_cpp_n_predict == 256
        assert callable(caption_images)
        return LoopRanking(score=0.74, reasons=["usable"])

    monkeypatch.setattr(bake_and_rank_module, "LlamaCppVisionRanker", FakeLlamaCppVisionRanker)
    monkeypatch.setattr(bake_and_rank_module, "rank_review_item_with_caption_images", fake_rank_review_item_with_caption_images)
    monkeypatch.setattr(bake_and_rank_module, "apply_loop_continuity_adjustment", lambda review_item, ranking: ranking)

    rankings = bake_and_rank_module.rank_review_items_with_llama_cpp(
        [item],
        BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            llama_cpp_n_predict=256,
        ),
    )

    assert FakeLlamaCppVisionRanker.closed == 1
    assert rankings == [LoopRanking(score=0.74, reasons=["usable"])]


def test_classify_support_dominance_from_review_loop_uses_classification_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {"called": 0}
    expected_frame_paths: list[Path] = []
    review_video = tmp_path / "review.webm"
    review_video.write_bytes(b"video")
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for index in range(3):
        frame_path = frame_dir / f"frame_{index:02d}.jpg"
        frame_path.write_bytes(b"frame")
        expected_frame_paths.append(frame_path)

    def fake_read_basic_video_metadata(path: Path):
        from exercise_motion_pkg.video_utils import BasicVideoMetadata
        return BasicVideoMetadata(fps=30.0, frame_count=30, width=640, height=480)

    def fake_extract_window_frames(
        *,
        video_path: Path,
        window: DetectionWindow,
        frames_per_window: int,
        max_frame_width: int,
        output_dir: Path,
    ) -> list[Path]:
        assert frames_per_window == 7
        assert float(window.start_seconds) == 0.0
        assert float(window.end_seconds) == pytest.approx(1.0)
        return expected_frame_paths

    def fake_classify_support_dominance_from_frames(
        *,
        frame_paths: list[Path],
        exercise_name: str,
        caption_images: object,
    ) -> SupportDominanceResult:
        calls["called"] += 1
        assert exercise_name == "Pull Up"
        assert frame_paths == expected_frame_paths
        return SupportDominanceResult(
            support_dominance="hand_dominant",
            confidence=0.9,
            reason="Hands are clearly propelling the movement.",
            exercise_name=exercise_name,
            uncertain=False,
            model_output={"supportDominance": "hand_dominant"},
        )

    def fake_caption_images(*, frame_paths: list[Path], prompt: str) -> str:
        return "unused"

    monkeypatch.setattr(bake_and_rank_module, "read_basic_video_metadata", fake_read_basic_video_metadata)
    monkeypatch.setattr(bake_and_rank_module, "extract_window_frames", fake_extract_window_frames)
    monkeypatch.setattr(
        bake_and_rank_module,
        "classify_support_dominance_from_frames",
        fake_classify_support_dominance_from_frames,
    )

    result = bake_and_rank_module.classify_support_dominance_for_review_loop(
        review_video_path=review_video,
        exercise_name="Pull Up",
        classifier=fake_caption_images,
        candidate_workspace=tmp_path,
        loop_index=0,
        sample_frames=7,
    )

    assert calls["called"] == 1
    assert result is not None
    assert result.support_dominance == "hand_dominant"
    assert result.confidence == pytest.approx(0.9)


def test_generate_candidate_motion_trims_llm_selected_source_segment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    captured: dict[str, Path] = {}

    def fake_detect_exercise_segment(**kwargs: object) -> DetectionResult:
        return DetectionResult(
            video_path=str(kwargs["video_path"]),
            exercise_name=str(kwargs["exercise_name"]),
            source_duration_seconds=20.0,
            window_seconds=8.0,
            overlap_seconds=4.0,
            detected_span=DetectedSpan(
                start_seconds=3.0,
                end_seconds=9.0,
                confidence=0.85,
                average_camera_variation=0.01,
                contributing_windows=[0, 1],
            ),
            windows=[],
        )

    def fake_trim_video(**kwargs: object) -> Path:
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"trimmed")
        captured["trim_start"] = float(kwargs["start_seconds"])
        captured["trim_end"] = float(kwargs["end_seconds"])
        return output_path

    def fake_run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
        assert request.video_path is not None
        captured["video_path"] = request.video_path
        root = request.workspace / request.exercise_slug
        for directory in ("cleaned", "preview", "raw", "retarget", "wear", "input", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.write_text("<html></html>", encoding="utf-8")
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=1,
                output_frames=1,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    monkeypatch.setattr(bake_and_rank_module, "detect_exercise_segment", fake_detect_exercise_segment)
    monkeypatch.setattr(bake_and_rank_module, "trim_video", fake_trim_video)
    monkeypatch.setattr(bake_and_rank_module, "run_generation_pipeline", fake_run_generation_pipeline)

    result = bake_and_rank_module.generate_candidate_motion(
        RankedCandidate(
            exercise_index=0,
            candidate_rank=0,
            exercise_id="clean-and-jerk",
            exercise_name="Clean and Jerk",
            exercise_slug="clean-and-jerk",
            candidate={"videoPath": str(source_video), "title": "Clean and Jerk"},
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            segment_padding_seconds=0.5,
            segment_end_padding_seconds=3.0,
        ),
    )

    assert result.cleaned_motion_json_path.exists()
    assert captured["video_path"].name == "selected_segment.mp4"
    assert captured["trim_start"] == pytest.approx(2.5)
    assert captured["trim_end"] == pytest.approx(12.0)
    assert (tmp_path / "build" / "clean-and-jerk-001-clean-and-jerk" / "segment_detection" / "segment_detection.json").exists()


def test_generate_candidate_motion_detects_inside_ranked_source_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    captured: dict[str, object] = {"trim_calls": []}

    def fake_detect_exercise_segment(**kwargs: object) -> DetectionResult:
        video_path = Path(str(kwargs["video_path"]))
        assert video_path.name == "source_ranked_best_chunk.mp4"
        return DetectionResult(
            video_path=str(video_path),
            exercise_name=str(kwargs["exercise_name"]),
            source_duration_seconds=14.0,
            window_seconds=8.0,
            overlap_seconds=4.0,
            detected_span=DetectedSpan(
                start_seconds=2.0,
                end_seconds=8.0,
                confidence=0.9,
                average_camera_variation=0.01,
                contributing_windows=[0],
            ),
            windows=[],
        )

    def fake_trim_video(**kwargs: object) -> Path:
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"trimmed")
        trim_calls = captured["trim_calls"]
        assert isinstance(trim_calls, list)
        trim_calls.append(
            {
                "source_path": Path(kwargs["source_path"]),
                "output_path": output_path,
                "start_seconds": float(kwargs["start_seconds"]),
                "end_seconds": float(kwargs["end_seconds"]),
            }
        )
        return output_path

    def fake_run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
        assert request.video_path is not None
        captured["video_path"] = request.video_path
        root = request.workspace / request.exercise_slug
        for directory in ("cleaned", "preview", "raw", "retarget", "wear", "input", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.write_text("<html></html>", encoding="utf-8")
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=1,
                output_frames=1,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    class FakeLlamaCppVisionRanker:
        def __init__(self, settings: YouTubeRankingSettings) -> None:
            self.settings = settings

        def close(self) -> None:
            pass

    monkeypatch.setattr(bake_and_rank_module, "detect_exercise_segment", fake_detect_exercise_segment)
    monkeypatch.setattr(bake_and_rank_module, "trim_video", fake_trim_video)
    monkeypatch.setattr(bake_and_rank_module, "run_generation_pipeline", fake_run_generation_pipeline)
    monkeypatch.setattr(bake_and_rank_module, "LlamaCppVisionRanker", FakeLlamaCppVisionRanker)

    result = bake_and_rank_module.generate_candidate_motion(
        RankedCandidate(
            exercise_index=0,
            candidate_rank=0,
            exercise_id="bulgarian-split-squat",
            exercise_name="Bulgarian Split Squat",
            exercise_slug="bulgarian-split-squat",
            candidate={
                "videoPath": str(source_video),
                "title": "Bulgarian Split Squat",
                "visionPayload": {
                    "bestChunkStartSeconds": 33.0,
                    "bestChunkEndSeconds": 47.0,
                    "bestChunkScore": 0.8,
                },
            },
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            segment_padding_seconds=0.5,
            segment_end_padding_seconds=3.0,
        ),
    )

    assert result.cleaned_motion_json_path.exists()
    assert captured["video_path"].name == "selected_segment.mp4"
    trim_calls = captured["trim_calls"]
    assert isinstance(trim_calls, list)
    assert len(trim_calls) == 2
    assert trim_calls[0]["output_path"].name == "source_ranked_best_chunk.mp4"
    assert trim_calls[0]["start_seconds"] == pytest.approx(33.0)
    assert trim_calls[0]["end_seconds"] == pytest.approx(47.0)
    assert trim_calls[1]["source_path"].name == "source_ranked_best_chunk.mp4"
    assert trim_calls[1]["start_seconds"] == pytest.approx(1.5)
    assert trim_calls[1]["end_seconds"] == pytest.approx(11.0)

    selection_path = (
        tmp_path
        / "build"
        / "bulgarian-split-squat-001-bulgarian-split-squat"
        / "segment_detection"
        / "segment_selection.json"
    )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert selection["source"] == "segment_detection"
    assert selection["sourcePrepReason"] == "segment_detection"
    assert selection["sourceChunkHint"]["startSeconds"] == pytest.approx(33.0)
    assert selection["sourceChunkHint"]["endSeconds"] == pytest.approx(47.0)
    assert selection["selectedSpan"]["startSeconds"] == pytest.approx(2.0)
    assert selection["selectedSpan"]["endSeconds"] == pytest.approx(8.0)
    assert selection["selectedSpanInOriginalSource"]["startSeconds"] == pytest.approx(35.0)
    assert selection["selectedSpanInOriginalSource"]["endSeconds"] == pytest.approx(41.0)


def test_generate_candidate_motion_uses_strong_short_ranked_source_chunk_without_segment_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    captured: dict[str, object] = {"trim_calls": []}

    def fake_detect_exercise_segment(**kwargs: object) -> DetectionResult:
        raise AssertionError("segment detection should be skipped for a strong short ranked chunk")

    def fake_trim_video(**kwargs: object) -> Path:
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ranked chunk")
        trim_calls = captured["trim_calls"]
        assert isinstance(trim_calls, list)
        trim_calls.append(
            {
                "source_path": Path(kwargs["source_path"]),
                "output_path": output_path,
                "start_seconds": float(kwargs["start_seconds"]),
                "end_seconds": float(kwargs["end_seconds"]),
            }
        )
        return output_path

    def fake_run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
        assert request.video_path is not None
        captured["video_path"] = request.video_path
        root = request.workspace / request.exercise_slug
        for directory in ("cleaned", "preview", "raw", "retarget", "wear", "input", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.write_text("<html></html>", encoding="utf-8")
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=1,
                output_frames=1,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    monkeypatch.setattr(bake_and_rank_module, "detect_exercise_segment", fake_detect_exercise_segment)
    monkeypatch.setattr(bake_and_rank_module, "trim_video", fake_trim_video)
    monkeypatch.setattr(bake_and_rank_module, "run_generation_pipeline", fake_run_generation_pipeline)

    result = bake_and_rank_module.generate_candidate_motion(
        RankedCandidate(
            exercise_index=0,
            candidate_rank=0,
            exercise_id="bench-press",
            exercise_name="Bench Press",
            exercise_slug="bench-press",
            candidate={
                "videoPath": str(source_video),
                "title": "Bench Press",
                "visionPayload": {
                    "bestChunkStartSeconds": 6.0,
                    "bestChunkEndSeconds": 15.0,
                    "bestChunkScore": 0.95,
                },
            },
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
        ),
    )

    assert result.cleaned_motion_json_path.exists()
    assert captured["video_path"].name == "selected_segment.mp4"
    trim_calls = captured["trim_calls"]
    assert isinstance(trim_calls, list)
    assert len(trim_calls) == 1
    assert trim_calls[0]["start_seconds"] == pytest.approx(6.0)
    assert trim_calls[0]["end_seconds"] == pytest.approx(15.0)

    selection_path = (
        tmp_path
        / "build"
        / "bench-press-001-bench-press"
        / "segment_detection"
        / "segment_selection.json"
    )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert selection["source"] == "ranked_best_chunk"
    assert selection["sourcePrepReason"] == "ranked_best_chunk"
    assert selection["selectedSpanInOriginalSource"]["startSeconds"] == pytest.approx(6.0)
    assert selection["selectedSpanInOriginalSource"]["endSeconds"] == pytest.approx(15.0)


def test_generate_candidate_motion_falls_back_to_strong_ranked_source_chunk_on_detection_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    captured: dict[str, object] = {"trim_calls": []}

    def fake_detect_exercise_segment(**kwargs: object) -> DetectionResult:
        raise TimeoutError("timed out")

    def fake_trim_video(**kwargs: object) -> Path:
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ranked chunk")
        trim_calls = captured["trim_calls"]
        assert isinstance(trim_calls, list)
        trim_calls.append(
            {
                "source_path": Path(kwargs["source_path"]),
                "output_path": output_path,
                "start_seconds": float(kwargs["start_seconds"]),
                "end_seconds": float(kwargs["end_seconds"]),
            }
        )
        return output_path

    def fake_run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
        assert request.video_path is not None
        captured["video_path"] = request.video_path
        root = request.workspace / request.exercise_slug
        for directory in ("cleaned", "preview", "raw", "retarget", "wear", "input", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.write_text("<html></html>", encoding="utf-8")
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=1,
                output_frames=1,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    class FakeLlamaCppVisionRanker:
        def __init__(self, settings: YouTubeRankingSettings) -> None:
            self.settings = settings

        def close(self) -> None:
            pass

    monkeypatch.setattr(bake_and_rank_module, "detect_exercise_segment", fake_detect_exercise_segment)
    monkeypatch.setattr(bake_and_rank_module, "trim_video", fake_trim_video)
    monkeypatch.setattr(bake_and_rank_module, "run_generation_pipeline", fake_run_generation_pipeline)
    monkeypatch.setattr(bake_and_rank_module, "LlamaCppVisionRanker", FakeLlamaCppVisionRanker)

    result = bake_and_rank_module.generate_candidate_motion(
        RankedCandidate(
            exercise_index=0,
            candidate_rank=0,
            exercise_id="bulgarian-split-squat",
            exercise_name="Bulgarian Split Squat",
            exercise_slug="bulgarian-split-squat",
            candidate={
                "videoPath": str(source_video),
                "title": "Bulgarian Split Squat",
                "visionPayload": {
                    "bestChunkStartSeconds": 6.0,
                    "bestChunkEndSeconds": 31.0,
                    "bestChunkScore": 1.0,
                },
            },
        ),
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
        ),
    )

    assert result.cleaned_motion_json_path.exists()
    assert captured["video_path"].name == "selected_segment.mp4"
    trim_calls = captured["trim_calls"]
    assert isinstance(trim_calls, list)
    assert len(trim_calls) == 1
    assert trim_calls[0]["output_path"].name == "source_ranked_best_chunk.mp4"
    assert trim_calls[0]["start_seconds"] == pytest.approx(6.0)
    assert trim_calls[0]["end_seconds"] == pytest.approx(31.0)

    selection_path = (
        tmp_path
        / "build"
        / "bulgarian-split-squat-001-bulgarian-split-squat"
        / "segment_detection"
        / "segment_selection.json"
    )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert selection["source"] == "segment_detection_fallback"
    assert selection["sourcePrepReason"] == "segment_detection_fallback"
    assert selection["fallbackErrorType"] == "TimeoutError"
    assert selection["selectedSpan"]["startSeconds"] == pytest.approx(0.0)
    assert selection["selectedSpan"]["endSeconds"] == pytest.approx(25.0)
    assert selection["selectedSpanInOriginalSource"]["startSeconds"] == pytest.approx(6.0)
    assert selection["selectedSpanInOriginalSource"]["endSeconds"] == pytest.approx(31.0)


def test_bake_and_rank_wrapper_defaults_to_adaptive_without_preset_or_support_dominance() -> None:
    script = (Path(__file__).resolve().parents[1] / "scripts" / "run_exercise_motion_bake_and_rank.ps1").read_text(
        encoding="utf-8"
    )

    assert "[int]$MaxAdaptivePreviewSettings = 1" in script
    assert "if ($RankPreviewVariants -and -not $SkipPreviewVariantRanking)" in script
    assert "if ($AdaptivePreviewSettings -or (-not $SkipAdaptivePreviewSettings -and -not $RankPreviewVariants))" in script
    assert '\"--adaptive-preview-settings\"' in script
    assert '\"--no-classify-support-dominance\"' in script
    assert "if (-not $ClassifySupportDominance -or $SkipSupportDominanceClassification)" in script


def test_youtube_bake_and_rank_wrapper_defaults_to_adaptive_without_preset_or_support_dominance() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_exercise_motion_youtube_bake_and_rank.ps1"
    ).read_text(encoding="utf-8")

    assert "[int]$ResultsPerQuery = 25" in script
    assert "[int]$YoutubeSearchEmptyRetries = 5" in script
    assert '"--youtube-search-empty-retries", "$YoutubeSearchEmptyRetries"' in script
    assert "[string]$YouTubeCookiesPath" in script
    assert '"--youtube-cookies", $YouTubeCookiesPath' in script
    assert "[int]$MaxAdaptivePreviewSettings = 1" in script
    assert "[int]$MaxCandidates = 12" in script
    assert "[int]$MetadataCandidatePoolSize = 36" in script
    assert "[int]$VisionCandidatesPerExercise = 12" in script
    assert "[Nullable[int]]$SemanticGateCandidatesPerExercise = 12" in script
    assert "[Nullable[int]]$PosePrefilterCandidatesPerExercise = 12" in script
    assert "[int]$FallbackCandidates = 5" in script
    assert "[double]$PosePrefilterSampleFps = 1.0" in script
    assert "[double]$PosePrefilterMaxSeconds = 32.0" in script
    assert "if ($PosePrefilter -or -not $SkipPosePrefilter)" in script
    assert "[switch]$SkipSemanticGate" in script
    assert "[double]$SemanticGateTimeoutSeconds = 0.0" in script
    assert "if ($SemanticGateWithLiteRt -or -not $SkipSemanticGate)" in script
    assert "if ($RankPreviewVariants -and -not $SkipPreviewVariantRanking)" in script
    assert "if ($AdaptivePreviewSettings -or (-not $SkipAdaptivePreviewSettings -and -not $RankPreviewVariants))" in script
    assert '\"--adaptive-preview-settings\"' in script
    assert '\"--no-classify-support-dominance\"' in script
    assert "if (-not $ClassifySupportDominance -or $SkipSupportDominanceClassification)" in script


def test_workout_plan_wrapper_keeps_pose_prefilter_opt_in() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_exercise_motion_workout_plan.ps1"
    ).read_text(encoding="utf-8")

    assert "if ($PosePrefilter -and -not $SkipPosePrefilter)" in script
    assert "if ($PosePrefilter -or -not $SkipPosePrefilter)" not in script
    assert "[double]$SemanticGateTimeoutSeconds = 0.0" in script


def test_loop_ranking_parser_handles_valid_malformed_and_missing_score() -> None:
    valid = parse_loop_ranking_response('{"score": 0.82, "reasons": ["smooth", "readable"]}')
    malformed = parse_loop_ranking_response("not json")
    missing_score = parse_loop_ranking_response('{"reasons": ["no score"]}')

    assert valid.score == pytest.approx(0.82)
    assert valid.reasons == ["smooth", "readable"]
    assert malformed.score == 0.0
    assert malformed.reasons == ["ranking_invalid_json"]
    assert missing_score.score == 0.0
    assert missing_score.reasons == ["ranking_missing_score"]


def test_review_video_capture_samples_loop_frames_and_export_fps() -> None:
    payload = {"frameCount": 87, "fps": 30.0}

    assert sample_review_frame_indices(payload, 8) == [0, 12, 25, 37, 49, 61, 74, 86]
    assert dense_loop_review_video_frame_indices(payload) == list(range(87))
    assert repeated_review_frame_data_urls(["f0", "f1", "f2"], repeats=3) == [
        "f0",
        "f1",
        "f2",
        "f1",
        "f2",
        "f1",
        "f2",
    ]
    assert repeated_review_frame_data_urls(["f0", "f1"], repeats=1) == ["f0", "f1"]
    capped = dense_loop_review_video_frame_indices({"frameCount": 500, "fps": 30.0})
    assert len(capped) == 360
    assert capped[0] == 0
    assert capped[-1] == 499
    assert parse_export_fps(payload) == pytest.approx(30.0)
    assert parse_export_fps({"fps": 0}) == pytest.approx(30.0)


def test_selected_section_review_video_is_not_time_stretched_by_default() -> None:
    assert bake_and_rank_module.SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS == 1
    assert repeated_review_frame_data_urls(
        ["f0", "f1", "f2"],
        repeats=bake_and_rank_module.SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS,
    ) == ["f0", "f1", "f2"]


def test_selected_section_review_video_cache_requires_current_repeat_metadata(tmp_path: Path) -> None:
    metadata_path = tmp_path / "review_video.json"
    export_payload = {"frameCount": 87, "fps": 30.0}

    assert bake_and_rank_module.selected_section_review_video_cache_is_current(
        metadata_path,
        export_payload=export_payload,
    ) is False

    metadata_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "frameCount": 87,
                "repeats": 3,
            }
        ),
        encoding="utf-8",
    )
    assert bake_and_rank_module.selected_section_review_video_cache_is_current(
        metadata_path,
        export_payload=export_payload,
    ) is False

    metadata_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "frameCount": 87,
                "repeats": bake_and_rank_module.SELECTED_SECTION_REVIEW_VIDEO_LOOP_REPEATS,
            }
        ),
        encoding="utf-8",
    )
    assert bake_and_rank_module.selected_section_review_video_cache_is_current(
        metadata_path,
        export_payload=export_payload,
    ) is True


def test_loop_time_bounds_ignore_synthetic_bridge_frames() -> None:
    start, end = bake_and_rank_module.loop_time_bounds_from_export(
        {
            "frames": [
                {"sourceTimeSec": 3.25},
                {"sourceTimeSec": 4.25},
                {"sourceTimeSec": 7.32},
                {"sourceTimeSec": 3.58, "syntheticLoopBridge": True},
            ]
        },
        fallback=bake_and_rank_module.EligibleLoop(
            loop_index=-1,
            loop={},
            duration_sec=0.0,
            start_seconds=0.0,
            end_seconds=0.0,
        ),
    )

    assert start == pytest.approx(3.25)
    assert end == pytest.approx(7.32)


def test_loop_continuity_adjustment_penalizes_bad_restart_seam(tmp_path: Path) -> None:
    good_skeleton = tmp_path / "good.json"
    bad_skeleton = tmp_path / "bad.json"
    good_skeleton.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "left_ankle"],
                "frames": [
                    {"joints": {"pelvis": [0.0, 1.0, 0.0], "left_ankle": [0.0, 0.0, 0.0]}},
                    {"joints": {"pelvis": [0.1, 1.0, 0.0], "left_ankle": [0.1, 0.0, 0.0]}},
                    {"joints": {"pelvis": [0.0, 1.0, 0.0], "left_ankle": [0.0, 0.0, 0.0]}},
                ],
            }
        ),
        encoding="utf-8",
    )
    bad_skeleton.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "left_ankle"],
                "frames": [
                    {"joints": {"pelvis": [0.0, 1.0, 0.0], "left_ankle": [0.0, 0.0, 0.0]}},
                    {"joints": {"pelvis": [0.1, 1.0, 0.0], "left_ankle": [0.1, 0.0, 0.0]}},
                    {"joints": {"pelvis": [0.4, 1.0, 0.0], "left_ankle": [0.4, 0.0, 0.0]}},
                ],
            }
        ),
        encoding="utf-8",
    )
    candidate_workspace = tmp_path / "candidate"
    good_item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Squat",
        candidate_title="Top",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=good_skeleton,
        review_video_path=candidate_workspace / "review" / "good.webm",
        duration_sec=3.0,
        loop_start_seconds=0.0,
        loop_end_seconds=3.0,
        candidate={"videoId": "top"},
    )
    bad_item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=1,
        exercise_name="Squat",
        candidate_title="Top",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=bad_skeleton,
        review_video_path=candidate_workspace / "review" / "bad.webm",
        duration_sec=3.0,
        loop_start_seconds=0.0,
        loop_end_seconds=3.0,
        candidate={"videoId": "top"},
    )

    good_adjusted = apply_loop_continuity_adjustment(good_item, LoopRanking(score=0.65, reasons=[]))
    bad_adjusted = apply_loop_continuity_adjustment(bad_item, LoopRanking(score=0.75, reasons=[]))

    good_metrics = compute_loop_continuity_metrics(good_skeleton)
    bad_metrics = compute_loop_continuity_metrics(bad_skeleton)

    assert good_metrics["continuityScore"] > bad_metrics["continuityScore"]
    assert good_adjusted.score == pytest.approx(0.65)
    assert bad_adjusted.score == pytest.approx(0.75)
    assert "deterministic_review_validation_skipped" in bad_adjusted.reasons
    assert "loop_restart_discontinuity_penalty" not in bad_adjusted.reasons
    assert bad_adjusted.payload is not None
    assert bad_adjusted.payload["deterministicReviewValidationSkipped"] is True
    assert good_adjusted.model_score is None
    assert good_adjusted.continuity_score is None


def test_loop_bridge_quality_detects_endpoint_mismatch_hidden_by_bridge(tmp_path: Path) -> None:
    skeleton = tmp_path / "bridge-mismatch.json"
    write_loop_bridge_mismatch_skeleton(skeleton)
    candidate_workspace = tmp_path / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bridge mismatch",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton,
        review_video_path=candidate_workspace / "review" / "bridge.webm",
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"videoId": "bridge"},
    )

    metrics = compute_loop_bridge_quality_metrics(skeleton)
    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert metrics["severeLoopMismatch"] is True
    assert metrics["endpointJoint"] == "left_knee"
    assert metrics["endpointMaxDistanceBodyRatio"] >= 0.10
    assert adjusted.score > 0.55
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert "loop_bridge_pose_mismatch_penalty" not in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_multi_phase_motion_does_not_require_loop_seam_for_acceptance(tmp_path: Path) -> None:
    skeleton = tmp_path / "clean-and-jerk-one-shot.json"
    write_loop_bridge_mismatch_skeleton(skeleton)
    candidate_workspace = tmp_path / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Clean and Jerk",
        candidate_title="Clean and jerk",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton,
        review_video_path=candidate_workspace / "review" / "clean-and-jerk.webm",
        duration_sec=8.0,
        loop_start_seconds=0.0,
        loop_end_seconds=8.0,
        candidate={"videoId": "clean"},
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert adjusted.score > 0.55
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert "loop_bridge_pose_mismatch_penalty" not in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_loop_ranking_prompt_describes_clean_movement_goal_for_multi_phase_lifts(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Clean and Jerk",
        candidate_title="Clean and jerk",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=8.0,
        loop_start_seconds=0.0,
        loop_end_seconds=8.0,
        candidate={"videoId": "clean"},
    )
    chunk_estimate = bake_and_rank_module.estimate_chunking(
        exercise_name="Clean and Jerk",
        litert_command="litert-lm",
        use_llm=False,
    )

    prompt = bake_and_rank_module.build_loop_ranking_prompt(
        item,
        chunk_window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=8.0),
        chunk_index=0,
        chunk_count=1,
        chunk_estimate=chunk_estimate,
        original_chunk_index=0,
        original_chunk_count=1,
        deterministic_window_score=0.8,
        review_frame_count=16,
    )

    assert "cleanest complete exercise movement section" in prompt
    assert "Loop continuity required for final acceptance: false" in prompt
    assert "Do not require the start and end poses to match" in prompt
    assert "one-shot exercise animation clip" in prompt


def test_loop_ranking_prompt_prioritizes_actual_movement_boundaries_for_rep_lifts(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Barbell Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=10.0,
        loop_start_seconds=0.0,
        loop_end_seconds=10.0,
        candidate={"videoId": "bench"},
    )
    chunk_estimate = bake_and_rank_module.estimate_chunking(
        exercise_name="Barbell Bench Press",
        litert_command="litert-lm",
        use_llm=False,
    )

    prompt = bake_and_rank_module.build_loop_ranking_prompt(
        item,
        chunk_window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=10.0),
        chunk_index=0,
        chunk_count=1,
        chunk_estimate=chunk_estimate,
        original_chunk_index=0,
        original_chunk_count=1,
        deterministic_window_score=0.8,
        review_frame_count=16,
    )

    assert "cut to the actual exercise movement" in prompt
    assert "first frame where the loaded movement begins" in prompt
    assert "Only select the entire chunk when its first and last frames are already the true movement boundaries" in prompt
    assert "extra holds" in prompt
    assert "clean complete movement clip over a seamless loop" in prompt


def test_loop_ranking_prompt_penalizes_unreadable_orientation(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Barbell Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=10.0,
        loop_start_seconds=0.0,
        loop_end_seconds=10.0,
        candidate={"videoId": "bench"},
    )
    chunk_estimate = bake_and_rank_module.estimate_chunking(
        exercise_name="Barbell Bench Press",
        litert_command="litert-lm",
        use_llm=False,
    )

    prompt = bake_and_rank_module.build_loop_ranking_prompt(
        item,
        chunk_window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=10.0),
        chunk_index=0,
        chunk_count=1,
        chunk_estimate=chunk_estimate,
        original_chunk_index=0,
        original_chunk_count=1,
        deterministic_window_score=0.8,
        review_frame_count=32,
    )

    assert "upside down" in prompt
    assert "do not give it a high score" in prompt
    assert "sceneInverted" in prompt
    assert "cameraPitchDegrees" in prompt


def test_loop_ranking_prompt_does_not_repeat_settings_catalog_after_adaptive_planning(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Barbell Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=10.0,
        loop_start_seconds=0.0,
        loop_end_seconds=10.0,
        candidate={"videoId": "bench"},
        settings_variant_id="adaptive-orientation-fix",
        settings_variant_label="Adaptive orientation fix",
        settings_options={"sceneInverted": True, "cameraPitchDegrees": 20.0},
    )
    chunk_estimate = bake_and_rank_module.estimate_chunking(
        exercise_name="Barbell Bench Press",
        litert_command="litert-lm",
        use_llm=False,
    )

    prompt = bake_and_rank_module.build_loop_ranking_prompt(
        item,
        chunk_window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=10.0),
        chunk_index=0,
        chunk_count=1,
        chunk_estimate=chunk_estimate,
        original_chunk_index=0,
        original_chunk_count=1,
        deterministic_window_score=0.8,
        review_frame_count=32,
        allow_settings_recommendations=False,
    )

    assert "cut to the actual exercise movement" in prompt
    assert "Render settings have already been chosen by the adaptive settings planner" in prompt
    assert "return recommended_settings as an empty object" in prompt
    assert "Available preview tuning options and what they do" not in prompt


def test_tight_active_motion_window_trims_idle_edges(tmp_path: Path) -> None:
    skeleton_path = tmp_path / "skeleton.json"
    frames = []
    for index in range(20):
        moving = 6 <= index <= 13
        progress = (index - 6) / 7.0 if moving else (0.0 if index < 6 else 1.0)
        frames.append(
            {
                "frameIndex": index,
                "sourceTimeSec": index / 10.0,
                "joints": {
                    "pelvis": [0.0, 1.0, 0.0],
                    "neck": [0.0, 1.8, 0.0],
                    "head": [0.0, 2.0, 0.0],
                    "left_hand": [-0.2, 1.4 + progress * 0.4, 0.0],
                    "right_hand": [0.2, 1.4 + progress * 0.4, 0.0],
                },
            }
        )
    skeleton_path.write_text(
        json.dumps(
            {
                "fps": 10.0,
                "jointNames": ["pelvis", "neck", "head", "left_hand", "right_hand"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Movement",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton_path,
        review_video_path=tmp_path / "review.webm",
        duration_sec=1.9,
        loop_start_seconds=0.0,
        loop_end_seconds=1.9,
        candidate={"videoId": "demo"},
    )

    proposal = bake_and_rank_module.propose_tight_active_motion_window(
        item,
        DetectionWindow(index=0, start_seconds=0.0, end_seconds=1.9),
        padding_seconds=0.1,
    )

    assert proposal is not None
    assert proposal.window.start_seconds > 0.0
    assert proposal.window.end_seconds < 1.9
    assert proposal.metrics["activeFrameCount"] > 0


def test_tight_active_motion_window_merges_short_internal_pause(tmp_path: Path) -> None:
    skeleton_path = tmp_path / "skeleton.json"
    frames = []
    for index in range(32):
        if 4 <= index <= 11:
            progress = (index - 4) / 7.0
        elif 18 <= index <= 25:
            progress = 1.0 + (index - 18) / 7.0
        elif index < 4:
            progress = 0.0
        elif index < 18:
            progress = 1.0
        else:
            progress = 2.0
        frames.append(
            {
                "frameIndex": index,
                "sourceTimeSec": index / 10.0,
                "joints": {
                    "pelvis": [0.0, 1.0, 0.0],
                    "neck": [0.0, 1.8, 0.0],
                    "head": [0.0, 2.0, 0.0],
                    "left_hand": [-0.2, 1.2 + progress * 0.25, 0.0],
                    "right_hand": [0.2, 1.2 + progress * 0.25, 0.0],
                },
            }
        )
    skeleton_path.write_text(
        json.dumps(
            {
                "fps": 10.0,
                "jointNames": ["pelvis", "neck", "head", "left_hand", "right_hand"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Movement",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton_path,
        review_video_path=tmp_path / "review.webm",
        duration_sec=3.1,
        loop_start_seconds=0.0,
        loop_end_seconds=3.1,
        candidate={"videoId": "demo"},
    )

    proposal = bake_and_rank_module.propose_tight_active_motion_window(
        item,
        DetectionWindow(index=0, start_seconds=0.0, end_seconds=3.1),
        padding_seconds=0.1,
    )

    assert proposal is not None
    assert proposal.window.start_seconds > 0.0
    assert proposal.window.start_seconds < 0.6
    assert proposal.window.end_seconds > 2.4
    assert proposal.window.end_seconds < 3.1
    assert proposal.metrics["selectedActiveFrameCount"] > 10


def test_loop_ranking_prompt_uses_timestamped_generated_preview_contact_sheet(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Barbell Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=10.0,
        loop_start_seconds=0.0,
        loop_end_seconds=10.0,
        candidate={"videoId": "bench"},
    )
    chunk_estimate = bake_and_rank_module.estimate_chunking(
        exercise_name="Barbell Bench Press",
        litert_command="litert-lm",
        use_llm=False,
    )
    prompt = bake_and_rank_module.build_loop_ranking_prompt(
        item,
        chunk_window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=10.0),
        chunk_index=0,
        chunk_count=1,
        chunk_estimate=chunk_estimate,
        original_chunk_index=0,
        original_chunk_count=1,
        deterministic_window_score=0.8,
        review_frame_count=32,
    )

    assert "generated interactive preview with 32 evenly sampled frames and visible preview timeline labels" in prompt
    assert "original selected source video" not in prompt
    assert "TIGHT_ACTIVE_MOTION" not in prompt
    assert "active-motion proposal" not in prompt
    assert '"startSeconds": 2.0' not in prompt
    assert '"endSeconds": 6.0' not in prompt


def test_adaptive_preview_settings_prompt_requests_orientation_fix_when_unreadable() -> None:
    prompt = bake_and_rank_module.build_adaptive_preview_settings_prompt(
        base_options=bake_and_rank_module.build_preview_bake_base_options(
            motion_tuning_enabled=True,
        ),
        motion_tuning_enabled=True,
        max_variants=1,
    )

    assert "upside down" in prompt
    assert "head/feet reversed" in prompt
    assert "sceneInverted" in prompt
    assert "cameraYawDegrees" in prompt


def test_review_window_scoring_caps_high_motion_low_loopability(tmp_path: Path) -> None:
    candidate_workspace = tmp_path / "candidate"
    good_skeleton = tmp_path / "good-window.json"
    bad_skeleton = tmp_path / "bad-window.json"
    write_motion_strength_skeleton(good_skeleton, [0.0, 0.30, 0.0])
    write_motion_strength_skeleton(bad_skeleton, [0.0, 0.30, 0.60])
    window = DetectionWindow(index=0, start_seconds=0.0, end_seconds=3.0)

    good_candidates = bake_and_rank_module.score_review_windows_by_skeleton_motion(
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=0,
            exercise_name="Movement",
            candidate_title="Good loop",
            candidate_workspace=candidate_workspace,
            preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
            skeleton_path=good_skeleton,
            review_video_path=candidate_workspace / "review" / "good.webm",
            duration_sec=3.0,
            loop_start_seconds=0.0,
            loop_end_seconds=3.0,
            candidate={"videoId": "good"},
        ),
        [window],
    )
    bad_candidates = bake_and_rank_module.score_review_windows_by_skeleton_motion(
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=0,
            exercise_name="Movement",
            candidate_title="Bad loop",
            candidate_workspace=candidate_workspace,
            preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
            skeleton_path=bad_skeleton,
            review_video_path=candidate_workspace / "review" / "bad.webm",
            duration_sec=3.0,
            loop_start_seconds=0.0,
            loop_end_seconds=3.0,
            candidate={"videoId": "bad"},
        ),
        [window],
    )

    assert good_candidates[0].score == pytest.approx(bad_candidates[0].score)
    assert bad_candidates[0].continuity_metrics["continuityScore"] < good_candidates[0].continuity_metrics["continuityScore"]
    assert bad_candidates[0].loop_bridge_quality_metrics["severeLoopMismatch"] is True


def test_preview_readability_prefers_screen_plane_motion(tmp_path: Path) -> None:
    screen_motion = tmp_path / "screen-motion.json"
    depth_motion = tmp_path / "depth-motion.json"
    write_horizontal_motion_skeleton(screen_motion, [(index * 0.05, 0.0) for index in range(8)])
    write_horizontal_motion_skeleton(depth_motion, [(index * 0.05, index * 0.05) for index in range(8)])

    screen_metrics = compute_preview_readability_metrics(screen_motion, camera_yaw_degrees=45.0)
    depth_metrics = compute_preview_readability_metrics(depth_motion, camera_yaw_degrees=45.0)

    assert screen_metrics["screenMotionShare"] > depth_metrics["screenMotionShare"]
    assert screen_metrics["previewReadabilityScore"] > depth_metrics["previewReadabilityScore"]


def test_loop_continuity_adjustment_keeps_deterministic_fallback_below_selection_threshold(tmp_path: Path) -> None:
    skeleton = tmp_path / "fallback.json"
    write_motion_strength_skeleton(skeleton, [0.0, 0.30, 0.0])
    candidate_workspace = tmp_path / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Fallback",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton,
        review_video_path=candidate_workspace / "review" / "fallback.webm",
        duration_sec=3.0,
        loop_start_seconds=0.0,
        loop_end_seconds=3.0,
        candidate={"videoId": "fallback"},
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(
            score=0.49,
            reasons=["llm_section_review_failed", "deterministic_section_fallback"],
            payload={"full_rep_motion": 1.0},
        ),
    )

    assert adjusted.score <= 0.49
    assert "deterministic_fallback_selection_cap" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons


def write_motion_strength_skeleton(path: Path, offsets: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, offset in enumerate(offsets):
        frames.append(
            {
                "frameIndex": index,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60 + offset, 0.0],
                    "head": [0.0, 1.20 + offset, 0.0],
                    "left_ankle": [0.0, 0.0, 0.0],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "head", "left_ankle"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_loop_bridge_mismatch_skeleton(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        {
            "frameIndex": 0,
            "syntheticLoopBridge": False,
            "joints": {
                "pelvis": [0.0, 0.60, 0.0],
                "head": [0.0, 1.20, 0.0],
                "left_knee": [0.0, 0.35, 0.0],
                "right_knee": [0.0, 0.35, 0.0],
            },
        },
        {
            "frameIndex": 1,
            "syntheticLoopBridge": False,
            "joints": {
                "pelvis": [0.0, 0.60, 0.0],
                "head": [0.0, 1.20, 0.0],
                "left_knee": [0.03, 0.35, 0.0],
                "right_knee": [0.0, 0.35, 0.0],
            },
        },
        {
            "frameIndex": 2,
            "syntheticLoopBridge": False,
            "joints": {
                "pelvis": [0.0, 0.60, 0.0],
                "head": [0.0, 1.20, 0.0],
                "left_knee": [0.16, 0.35, 0.0],
                "right_knee": [0.0, 0.35, 0.0],
            },
        },
        {
            "frameIndex": "bridge-0",
            "syntheticLoopBridge": True,
            "joints": {
                "pelvis": [0.0, 0.60, 0.0],
                "head": [0.0, 1.20, 0.0],
                "left_knee": [0.08, 0.35, 0.0],
                "right_knee": [0.0, 0.35, 0.0],
            },
        },
        {
            "frameIndex": "bridge-1",
            "syntheticLoopBridge": True,
            "joints": {
                "pelvis": [0.0, 0.60, 0.0],
                "head": [0.0, 1.20, 0.0],
                "left_knee": [0.01, 0.35, 0.0],
                "right_knee": [0.0, 0.35, 0.0],
            },
        },
    ]
    path.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "head", "left_knee", "right_knee"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_horizontal_motion_skeleton(path: Path, offsets: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, (offset_x, offset_z) in enumerate(offsets):
        frames.append(
            {
                "frameIndex": index,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60, 0.0],
                    "head": [0.0, 1.20, 0.0],
                    "right_hand": [0.2 + offset_x, 0.95, offset_z],
                    "left_hand": [-0.2, 0.95, 0.0],
                    "left_ankle": [-0.1, 0.0, 0.0],
                    "right_ankle": [0.1, 0.0, 0.0],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "head", "right_hand", "left_hand", "left_ankle", "right_ankle"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_motion_strength_skeleton_with_source_times(path: Path, samples: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, (source_time, offset) in enumerate(samples):
        frames.append(
            {
                "frameIndex": index,
                "timeSec": source_time,
                "sourceTimeSec": source_time,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60 + offset, 0.0],
                    "head": [0.0, 1.20 + offset, 0.0],
                    "left_ankle": [0.0, 0.0, 0.0],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "fps": 30.0,
                "jointNames": ["pelvis", "head", "left_ankle"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_rigid_root_motion_skeleton(path: Path, offsets: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, offset in enumerate(offsets):
        frames.append(
            {
                "frameIndex": index,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60 + offset, 0.0],
                    "head": [0.0, 1.20 + offset, 0.0],
                    "left_knee": [-0.12, 0.30 + offset, 0.0],
                    "right_knee": [0.12, 0.30 + offset, 0.0],
                    "left_ankle": [-0.12, 0.0 + offset, 0.0],
                    "right_ankle": [0.12, 0.0 + offset, 0.0],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "jointNames": ["pelvis", "head", "left_knee", "right_knee", "left_ankle", "right_ankle"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_leg_kinematic_artifact_skeleton(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joint_names = [
        "pelvis",
        "head",
        "left_hip",
        "left_knee",
        "left_ankle",
        "left_foot",
        "right_hip",
        "right_knee",
        "right_ankle",
        "right_foot",
    ]
    frames = []
    for index in range(12):
        drift = index * 0.004
        right_ankle = [0.12 + drift, 0.00, 0.04]
        right_foot = [0.13 + drift, -0.04, 0.10]
        if index == 6:
            right_ankle = [0.52, 0.18, 0.42]
            right_foot = [0.61, 0.14, 0.52]
        frames.append(
            {
                "frameIndex": index,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60, 0.0],
                    "head": [0.0, 1.25, 0.0],
                    "left_hip": [-0.12, 0.58, 0.0],
                    "left_knee": [-0.12, 0.30, 0.02],
                    "left_ankle": [-0.12, 0.00, 0.04],
                    "left_foot": [-0.13, -0.04, 0.10],
                    "right_hip": [0.12, 0.58, 0.0],
                    "right_knee": [0.12, 0.30, 0.02],
                    "right_ankle": right_ankle,
                    "right_foot": right_foot,
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "jointNames": joint_names,
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_hand_lock_arm_distortion_skeleton(path: Path, *, distorted: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joint_names = [
        "pelvis",
        "head",
        "left_shoulder",
        "left_elbow",
        "left_wrist",
        "right_shoulder",
        "right_elbow",
        "right_wrist",
    ]
    frames = []
    for index in range(12):
        phase = math.sin(index / 11.0 * math.pi)
        if distorted:
            left_elbow = [-0.20, 0.44 - phase * 0.08, 0.0]
            left_wrist = [-0.04, 0.52 + phase * 0.05, 0.0]
            right_elbow = [0.28, 0.52, 0.0]
            right_wrist = [0.52, 0.53, 0.0]
        else:
            left_elbow = [-0.22, 0.44 - phase * 0.05, 0.0]
            left_wrist = [-0.34, 0.62 + phase * 0.06, 0.0]
            right_elbow = [0.22, 0.44 - phase * 0.05, 0.0]
            right_wrist = [0.34, 0.62 + phase * 0.06, 0.0]
        frames.append(
            {
                "frameIndex": index,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.0, 0.0],
                    "head": [0.0, 0.7, 0.0],
                    "left_shoulder": [-0.18, 0.52, 0.0],
                    "left_elbow": left_elbow,
                    "left_wrist": left_wrist,
                    "right_shoulder": [0.18, 0.52, 0.0],
                    "right_elbow": right_elbow,
                    "right_wrist": right_wrist,
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "jointNames": joint_names,
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_paired_hands_skeleton(path: Path, *, distorted: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joint_names = [
        "pelvis",
        "head",
        "left_shoulder",
        "left_elbow",
        "left_wrist",
        "left_hand",
        "right_shoulder",
        "right_elbow",
        "right_wrist",
        "right_hand",
    ]
    frames = []
    for index in range(12):
        phase = math.sin(index / 11.0 * math.pi)
        press_y = 0.18 * phase
        source_joints = {
            "pelvis": [0.0, 0.0, 0.0],
            "head": [0.0, 0.76, 0.0],
            "left_shoulder": [-0.18, 0.52, 0.0],
            "left_elbow": [-0.26, 0.40 + press_y * 0.45, 0.0],
            "left_wrist": [-0.34, 0.48 + press_y, 0.0],
            "left_hand": [-0.36, 0.50 + press_y, 0.0],
            "right_shoulder": [0.18, 0.52, 0.0],
            "right_elbow": [0.26, 0.40 + press_y * 0.45, 0.0],
            "right_wrist": [0.34, 0.48 + press_y, 0.0],
            "right_hand": [0.36, 0.50 + press_y, 0.0],
        }
        if distorted:
            joints = {
                **source_joints,
                "left_elbow": [-0.26, 0.40 + press_y * 0.10, 0.0],
                "left_wrist": [-0.34 - phase * 0.16, 0.50 + press_y * 0.20, 0.0],
                "left_hand": [-0.36 - phase * 0.18, 0.52 + press_y * 0.20, 0.0],
                "right_elbow": [0.26, 0.40 - press_y * 0.10, 0.0],
                "right_wrist": [0.34 + phase * 0.02, 0.50 - press_y * 0.10, 0.0],
                "right_hand": [0.36 + phase * 0.02, 0.52 - press_y * 0.10, 0.0],
            }
        else:
            joints = dict(source_joints)
        frames.append(
            {
                "frameIndex": index,
                "sourceTimeSec": index / 10.0,
                "syntheticLoopBridge": False,
                "sourceJoints": source_joints,
                "joints": joints,
            }
        )
    path.write_text(
        json.dumps(
            {
                "fps": 10.0,
                "jointNames": joint_names,
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def write_two_rep_source_with_kinematic_artifact(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joint_names = [
        "pelvis",
        "head",
        "left_hip",
        "left_knee",
        "left_ankle",
        "left_foot",
        "right_hip",
        "right_knee",
        "right_ankle",
        "right_foot",
    ]
    frames = []
    fps = 10.0
    for index in range(81):
        source_time = index / fps
        if source_time < 3.0:
            phase = min(1.0, source_time / 3.0)
        else:
            phase = min(1.0, (source_time - 3.0) / 5.0)
        offset = 0.24 * math.sin(math.pi * phase)
        right_ankle = [0.12, 0.00, 0.04]
        right_foot = [0.13, -0.04, 0.10]
        if index == 20:
            right_ankle = [0.58, 0.20, 0.45]
            right_foot = [0.66, 0.15, 0.55]
        frames.append(
            {
                "frameIndex": index,
                "sourceTimeSec": source_time,
                "syntheticLoopBridge": False,
                "joints": {
                    "pelvis": [0.0, 0.60 + offset, 0.0],
                    "head": [0.0, 1.25 + offset, 0.0],
                    "left_hip": [-0.12, 0.58 + offset, 0.0],
                    "left_knee": [-0.12, 0.30 + offset * 0.35, 0.02],
                    "left_ankle": [-0.12, 0.00, 0.04],
                    "left_foot": [-0.13, -0.04, 0.10],
                    "right_hip": [0.12, 0.58 + offset, 0.0],
                    "right_knee": [0.12, 0.30 + offset * 0.35, 0.02],
                    "right_ankle": right_ankle,
                    "right_foot": right_foot,
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "fps": fps,
                "jointNames": joint_names,
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )


def test_process_ranked_candidate_skips_static_baked_motion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="movement",
        exercise_name="Movement",
        exercise_slug="movement",
        candidate={
            "videoId": "static",
            "url": "https://www.youtube.com/watch?v=static",
            "title": "Static source",
        },
    )

    def fake_generate_candidate_motion(
        ranked_candidate: RankedCandidate,
        *,
        request: BakeAndRankRequest,
    ) -> GenerateResult:
        root = request.workspace / ranked_candidate.workspace_slug
        root.mkdir(parents=True, exist_ok=True)
        preview_html = root / "preview" / "motion_preview.html"
        preview_html.parent.mkdir(parents=True, exist_ok=True)
        preview_html.write_text("<html></html>", encoding="utf-8")
        cleaned_motion_json = root / "cleaned" / "motion.cleaned.json"
        cleaned_motion_json.parent.mkdir(parents=True, exist_ok=True)
        save_motion_json(cleaned_motion_json, build_loop_fixture_clip())
        return GenerateResult(
            manifest_path=root / "manifest.json",
            preview_html_path=preview_html,
            raw_preview_html_path=root / "preview" / "motion_preview.raw.html",
            wear_skeleton_json_path=root / "wear" / "skeleton.preview.json",
            cleaned_motion_json_path=cleaned_motion_json,
            raw_motion_json_path=root / "raw" / "motion.raw.json",
            target_rig_contract_path=root / "retarget" / "target_rig.contract.json",
            retarget_source_path=None,
            smpl_preview_json_path=None,
            copied_input_video_path=root / "input" / "selected_segment.mp4",
            cleanup_stats=CleanupStats(
                input_frames=10,
                output_frames=10,
                trimmed_start_frames=0,
                trimmed_end_frames=0,
                average_root_height_before=0.0,
                average_root_height_after=0.0,
            ),
            ground_metadata_path=None,
            motion_tuning_enabled=request.motion_tuning_enabled,
        )

    def fake_preview_baker(
        preview_html_path: Path,
        eligible_loops: list[bake_and_rank_module.EligibleLoop],
        candidate_workspace: Path,
        review_frames: int,
    ) -> list[BakedLoopArtifact]:
        skeleton_path = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
        review_video_path = candidate_workspace / "review" / "full-input.webm"
        write_motion_strength_skeleton(skeleton_path, [0.0, 0.0, 0.0])
        review_video_path.parent.mkdir(parents=True, exist_ok=True)
        review_video_path.write_bytes(b"video")
        return [
            BakedLoopArtifact(
                loop_index=-1,
                skeleton_path=skeleton_path,
                review_video_path=review_video_path,
                export_payload={},
            )
        ]

    monkeypatch.setattr(bake_and_rank_module, "generate_candidate_motion", fake_generate_candidate_motion)

    review_items: list[ReviewItem] = []
    review_entries: list[dict[str, object]] = []
    result = bake_and_rank_module.process_ranked_candidate(
        candidate,
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            detect_source_segment=False,
            classify_support_dominance=False,
        ),
        preview_baker=fake_preview_baker,
        review_items=review_items,
        review_item_entries=review_entries,
        support_dominance_classifier=None,
    )

    assert result["status"] == "skipped_no_usable_baked_motion"
    assert review_items == []
    assert result["rejectedSourceClips"][0]["reason"] == "baked_motion_too_static"
    assert result["rejectedSourceClips"][0]["bakedMotionGate"]["motionStrengthScore"] == pytest.approx(0.0)


def test_motion_strength_metrics_measure_body_normalized_rep_range(tmp_path: Path) -> None:
    strong_skeleton = tmp_path / "strong.json"
    weak_skeleton = tmp_path / "weak.json"
    write_motion_strength_skeleton(strong_skeleton, [0.0, 0.30, 0.0])
    write_motion_strength_skeleton(weak_skeleton, [0.0, 0.06, 0.0])

    strong = compute_motion_strength_metrics(strong_skeleton)
    weak = compute_motion_strength_metrics(weak_skeleton)

    assert strong["motionStrengthScore"] > weak["motionStrengthScore"]
    assert strong["primaryMotionRangeRatio"] > weak["primaryMotionRangeRatio"]
    assert strong["rootVerticalRangeRatio"] == pytest.approx(0.25)


def test_motion_strength_metrics_expose_root_relative_articulation(tmp_path: Path) -> None:
    articulated_skeleton = tmp_path / "articulated.json"
    rigid_skeleton = tmp_path / "rigid.json"
    write_motion_strength_skeleton(articulated_skeleton, [0.0, 0.30, 0.0])
    write_rigid_root_motion_skeleton(rigid_skeleton, [0.0, 0.30, 0.0])

    articulated = compute_motion_strength_metrics(articulated_skeleton)
    rigid = compute_motion_strength_metrics(rigid_skeleton)

    assert articulated["rootVerticalRangeRatio"] == pytest.approx(rigid["rootVerticalRangeRatio"])
    assert articulated["rootRelativeArticulationRangeRatio"] > 0.20
    assert rigid["rootRelativeArticulationRangeRatio"] == pytest.approx(0.0)


def test_loop_adjustment_penalizes_rigid_root_only_motion(tmp_path: Path) -> None:
    skeleton = tmp_path / "rigid.json"
    review = tmp_path / "review.webm"
    write_rigid_root_motion_skeleton(skeleton, [0.0, 0.30, 0.0])
    review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Rigid root motion",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton,
        review_video_path=review,
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"videoId": "rigid"},
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert adjusted.score == pytest.approx(0.95)
    assert "rigid_root_motion_penalty" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_kinematic_plausibility_metrics_detect_limb_artifact(tmp_path: Path) -> None:
    skeleton = tmp_path / "leg-artifact.json"
    write_leg_kinematic_artifact_skeleton(skeleton)

    metrics = compute_kinematic_plausibility_metrics(skeleton)

    assert metrics["severeArtifact"] is True
    assert "limb_velocity_spike_penalty" in metrics["artifactReasons"]
    assert "joint_angle_spike_penalty" in metrics["artifactReasons"]
    assert "bone_length_instability_penalty" in metrics["artifactReasons"]
    assert metrics["kinematicPlausibilityScore"] < 0.52
    assert metrics["distalStep"]["joint"] in {"right_ankle", "right_foot"}
    assert metrics["distalStep"]["maxStepRatio"] >= 8.0
    assert metrics["distalStep"]["maxStepBodyRatio"] >= 0.08
    assert metrics["jointAngleStep"]["maxAngleStepDegrees"] >= 25.0
    assert metrics["boneLength"]["bone"] in {"right_knee:right_ankle", "right_ankle:right_foot"}


def test_hand_lock_arm_distortion_metrics_detect_stable_wrong_arm_pose(tmp_path: Path) -> None:
    distorted = tmp_path / "distorted-arms.json"
    clean = tmp_path / "clean-arms.json"
    write_hand_lock_arm_distortion_skeleton(distorted, distorted=True)
    write_hand_lock_arm_distortion_skeleton(clean, distorted=False)

    distorted_metrics = compute_hand_lock_arm_distortion_metrics(distorted)
    clean_metrics = compute_hand_lock_arm_distortion_metrics(clean)

    assert distorted_metrics["severeArmDistortion"] is True
    assert distorted_metrics["medianBilateralElbowAngleDifferenceDegrees"] >= 35.0
    assert clean_metrics["severeArmDistortion"] is False


def test_paired_hands_preservation_metrics_measure_spacing_and_raw_capture(tmp_path: Path) -> None:
    preserved = tmp_path / "paired-preserved.json"
    distorted = tmp_path / "paired-distorted.json"
    write_paired_hands_skeleton(preserved, distorted=False)
    write_paired_hands_skeleton(distorted, distorted=True)

    preserved_metrics = compute_paired_hands_preservation_metrics(preserved)
    distorted_metrics = compute_paired_hands_preservation_metrics(distorted)

    assert preserved_metrics["severePairedHandsDistortion"] is False
    assert preserved_metrics["sharedHandTravelCaptureRatio"] == pytest.approx(1.0)
    assert preserved_metrics["elbowFlexionRangeCaptureRatio"] == pytest.approx(1.0)
    assert distorted_metrics["severePairedHandsDistortion"] is True
    assert distorted_metrics["handSpacingInstabilityRatio"] > preserved_metrics["handSpacingInstabilityRatio"]
    assert distorted_metrics["sharedHandTravelCaptureRatio"] < 0.75


def test_loop_adjustment_penalizes_hand_lock_arm_distortion(tmp_path: Path) -> None:
    skeleton = tmp_path / "distorted-arms.json"
    review = tmp_path / "review.webm"
    write_hand_lock_arm_distortion_skeleton(skeleton, distorted=True)
    review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton,
        review_video_path=review,
        duration_sec=3.2,
        loop_start_seconds=0.0,
        loop_end_seconds=3.2,
        candidate={"videoId": "bench"},
        settings_options={"lockPlantedHands": True},
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert adjusted.score == pytest.approx(0.95)
    assert "hand_lock_arm_distortion_penalty" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_loop_adjustment_penalizes_paired_hands_distortion(tmp_path: Path) -> None:
    skeleton = tmp_path / "paired-distorted.json"
    review = tmp_path / "review.webm"
    write_paired_hands_skeleton(skeleton, distorted=True)
    review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton,
        review_video_path=review,
        duration_sec=3.2,
        loop_start_seconds=0.0,
        loop_end_seconds=3.2,
        candidate={"videoId": "bench"},
        settings_options={"lockPlantedHands": False},
        cleanup_interpretation="support_lock",
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert adjusted.score == pytest.approx(0.95)
    assert "paired_hands_distortion_penalty" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_loop_adjustment_penalizes_kinematic_artifact(tmp_path: Path) -> None:
    skeleton = tmp_path / "leg-artifact.json"
    review = tmp_path / "review.webm"
    write_leg_kinematic_artifact_skeleton(skeleton)
    review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Kinematic artifact",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=skeleton,
        review_video_path=review,
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"videoId": "artifact"},
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model liked it"], payload={"full_rep_motion": 1.0}),
    )

    assert adjusted.score == pytest.approx(0.95)
    assert "limb_velocity_spike_penalty" not in adjusted.reasons
    assert "joint_angle_spike_penalty" not in adjusted.reasons
    assert "bone_length_instability_penalty" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_materialized_selection_keeps_weak_cut_when_deterministic_validation_penalizes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    preview_html = candidate_workspace / "preview" / "motion_preview.html"
    preview_html.parent.mkdir(parents=True)
    preview_html.write_text("<html></html>", encoding="utf-8")
    source_skeleton = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
    write_motion_strength_skeleton(source_skeleton, [0.0, 0.32, 0.0])
    source_review = candidate_workspace / "review" / "full-input.webm"
    source_review.parent.mkdir(parents=True)
    source_review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squats",
        candidate_workspace=candidate_workspace,
        preview_html_path=preview_html,
        skeleton_path=source_skeleton,
        review_video_path=source_review,
        duration_sec=9.3,
        loop_start_seconds=0.0,
        loop_end_seconds=9.3,
        candidate={"videoId": "I1Ee3M6SDgQ"},
    )
    original_ranking = LoopRanking(
        score=0.9,
        reasons=["model claims full rep"],
        payload={
            "selected_section_start_seconds": 3.25,
            "selected_section_end_seconds": 6.51,
            "full_rep_motion": 0.9,
        },
    )

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        weak_skeleton = candidate_workspace / "wear" / "skeleton.baked.llm-selected-section.json"
        write_motion_strength_skeleton(weak_skeleton, [0.0, 0.08, 0.0])
        review_video_path = candidate_workspace / "review" / "llm-selected-section.webm"
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=weak_skeleton,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": float(kwargs["end_seconds"]) - float(kwargs["start_seconds"]),
            },
            settings_variant_id=str(kwargs["artifact_id"]),
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=dict(kwargs["options"]),
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    selected, rejected_best = bake_and_rank_module.choose_best_materialized_review_item(
        [item],
        [original_ranking],
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            min_selected_score=0.55,
        ),
    )

    assert rejected_best is None
    assert selected is not None
    _selected_item, selected_ranking = selected
    assert selected_ranking is not None
    assert selected_ranking.score == pytest.approx(0.9)
    assert "weak_full_rep_motion_penalty" not in selected_ranking.reasons
    assert "deterministic_review_validation_skipped" in selected_ranking.reasons
    assert selected_ranking.payload is not None
    assert selected_ranking.payload["deterministicReviewValidationSkipped"] is True


def test_materialized_selection_source_capture_compares_selected_source_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    preview_html = candidate_workspace / "preview" / "motion_preview.html"
    preview_html.parent.mkdir(parents=True)
    preview_html.write_text("<html></html>", encoding="utf-8")
    source_skeleton = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
    write_motion_strength_skeleton_with_source_times(
        source_skeleton,
        [
            (0.0, 0.0),
            (1.0, 0.32),
            (2.0, 0.0),
            (3.25, 0.0),
            (4.8, 0.08),
            (6.51, 0.0),
            (8.0, 0.32),
            (9.3, 0.0),
        ],
    )
    source_review = candidate_workspace / "review" / "full-input.webm"
    source_review.parent.mkdir(parents=True)
    source_review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squats",
        candidate_workspace=candidate_workspace,
        preview_html_path=preview_html,
        skeleton_path=source_skeleton,
        review_video_path=source_review,
        duration_sec=9.3,
        loop_start_seconds=0.0,
        loop_end_seconds=9.3,
        candidate={"videoId": "I1Ee3M6SDgQ"},
    )
    original_ranking = LoopRanking(
        score=0.9,
        reasons=["model selected valid source interval"],
        payload={
            "selected_section_start_seconds": 3.25,
            "selected_section_end_seconds": 6.51,
            "full_rep_motion": 0.9,
        },
    )

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        selected_skeleton = candidate_workspace / "wear" / "skeleton.baked.llm-selected-section.json"
        write_motion_strength_skeleton(selected_skeleton, [0.0, 0.08, 0.0])
        review_video_path = candidate_workspace / "review" / "llm-selected-section.webm"
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=selected_skeleton,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": kwargs["start_seconds"]},
                    {"sourceTimeSec": kwargs["end_seconds"]},
                ],
                "durationSec": float(kwargs["end_seconds"]) - float(kwargs["start_seconds"]),
            },
            settings_variant_id=str(kwargs["artifact_id"]),
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=dict(kwargs["options"]),
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    selected, rejected_best = bake_and_rank_module.choose_best_materialized_review_item(
        [item],
        [original_ranking],
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            min_selected_score=0.55,
        ),
    )

    assert rejected_best is None
    assert selected is not None
    _selected_item, selected_ranking = selected
    assert selected_ranking is not None
    assert "weak_full_rep_motion_penalty" not in selected_ranking.reasons
    assert "deterministic_review_validation_skipped" in selected_ranking.reasons
    assert selected_ranking.payload is not None
    assert selected_ranking.payload["deterministicReviewValidationSkipped"] is True


def test_loop_adjustment_penalizes_weak_source_capture_even_for_full_source_span(
    tmp_path: Path,
) -> None:
    source_skeleton = tmp_path / "source.json"
    selected_skeleton = tmp_path / "selected.json"
    review_video = tmp_path / "review.webm"
    write_motion_strength_skeleton_with_source_times(
        source_skeleton,
        [
            (0.0, 0.0),
            (3.0, 0.32),
            (6.0, 0.0),
        ],
    )
    write_motion_strength_skeleton_with_source_times(
        selected_skeleton,
        [
            (0.0, 0.0),
            (3.0, 0.08),
            (6.0, 0.0),
        ],
    )
    review_video.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=selected_skeleton,
        review_video_path=review_video,
        duration_sec=6.0,
        loop_start_seconds=0.0,
        loop_end_seconds=6.0,
        candidate={"videoId": "bench"},
        llm_time_range_cut_applied=True,
        source_skeleton_path=source_skeleton,
    )

    adjusted = apply_loop_continuity_adjustment(
        item,
        LoopRanking(score=0.95, reasons=["model selected full source"], payload={"full_rep_motion": 0.95}),
    )

    assert "weak_full_rep_motion_penalty" not in adjusted.reasons
    assert "deterministic_review_validation_skipped" in adjusted.reasons
    assert adjusted.payload is not None
    assert adjusted.payload["deterministicReviewValidationSkipped"] is True


def test_materialized_selection_retries_clean_subinterval_after_kinematic_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    preview_html = candidate_workspace / "preview" / "motion_preview.html"
    preview_html.parent.mkdir(parents=True)
    preview_html.write_text("<html></html>", encoding="utf-8")
    source_skeleton = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
    write_two_rep_source_with_kinematic_artifact(source_skeleton)
    source_review = candidate_workspace / "review" / "full-input.webm"
    source_review.parent.mkdir(parents=True)
    source_review.write_bytes(b"video")
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Movement",
        candidate_title="Movement demo",
        candidate_workspace=candidate_workspace,
        preview_html_path=preview_html,
        skeleton_path=source_skeleton,
        review_video_path=source_review,
        duration_sec=8.0,
        loop_start_seconds=0.0,
        loop_end_seconds=8.0,
        candidate={"videoId": "artifact-source"},
    )
    original_ranking = LoopRanking(
        score=0.95,
        reasons=[
            "model chose a section",
            "loop_restart_discontinuity_penalty",
            "limb_velocity_spike_penalty",
            "joint_angle_spike_penalty",
            "bone_length_instability_penalty",
        ],
        payload={
            "selected_section_start_seconds": 0.0,
            "selected_section_end_seconds": 3.0,
            "full_rep_motion": 0.95,
            "recommended_settings": {"lockPlantedFeet": True},
        },
    )
    bake_calls: list[tuple[str, float, float]] = []

    def fake_bake_preview_time_range_with_playwright(**kwargs: object) -> BakedLoopArtifact:
        artifact_id = str(kwargs["artifact_id"])
        start_seconds = float(kwargs["start_seconds"])
        end_seconds = float(kwargs["end_seconds"])
        options = dict(kwargs["options"])
        bake_calls.append((artifact_id, start_seconds, end_seconds))
        skeleton_path = candidate_workspace / "wear" / f"{artifact_id}-{len(bake_calls)}.json"
        review_video_path = candidate_workspace / "review" / f"{artifact_id}-{len(bake_calls)}.webm"
        if artifact_id.startswith("llm-selected-section"):
            write_leg_kinematic_artifact_skeleton(skeleton_path)
        elif options.get("lockPlantedFeet"):
            write_loop_bridge_mismatch_skeleton(skeleton_path)
        else:
            write_motion_strength_skeleton(skeleton_path, [0.0, 0.30, 0.0])
        review_video_path.parent.mkdir(parents=True, exist_ok=True)
        review_video_path.write_bytes(b"video")
        return BakedLoopArtifact(
            loop_index=-1,
            skeleton_path=skeleton_path,
            review_video_path=review_video_path,
            export_payload={
                "frames": [
                    {"sourceTimeSec": start_seconds},
                    {"sourceTimeSec": (start_seconds + end_seconds) / 2.0},
                    {"sourceTimeSec": end_seconds},
                ],
                "durationSec": end_seconds - start_seconds,
            },
            settings_variant_id=artifact_id,
            settings_variant_label=str(kwargs["artifact_label"]),
            settings_options=dict(kwargs["options"]),
        )

    monkeypatch.setattr(
        bake_and_rank_module,
        "bake_preview_time_range_with_playwright",
        fake_bake_preview_time_range_with_playwright,
    )

    selected, rejected_best = bake_and_rank_module.choose_best_materialized_review_item(
        [item],
        [original_ranking],
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            min_selected_score=0.55,
        ),
    )

    assert rejected_best is None
    assert selected is not None
    selected_item, selected_ranking = selected
    assert selected_ranking is not None
    assert selected_item.settings_variant_id == "llm-selected-section"
    assert selected_ranking.score == pytest.approx(0.95)
    assert "kinematic_clean_subinterval_fallback" not in selected_ranking.reasons
    assert "support_lock_safe_rebake" not in selected_ranking.reasons
    assert "support_lock_loop_bridge_rebake" not in selected_ranking.reasons
    assert "deterministic_review_validation_skipped" in selected_ranking.reasons
    assert selected_ranking.payload is not None
    assert selected_ranking.payload["deterministicReviewValidationSkipped"] is True
    assert "loop_restart_discontinuity_penalty" not in selected_ranking.reasons
    assert "limb_velocity_spike_penalty" not in selected_ranking.reasons
    assert "joint_angle_spike_penalty" not in selected_ranking.reasons
    assert "bone_length_instability_penalty" not in selected_ranking.reasons
    assert bake_calls[0][0] == "llm-selected-section"
    assert not any(call[0] == "kinematic-clean-subinterval" for call in bake_calls)


def test_materialized_selection_falls_back_after_best_candidate_downgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=-1,
            exercise_name="Bulgarian Split Squat",
            candidate_title="Weak first",
            candidate_workspace=tmp_path / "candidate-1",
            preview_html_path=tmp_path / "candidate-1" / "preview" / "motion_preview.html",
            skeleton_path=tmp_path / "candidate-1" / "wear" / "full.json",
            review_video_path=tmp_path / "candidate-1" / "review" / "full.webm",
            duration_sec=4.0,
            loop_start_seconds=0.0,
            loop_end_seconds=4.0,
            candidate={"videoId": "weak"},
        ),
        ReviewItem(
            exercise_index=0,
            candidate_rank=1,
            loop_index=-1,
            exercise_name="Bulgarian Split Squat",
            candidate_title="Strong fallback",
            candidate_workspace=tmp_path / "candidate-2",
            preview_html_path=tmp_path / "candidate-2" / "preview" / "motion_preview.html",
            skeleton_path=tmp_path / "candidate-2" / "wear" / "full.json",
            review_video_path=tmp_path / "candidate-2" / "review" / "full.webm",
            duration_sec=4.0,
            loop_start_seconds=0.0,
            loop_end_seconds=4.0,
            candidate={"videoId": "strong"},
        ),
    ]
    materialized_order: list[int] = []

    def fake_materialize(selected: tuple[ReviewItem, LoopRanking], *, request: BakeAndRankRequest):
        materialized_order.append(selected[0].candidate_rank)
        return selected

    def fake_refresh_materialized_selection_ranking(
        *,
        original: tuple[ReviewItem, LoopRanking],
        materialized: tuple[ReviewItem, LoopRanking],
    ):
        item, ranking = original
        if item.candidate_rank == 0:
            return item, LoopRanking(score=0.60, reasons=[*ranking.reasons, "acceptable_but_weaker"])
        return item, LoopRanking(score=0.72, reasons=[*ranking.reasons, "strong_full_rep"])

    monkeypatch.setattr(bake_and_rank_module, "materialize_llm_selected_time_range", fake_materialize)
    monkeypatch.setattr(
        bake_and_rank_module,
        "refresh_materialized_selection_ranking",
        fake_refresh_materialized_selection_ranking,
    )

    selected, rejected_best = bake_and_rank_module.choose_best_materialized_review_item(
        items,
        [
            LoopRanking(score=0.95, reasons=["model liked first"]),
            LoopRanking(score=0.80, reasons=["model liked fallback"]),
        ],
        request=BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            min_selected_score=0.55,
        ),
    )

    assert rejected_best is None
    assert selected is not None
    assert selected[0].candidate_rank == 1
    assert selected[1] is not None
    assert selected[1].score == pytest.approx(0.72)
    assert materialized_order == [0, 1]


def test_rank_review_item_prefilters_chunks_with_skeleton_motion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_workspace = tmp_path / "candidate"
    skeleton_path = candidate_workspace / "wear" / "skeleton.baked.full-input.json"
    review_video_path = candidate_workspace / "review" / "full-input.webm"
    skeleton_path.parent.mkdir(parents=True)
    review_video_path.parent.mkdir(parents=True)
    review_video_path.write_bytes(b"video")
    frames = []
    for index, source_time in enumerate([0, 1, 2, 3, 4, 5, 6]):
        offset = 0.30 if source_time == 3 else 0.02 if source_time in {1, 5} else 0.0
        frames.append(
            {
                "frameIndex": index,
                "sourceTimeSec": float(source_time),
                "joints": {
                    "pelvis": [0.0, 0.60 + offset, 0.0],
                    "head": [0.0, 1.20 + offset, 0.0],
                    "left_ankle": [0.0, 0.0, 0.0],
                },
            }
        )
    skeleton_path.write_text(
        json.dumps(
            {
                "fps": 1.0,
                "jointNames": ["pelvis", "head", "left_ankle"],
                "rootJoint": "pelvis",
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Bulgarian split squat demo",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton_path,
        review_video_path=review_video_path,
        duration_sec=6.0,
        loop_start_seconds=0.0,
        loop_end_seconds=6.0,
        candidate={"videoId": "demo"},
    )

    class FakeChunkEstimate:
        rep_duration_min_sec = 2.0
        rep_duration_max_sec = 2.0
        movement_complexity = "medium"
        chunk_seconds = 2.0
        chunk_overlap_seconds = 0.0
        source = "test"
        reason = "fixed test chunking"

    captured_windows: list[DetectionWindow] = []
    rendered_preview_windows: list[DetectionWindow] = []
    prompts: list[str] = []
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")

    def fake_render_source_review_window_contact_sheet(**kwargs: object) -> list[Path]:
        window = kwargs["window"]
        assert isinstance(window, DetectionWindow)
        captured_windows.append(window)
        assert kwargs["frame_count"] == 16
        return [frame_path]

    def fake_render_review_window_contact_sheet(**kwargs: object) -> list[Path]:
        window = kwargs["window"]
        assert isinstance(window, DetectionWindow)
        rendered_preview_windows.append(window)
        return [frame_path]

    def fake_caption_images(**kwargs: object) -> str:
        assert kwargs["frame_paths"] == [frame_path]
        prompts.append(str(kwargs["prompt"]))
        return json.dumps(
            {
                "selected_candidate_id": "A",
                "score": 0.81,
                "valid_single_movement": True,
                "reason": "strong middle rep",
            }
        )

    monkeypatch.setattr(bake_and_rank_module, "estimate_chunking", lambda **_: FakeChunkEstimate())
    monkeypatch.setattr(
        bake_and_rank_module,
        "render_source_review_window_contact_sheet",
        fake_render_source_review_window_contact_sheet,
    )
    monkeypatch.setattr(
        bake_and_rank_module,
        "render_review_window_contact_sheet",
        fake_render_review_window_contact_sheet,
    )

    ranking = bake_and_rank_module.rank_review_item_with_caption_images(
        item,
        BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            wham_repo_path=None,
            body_model_root=None,
            review_frames=4,
            max_review_windows=1,
        ),
        fake_caption_images,
    )

    assert [(window.start_seconds, window.end_seconds) for window in captured_windows] == [(2.0, 4.0)]
    assert rendered_preview_windows == []
    assert "Candidate A: 2.00s to 4.00s." in prompts[0]
    assert "generated interactive preview" not in prompts[0]
    assert "source-video cut" in prompts[0]
    assert "Do not choose the least-bad candidate" in prompts[0]
    assert "selected_candidate_id null" in prompts[0]
    assert ranking.score == pytest.approx(0.81)
    assert ranking.payload is not None
    assert ranking.payload["reviewOriginalChunkIndex"] == 1
    assert ranking.payload["reviewFrameSource"] == "source_candidate_window_contact_sheets"
    assert ranking.payload["reviewFrameCount"] == 32
    assert ranking.payload["selectedCandidateId"] == "A"
    assert ranking.payload["selected_section_start_seconds"] == pytest.approx(2.0)
    assert ranking.payload["selected_section_end_seconds"] == pytest.approx(4.0)
    assert ranking.payload["deterministicWindowMotionMetrics"]["primaryMotionRangeRatio"] > 0.2


def test_source_cut_candidate_choice_can_reject_all_partial_windows() -> None:
    candidates = [
        bake_and_rank_module.SourceCutCandidate(
            candidate_id="A",
            window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=3.0),
            frame_paths=[Path("a.jpg")],
        )
    ]

    ranking = bake_and_rank_module.parse_source_cut_candidate_choice(
        json.dumps(
            {
                "selected_candidate_id": None,
                "score": 0.1,
                "valid_single_movement": False,
                "reason": "all candidates are partial lowering-only fragments",
            }
        ),
        candidates,
    )

    assert ranking is None


def test_llm_review_frame_count_scales_for_fast_movement_boundaries(tmp_path: Path) -> None:
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "build",
        wham_repo_path=None,
        body_model_root=None,
        review_frames=6,
    )

    assert bake_and_rank_module.llm_review_frame_count_for_chunk(2.0, request) == 32
    assert bake_and_rank_module.llm_review_frame_count_for_chunk(10.0, request) == 40
    assert bake_and_rank_module.llm_review_frame_count_for_chunk(20.0, request) == 48


def test_review_window_contact_sheet_renders_with_selected_postprocessing_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {"bake_options": None, "render_options": [], "timestamps": None}
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path / "candidate",
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=3.0,
        loop_start_seconds=0.0,
        loop_end_seconds=3.0,
        candidate={"videoId": "bench"},
        settings_options={
            "fixedRoot": True,
            "autoWorldAlignment": False,
            "sceneInverted": True,
            "cameraYawDegrees": 90.0,
            "lockPlantedHands": True,
        },
    )
    item.preview_html_path.write_text("<html></html>", encoding="utf-8")

    class FakePage:
        def goto(self, *_args: object, **_kwargs: object) -> None:
            pass

        def wait_for_function(self, *_args: object, **_kwargs: object) -> None:
            pass

        def evaluate(self, script: str, payload: dict[str, object]) -> object:
            if "bakeTimeRange" in script:
                captured["bake_options"] = dict(payload["options"])  # type: ignore[arg-type]
                return {
                    "durationSec": 3.0,
                    "frameCount": 3,
                    "fps": 1.0,
                    "frames": [
                        {"frameIndex": 0, "sourceTimeSec": 0.0},
                        {"frameIndex": 1, "sourceTimeSec": 1.5},
                        {"frameIndex": 2, "sourceTimeSec": 3.0},
                    ],
                }
            if "renderFrame" in script:
                render_options = captured["render_options"]
                assert isinstance(render_options, list)
                render_options.append(dict(payload["options"]))  # type: ignore[arg-type]
                return "data:image/png;base64,"
            raise AssertionError(script)

    class FakeBrowser:
        def new_page(self, **_kwargs: object) -> FakePage:
            return FakePage()

        def close(self) -> None:
            pass

    class FakePlaywright:
        pass

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(bake_and_rank_module, "launch_chromium_browser", lambda _playwright: FakeBrowser())
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: FakeSyncPlaywright(),
    )
    monkeypatch.setattr(
        bake_and_rank_module,
        "write_review_contact_sheet_from_data_urls",
        lambda _data_urls, output_path, *, timestamps=None: (
            captured.__setitem__("timestamps", timestamps),
            Path(output_path).write_bytes(b"sheet"),
        ),
    )

    result = bake_and_rank_module.render_review_window_contact_sheet(
        item=item,
        window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=3.0),
        output_dir=tmp_path / "frames",
        frame_count=3,
    )

    assert result == [tmp_path / "frames" / "contact_sheet.jpg"]
    assert captured["bake_options"] == item.settings_options
    render_options = captured["render_options"]
    assert isinstance(render_options, list)
    assert render_options
    assert all(options == item.settings_options for options in render_options)
    assert captured["timestamps"] == [0.0, 1.5, 3.0]


def test_final_selection_chooses_highest_score_deterministically(tmp_path: Path) -> None:
    items = [
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=1,
            exercise_name="Squat",
            candidate_title="Top",
            candidate_workspace=tmp_path / "candidate",
            preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
            skeleton_path=tmp_path / "candidate" / "wear" / "loop-2.json",
            review_video_path=tmp_path / "candidate" / "review" / "loop-2.mp4",
            duration_sec=3.0,
            loop_start_seconds=0.0,
            loop_end_seconds=3.0,
            candidate={"videoId": "top"},
        ),
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=0,
            exercise_name="Squat",
            candidate_title="Top",
            candidate_workspace=tmp_path / "candidate",
            preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
            skeleton_path=tmp_path / "candidate" / "wear" / "loop-1.json",
            review_video_path=tmp_path / "candidate" / "review" / "loop-1.mp4",
            duration_sec=3.0,
            loop_start_seconds=0.0,
            loop_end_seconds=3.0,
            candidate={"videoId": "top"},
        ),
    ]

    selected = choose_best_review_item(
        items,
        [
            LoopRanking(score=0.9, reasons=["tie"]),
            LoopRanking(score=0.9, reasons=["tie"]),
        ],
    )

    assert selected is not None
    assert selected[0].loop_index == 0


def test_review_item_to_manifest_includes_support_dominance_fields() -> None:
    candidate_workspace = Path("tmp") / "candidate"
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=1,
        exercise_name="Pull Up",
        candidate_title="Demo",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=candidate_workspace / "wear" / "loop-1.json",
        skeleton_path_no_feet_lock=candidate_workspace / "wear" / "loop-1.no-foot-lock.json",
        skeleton_path_no_hand_lock=candidate_workspace / "wear" / "loop-1.no-hand-lock.json",
        review_video_path=candidate_workspace / "review" / "loop-1.webm",
        duration_sec=2.5,
        loop_start_seconds=0.0,
        loop_end_seconds=2.5,
        candidate={"videoId": "abc"},
        support_dominance="hand_dominant",
        support_dominance_confidence=0.88,
        support_dominance_reason="Hands and forearms clearly carry the body.",
        support_dominance_uncertain=False,
        support_dominance_model_output={"supportDominance": "hand_dominant"},
    )

    manifest = bake_and_rank_module.review_item_to_manifest(item)

    assert manifest["supportDominance"] == "hand_dominant"
    assert manifest["supportDominanceConfidence"] == pytest.approx(0.88)
    assert manifest["supportDominanceReason"] == "Hands and forearms clearly carry the body."
    assert manifest["supportDominanceUncertain"] is False
    assert manifest["supportDominanceModelOutput"] == {"supportDominance": "hand_dominant"}
    assert manifest["skeletonPathNoHandLock"] == str(candidate_workspace / "wear" / "loop-1.no-hand-lock.json")


def test_selected_section_preview_embeds_interactive_selected_range(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    candidate_workspace = workspace / "candidate"
    review_video = candidate_workspace / "review" / "llm-selected-section.webm"
    skeleton = candidate_workspace / "wear" / "skeleton.baked.llm-selected-section.json"
    review_video.parent.mkdir(parents=True)
    skeleton.parent.mkdir(parents=True)
    review_video.write_bytes(b"video")
    skeleton.write_text("{}", encoding="utf-8")

    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Bulgarian Split Squat",
        candidate_title="Dumbbell Bulgarian Split Squat",
        candidate_workspace=candidate_workspace,
        preview_html_path=candidate_workspace / "preview" / "motion_preview.html",
        skeleton_path=skeleton,
        review_video_path=review_video,
        duration_sec=2.5,
        loop_start_seconds=1.25,
        loop_end_seconds=3.75,
        candidate={"videoId": "demo"},
        settings_options={
            "fixedRoot": True,
            "autoWorldAlignment": True,
            "lockPlantedFeet": True,
            "cameraYawDegrees": 45.0,
        },
        llm_time_range_cut_applied=True,
    )

    html_path = bake_and_rank_module.write_selected_section_preview_html(
        workspace,
        (item, LoopRanking(score=0.8, reasons=[])),
    )

    assert html_path is not None
    text = html_path.read_text(encoding="utf-8")
    assert "<iframe src=\"candidate/preview/motion_preview.html?startSeconds=1.250000&amp;endSeconds=3.750000" in text
    assert "%22lockPlantedFeet%22%3Atrue" in text
    assert "%22cameraYawDegrees%22%3A45.0" in text
    assert "<summary>Review sample</summary>" in text
    assert "<video controls loop muted>" in text
    assert "Open interactive preview" in text


def test_final_selection_rejects_best_loop_below_min_score(tmp_path: Path) -> None:
    items = [
        ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=0,
            exercise_name="Clean and Jerk",
            candidate_title="Top",
            candidate_workspace=tmp_path / "candidate",
            preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
            skeleton_path=tmp_path / "candidate" / "wear" / "loop-1.json",
            review_video_path=tmp_path / "candidate" / "review" / "loop-1.webm",
            duration_sec=2.0,
            loop_start_seconds=0.0,
            loop_end_seconds=2.0,
            candidate={"videoId": "top"},
        )
    ]

    selected = choose_best_review_item(items, [LoopRanking(score=0.31, reasons=[])], min_score=0.55)

    assert selected is None


def test_final_selection_uses_model_score_when_deterministic_validation_penalizes_artifact(tmp_path: Path) -> None:
    item = ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Bench Press",
        candidate_title="Bench press",
        candidate_workspace=tmp_path / "candidate",
        preview_html_path=tmp_path / "candidate" / "preview" / "motion_preview.html",
        skeleton_path=tmp_path / "candidate" / "wear" / "loop-1.json",
        review_video_path=tmp_path / "candidate" / "review" / "loop-1.webm",
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"videoId": "top"},
    )
    ranking = LoopRanking(
        score=0.49,
        reasons=["loop_bridge_pose_mismatch_penalty"],
        payload={"modelScore": 0.95},
        model_score=0.95,
    )

    selected = choose_best_review_item([item], [ranking], min_score=0.55)

    assert selected == (item, ranking)


def test_preview_html_exposes_headless_bake_automation_api(tmp_path: Path) -> None:
    html_path = tmp_path / "motion_preview.html"
    write_preview_html(html_path, build_loop_fixture_clip(), title="Squat")

    html = html_path.read_text(encoding="utf-8")
    assert "window.exerciseMotionAutomation" in html
    assert "bakeLoop(loopIndex" in html
    assert "lockPlantedFeet" in html
    assert "lockPlantedHands" in html
    assert "autoWorldAlignment" in html
    assert "showBoundsHelper" in html
    assert "cameraYawDegrees" in html
    assert "cameraPitchDegrees" in html


def test_preview_settings_variants_include_no_auto_alignment_combinations() -> None:
    variants = bake_and_rank_module.preview_settings_variants(motion_tuning_enabled=True)
    options_by_id = {
        str(variant["id"]): variant["options"]
        for variant in variants
    }

    assert options_by_id["no-support-lock-no-auto-alignment"] == {
        "lockPlantedFeet": False,
        "lockPlantedHands": False,
        "cleanupInterpretation": "support_lock",
        "autoWorldAlignment": False,
        "fixedRoot": True,
        "sceneInverted": False,
    }
    assert options_by_id["lock-feet-hands-no-auto-alignment-inverted"] == {
        "lockPlantedFeet": True,
        "lockPlantedHands": True,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": False,
        "sceneInverted": True,
    }


def test_preview_settings_variants_include_paired_hands_cleanup_mode() -> None:
    variants = preview_settings_variants(motion_tuning_enabled=True)
    by_id = {str(variant["id"]): variant for variant in variants}

    paired = by_id["paired-hands"]

    assert paired["cleanupInterpretation"] == "paired_hands"
    assert paired["options"]["cleanupInterpretation"] == "paired_hands"
    assert paired["options"]["lockPlantedHands"] is False
    assert paired["options"]["lockPlantedFeet"] is True
    assert by_id["lock-feet-hands"]["cleanupInterpretation"] == "support_lock"
    assert by_id["lock-feet-hands"]["options"]["lockPlantedHands"] is True


def test_preview_settings_variants_include_scene_inversion_and_global_drift_controls() -> None:
    variants = bake_and_rank_module.preview_settings_variants(motion_tuning_enabled=True)
    options_by_id = {
        str(variant["id"]): variant["options"]
        for variant in variants
    }

    assert options_by_id["lock-feet-hands-inverted"] == {
        "lockPlantedFeet": True,
        "lockPlantedHands": True,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": True,
        "sceneInverted": True,
    }
    assert options_by_id["lock-feet-hands-free-root"] == {
        "lockPlantedFeet": True,
        "lockPlantedHands": True,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": False,
        "autoWorldAlignment": True,
        "sceneInverted": False,
    }
    assert options_by_id["no-support-lock-inverted"] == {
        "lockPlantedFeet": False,
        "lockPlantedHands": False,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": True,
        "sceneInverted": True,
    }
    assert options_by_id["no-foot-lock-no-auto-alignment"] == {
        "lockPlantedFeet": False,
        "lockPlantedHands": True,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": False,
        "sceneInverted": False,
    }
    assert options_by_id["no-hand-lock-no-auto-alignment"] == {
        "lockPlantedFeet": True,
        "lockPlantedHands": False,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": False,
        "sceneInverted": False,
    }
    assert options_by_id["no-support-lock-no-auto-alignment-inverted"] == {
        "lockPlantedFeet": False,
        "lockPlantedHands": False,
        "cleanupInterpretation": "support_lock",
        "fixedRoot": True,
        "autoWorldAlignment": False,
        "sceneInverted": True,
    }

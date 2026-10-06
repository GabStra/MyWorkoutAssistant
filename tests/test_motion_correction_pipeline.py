import copy
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg.contact_pinning import pin_stationary_contact_chains


def test_yaw_translation_track_fills_unconstrained_frame_translations():
    anchors = [[-.2, 0., 0.], [.2, 0., 0.]]

    def constraints(angle):
        import math

        return [
            (1., anchor, [
                math.cos(angle) * anchor[0] + math.sin(angle) * anchor[2],
                anchor[1],
                -math.sin(angle) * anchor[0] + math.cos(angle) * anchor[2],
            ])
            for anchor in anchors
        ]

    result = bake._solve_yaw_translation_track({0: constraints(0.), 2: constraints(.12)}, 3, 1.)

    assert result is not None
    yaws, translations, _pivot = result
    assert len(yaws) == len(translations) == 3
    assert all(len(translation) == 3 for translation in translations)


def test_contact_pinning_fully_pins_confirmed_interval_at_clip_boundaries():
    frames = []
    for index in range(15):
        shift = index / 14 * 0.1
        frames.append({
            "timeSec": index / 30,
            "joints": {
                "left_hip": [shift, 1.0, 0.0],
                "left_knee": [shift + 0.1, 0.55, 0.0],
                "left_ankle": [shift, 0.2, 0.0],
                "left_foot": [shift, 0.1, 0.0],
            },
        })

    anchor = [0.05, 0.1, 0.0]
    report = pin_stationary_contact_chains(
        frames,
        [{
            "jointName": "left_foot",
            "evaluatedJointName": "left_foot",
            "startFrame": 0,
            "endFrame": len(frames) - 1,
            "anchor": anchor,
            "isObservedGroundContact": True,
        }],
        body_span=1.0,
        slide_threshold_ratio=0.0,
        joint_names=["left_hip", "left_knee", "left_ankle", "left_foot"],
        support_plane_y=anchor[1],
    )

    assert report["joints"]["left_foot"][0]["applied"]
    assert all(frame["joints"]["left_foot"] == pytest.approx(anchor) for frame in frames)


def test_confirmed_body_support_replaces_sparse_foot_contacts_with_full_clip_intervals():
    evidence = {
        "sharedSupportPlaneY": 0.0,
        "contacts": [{
            "jointName": "left_foot",
            "startRatio": 0.25,
            "endRatio": 0.5,
            "contactMotion": "stationary",
        }],
        "bodySupport": {
            "required": True,
            "status": "confirmed",
            "stationaryJoints": ["left_foot", "right_ankle"],
        },
    }

    intervals = bake.source_contact_intervals_from_evidence(
        evidence,
        frame_count=20,
    )

    by_joint = {row["jointName"]: row for row in intervals}
    assert set(by_joint) == {"left_foot", "right_ankle"}
    assert (by_joint["left_foot"]["startFrame"], by_joint["left_foot"]["endFrame"]) == (0, 19)
    assert (by_joint["right_ankle"]["startFrame"], by_joint["right_ankle"]["endFrame"]) == (0, 19)
    assert by_joint["left_foot"]["supportKind"] == "observed_foot_patch"


def test_reconstructed_support_fusion_preserves_explicit_airborne_release():
    frame_count = 60
    frames = [
        {"joints": {
            "head": [0.0, 1.8, 0.0],
            "pelvis": [0.0, 1.0, 0.0],
            "left_ankle": [0.0, 0.1, 0.0],
            "left_foot": [0.0, 0.0, 0.0],
        }}
        for _ in range(frame_count)
    ]
    evidence = {
        "contacts": [
            {"jointName": "left_ankle", "startFrame": 0, "endFrame": 27,
             "contactMotion": "stationary"},
            {"jointName": "left_ankle", "startFrame": 31, "endFrame": 59,
             "contactMotion": "stationary"},
        ],
        "feet": {"left": {
            "jointName": "left_ankle",
            "continuousSupport": False,
            "supportSplitByObservedAirborne": True,
            "chunkCenterRangeRatio": 0.0,
            "endpointDisplacementRatio": 0.0,
        }},
        "footPatchEvidence": {"feet": {"left": {
            "states": ["full_sole"] * 28 + ["airborne"] * 3 + ["full_sole"] * 29,
        }}},
    }

    fused, inference = bake.fuse_reconstructed_support_evidence(
        {"frames": frames}, evidence,
    )

    assert fused is not None
    assert fused["feet"]["left"]["continuousSupport"] is False
    assert fused.get("supportContacts", []) == []
    assert inference["applied"] is False

    legacy_full_clip = bake.source_contact_intervals_from_evidence(
        {
            "feet": {"left": {
                "jointName": "left_ankle",
                "continuousSupport": True,
            }},
            "footPatchEvidence": evidence["footPatchEvidence"],
        },
        frame_count=frame_count,
    )
    assert [(row["startFrame"], row["endFrame"]) for row in legacy_full_clip] == [
        (0, 27), (31, 59),
    ]


@pytest.mark.parametrize("anchor_ids", [
    ("shared", "shared"),
    ("before-flight", "after-flight"),
    (None, None),
])
def test_explicit_airborne_epochs_split_source_correction_anchors(anchor_ids):
    frame_count = 60
    frames = []
    for index in range(frame_count):
        if index <= 27:
            foot_x = 0.0
        elif index >= 31:
            foot_x = 1.0
        else:
            foot_x = 0.5
        frames.append({"joints": {
            "head": [0.0, 1.8, 0.0],
            "pelvis": [0.0, 1.0, 0.0],
            "left_hip": [-0.1, 1.0, 0.0],
            "left_knee": [-0.1, 0.5, 0.0],
            "left_ankle": [foot_x, 0.1, 0.0],
            "left_foot": [foot_x, 0.0, 0.0],
        }})
    first_contact = {
        "jointName": "left_foot", "supportKind": "foot",
        "startFrame": 0, "endFrame": 27,
        "contactMotion": "stationary", "contactState": "full_sole",
        "confidence": 1.0,
    }
    second_contact = {
        "jointName": "left_foot", "supportKind": "foot",
        "startFrame": 31, "endFrame": 59,
        "contactMotion": "stationary", "contactState": "full_sole",
        "confidence": 1.0,
    }
    if anchor_ids[0] is not None:
        first_contact["anchorGroupId"] = anchor_ids[0]
    if anchor_ids[1] is not None:
        second_contact["anchorGroupId"] = anchor_ids[1]
    evidence = {
        "contacts": [first_contact, second_contact],
        "feet": {"left": {"continuousSupport": False}},
        "footPatchEvidence": {"feet": {"left": {
            "states": ["full_sole"] * 28 + ["airborne"] * 3 + ["full_sole"] * 29,
        }}},
    }
    payload = {"frames": frames, "fps": 30.0}

    intervals = bake.source_contact_intervals_from_evidence(
        evidence,
        frame_count=frame_count,
    )
    correction, correction_metrics = bake.apply_source_contact_sequence_correction(
        payload,
        evidence,
    )
    support_metrics = bake.source_confirmed_support_stationarity_metrics(
        payload,
        evidence,
    )

    foot_intervals = [row for row in intervals if row["jointName"] == "left_foot"]
    corrected_intervals = correction_metrics["contactIntervals"]
    assert [(row["startFrame"], row["endFrame"]) for row in foot_intervals] == [
        (0, 27), (31, 59),
    ]
    assert [row["airborneEpoch"] for row in foot_intervals] == [0, 1]
    assert corrected_intervals[0]["airborneEpoch"] == 0
    assert corrected_intervals[1]["airborneEpoch"] == 1
    assert corrected_intervals[0]["anchor"][0] == pytest.approx(0.0)
    assert corrected_intervals[1]["anchor"][0] == pytest.approx(1.0)
    assert support_metrics["passed"] is True
    assert len(support_metrics["sides"]["left"]["anchorGroups"]) == sum(
        anchor_id is not None for anchor_id in anchor_ids
    )
    assert correction["frames"][28]["joints"]["left_foot"][0] == pytest.approx(0.5)


def test_ground_plane_uses_confirmed_support_geometry_before_drifting_reconstruction():
    frames = [
        {"joints": {"left_foot": [0.0, 0.3, 0.0], "right_foot": [0.2, 0.4, 0.0]}}
        for _ in range(3)
    ]
    intervals = [
        {"jointName": name, "startFrame": 0, "endFrame": 2,
         "supportKind": "observed_foot_patch", "surfaceKind": "ground"}
        for name in ("left_foot", "right_foot")
    ]
    evidence = {
        "bodySupport": {
            "required": True,
            "status": "confirmed",
            "stationaryJoints": ["left_foot", "right_foot"],
            "coplanarGroups": [{
                "joints": ["left_foot", "right_foot"],
                "normal": [0.0, 2.0, 0.0],
                "planeOffsetMeters": 0.05,
            }],
        },
    }

    plane_y, source = bake.observed_ground_support_plane_y(
        frames,
        intervals,
        evidence,
        render_floor_y=0.2,
    )

    assert plane_y == pytest.approx(0.05)
    assert source == "confirmed_body_support_geometry"


def test_swapped_source_support_is_mapped_for_correction_and_final_gate(monkeypatch):
    evidence = {
        "supportContacts": [{
            "jointName": "left_foot",
            "startRatio": 0.0,
            "endRatio": 1.0,
            "continuousSupport": True,
        }],
    }
    payload = {
        "frames": [],
        "sourceFootSupportEvidence": evidence,
        "sourcePoseCameraReference": {
            "camera": {"bilateralAssignment": "swapped"},
        },
    }
    observed = {}

    def record_intervals(value, **kwargs):
        observed.setdefault("intervalEvidence", value)
        return []

    monkeypatch.setattr(bake, "source_contact_intervals_from_evidence", record_intervals)
    corrected, report = bake.apply_source_contact_sequence_correction(payload, evidence)
    assert [row["jointName"] for row in observed["intervalEvidence"]["supportContacts"]] == [
        "right_foot"
    ]
    assert report["contactIntervals"] == []
    assert corrected["sourceFootSupportEvidence"] == evidence

    observed.clear()
    metrics = bake.source_confirmed_support_stationarity_metrics(payload, evidence)
    assert [row["jointName"] for row in observed["intervalEvidence"]["supportContacts"]] == [
        "right_foot"
    ]
    assert metrics["required"] is False
    assert payload["sourceFootSupportEvidence"] == evidence


@pytest.mark.parametrize("rigid_passes,loop_required,selection_class", [
    (True, True, bake.FULL_CLIP_BAKE),
    (True, False, bake.FULL_CLIP_BAKE),
    (False, True, bake.FULL_CLIP_BAKE),
    (False, False, bake.FULL_CLIP_BAKE),
    (False, True, bake.BOUNDED_MOVEMENT_SELECTION),
])
def test_source_contact_correction_preserves_artifact_interval_and_baseline(
        tmp_path, monkeypatch, rigid_passes, loop_required, selection_class):
    baseline = {"frames": [{"joints": {"left_ankle": [0, 0, 0]}} for _ in range(10)],
                "jointNames": ["left_ankle"], "frameCount": 10, "fps": 30}
    calls = []
    fit_payload_states = []

    class Page:
        def goto(self, *args, **kwargs): pass
        def wait_for_function(self, *args): pass
        def evaluate(self, script, args=None):
            if args is None:
                return {"motionTuningEnabled": True}
            if selection_class == bake.FULL_CLIP_BAKE:
                # Synthetic exact-source clips have no corresponding detected loop.
                assert args["explicitTimeRange"] is True
                assert "? window.exerciseMotionAutomation.bakeTimeRange" in script
            else:
                assert args["explicitTimeRange"] is False
                assert args["explicitFrameRange"] is False
            assert (args["startSeconds"], args["endSeconds"]) == (2.0, 5.0)
            calls.append(args["options"])
            result = copy.deepcopy(baseline)
            if selection_class == bake.BOUNDED_MOVEMENT_SELECTION:
                result["loop"] = {
                    "enabled": False,
                    "sourceStartFrame": 10,
                    "sourceEndFrame": 19,
                    "sourceStartTimeSec": 2.0,
                    "sourceEndTimeSec": 5.0,
                }
                for frame_index, frame in enumerate(result["frames"]):
                    frame["sourceFrameIndex"] = 10 + frame_index
                    frame["sourceTimeSec"] = 2.0 + frame_index / 3.0
            if args["options"].get("contactSequenceCorrection"):
                result["corrected"] = True
            return result

    class Context:
        def __enter__(self): return SimpleNamespace(new_page=lambda **kwargs: Page(), close=lambda: None)
        def __exit__(self, *args): pass

    monkeypatch.setattr(bake, "browser_session", lambda launch: Context())
    monkeypatch.setattr(bake, "stage_preview_for_browser_if_needed", lambda path: (path, None))
    monkeypatch.setattr(bake, "plan_adaptive_preview_settings_variants", lambda **kwargs: [
        {"id": "adaptive-baseline", "label": "Baseline", "options": {}}])
    monkeypatch.setattr(bake, "select_readable_preview_camera_options",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "deterministic_post_bake_scene_orientation_correction",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(
        bake,
        "load_baked_source_camera_reference",
        lambda *args: {"camera": {"bilateralAssignment": "swapped"}},
    )
    def record_fit_payload(payload, **kwargs):
        if payload.get("corrected"):
            fit_payload_states.append(copy.deepcopy(payload.get("artifactState")))
        return payload, {}

    monkeypatch.setattr(bake, "constrain_baked_payload_to_source_articulation", record_fit_payload)
    monkeypatch.setattr(bake, "render_baked_wear_frames_with_playwright", lambda *args, **kwargs: ["frame"])
    monkeypatch.setattr(bake, "write_validated_review_video_from_data_urls",
                        lambda frames, path, **kwargs: (path, {"passed": True}))
    monkeypatch.setattr(bake, "fuse_reconstructed_support_evidence",
                        lambda payload, evidence: (evidence, {"applied": True}))
    monkeypatch.setattr(bake, "source_contact_intervals_from_evidence",
                        lambda evidence, **kwargs: [{"jointName": "left_ankle"}])
    monkeypatch.setattr(bake, "apply_source_contact_sequence_correction",
                        lambda payload, evidence, **kwargs: (
                            {**copy.deepcopy(payload), "corrected": True}, {"applied": True}))
    monkeypatch.setattr(bake, "source_confirmed_support_stationarity_metrics",
                        lambda *args: {"passed": rigid_passes})
    monkeypatch.setattr(bake, "payload_loop_seam_joint_rms", lambda payload: 2 if payload.get("corrected") else 1)
    monkeypatch.setattr(bake, "exercise_requires_loop_continuity",
                        lambda *args, **kwargs: loop_required)
    selected_loop = (
        {"type": "exact_source_movement_instance"}
        if selection_class == bake.FULL_CLIP_BAKE
        else {
            "type": "bounded_movement_selection",
            "startFrame": 10,
            "endFrame": 19,
            "startTimeSec": 2.0,
            "endTimeSec": 5.0,
            "durationSec": 3.0,
        }
    )
    artifacts = bake.bake_preview_loops_with_playwright(
        tmp_path / "preview.html", [bake.EligibleLoop(
            0, selected_loop, 3, 2, 5, artifact_class=selection_class)],
        tmp_path / "candidate", 6, adaptive_preview_settings=True,
        source_foot_support_evidence={"supportContacts": [{
            "jointName": "left_foot",
            "startRatio": 0.0,
            "endRatio": 1.0,
            "continuousSupport": True,
        }]})
    assert calls[0]["sourceFootSupportEvidence"]["supportContacts"][0]["jointName"] == (
        "left_foot"
    )
    assert calls[0]["motionSpaceSupportEvidence"]["supportContacts"][0]["jointName"] == (
        "right_foot"
    )
    assert len(calls) == (1 if rigid_passes else 2)
    assert artifacts[0].settings_variant_id == "adaptive-baseline"
    assert len(artifacts) == (1 if loop_required else 2)
    if not rigid_passes:
        assert calls[-1]["contactSequenceCorrection"] is True
        if selection_class == bake.BOUNDED_MOVEMENT_SELECTION:
            assert len(fit_payload_states) == 1
            selected = fit_payload_states[0]["selectionEvidence"]["boundedMovementSelection"]
            assert selected["interval"] == {
                "type": "bounded_movement_selection",
                "startFrame": 10,
                "endFrame": 19,
                "startTimeSec": 2.0,
                "endTimeSec": 5.0,
                "durationSec": 3.0,
            }


@pytest.mark.parametrize("status,failure_stage,expected", [
    ("rejected_raw_wham_validation", None, "raw_reconstruction_validation"),
    ("rejected_baked_motion_validation", None, "baked_motion_validation"),
    ("skipped_no_baked_clip", None, "baked_motion_validation"),
    ("failed", "browser_bake", "browser_bake"),
    ("failed", None, "processing_error"),
])
def test_final_diagnostics_distinguish_quality_from_processing_errors(status, failure_stage, expected):
    manifest = {"candidateResults": [{"status": status, "failureStage": failure_stage,
        "failures": [{"reason": "test_failure"}],
        "timings": {"previewBakeSeconds": 12.5, "nested": {"secret": 1}}}]}
    diagnostics = wave.final_processing_diagnostics(manifest)
    candidate = diagnostics["candidateDiagnostics"][0]
    assert candidate["stage"] == expected
    assert candidate["reasons"] == ["test_failure"]
    assert candidate["timings"] == {"previewBakeSeconds": 12.5}


def test_final_diagnostics_surface_concrete_baked_rejection_codes():
    diagnostics = wave.final_processing_diagnostics({
        "candidateResults": [{
            "status": "rejected_baked_motion_validation",
            "failures": [{
                "reason": "baked_motion_validation_failed",
                "rejectionReasons": [
                    "materialized_pre_render_rejected",
                    "materialized_source_endpoint_pose_mismatch",
                ],
            }],
            "rejectedSourceClips": [{
                "reason": "materialized_pre_render_rejected",
                "rejectionReasons": ["materialized_source_endpoint_pose_mismatch"],
            }],
        }]
    })
    assert diagnostics["candidateDiagnostics"][0]["stage"] == "baked_motion_validation"
    assert diagnostics["candidateDiagnostics"][0]["reasons"] == [
        "baked_motion_validation_failed",
        "materialized_pre_render_rejected",
        "materialized_source_endpoint_pose_mismatch",
    ]


def test_final_diagnostics_surface_fit_timeout_under_incomplete_processing():
    diagnostics = wave.final_processing_diagnostics({
        "candidateResults": [{
            "status": "needs_motion_processing",
            "failures": [{
                "reason": "controlled_motion_processing_incomplete",
                "rejectionReasons": ["no_validated_loop_cycle"],
            }],
            "controlledMotionFit": {"applied": False, "reason": "fit_timeout"},
        }]
    })
    assert diagnostics["candidateDiagnostics"][0]["stage"] == "controlled_motion_processing"
    assert diagnostics["candidateDiagnostics"][0]["reasons"] == [
        "controlled_motion_processing_incomplete",
        "no_validated_loop_cycle",
        "fit_timeout",
    ]


def test_final_diagnostics_identify_model_rejection():
    diagnostics = wave.final_processing_diagnostics({
        "candidateResults": [{"status": "ready_for_selection"}],
        "timings": {"candidateSelectionAttempts": [{"rejectionReasons": ["final_output_model_rejected"]}],
                    "reviewRankingSeconds": 3.2}})
    assert diagnostics["candidateDiagnostics"][0]["stage"] == "model_review"
    assert diagnostics["reviewTimings"] == {"reviewRankingSeconds": 3.2}

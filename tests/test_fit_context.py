import json
from copy import deepcopy

import numpy as np

from exercise_motion_pkg import fit_context
from exercise_motion_pkg import controlled_motion as motion


JOINT_NAMES = ("pelvis", "left_foot")


def _candidate(frame_count=3, fps=30.0):
    return {
        "fps": fps,
        "jointNames": list(JOINT_NAMES),
        "frames": [
            {
                "timeSec": index / fps,
                "joints": {
                    name: [float(index), 1.0, 0.0] for name in JOINT_NAMES
                },
                "sourceJoints": {
                    name: [float(index), 1.0, 0.0] for name in JOINT_NAMES
                },
            }
            for index in range(frame_count)
        ],
    }


def _actual_constraints(frame_count=3):
    count, joints = frame_count, len(JOINT_NAMES)
    pinned = np.zeros((count, joints), dtype=bool)
    pinned[:, 1] = True
    targets = np.zeros((count, joints, 3), dtype=float)
    targets[:, 1, 1] = 1.0
    temporal = np.zeros((count, joints, 3), dtype=float)
    anchor_ids = np.full((count, joints), None, dtype=object)
    anchor_ids[:, 1] = "support-anchor"
    model_mask = np.zeros((count, joints), dtype=bool)
    native_tracks = {
        "version": 2,
        "left": {"activeFrames": [1, 2], "observed": True},
        "right": {"activeFrames": [], "observed": False},
    }
    native_geometry = {"sides": {"left": {"lengthMeters": 0.25}}}
    return dict(
        fit_contact_pinned=pinned,
        fit_contact_targets=targets,
        temporal_reference=temporal,
        jerk_limit=12.5,
        contact_limit=0.003,
        contact_anchor_ids=anchor_ids,
        model_intent_contact_mask=model_mask,
        native_foot_tracks=native_tracks,
        native_foot_geometry=native_geometry,
    )


def _build(candidate, **overrides):
    return fit_context.build_fit_context(
        candidate, **_actual_constraints(len(candidate["frames"])), **overrides
    )


def test_actual_arrays_survive_callback_serialization_and_report_is_copied():
    candidate = _candidate()
    constraints = _actual_constraints(len(candidate["frames"]))
    captured = {}

    def persist(saved_candidate, report, input_payload):
        captured["candidate"] = saved_candidate
        captured["report"] = json.loads(json.dumps(report))
        return {"path": "rejected.json"}

    report = {"applied": False, "reason": "synthetic_rejection"}
    with motion.capture_rejected_fit_candidate(persist):
        motion.retain_rejected_fit_candidate(
            candidate,
            report,
            candidate,
            fit_context_factory=lambda: fit_context.build_fit_context(
                candidate, **constraints
            ),
        )

    saved_context = captured["report"]["fitContext"]
    assert saved_context["complete"] is True
    assert saved_context["fitContactPinned"] == constraints[
        "fit_contact_pinned"
    ].tolist()
    assert saved_context["fitContactTargets"] == constraints[
        "fit_contact_targets"
    ].tolist()
    assert saved_context["temporalReferenceJoints"] == constraints[
        "temporal_reference"
    ].tolist()
    assert saved_context["contactAnchorIds"] == constraints[
        "contact_anchor_ids"
    ].tolist()
    assert saved_context["nativeFootMaterialTracks"] == constraints[
        "native_foot_tracks"
    ]
    assert saved_context["jerkLimit"] == 12.5
    assert saved_context["contactLimitMeters"] == 0.003
    assert captured["report"]["reason"] == "synthetic_rejection"
    # The ordinary report gets the existing reference only, never fitContext.
    assert "fitContext" not in report
    assert report["rejectedFitDiagnostic"] == {"path": "rejected.json"}
    assert fit_context.validate_fit_context(candidate, saved_context)["passed"]


def test_later_array_mutation_cannot_change_saved_snapshot():
    candidate = _candidate()
    constraints = _actual_constraints(len(candidate["frames"]))
    context = fit_context.build_fit_context(candidate, **constraints)
    pinned_before = deepcopy(context["fitContactPinned"])
    targets_before = deepcopy(context["fitContactTargets"])
    tracks_before = deepcopy(context["nativeFootMaterialTracks"])

    constraints["fit_contact_pinned"][:] = False
    constraints["fit_contact_targets"][:] = 99.0
    constraints["native_foot_tracks"]["left"]["activeFrames"].append(99)

    assert context["fitContactPinned"] == pinned_before
    assert context["fitContactTargets"] == targets_before
    assert context["nativeFootMaterialTracks"] == tracks_before
    assert fit_context.validate_fit_context(candidate, context)["passed"]


def test_stale_candidate_and_stale_context_are_rejected():
    candidate = _candidate()
    context = _build(candidate)
    assert fit_context.validate_fit_context(candidate, context)["passed"]

    changed = deepcopy(candidate)
    changed["frames"][0]["joints"]["pelvis"][0] = 8.0
    stale_candidate = fit_context.validate_fit_context(changed, context)
    assert stale_candidate["passed"] is False
    assert "candidate_pose_digest_mismatch" in stale_candidate["reasons"]

    stale_context = deepcopy(context)
    stale_context["frameCount"] = len(candidate["frames"]) + 1
    stale_frame_count = fit_context.validate_fit_context(candidate, stale_context)
    assert stale_frame_count["passed"] is False
    assert "frame_count_mismatch" in stale_frame_count["reasons"]
    assert "context_digest_mismatch" in stale_frame_count["reasons"]


def test_existing_three_argument_callback_still_works():
    candidate = _candidate()
    calls = []

    def callback(saved_candidate, report, input_payload):
        calls.append((saved_candidate, report, input_payload))
        return {"reference": True}

    report = {"applied": False}
    with motion.capture_rejected_fit_candidate(callback):
        motion.retain_rejected_fit_candidate(candidate, report, candidate)

    assert len(calls) == 1
    assert calls[0][1] is report
    assert "fitContext" not in calls[0][1]
    assert report["rejectedFitDiagnostic"] == {"reference": True}


def test_capture_off_does_not_invoke_context_builder():
    candidate = _candidate()
    report = {"applied": False}

    def forbidden_factory():
        raise AssertionError("builder must stay dormant without capture")

    motion.retain_rejected_fit_candidate(
        candidate, report, candidate, fit_context_factory=forbidden_factory
    )
    assert report == {"applied": False}


def test_failed_context_build_still_preserves_the_actual_proposal():
    candidate = _candidate()
    candidate["fixedRig"] = {"version": 1, "coordinates": [[0.25, 1.0, 0.0]]}
    captured = {}

    def persist(saved_candidate, report, input_payload):
        captured["candidate"] = saved_candidate
        captured["report"] = report
        return {"reference": True}

    def broken_factory():
        raise RuntimeError("synthetic context failure")

    report = {"applied": False, "reason": "synthetic_rejection"}
    with motion.capture_rejected_fit_candidate(persist):
        motion.retain_rejected_fit_candidate(
            candidate, report, candidate, fit_context_factory=broken_factory
        )

    assert captured["candidate"] is candidate
    assert captured["candidate"]["fixedRig"]["coordinates"][0][0] == 0.25
    context = captured["report"]["fitContext"]
    assert context["complete"] is False
    assert context["available"] is False
    assert "synthetic context failure" in context["error"]
    assert report["rejectedFitDiagnostic"] == {"reference": True}
    assert fit_context.validate_fit_context(candidate, context)["passed"] is False


def test_missing_required_constraints_are_incomplete_not_defaults():
    candidate = _candidate()
    context = fit_context.build_fit_context(
        candidate,
        fit_contact_pinned=None,
        fit_contact_targets=np.zeros((3, 2, 3)),
        temporal_reference=np.zeros((3, 2, 3)),
        jerk_limit=None,
        contact_limit=None,
    )
    assert context["complete"] is False
    assert context["fitContactPinned"] is None
    assert context["jerkLimit"] is None
    assert "fitContactPinned_unavailable" in context["unavailableReasons"]
    validation = fit_context.validate_fit_context(candidate, context)
    assert validation["passed"] is False
    assert "context_incomplete" in validation["reasons"]


def test_fit_and_hard_joint_masks_remain_distinct():
    candidate = _candidate()
    constraints = _actual_constraints(len(candidate["frames"]))
    hard_pinned = np.zeros((3, 2), dtype=bool)
    hard_pinned[:, 0] = True
    hard_targets = np.zeros((3, 2, 3), dtype=float)
    hard_targets[:, 0, 1] = 2.0

    context = fit_context.build_fit_context(
        candidate,
        **constraints,
        joint_contact_pinned=hard_pinned,
        joint_contact_targets=hard_targets,
    )

    assert context["jointContactPinned"] == hard_pinned.tolist()
    assert context["jointContactTargets"] == hard_targets.tolist()
    # The fitting/repair targets stay untouched and remain a different mask.
    assert context["fitContactPinned"] == constraints[
        "fit_contact_pinned"
    ].tolist()
    assert context["jointContactPinned"] != context["fitContactPinned"]
    assert context["complete"] is True
    assert fit_context.validate_fit_context(candidate, context)["passed"]


def test_missing_hard_joint_mask_stays_unavailable_not_fit_fallback():
    candidate = _candidate()
    context = _build(candidate)

    assert context["fitContactPinned"] is not None
    assert context["jointContactPinned"] is None
    assert context["jointContactTargets"] is None
    # An absent hard gate must never be silently replaced by the fit mask.
    assert context["jointContactPinned"] != context["fitContactPinned"]
    # Old builder callers stay complete; only the joint gate is unavailable.
    assert context["complete"] is True
    assert fit_context.validate_fit_context(candidate, context)["passed"]


def test_late_capture_uses_validator_contact_limit_and_hard_mask():
    candidate = _candidate()
    constraints = _actual_constraints(len(candidate["frames"]))
    hard_pinned = np.zeros((3, 2), dtype=bool)
    hard_pinned[:, 0] = True

    context = motion.build_late_fit_context(
        candidate,
        fit_contact_pinned=constraints["fit_contact_pinned"],
        fit_contact_targets=constraints["fit_contact_targets"],
        joint_contact_pinned=hard_pinned,
        joint_contact_targets=constraints["fit_contact_targets"],
        temporal_reference=constraints["temporal_reference"],
        jerk_limit=constraints["jerk_limit"],
        contact_anchor_ids=constraints["contact_anchor_ids"],
        model_intent_contact_mask=constraints["model_intent_contact_mask"],
        native_foot_tracks=constraints["native_foot_tracks"],
        native_foot_geometry=constraints["native_foot_geometry"],
    )

    assert context["contactLimitMeters"] == motion.KEYFRAME_CONTACT_LIMIT_METERS
    assert context["contactLimitMeters"] != motion.PLAYBACK_CONTACT_LIMIT_METERS
    assert context["jointContactPinned"] == hard_pinned.tolist()
    assert context["fitContactPinned"] == constraints[
        "fit_contact_pinned"
    ].tolist()
    assert fit_context.validate_fit_context(candidate, context)["passed"]

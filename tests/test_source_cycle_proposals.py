from exercise_motion_pkg import bake_and_rank
from exercise_motion_pkg import loop_cycles
import pytest


@pytest.fixture(autouse=True)
def phase_only_boundary_fixture(monkeypatch):
    # These phase fixtures omit joint geometry; boundary behavior is tested separately.
    monkeypatch.setattr(loop_cycles, 'cycle_boundary_motion_metrics',
                        lambda *_args, **_kwargs: {'passed': True})


@pytest.mark.parametrize('boundary_passed', [True, False])
def test_source_validated_cycle_proposals_uses_full_interval_only_when_both_phases_pass(monkeypatch, boundary_passed):
    payload = {"frames": [{} for _ in range(7)], "jointNames": []}
    monkeypatch.setattr(bake_and_rank, "observable_motion_spec_for_contract", lambda _contract: object())
    monkeypatch.setattr(bake_and_rank, "dominant_observable_motion_phase_track", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bake_and_rank, "body_height_from_payload_frames", lambda _frames: 1.0)
    monkeypatch.setattr(loop_cycles, "rank_loop_cycles", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(loop_cycles, "slice_loop_cycle", lambda original, _choice: original)
    monkeypatch.setattr(loop_cycles, 'cycle_boundary_motion_metrics',
                        lambda *_args, **_kwargs: {'passed': boundary_passed})
    monkeypatch.setattr(bake_and_rank, "source_pose_reference_for_motion", lambda *_args: {})
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda *_args, **_kwargs: {
            "required": True, "passed": True, "hasSingleMajorCycle": True,
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_payload",
        lambda *_args, **_kwargs: {
            "required": True, "passed": True, "hasSingleMajorCycle": True,
        },
    )

    accepted, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose={}, contract={}
    )

    assert accepted == ([{
        "startFrame": 0,
        "stopFrameExclusive": 7,
        "score": 1.0,
        "endpointGapMeters": 0.0,
    }] if boundary_passed else [])
    assert diagnostics[-1]["selectionSource"] == "whole_interval_source_and_output_phase"
    assert diagnostics[-1]['boundaryMotion']['passed'] is boundary_passed


def test_source_validated_cycle_proposals_rejects_unconfirmed_full_interval(monkeypatch):
    payload = {"frames": [{} for _ in range(7)], "jointNames": []}
    monkeypatch.setattr(bake_and_rank, "observable_motion_spec_for_contract", lambda _contract: object())
    monkeypatch.setattr(bake_and_rank, "dominant_observable_motion_phase_track", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bake_and_rank, "body_height_from_payload_frames", lambda _frames: 1.0)
    monkeypatch.setattr(loop_cycles, "rank_loop_cycles", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(loop_cycles, "slice_loop_cycle", lambda original, _choice: original)
    monkeypatch.setattr(bake_and_rank, "source_pose_reference_for_motion", lambda *_args: {})
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda *_args, **_kwargs: {"required": True, "passed": False},
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_payload",
        lambda *_args, **_kwargs: {"required": True, "passed": True},
    )

    accepted, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose={}, contract={}
    )

    assert accepted == []
    assert all(item.get('passed') is False for item in diagnostics)


def test_source_validated_cycle_proposals_rejects_partial_crop_and_keeps_full_interval_first(monkeypatch):
    payload = {"frames": [{} for _ in range(9)], "jointNames": []}
    monkeypatch.setattr(bake_and_rank, "observable_motion_spec_for_contract", lambda _contract: object())
    monkeypatch.setattr(bake_and_rank, "dominant_observable_motion_phase_track", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bake_and_rank, "body_height_from_payload_frames", lambda _frames: 1.0)
    monkeypatch.setattr(
        loop_cycles,
        "rank_loop_cycles",
        lambda *_args, **_kwargs: [{"startFrame": 2, "stopFrameExclusive": 7, "score": 3.0}],
    )
    monkeypatch.setattr(
        loop_cycles,
        "slice_loop_cycle",
        lambda original, selection: {
            **original,
            "frames": original["frames"] if selection["startFrame"] == 0 else original["frames"][2:7],
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "source_pose_reference_for_motion",
        lambda _source, motion: {"frames": motion["frames"], "jointNames": []},
    )

    def phase_metrics(actual, **_kwargs):
        full = len(actual["frames"]) == 9
        return {
            "required": True,
            "passed": True,
            "hasSingleMajorCycle": True,
            "dominantMotionRangeRatio": 1.0 if full else 0.5,
            "phaseSignalSignature": "same-approved-repetition",
        }

    monkeypatch.setattr(
        bake_and_rank, "full_repetition_phase_completeness_metrics_from_source_pose_payload", phase_metrics
    )
    monkeypatch.setattr(
        bake_and_rank, "full_repetition_phase_completeness_metrics_from_payload", phase_metrics
    )
    monkeypatch.setattr(
        bake_and_rank,
        "comparable_phase_motion_capture_ratio",
        lambda child, parent: child["dominantMotionRangeRatio"] / parent["dominantMotionRangeRatio"],
    )

    accepted, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose={}, contract={}
    )

    assert accepted[0]["startFrame"] == 0
    assert accepted[0]["stopFrameExclusive"] == 9
    assert all(choice.get("startFrame") != 2 for choice in accepted)
    rejected_crop = next(item for item in diagnostics if item.get("selection", {}).get("startFrame") == 2)
    assert rejected_crop["parentPhaseCaptureRatio"] == 0.5
    assert rejected_crop["passed"] is False


def test_multi_repetition_parent_without_approved_phase_envelope_stays_unresolved(monkeypatch):
    payload = {"frames": [{} for _ in range(18)], "jointNames": []}
    crop_choice = {
        "startFrame": 2,
        "stopFrameExclusive": 7,
        "score": 3.0,
        "minimumRetainedRangeRatio": 0.92,
    }
    monkeypatch.setattr(bake_and_rank, "observable_motion_spec_for_contract", lambda _contract: object())
    monkeypatch.setattr(bake_and_rank, "dominant_observable_motion_phase_track", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bake_and_rank, "body_height_from_payload_frames", lambda _frames: 1.0)
    monkeypatch.setattr(loop_cycles, "rank_loop_cycles", lambda *_args, **_kwargs: [crop_choice])
    monkeypatch.setattr(
        loop_cycles,
        "slice_loop_cycle",
        lambda original, selection: {
            **original,
            "frames": original["frames"][selection["startFrame"]:selection["stopFrameExclusive"]],
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "source_pose_reference_for_motion",
        lambda _source, motion: {"frames": motion["frames"], "jointNames": []},
    )

    def phase_metrics(actual, **_kwargs):
        single = len(actual["frames"]) < 18
        return {
            "required": True,
            "passed": True,
            "hasSingleMajorCycle": single,
            "dominantMotionRangeRatio": 1.0 if single else 2.0,
            "phaseSignalSignature": "same-approved-repetition",
        }

    monkeypatch.setattr(
        bake_and_rank, "full_repetition_phase_completeness_metrics_from_source_pose_payload", phase_metrics
    )
    monkeypatch.setattr(
        bake_and_rank, "full_repetition_phase_completeness_metrics_from_payload", phase_metrics
    )
    monkeypatch.setattr(
        bake_and_rank,
        "comparable_phase_motion_capture_ratio",
        lambda child, parent: child["dominantMotionRangeRatio"] / parent["dominantMotionRangeRatio"],
    )

    accepted, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose={}, contract={}
    )

    assert accepted == []
    crop_diagnostic = next(item for item in diagnostics if item.get("selection") == crop_choice)
    assert crop_diagnostic["parentSourcePhase"]["hasSingleMajorCycle"] is False
    assert crop_diagnostic["parentPhaseCaptureSource"] is None
    assert crop_diagnostic["parentPhaseCaptureRatio"] is None
    assert crop_diagnostic["needsReview"] is True
    assert crop_diagnostic["reason"] == "parent_phase_coverage_unresolved"


def test_multi_repetition_source_phase_uses_independently_validated_execution_ranges():
    contract = {
        "movementType": "repetition", "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "observableMotionSpec": {
            "schemaVersion": 1, "primaryMovingRegions": ["hands"],
            "referenceRegions": ["torso"], "primaryAxis": "vertical",
            "motionPattern": "joint_travel", "requiresReturnToStart": True,
            "oneWayPartialIsInvalid": True, "mustShowFullCycle": True,
            "mustBeVisibleRegions": ["hands", "torso"],
        },
    }

    for values in (
        [.5, .6, 1, .7, .2, 0, .2, .7, 1, .7, .2, 0],
        [.5, .4, 0, .3, .8, 1, .8, .3, 0, .3, .8, 1],
    ):
        frames = []
        for index, value in enumerate(values):
            joints = {
                "pelvis": [0, .5, 0], "hips": [0, .5, 0],
                "left_shoulder": [-.1, .8, 0], "right_shoulder": [.1, .8, 0],
                "left_hip": [-.1, .5, 0], "right_hip": [.1, .5, 0],
                "left_knee": [-.1, .3, 0], "right_knee": [.1, .3, 0],
                "left_ankle": [-.1, 0, 0], "right_ankle": [.1, 0, 0],
                "left_wrist": [-.1, .5 + value * .4, 0],
                "right_wrist": [.1, .5 + value * .4, 0],
            }
            frames.append({"sourceTimeSec": float(index), "joints": joints})
        source = {"frames": frames, "jointNames": list(frames[0]["joints"]), "rootJoint": "pelvis"}
        parent = bake_and_rank.full_repetition_phase_completeness_metrics_from_source_pose_payload(
            source, exercise_name="", ranking_payload={"exerciseMotionContract": contract})
        assert parent["passed"] is False
        assert parent["hasSingleMajorCycle"] is False
        assert parent["hasCompleteMajorCycle"] is True

        references = bake_and_rank.source_phase_reference_intervals(source, contract, parent)

        assert len(references) == 2
        assert all(item["source"] == "validated_source_execution" for item in references)


def test_source_execution_reference_requires_time_overlap_and_matching_phase(monkeypatch):
    source = {"frames": [{"sourceTimeSec": float(index)} for index in range(13)]}
    references = [{"startFrame": 0, "stopFrameExclusive": 7,
                   "metrics": {"dominantMotionRangeRatio": 1.0}}]
    candidate = {"frames": [{"sourceTimeSec": float(index)} for index in range(7)]}
    parent_metrics = {"required": True, "passed": True, "hasSingleMajorCycle": True}
    monkeypatch.setattr(bake_and_rank, "comparable_phase_motion_capture_ratio", lambda *_args: .8)

    reference, details = bake_and_rank.source_phase_reference_for_interval(
        references, candidate, source, parent_metrics)

    assert reference is references[0]
    assert details["phaseMotionCaptureRatio"] == .8
    assert details["sourceExecutionOverlapRatio"] == 1.0
    crossing = {"frames": [{"sourceTimeSec": float(index)} for index in range(2, 11)]}
    reference, details = bake_and_rank.source_phase_reference_for_interval(
        references, crossing, source, parent_metrics)
    assert reference is None
    assert details is None
    ambiguous_references = [
        {"startFrame": 0, "stopFrameExclusive": 11, "metrics": {"dominantMotionRangeRatio": 1.0}},
        {"startFrame": 2, "stopFrameExclusive": 13, "metrics": {"dominantMotionRangeRatio": 1.0}},
    ]
    ambiguous_candidate = {"frames": [{"sourceTimeSec": float(index)} for index in range(1, 12)]}
    reference, details = bake_and_rank.source_phase_reference_for_interval(
        ambiguous_references, ambiguous_candidate, source, parent_metrics)
    assert reference is None
    assert details is None


def test_multi_repetition_reference_requires_contract_observable_target():
    source = {"frames": [{"sourceTimeSec": float(index), "joints": {}}
                          for index in range(12)], "jointNames": [], "rootJoint": "pelvis"}
    parent = {"required": True, "passed": False, "hasSingleMajorCycle": False,
              "hasCompleteMajorCycle": True}

    references = bake_and_rank.source_phase_reference_intervals(
        source, {"requiresReturnToStart": True}, parent)

    assert references == []
    approved_single = {**parent, "passed": True, "hasSingleMajorCycle": True}
    references = bake_and_rank.source_phase_reference_intervals(
        source, {"requiresReturnToStart": True}, approved_single)
    assert references[0]["source"] == "approved_single_repetition_phase"


def test_selected_cycle_interval_preflight_checks_the_exact_declared_interval(monkeypatch):
    payload = {
        "frames": [{} for _ in range(7)],
        "artifactState": {
            "selectionEvidence": {
                "cycleSelection": {
                    "interval": {"startFrame": 4, "endFrame": 10},
                },
            },
        },
    }
    source = {"frames": ["source"]}
    observed = {"frames": ["matched-source"]}
    monkeypatch.setattr(
        bake_and_rank,
        "source_pose_reference_for_motion",
        lambda actual_source, actual_motion: observed
        if actual_source is source and actual_motion is payload
        else None,
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda actual, **_kwargs: {"required": True, "passed": False}
        if actual is observed
        else {"required": True, "passed": True},
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_payload",
        lambda actual, **_kwargs: {"required": True, "passed": True}
        if actual is payload
        else {"required": True, "passed": False},
    )

    result = bake_and_rank.selected_interval_source_phase_preflight(
        payload, source_pose=source, contract={}
    )

    assert result["selection"]["source"] == (
        "artifactState.selectionEvidence.cycleSelection"
    )
    assert result["sourcePhase"] == {"required": True, "passed": False}
    assert result["outputPhase"] == {"required": True, "passed": True}
    assert result["passed"] is False


def test_selected_interval_output_phase_near_miss_remains_repairable(monkeypatch):
    payload = {"frames": [{} for _ in range(7)], "loopCycleSelection": {"startFrame": 0}}
    monkeypatch.setattr(bake_and_rank, "source_pose_reference_for_motion", lambda *_args: {})
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda *_args, **_kwargs: {"required": True, "passed": True},
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_payload",
        lambda *_args, **_kwargs: {"required": True, "passed": False},
    )

    result = bake_and_rank.selected_interval_source_phase_preflight(
        payload, source_pose={}, contract={}
    )

    assert result["outputPhase"]["passed"] is False
    assert result["passed"] is True

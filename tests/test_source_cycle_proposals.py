from exercise_motion_pkg import bake_and_rank
from exercise_motion_pkg import loop_cycles


def test_source_validated_cycle_proposals_uses_full_interval_only_when_both_phases_pass(monkeypatch):
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
        lambda *_args, **_kwargs: {"required": True, "passed": True},
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_payload",
        lambda *_args, **_kwargs: {"required": True, "passed": True},
    )

    accepted, diagnostics = bake_and_rank.source_validated_cycle_proposals(
        payload, source_pose={}, contract={}
    )

    assert accepted == [{
        "startFrame": 0,
        "stopFrameExclusive": 7,
        "score": 1.0,
        "endpointGapMeters": 0.0,
    }]
    assert diagnostics[-1]["selectionSource"] == "whole_interval_source_and_output_phase_fallback"


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
    assert all(
        item.get("selectionSource") != "whole_interval_source_and_output_phase_fallback"
        for item in diagnostics
    )


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

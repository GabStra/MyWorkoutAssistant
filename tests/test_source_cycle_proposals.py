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

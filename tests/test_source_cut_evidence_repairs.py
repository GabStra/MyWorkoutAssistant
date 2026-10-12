import json
from types import SimpleNamespace

from exercise_motion_pkg import bake_and_rank as bake


def test_endpoint_failure_reuses_exact_pose_to_find_correct_transition(tmp_path, monkeypatch):
    reference = tmp_path / "pose.json"
    reference.write_text(json.dumps({"pose": {"frames": [
        {"sourceTimeSec": index * 0.2, "joints": {"left_wrist": [0.4, 0.5, 0.0]}}
        for index in range(20)
    ]}}))
    monkeypatch.setattr(bake, "propose_source_cut", lambda **kwargs: [SimpleNamespace(
        start_seconds=1.0, end_seconds=2.5, policy="distinct_end_state",
        confidence=0.8, stats={},
    )])
    candidate = {"candidateId": "PARENT", "startSeconds": 10.0, "endSeconds": 14.0}
    validation = {
        "sourcePoseReferencePath": str(reference),
        "sourcePoseEndpointContractValidation": {
            "available": True, "passed": False,
            "blockingMismatches": [{"endpoint": "end", "field": "handHeight"}],
        },
    }
    repairs = bake.exact_pose_single_cycle_refinement_candidates(
        candidate, validation, exercise_motion_contract={"completionMode": "distinct_end_state"},
    )
    assert [(r["startSeconds"], r["endSeconds"]) for r in repairs] == [(11.0, 12.5)]
    # A repaired child cannot recursively consume the confirmation budget.
    assert not bake.exact_pose_single_cycle_refinement_candidates(
        repairs[0], validation, exercise_motion_contract={"completionMode": "distinct_end_state"},
    )


def test_failed_cut_dedup_keeps_boundary_repairs():
    failed = {"startSeconds": 1.0, "endSeconds": 4.0, "passed": False,
              "failureClass": "pose_confirmed_incomplete"}
    assert bake.source_cut_repeats_failed_window(
        {"startSeconds": 1.02, "endSeconds": 4.02}, [failed],
    )
    assert not bake.source_cut_repeats_failed_window(
        {"startSeconds": 1.0, "endSeconds": 5.0,
         "chunking": {"strategy": "exact_pose_return_expansion"}}, [failed],
    )
    assert not bake.source_cut_repeats_failed_window(
        {"startSeconds": 1.02, "endSeconds": 4.02},
        [{**failed, "failureClass": "validation_execution_failed"}],
    )
    assert not bake.source_cut_repeats_failed_window(
        {"startSeconds": 1.0, "endSeconds": 4.03}, [failed],
    )
    assert not bake.source_cut_repeats_failed_window(
        {"startSeconds": 1.02, "endSeconds": 4.02},
        [{**failed, "failureClass": "complete_phase_other_gate_failed", "validation": {
            "sourcePoseEndpointContractValidation": {"blockingMismatches": [
                {"endpoint": "end", "field": "handHeight"},
            ]},
        }}],
    )


def test_failed_source_windows_do_not_disqualify_whole_video():
    for status in ("skipped_source_gate", "skipped_pre_reconstruction_source_validation"):
        assert bake.source_family_failure_stage({"status": status}) is None


def test_exact_confirmation_skips_duplicate_failed_interval(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"retained-source")
    candidates = [
        {"candidateId": "A", "startSeconds": 1.0, "endSeconds": 4.0},
        {"candidateId": "B", "startSeconds": 1.02, "endSeconds": 4.02},
    ]
    monkeypatch.setattr(bake, "source_cut_deterministic_confirmation_candidates", lambda _: candidates)
    monkeypatch.setattr(bake, "source_cut_return_phase_expansion_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(bake, "materialize_source_cut_candidate_for_exact_validation",
                        lambda **kwargs: (video, "reused"))
    validations = []

    def validate(**kwargs):
        validations.append(kwargs["source_video_path"])
        return {"required": True, "passed": False,
                "reason": "source_pose_no_complete_repetition_cycle"}

    monkeypatch.setattr(bake, "validate_exact_source_with_cached_gpu_handoff", validate)
    rejected, _ = bake.select_exact_pose_confirmed_source_cut(
        bake.LoopRanking(score=0.95, reasons=[], payload={}),
        detection_source_video_path=video, exercise_name="Movement",
        exercise_motion_contract={}, caption_images=lambda **kwargs: "",
        output_dir=tmp_path / "review",
    )
    assert len(validations) == 1
    assert rejected.score == 0.0
    assert rejected.payload["sourceCutDuplicateConfirmationWindowCount"] == 1

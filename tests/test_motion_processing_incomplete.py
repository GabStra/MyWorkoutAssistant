import copy
import json
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.controlled_motion import controlled_fit_processing_incomplete
from exercise_motion_pkg.source_outcomes import update_source_outcome_index
from exercise_motion_pkg.wave_pipeline import final_processing_diagnostics, wave_retry_disposition


@pytest.mark.parametrize("report,incomplete", [
    ({"applied": False, "reason": "fit_timeout"}, True),
    ({"applied": False, "reason": "no_validated_loop_cycle", "cycleSelectionAttempts": [
        {"fitReport": {"reason": "fit_timeout"}}]}, True),
    ({"applied": False, "reason": "fit_validation_failed"}, False),
    ({"applied": True, "reason": "validated_controlled_motion"}, False),
])
def test_fitting_deadline_is_distinct_from_completed_validation(report, incomplete):
    assert controlled_fit_processing_incomplete(report) is incomplete


def test_timeout_blocks_export_without_calling_unchanged_pose_a_kinematic_defect():
    joints = json.loads((Path(__file__).parent / "fixtures/sequence_stabilization_stance.json").read_text())["joints"]
    payload = {"fps": 30, "jointNames": list(joints), "frames": [
        {"timeSec": i / 30, "joints": copy.deepcopy(joints)} for i in range(12)]}
    before = bake.pre_render_deterministic_gate(payload, None)
    payload["controlledMotionFit"] = {"applied": False, "reason": "fit_timeout"}
    after = bake.pre_render_deterministic_gate(payload, None)
    assert after["kinematics"]["artifactReasons"] == before["kinematics"]["artifactReasons"]
    assert not after["passed"]
    assert "controlled_motion_processing_incomplete" in after["rejectionReasons"]
    assert "controlled_motion_processing_incomplete" in bake.blocking_materialized_kinematic_reasons(
        after["kinematics"], source_corroborated_joint_angle_step=False)


def test_incomplete_processing_preserves_source_and_resumes_processing(tmp_path):
    candidate = {"status": "needs_motion_processing", "candidate": {"videoId": "good-source"},
                 "reconstructionAttempted": True,
                 "failures": [{"reason": "controlled_motion_processing_incomplete"}]}
    bake.mark_parallel_candidate_final_selection_statuses(
        [candidate], [], selected=None, selected_results=[], rejected_best=None)
    assert candidate["finalSelectionStatus"] == "processing_incomplete"
    assert not bake.candidate_result_has_terminal_quality_decision(candidate)
    diagnostics = final_processing_diagnostics({"candidateResults": [candidate]})
    assert wave_retry_disposition({"finalValidation": {"status": "no_selection", **diagnostics}}) == "retry_processing"
    index = tmp_path / "outcomes.json"
    assert update_source_outcome_index(index, [candidate]) is None
    assert not index.exists()


def test_timed_out_bake_reuses_prefetch_but_retries_on_next_run(tmp_path, monkeypatch):
    from exercise_motion_pkg import stage_cache
    preview = tmp_path / "preview.html"
    preview.write_text("fixture")
    skeleton = tmp_path / "skeleton.json"
    calls = []
    def render(*args, **kwargs):
        calls.append(True)
        payload = {"frames": [], "controlledMotionFit": {"reason": "fit_timeout", "applied": False},
                   "preRenderDeterministicGate": {"passed": False}}
        skeleton.write_text(json.dumps(payload))
        return [bake.BakedLoopArtifact(0, skeleton, tmp_path / "absent.webm", payload)]
    monkeypatch.setattr(bake, "_bake_preview_loops_with_playwright_uncached", render)
    args = (preview, [bake.EligibleLoop(0, {}, 1, 0, 1)], tmp_path, 6)
    bake.bake_preview_loops_with_playwright(*args)
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 1
    monkeypatch.setattr(stage_cache, "PROCESSING_ATTEMPT_ID", "next-process")
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 2

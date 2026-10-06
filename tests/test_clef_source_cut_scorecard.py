import json
import pytest
from contextlib import nullcontext

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import clef_systemone
from exercise_motion_pkg.segment_detection import DetectionWindow


def _decisions(**changes):
    choices = {
        "approval": "approved",
        "identity": "match",
        "complete_movement": "yes",
        "start_boundary": "clean",
        "finish_boundary": "clean",
        "setup_or_filler": "absent",
        "identity_cue": "target_action_and_variant_visible",
        "mechanics": "consistent",
        "contact": "stable",
        "source_quality": "adequate",
        "synthetic_subject": "no",
        "overall_confidence": "C04",
        "required_equipment": "engaged",
    }
    choices.update(changes)
    return {
        name: {"choice": choice, "confidence": 0.8}
        for name, choice in choices.items()
    }


def _candidate(tmp_path):
    return bake.SourceCutCandidate(
        "A",
        DetectionWindow(0, 0.0, 4.0),
        [tmp_path / "candidate.jpg"],
    )


def test_typed_source_cut_answers_preserve_existing_acceptance_gates(tmp_path):
    candidate = _candidate(tmp_path)
    scorecard = bake.source_cut_scorecard_from_systemone_answers(
        candidate_id="A",
        required_equipment="barbell",
        decisions=_decisions(),
    )
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}),
        [candidate],
        required_equipment="barbell",
        require_identity_evidence=True,
    )

    assert ranking is not None
    assert bake.source_cut_ranking_has_vlm_approval(ranking)
    row = ranking.payload["sourceCutScorecardCandidates"][0]
    assert row["identityEvidence"]
    assert row["clefTypedDecisionSummary"]["choices"]["overall_confidence"] == "C04"
    assert row["requiredEquipment"] == "barbell"


def test_uncertain_or_inconsistent_typed_answers_cannot_pass(tmp_path):
    candidate = _candidate(tmp_path)
    scorecard = bake.source_cut_scorecard_from_systemone_answers(
        candidate_id="A",
        required_equipment="barbell",
        decisions=_decisions(
            approval="uncertain",
            identity="match",
            identity_cue="different_action_visible",
            finish_boundary="uncertain",
            required_equipment="unclear",
        ),
    )
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}),
        [candidate],
        required_equipment="barbell",
        require_identity_evidence=True,
    )

    assert ranking is not None
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    row = ranking.payload["sourceCutScorecardCandidates"][0]
    assert row["passed"] is False
    assert "unclear" in row["reject"]


def test_bodyweight_source_cut_does_not_ask_for_named_equipment():
    questions = bake.source_cut_systemone_questions(required_equipment="none")

    assert "required_equipment" not in questions
    assert questions["overall_confidence"]["criteria"]["C04"].startswith("Confidence 0.85")


def test_nested_clef_decision_reuses_the_active_managed_lease(monkeypatch):
    endpoint = clef_systemone._local_server_endpoint("http://127.0.0.1:8091")
    token = clef_systemone._ACTIVE_MANAGED_CLEF_ENDPOINT.set(endpoint)

    def unexpected_lease_acquisition(**_kwargs):
        raise AssertionError("nested lease reacquired model ownership")

    monkeypatch.setattr(clef_systemone, "_run_with_managed_clef_server", unexpected_lease_acquisition)
    try:
        result = clef_systemone.run_clef_visual_decision_exclusively(
            base_url="http://127.0.0.1:8091",
            operation=lambda: "reused",
            exclusive_runner=unexpected_lease_acquisition,
        )
    finally:
        clef_systemone._ACTIVE_MANAGED_CLEF_ENDPOINT.reset(token)

    assert result == "reused"


@pytest.mark.parametrize("backend", ["qwen-chat", "clef-systemone"])
def test_visual_backend_and_comparative_switch_reach_bake_request(tmp_path, backend):
    from exercise_motion_pkg.cli import build_parser, build_bake_and_rank_request

    args = build_parser().parse_args([
        "bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path), "--wham-repo-path", str(tmp_path),
        "--body-model-root", str(tmp_path), "--visual-decision-backend", backend,
        "--final-output-review-backend", backend, "--comparative-segment-selection",
    ])
    request = build_bake_and_rank_request(args)
    assert request.visual_decision_backend == backend
    assert request.final_output_review_backend == backend
    assert request.comparative_segment_selection_enabled is True


@pytest.mark.parametrize("operation_fails", [False, True])
def test_managed_clef_owner_releases_server_and_nested_lease(tmp_path, monkeypatch, operation_fails):
    process = object()
    stopped = []
    launched = []
    monkeypatch.setattr(clef_systemone, "GlobalGpuLock", lambda **kwargs: nullcontext())
    monkeypatch.setattr(clef_systemone, "_endpoint_is_responding", lambda endpoint: False)
    monkeypatch.setattr(clef_systemone, "_managed_runtime_files", lambda: (
        tmp_path / "llama-server.exe", tmp_path / "model.gguf", tmp_path / "mmproj.gguf"))
    monkeypatch.setattr(clef_systemone.subprocess, "Popen",
                        lambda command, **kwargs: launched.append(command) or process)
    monkeypatch.setattr(clef_systemone, "_wait_for_managed_server", lambda *args, **kwargs: None)
    monkeypatch.setattr(clef_systemone, "_stop_managed_server", stopped.append)

    def operation():
        assert clef_systemone._ACTIVE_MANAGED_CLEF_ENDPOINT.get() == ("127.0.0.1", 8091)
        if operation_fails:
            raise RuntimeError("decision failed")
        return clef_systemone.run_clef_visual_decision_exclusively(
            base_url="http://127.0.0.1:8091", operation=lambda: "nested decision")

    try:
        if operation_fails:
            with pytest.raises(RuntimeError, match="decision failed"):
                clef_systemone.run_clef_visual_decision_exclusively(
                    base_url="http://127.0.0.1:8091", operation=operation)
        else:
            assert clef_systemone.run_clef_visual_decision_exclusively(
                base_url="http://127.0.0.1:8091", operation=operation) == "nested decision"
    finally:
        assert stopped == [process]
        assert len(launched) == 1
        assert clef_systemone._ACTIVE_MANAGED_CLEF_ENDPOINT.get() is None

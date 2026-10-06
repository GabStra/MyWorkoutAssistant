import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import source_review_authority as authority
from exercise_motion_pkg.segment_detection import DetectionWindow
from exercise_motion_pkg.wave_pipeline import wave_retry_disposition


def response(**changes):
    row = dict(id="A", approved=True, confidence=0.95, completeMovement=True,
               startBoundaryClean=True, finishBoundaryClean=True, setupOrFiller=False,
               namedEquipmentEngagedStatus="engaged", reject=[], note="Complete visible repetition.",
               identityMatch="match", identityEvidence="Both hands grip the moving barbell.",
               boundaryEvidence="Both endpoints cut through the same repetition.", qualityEvidence="")
    row.update(changes)
    return json.dumps({"candidates": [row]})


@pytest.fixture
def candidate(tmp_path):
    return bake.SourceCutCandidate("A", DetectionWindow(0, 0, 4), [tmp_path / "sheet.jpg"])


def test_inferred_descriptions_do_not_change_prompt_or_decision(candidate):
    contracts = [None, {"startState": "mandatory plank", "completionMode": "active_travel"},
                 {"startPoseConstraints": {"supportMode": "mandatory standing"},
                  "movementTopology": {"phases": [{"id": "invented_phase", "label": "invented return"}]}}]
    prompts = [bake.build_source_cut_candidate_choice_prompt(exercise_name="Barbell Curl",
               candidate_title="irrelevant", candidate=candidate, exercise_motion_contract=contract)
               for contract in contracts]
    assert len(set(prompts)) == 1
    assert "mandatory" not in prompts[0] and "invented_phase" not in prompts[0]
    rankings = [bake.parse_source_cut_candidate_choice(response(), [candidate],
                exercise_motion_contract=contract, require_identity_evidence=True)
                for contract in contracts]
    assert all(bake.source_cut_ranking_has_vlm_approval(ranking) for ranking in rankings)
    assert all(ranking == rankings[0] for ranking in rankings)


def test_hold_review_has_no_unconditional_dynamic_completion_requirement(candidate):
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Copenhagen Plank", candidate_title="irrelevant", candidate=candidate,
        exercise_motion_contract={"completionMode": "stable_hold"})
    assert "maintaining the target hold is exercise execution, not waiting or setup" in prompt
    assert "starting or ending mid-hold or mid-travel is not a bad boundary" in prompt
    assert "Apply the matching case below, not all cases" in prompt
    assert "completeMovement must be true only when the full execution" not in prompt
    assert "namedEquipmentEngagedStatus" in prompt
    assert "correct explicit qualifiers" in prompt


@pytest.mark.parametrize("changes", [
    {"approved": False, "reject": ["wrong_variant"], "identityMatch": "mismatch",
     "identityEvidence": "Dumbbells are held instead of the required barbell."},
    {"approved": False, "reject": ["partial_movement"], "completeMovement": False},
    {"namedEquipmentEngagedStatus": "absent"},
    {"identityEvidence": ""},
    {"identityEvidence": {"invented": "not a textual observation"}},
])
def test_real_failures_and_missing_identity_evidence_cannot_pass(candidate, changes):
    ranking = bake.parse_source_cut_candidate_choice(response(**changes), [candidate],
               required_equipment="barbell", require_identity_evidence=True)
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)


@pytest.mark.parametrize("secondary,expected", [
    ({"approved": False, "reject": ["partial_movement"]}, "model_rejected"),
    ({"approved": True}, "needs_review"),
    ({"approved": False, "reject": ["partial_movement"], "boundaryEvidence": ""}, "needs_review"),
    ({"approved": False, "reject": ["partial_movement"], "confidence": 0.3}, "needs_review"),
    ({"approved": False, "reject": ["partial_movement"], "confidence": None}, "needs_review"),
    ({"approved": False, "reject": ["partial_movement"], "boundaryEvidence": True}, "needs_review"),
])
def test_exactly_one_independent_review_cannot_override_negative(candidate, secondary, expected):
    replies = [response(approved=False, reject=["partial_movement"]), response(**secondary)]
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        return replies[len(calls) - 1]
    result = bake.rank_cut_candidate_with_caption_images(
        candidate=candidate, caption_images=caption, prompt_builder=lambda _: "neutral prompt",
        parser=lambda raw, item: bake.parse_source_cut_candidate_choice(
            raw, [item], require_identity_evidence=True))
    assert len(calls) == 2
    assert calls[0]["frame_paths"] == calls[1]["frame_paths"]
    assert "partial_movement" not in calls[1]["prompt"]
    ranking = result.rankings[0]
    assert ranking.payload["sourceReviewAssessment"]["status"] == expected
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    assert (authority.SOURCE_REVIEW_REQUIRED in ranking.reasons) == (expected == "needs_review")


def test_approved_cut_needs_no_second_request(candidate):
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        return response()
    result = bake.rank_cut_candidate_with_caption_images(
        candidate=candidate, caption_images=caption, prompt_builder=lambda _: "neutral",
        parser=lambda raw, item: bake.parse_source_cut_candidate_choice(raw, [item], require_identity_evidence=True))
    assert len(calls) == 1
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0])


def test_timeout_is_uncertainty_and_preserves_evidence():
    def timeout():
        raise TimeoutError("review deadline")
    original = bake.LoopRanking(0, ["partial_movement"], payload={"original": True})
    result = authority.assess_source_rejection(original, {}, independent_review=timeout)
    assert result.payload["original"] is True
    assert result.payload["sourceReviewAssessment"]["status"] == "needs_review"
    assert "TimeoutError" in result.payload["sourceReviewAssessment"]["error"]


@pytest.mark.parametrize("payload", [None, {}, {"candidates": None}, {"candidates": [None]},
                                     {"candidates": "invalid"}])
def test_malformed_review_cannot_confirm_rejection(payload):
    observation = authority.review_observation(payload)
    assert not authority.agreed_rejection(observation, observation)


def test_retry_disposition_keeps_uncertainty_separate_from_quality():
    assert wave_retry_disposition({"source": {"failureReason": "source_review_incomplete"}}) == "retry_review"
    assert wave_retry_disposition({"source": {"failureReason": "source_processing_failed"}}) == "retry_infrastructure"
    assert wave_retry_disposition({"source": {"failureReason": "no_source_passed_exact_window_validation"}}) == "next_source"


def test_replay_only_legacy_negative_model_cuts(tmp_path):
    payload = {"selectedSpan": None, "sourceCutRanking": {
        "reasons": ["source_candidate_window_choice_failed"],
        "payload": {"sourceCutScorecardCandidates": [{"passed": False}]}}}
    assert authority.rejection_needs_authority_replay(payload)
    path = tmp_path / "segment_detection" / "segment_selection.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload))
    assert authority.candidate_needs_authority_replay(tmp_path)
    assert authority.retained_source_attempt_keys(["legacy", "other"], {"legacy": tmp_path}) == ["other"]
    payload["selectedSpan"] = {"startSeconds": 0, "endSeconds": 4}
    assert not authority.rejection_needs_authority_replay(payload)
    path.write_text(json.dumps(payload))
    assert authority.retained_source_attempt_keys(["legacy", "other"], {"legacy": tmp_path}) == ["legacy", "other"]
    payload["selectedSpan"] = None
    payload["sourceCutRanking"]["payload"]["sourceReviewAuthorityVersion"] = authority.SOURCE_REVIEW_AUTHORITY_VERSION
    assert not authority.rejection_needs_authority_replay(payload)


def test_replay_inventory_preserves_selected_exercises(tmp_path):
    path = tmp_path / "example" / "bake" / "candidate" / "segment_detection" / "segment_selection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"selectedSpan": None, "sourceCutRanking": {
        "reasons": ["source_candidate_window_choice_failed"],
        "payload": {"sourceCutScorecardCandidates": [{"passed": False}]}}}))
    assert len(authority.source_authority_replay_plan(tmp_path)) == 1
    selected = tmp_path / "example" / "selected" / "example_wear_skeleton.json"
    selected.parent.mkdir()
    selected.write_text("{}")
    assert authority.source_authority_replay_plan(tmp_path) == []
    assert selected.read_text() == "{}" and path.exists()

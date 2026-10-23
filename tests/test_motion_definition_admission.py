import copy
import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave


def candidate(contract):
    return bake.RankedCandidate(0, 0, "example", "Example", "example", {
        "videoId": "retained", "exerciseMotionContract": contract,
    })


def test_unresolved_definition_stops_before_download(tmp_path, monkeypatch):
    contract = {
        "status": "generated", "completionMode": "distinct_end_state",
        "requiredPhases": ["perform the defining pull"],
        "actionDefinitionAuthority": "unresolved",
    }
    request = bake.BakeAndRankRequest(
        tmp_path / "candidates.json", tmp_path, None,
        pre_reconstruction_source_validation=True, exercise_motion_contract_enabled=True,
    )
    monkeypatch.setattr(bake, "copy_or_download_candidate_source", lambda *_a, **_k: pytest.fail("downloaded before target resolution"))
    with pytest.raises(bake.ExerciseDefinitionReviewRequired, match="target_action_definition_unresolved"):
        bake.prepare_candidate_input_video(
            candidate(contract), request=request,
            source_cut_caption_images=lambda **_k: pytest.fail("reviewed before target resolution"),
            exercise_motion_contract_resolver=lambda _candidate: contract,
        )


def test_definition_review_stops_candidate_retries(tmp_path, monkeypatch):
    calls = []

    def process(item, **_kwargs):
        calls.append(item)
        return {"status": "needs_definition_review", "failureOwner": "definition"}

    monkeypatch.setattr(bake, "process_ranked_candidate", process)
    request = bake.BakeAndRankRequest(tmp_path / "candidates.json", tmp_path, None)
    result = bake.process_ranked_candidates_until_final_selection(
        [candidate({}), candidate({})], request=request,
        preview_baker=lambda *_a, **_k: pytest.fail("baked unresolved target"),
        effective_ranker=None, support_dominance_classifier=None,
    )
    assert len(calls) == 1
    assert result[-1]["terminalOutcome"] == "definition_review_required"
    assert result[0][0]["finalSelectionStatus"] == "definition_review_required"


def test_definition_failure_retains_its_owner_in_final_checkpoint(tmp_path, monkeypatch):
    contract = {"completionMode": "distinct_end_state", "actionDefinitionAuthority": "unresolved"}
    monkeypatch.setattr(bake, "evaluate_source_candidate_gate", lambda *_a, **_k: {"passed": True})

    def generate(*_args, **_kwargs):
        raise bake.ExerciseDefinitionReviewRequired("target_action_definition_unresolved", contract)

    monkeypatch.setattr(bake, "generate_candidate_motion", generate)
    result = bake.process_ranked_candidate(
        candidate(contract), request=bake.BakeAndRankRequest(tmp_path / "candidates.json", tmp_path, None),
        preview_baker=None, review_items=[], review_item_entries=[], support_dominance_classifier=None,
    )
    assert result["status"] == "needs_definition_review"
    assert result["failureOwner"] == "definition"
    assert not result.get("reconstructionAttempted")
    manifest = {"candidateResults": [result]}
    status = wave.final_validation_outcome_status(manifest)
    assert status == "needs_definition_review"
    assert wave.wave_retry_disposition({
        "finalValidation": {"status": status, **wave.final_processing_diagnostics(manifest)},
    }) == "needs_definition_review"


def test_prepared_source_cannot_bypass_unresolved_target(tmp_path):
    contract = {
        "exerciseName": "Example", "advisoryText": "Perform the requested action.",
        "completionMode": "distinct_end_state", "actionDefinitionAuthority": "unresolved",
    }
    request = bake.BakeAndRankRequest(
        tmp_path / "candidates.json", tmp_path, None,
        pre_reconstruction_source_validation=True, exercise_motion_contract_enabled=True,
    )
    with pytest.raises(bake.ExerciseDefinitionReviewRequired):
        bake.generate_candidate_motion(
            candidate(contract), request=request, prepared_video_path=tmp_path / "old-approved-input.mp4",
        )


def test_source_selection_cache_is_bound_to_target_action(tmp_path, monkeypatch):
    contract = {
        "exerciseName": "Example", "advisoryText": "A target action.",
        "definingAction": "Raise the implement overhead.",
        "completionMode": "distinct_end_state",
        "variantQualifiers": ["one arm"],
    }
    path = tmp_path / "segment_selection.json"
    path.write_text(json.dumps({
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "preReconstructionSourceValidationEnabled": True,
        "exerciseMotionContractEnabled": True,
        "exerciseMotionContract": contract,
        "exactSourcePhaseValidation": {
            "validationPolicyVersion": bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
        },
    }))
    monkeypatch.setattr(bake, "exercise_motion_contract_is_usable", lambda *_a, **_k: True)
    monkeypatch.setattr(bake, "exact_source_validation_effectively_passed", lambda _v: True)
    check = lambda target: bake.cached_source_selection_matches_validation_mode(
        path, pre_reconstruction_source_validation=True,
        exercise_motion_contract_enabled=True, expected_contract=target,
    )
    assert check(copy.deepcopy(contract))
    for key, value in (("definingAction", "Raise it only to the waist."), ("variantQualifiers", ["both arms"])):
        changed = {**contract, key: value}
        assert not check(changed)

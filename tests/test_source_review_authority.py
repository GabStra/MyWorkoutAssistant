import json
from dataclasses import replace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import source_review_authority as authority
from exercise_motion_pkg import youtube
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
    assert "mandatory plank" not in prompts[0]
    assert "mandatory standing" not in prompts[0]
    assert "invented_phase" not in prompts[0]
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


def test_source_cut_completion_follows_explicit_end_state_contract(candidate):
    distinct_end = {
        "completionMode": "distinct_end_state",
        "movementType": "repetition",
        "requiresReturnToStart": False,
        "source": "library",
        "actionDefinitionAuthority": "structured_definition",
        "actionDefinitionStatus": "defined",
        "definingAction": "Pull the bar close to the torso and finish high without receiving it.",
        "requiredPhases": ["pull the bar upward close to the torso"],
        "movementTopology": {
            "completionMode": "distinct_end_state",
            "startState": {"id": "start", "label": "unspecified"},
            "phases": [{"id": "phase_01", "label": "pull the bar upward close to the torso"}],
            "endState": {"id": "end", "label": "unspecified"},
            "endpointEvidenceRequired": False,
        },
    }
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell High Pull", candidate_title="retained candidate",
        candidate=candidate, exercise_motion_contract=distinct_end,
    )
    assert "distinct finish" in prompt
    assert "Do not infer a floor start, hang, or other unspecified endpoint posture" in prompt
    assert "turning points and return" not in prompt
    assert '"startStateMatch"' not in prompt
    assert '"endStateMatch"' not in prompt
    assert "phaseEvidence" in prompt

    row = json.loads(response(
        approved=False,
        completeMovement=False,
        startStateMatch="mismatch",
        endStateMatch="mismatch",
        reject=["partial_movement"],
    ))["candidates"][0]
    row["phaseEvidence"] = []
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [row]}), [candidate],
        exercise_motion_contract=distinct_end, require_identity_evidence=True,
    )
    scorecard_row = ranking.payload["sourceCutScorecardCandidates"][0]
    assert "source_cut_contract_start_state_mismatch" not in scorecard_row["rejectionReasons"]
    assert "source_cut_contract_end_state_mismatch" not in scorecard_row["rejectionReasons"]
    assert "source_cut_contract_phase_sequence_mismatch" in scorecard_row["rejectionReasons"]
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)

    return_to_start = {
        **distinct_end,
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "movementTopology": {
            **distinct_end["movementTopology"],
            "completionMode": "return_to_start",
            "endpointEvidenceRequired": True,
        },
    }
    return_prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell High Pull", candidate_title="cyclic target",
        candidate=candidate, exercise_motion_contract=return_to_start,
    )
    assert "complete repetition is visibly contained" in return_prompt
    assert "directions and a return" in return_prompt

    return_without_endpoint_labels = {
        **return_to_start,
        "movementTopology": {
            **return_to_start["movementTopology"],
            "endpointEvidenceRequired": False,
        },
    }
    return_without_endpoint_prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell High Pull", candidate_title="cyclic target",
        candidate=candidate, exercise_motion_contract=return_without_endpoint_labels,
    )
    assert "completion mode requires a visible return" in return_without_endpoint_prompt


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


def test_discrete_action_without_grounded_definition_stays_unresolved(candidate):
    contract = {
        "completionMode": "distinct_end_state",
        "status": "generated",
        "source": "reused_candidate_contract",
    }
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell High Pull", candidate_title="retained candidate",
        candidate=candidate, exercise_motion_contract=contract,
    )
    assert "target action definition is unresolved" in prompt
    ranking = bake.parse_source_cut_candidate_choice(
        response(), [candidate], exercise_motion_contract=contract,
        require_identity_evidence=True,
    )
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    assert bake.source_cut_scorecard_rows_need_review(
        ranking.payload["sourceCutScorecardCandidates"]
    )
    calls = []
    result = bake.rank_cut_candidate_with_caption_images(
        candidate=candidate,
        caption_images=lambda **_kwargs: calls.append(_kwargs) or response(),
        prompt_builder=lambda _candidate: prompt,
        parser=lambda raw, item: bake.parse_source_cut_candidate_choice(
            raw, [item], exercise_motion_contract=contract, require_identity_evidence=True,
        ),
    )
    assert len(calls) == 1
    assert not bake.source_cut_ranking_has_vlm_approval(result.rankings[0])


def test_untrusted_contract_keeps_phase_proposal_as_review_checklist():
    exercise = youtube.ExerciseEntry(
        exercise_id="high-pull", name="Barbell High Pull", slug="barbell-high-pull",
        motion_context={"primaryEquipment": {"name": "barbell"}},
    )
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        {
            "movementType": "repetition",
            "completionMode": "distinct_end_state",
            "requiredPhases": ["raise the bar from the floor to the upper chest"],
            "actionDefinitionStatus": "defined",
        },
        exercise=exercise,
        source="llm",
    )
    assert contract["requiredPhases"] == ["raise the bar from the floor to the upper chest"]
    assert contract["actionDefinitionStatus"] == "defined"
    assert contract["actionDefinitionAuthority"] == "unresolved"
    topology = bake.movement_topology_from_contract(contract)
    assert topology["actionDefinitionTrusted"] is False
    assert topology["phaseEvidenceHardGate"] is False
    assert youtube.exercise_motion_action_definition_review_reason(contract) == "target_action_definition_unresolved"


def test_structured_minimal_action_definition_is_trusted_and_reuses_phase_topology():
    exercise = youtube.ExerciseEntry(
        exercise_id="high-pull", name="Barbell High Pull", slug="barbell-high-pull",
        motion_context={
            "primaryEquipment": {"name": "barbell"},
            "exerciseDefinition": {
                "definingAction": "Pull the barbell from the floor to the upper chest.",
                "completionMode": "distinct_end_state",
                "variantQualifiers": ["barbell", "high pull"],
            },
        },
    )
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        {
            "movementType": "repetition",
            "completionMode": "return_to_start",
            "definingAction": "model's generic proposal",
            "requiredPhases": ["model phase"],
            "actionDefinitionStatus": "defined",
        },
        exercise=exercise,
        source="llm",
    )
    assert contract["definingAction"] == "Pull the barbell from the floor to the upper chest."
    assert contract["completionMode"] == "distinct_end_state"
    assert contract["variantQualifiers"] == ["barbell", "high pull"]
    assert contract["requiredPhases"] == [contract["definingAction"].rstrip(".")]
    assert contract["actionDefinitionAuthority"] == "structured_definition"
    assert youtube.exercise_motion_action_definition_review_reason(contract) is None


def test_generic_coaching_text_does_not_establish_trusted_action_definition():
    exercise = youtube.ExerciseEntry(
        exercise_id="curl", name="Dumbbell Curl", slug="dumbbell-curl",
        motion_context={"instructions": "Use controlled technique."},
    )
    assert not youtube.exercise_motion_context_has_action_definition(exercise.motion_context)
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        {
            "movementType": "repetition",
            "completionMode": "return_to_start",
            "definingAction": "Flex the elbow to raise the dumbbell.",
            "actionDefinitionStatus": "defined",
        },
        exercise=exercise,
        source="llm",
    )
    assert contract["actionDefinitionAuthority"] == "unresolved"
    assert contract["requiredPhases"] == [contract["definingAction"]]
    assert youtube.exercise_motion_action_definition_review_reason(contract) == "target_action_definition_unresolved"


def test_trusted_action_does_not_inherit_model_variant_guesses():
    exercise = youtube.ExerciseEntry(
        exercise_id="press", name="Floor Press", slug="floor-press",
        motion_context={"exerciseDefinition": {
            "definingAction": "Press the barbell from the chest to arm extension.",
            "completionMode": "return_to_start",
        }},
    )
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        {
            "movementType": "repetition",
            "completionMode": "return_to_start",
            "definingAction": "model action guess",
            "variantQualifiers": ["incline", "single-arm"],
        },
        exercise=exercise,
        source="llm",
    )
    assert contract["definingAction"] == "Press the barbell from the chest to arm extension."
    assert "variantQualifiers" not in contract


def test_definition_prompt_requests_minimal_action_semantics_as_provisional():
    exercise = youtube.ExerciseEntry(
        exercise_id="high-pull", name="Barbell High Pull", slug="barbell-high-pull",
        motion_context={"primaryEquipment": {"name": "barbell"}},
    )
    prompt = youtube.build_exercise_motion_contract_prompt(exercise)
    assert "definingAction" in prompt
    assert "variantQualifiers" in prompt
    assert "completionMode" in prompt
    assert "provisional evidence checklists" in prompt
    assert "exact start/end posture" in prompt


def test_grounded_one_way_action_can_pass_with_ordered_visible_evidence(candidate):
    contract = {
        "completionMode": "distinct_end_state",
        "contractScope": "definition_only",
        "actionDefinitionStatus": "defined",
        "actionDefinitionAuthority": "structured_definition",
        "requiredPhases": ["raise the bar to the final overhead position"],
    }
    row = json.loads(response())["candidates"][0]
    row["phaseEvidence"] = [{
        "phaseId": "phase_01", "visible": True, "position": 0.72,
        "evidence": "bar is visibly raised overhead",
    }]
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [row]}), [candidate],
        exercise_motion_contract=contract, require_identity_evidence=True,
    )
    assert bake.source_cut_ranking_has_vlm_approval(ranking)


def test_minimal_trusted_action_definition_works_without_phase_list_or_status(candidate):
    contract = {
        "completionMode": "distinct_end_state",
        "contractScope": "definition_only",
        "actionDefinitionAuthority": "structured_definition",
        "definingAction": "Raise the bar to the final overhead position.",
    }
    topology = bake.movement_topology_from_contract(contract)
    assert topology["actionDefinitionTrusted"] is True
    assert [phase["label"] for phase in topology["phases"]] == [contract["definingAction"]]
    assert youtube.exercise_motion_action_definition_review_reason(contract) is None
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell High Pull", candidate_title="retained candidate",
        candidate=candidate, exercise_motion_contract=contract,
    )
    assert contract["definingAction"] in prompt
    assert "phase_01" in prompt
    row = json.loads(response())["candidates"][0]
    row["phaseEvidence"] = [{
        "phaseId": "phase_01", "visible": True, "position": 0.72,
        "evidence": "bar is visibly raised overhead",
    }]
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [row]}), [candidate],
        exercise_motion_contract=contract, require_identity_evidence=True,
    )
    assert bake.source_cut_ranking_has_vlm_approval(ranking)


@pytest.mark.parametrize("phase_evidence", [
    [{"phaseId": "phase_01", "visible": True, "position": 0.25, "evidence": "first action"},
     {"phaseId": "phase_02", "visible": True, "position": 0.75, "evidence": "second action"}],
    [{"phaseId": "phase_01", "visible": False, "evidence": "not shown"}],
    [{"phaseId": "phase_02", "visible": True, "position": 0.8, "evidence": "later action"},
     {"phaseId": "phase_01", "visible": True, "position": 0.2, "evidence": "earlier action"}],
])
def test_untrusted_generated_phases_are_review_obligations_not_rejections(
    candidate, phase_evidence,
):
    contract = {
        "completionMode": "distinct_end_state",
        "source": "llm",
        "status": "generated",
        "actionDefinitionStatus": "defined",
        "actionDefinitionAuthority": "unresolved",
        "requiredPhases": ["phase one", "phase two"],
        "movementTopology": {
            "completionMode": "distinct_end_state",
            "startState": {"id": "start", "label": "unspecified"},
            "phases": [{"id": "phase_01", "label": "first action"},
                       {"id": "phase_02", "label": "second action"}],
            "endState": {"id": "end", "label": "unspecified"},
            "endpointEvidenceRequired": False,
        },
    }
    row = json.loads(response())["candidates"][0]
    row["phaseEvidence"] = phase_evidence
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [row]}), [candidate],
        exercise_motion_contract=contract, require_identity_evidence=True,
    )
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    scorecard_rows = ranking.payload["sourceCutScorecardCandidates"]
    assert bake.source_cut_scorecard_rows_need_review(scorecard_rows)
    assert "source_cut_action_definition_unresolved" in scorecard_rows[0]["rejectionReasons"]


def test_exact_source_interval_approval_is_reused_and_invalidated(candidate, monkeypatch):
    candidate.frame_paths[0].write_bytes(b"approved interval evidence")
    calls = []

    class Session:
        settings = object()

        def caption_images(self, **kwargs):
            calls.append(kwargs)
            return response()

    monkeypatch.setattr(bake, "source_review_model_identity", lambda _settings: {"model": "test-model"})
    session = Session()
    classify = lambda prompt: bake.rank_cut_candidate_with_caption_images(
        candidate=candidate,
        caption_images=session.caption_images,
        prompt_builder=lambda _candidate: prompt,
        parser=lambda raw, item: bake.parse_source_cut_candidate_choice(raw, [item], require_identity_evidence=True),
    )

    first = classify("exercise config A")
    cached = classify("exercise config A")
    assert len(calls) == 1
    assert bake.source_cut_ranking_has_vlm_approval(first.rankings[0])
    assert bake.source_cut_ranking_has_vlm_approval(cached.rankings[0])

    candidate = replace(candidate, window=DetectionWindow(0, 0, 5))
    classify("exercise config A")
    classify("exercise config B")
    assert len(calls) == 3

    monkeypatch.setattr(
        bake, "SOURCE_CUT_APPROVAL_CACHE_POLICY_VERSION",
        bake.SOURCE_CUT_APPROVAL_CACHE_POLICY_VERSION + 1,
    )
    classify("exercise config A")
    assert len(calls) == 4


def test_incomplete_source_approval_is_not_reused(candidate, monkeypatch):
    candidate.frame_paths[0].write_bytes(b"incomplete interval evidence")
    calls = []

    class Session:
        settings = object()

        def caption_images(self, **kwargs):
            calls.append(kwargs)
            return "not JSON"

    monkeypatch.setattr(bake, "source_review_model_identity", lambda _settings: {"model": "test-model"})
    session = Session()
    for _ in range(2):
        result = bake.rank_cut_candidate_with_caption_images(
            candidate=candidate,
            caption_images=session.caption_images,
            prompt_builder=lambda _candidate: "exercise config A",
            parser=lambda _raw, _item: None,
        )
        assert not result.rankings
    assert len(calls) == 4


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


@pytest.mark.parametrize("phase", [
    {"required": True, "passed": False, "reason": "source_pose_samples_unavailable"},
    {"required": True, "passed": False, "reason": "one_way_partial_repetition_phase",
     "phaseSignalEvidence": {"resolved": False}},
])
def test_known_endpoint_mismatch_stays_hard_when_phase_evidence_is_uncertain(phase):
    metrics = {
        "candidateFullRepetitionPhaseCompletenessMetrics": phase,
        "sourcePoseEndpointContractValidation": {
            "available": True,
            "passed": False,
            "blockingMismatches": [{"endpoint": "end", "field": "supportMode"}],
        },
    }

    assert not authority.source_cut_pose_evidence_needs_review(metrics)


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

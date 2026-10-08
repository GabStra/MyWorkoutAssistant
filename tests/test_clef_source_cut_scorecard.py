import json
import hashlib
import shutil
import pytest
from types import SimpleNamespace
from contextlib import nullcontext

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import clef_systemone
from exercise_motion_pkg import acceptance
from exercise_motion_pkg import segment_detection
from exercise_motion_pkg.segment_detection import DetectionSettings, DetectionWindow


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


def test_clef_source_cut_error_stays_unresolved_without_qwen_switch():
    def failed_managed_clef_review():
        raise RuntimeError("managed Clef server failed")

    choice, recoveries = bake.run_clef_source_cut_review_without_backend_fallback(
        failed_managed_clef_review,
        candidate_ids=["A"],
    )

    assert choice.ranking is None
    assert choice.errors[0]["errorType"] == "RuntimeError"
    assert choice.errors[0]["candidateIds"] == ["A"]
    assert recoveries[0]["backend"] == "clef-systemone"
    assert recoveries[0]["reason"] == "clef_source_review_failed_no_backend_fallback"


def test_low_confidence_clef_scorecard_remains_review_required(tmp_path):
    candidate = _candidate(tmp_path)
    scorecard = bake.source_cut_scorecard_from_systemone_answers(
        candidate_id="A",
        required_equipment="barbell",
        decisions=_decisions(overall_confidence="C02"),
    )
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}),
        [candidate],
        required_equipment="barbell",
        require_identity_evidence=True,
    )

    assert ranking is not None
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    assert bake.source_cut_deterministic_confirmation_candidates(ranking) == []
    row = ranking.payload["sourceCutScorecardCandidates"][0]
    assert row["reject"] == ["low_confidence"]
    assert row["passed"] is False
    assert bake.source_cut_scorecard_rows_need_review([row]) is True


def test_source_cut_equipment_roles_separate_active_load_support_and_rack_setup(tmp_path):
    contract = {
        "motionContext": {
            "primaryEquipment": {"id": "bar", "type": "BARBELL", "name": "Barbell"},
            "requiredAccessories": [
                {
                    "id": "bench",
                    "type": "ACCESSORY",
                    "name": "Adjustable Bench",
                    "capabilities": ["BENCH", "FLAT_BENCH", "ADJUSTABLE_BENCH"],
                },
                {
                    "id": "rack",
                    "type": "ACCESSORY",
                    "name": "Squat Rack",
                    "capabilities": ["RACKED_BAR_SUPPORT"],
                },
            ],
        }
    }

    requirements = bake.two_scale_equipment_role_requirements("Barbell Floor Press", contract)
    roles = {item["normalizedName"]: item["role"] for item in requirements}
    policy = bake.two_scale_equipment_role_policy("Barbell Floor Press", contract)
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell Floor Press",
        candidate_title="candidate A",
        candidate=_candidate(tmp_path),
        exercise_motion_contract=contract,
    )

    assert roles == {
        "barbell": "active_implement",
        "bench": "support_surface",
        "squat rack": "setup_fixture",
    }
    assert "visibly held, worn, attached, or connected" in policy
    assert "body-support surface" in policy
    assert "do not demand contact during the repetition" in policy
    assert "presence alone" in policy
    assert "Required equipment role policy" in prompt


def test_role_policy_does_not_allow_absent_active_implement(tmp_path):
    contract = {
        "motionContext": {
            "primaryEquipment": {"id": "bar", "type": "BARBELL", "name": "Barbell"},
            "requiredAccessories": [{
                "id": "rack",
                "type": "ACCESSORY",
                "name": "Squat Rack",
                "capabilities": ["RACKED_BAR_SUPPORT"],
            }],
        }
    }
    required_equipment = ", ".join(
        bake.two_scale_required_equipment_names("Barbell Floor Press", contract)
    )
    candidate = _candidate(tmp_path)
    scorecard = bake.source_cut_scorecard_from_systemone_answers(
        candidate_id="A",
        required_equipment=required_equipment,
        decisions=_decisions(required_equipment="absent"),
    )
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}),
        [candidate],
        required_equipment=required_equipment,
        require_identity_evidence=True,
    )

    assert ranking is not None
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    row = ranking.payload["sourceCutScorecardCandidates"][0]
    assert "source_cut_required_equipment_absent" in row["rejectionReasons"]


def test_dumbbell_pair_primary_type_covers_generic_title_alias_without_changing_flat_names():
    contract = {
        "motionContext": {
            "primaryEquipment": {"id": "pair", "type": "DUMBBELLS", "name": "Dumbbell Pair"},
            "requiredAccessories": [],
        }
    }

    requirements = bake.two_scale_equipment_role_requirements("Dumbbell Overhead Press", contract)

    assert requirements == [{
        "name": "Dumbbell Pair",
        "normalizedName": "dumbbell pair",
        "role": "active_implement",
    }]
    assert bake.two_scale_required_equipment_names("Dumbbell Overhead Press", contract) == [
        "dumbbell",
        "dumbbell pair",
    ]


def test_clef_request_error_blocks_unreviewed_candidate_but_keeps_other_valid_pass(tmp_path):
    candidate_a = _candidate(tmp_path)
    candidate_b = bake.SourceCutCandidate(
        "B",
        DetectionWindow(1, 5.0, 9.0),
        [tmp_path / "candidate-b.jpg"],
    )
    scorecard_b = bake.source_cut_scorecard_from_systemone_answers(
        candidate_id="B",
        required_equipment="barbell",
        decisions=_decisions(overall_confidence="C04"),
    )
    ranking_b = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard_b]}),
        [candidate_b],
        required_equipment="barbell",
        require_identity_evidence=True,
    )
    row_b = ranking_b.payload["sourceCutScorecardCandidates"][0]
    ranking = bake.LoopRanking(
        score=ranking_b.score,
        reasons=[],
        raw_response="clef response for B",
        payload={
            "sourceCutCandidates": bake.source_cut_candidates_payload([candidate_a, candidate_b]),
            "sourceCutScorecardCandidates": [row_b],
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutVlmRequestErrors": [{
                "candidateIds": ["A"],
                "errorType": "RuntimeError",
                "message": "Clef request failed",
            }],
            "selectedCandidateId": "B",
            "selectedScorecard": row_b,
        },
        model_score=ranking_b.model_score,
    )

    assert [row["candidateId"] for row in bake.source_cut_deterministic_confirmation_candidates(ranking)] == ["B"]


def test_clef_request_error_cannot_promote_geometry_only_candidate(tmp_path):
    candidate = _candidate(tmp_path)
    ranking = bake.LoopRanking(
        score=0.0,
        reasons=["source_candidate_choice_invalid_response"],
        payload={
            "sourceCutCandidates": bake.source_cut_candidates_payload([candidate]),
            "sourceCutScorecardCandidates": [],
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutVlmRequestErrors": [{
                "candidateIds": ["A"],
                "errorType": "RuntimeError",
                "message": "Clef request failed",
            }],
        },
        model_score=0.0,
    )

    assert bake.source_cut_deterministic_confirmation_candidates(ranking) == []


def test_clef_hard_semantic_rejections_cannot_promote_unreviewed_pose_candidate(tmp_path):
    reviewed_video = tmp_path / "reviewed.mp4"
    reviewed_video.write_bytes(b"reviewed candidate source")
    reviewed_video_sha256 = hashlib.sha256(reviewed_video.read_bytes()).hexdigest()
    candidates = [
        bake.SourceCutCandidate(candidate_id, DetectionWindow(index, index * 3.0, index * 3.0 + 4.0), [tmp_path / f"{candidate_id}.jpg"])
        for index, candidate_id in enumerate(("A", "H", "J", "K", "G", "F", "I"))
    ]
    rejected_rows = []
    for candidate_id, identity, reasons in (
        ("A", "mismatch", ["source_cut_scorecard_reject_wrong_exercise", "source_cut_low_confidence"]),
        ("H", "uncertain", ["source_cut_scorecard_reject_unclear", "source_cut_low_confidence"]),
        ("J", "mismatch", ["source_cut_scorecard_reject_wrong_exercise", "source_cut_low_confidence"]),
        ("K", "uncertain", ["source_cut_scorecard_reject_unclear", "source_cut_scorecard_reject_bad_boundary", "source_cut_low_confidence"]),
        ("G", "mismatch", ["source_cut_scorecard_reject_wrong_exercise", "source_cut_scorecard_reject_bad_boundary", "source_cut_low_confidence"]),
        ("F", "uncertain", ["source_cut_scorecard_reject_unclear", "source_cut_low_confidence"]),
    ):
        rejected_rows.append({
            "id": candidate_id,
            "passed": False,
            "score": 0.65 if identity == "uncertain" else 0.5,
            "confidence": 0.65 if identity == "uncertain" else 0.5,
            "identityMatch": identity,
            "rejectionReasons": ["source_cut_model_rejected", *reasons],
        })
    ranking = bake.LoopRanking(
        score=0.0,
        reasons=["source_cut_review_required"],
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutReviewVideoPath": str(reviewed_video.resolve()),
            "sourceCutReviewVideoSha256": reviewed_video_sha256,
            "sourceCutReviewVideoSha256After": reviewed_video_sha256,
            "sourceCutOriginalVideoPath": str(reviewed_video.resolve()),
            "sourceCutOriginalVideoSha256": reviewed_video_sha256,
            "sourceCutOriginalVideoSha256After": reviewed_video_sha256,
            "sourceCutScorecardCandidates": rejected_rows,
            "sourceCutCandidates": bake.source_cut_candidates_payload(candidates),
            "selectedCandidateId": "I",
        },
    )

    assert bake.source_cut_deterministic_confirmation_candidates(ranking) == []


def test_clef_positive_identity_keeps_completeness_and_boundary_repairs(tmp_path):
    selected = bake.SourceCutCandidate("A", DetectionWindow(0, 2.0, 5.0), [tmp_path / "a.jpg"])
    expansion = bake.SourceCutCandidate("B", DetectionWindow(1, 1.0, 5.0), [tmp_path / "b.jpg"])
    unrelated = bake.SourceCutCandidate("C", DetectionWindow(2, 8.0, 11.0), [tmp_path / "c.jpg"])
    base_candidate_rows = bake.source_cut_candidates_payload([selected, expansion, unrelated])
    completeness_only = {
        "id": "A",
        "passed": False,
        "score": 0.9,
        "confidence": 0.9,
        "identityMatch": "match",
        "rejectionReasons": [
            "source_cut_model_rejected",
            "source_cut_partial_movement",
            "source_cut_scorecard_reject_partial_movement",
        ],
    }
    fallback_ranking = bake.LoopRanking(
        score=0.0,
        reasons=["source_candidate_scorecard_no_passing_candidate"],
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutScorecardCandidates": [completeness_only],
            "sourceCutCandidates": base_candidate_rows,
        },
    )

    assert [row["candidateId"] for row in bake.source_cut_deterministic_confirmation_candidates(fallback_ranking)] == ["A"]

    passing = {
        "id": "A",
        "passed": True,
        "score": 0.9,
        "confidence": 0.9,
        "identityMatch": "match",
        "rejectionReasons": [],
    }
    unreviewed_repair_ranking = bake.LoopRanking(
        score=0.9,
        reasons=[],
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "selectedCandidateId": "A",
            "selectedScorecard": passing,
            "sourceCutScorecardCandidates": [passing],
            "sourceCutCandidates": base_candidate_rows,
        },
    )
    assert [row["candidateId"] for row in bake.source_cut_deterministic_confirmation_candidates(unreviewed_repair_ranking)] == ["A"]

    reviewed_expansion = {
        "id": "B",
        "passed": True,
        "score": 0.9,
        "confidence": 0.9,
        "identityMatch": "match",
        "rejectionReasons": [],
    }
    boundary_repair_ranking = bake.LoopRanking(
        score=0.9,
        reasons=[],
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "selectedCandidateId": "A",
            "selectedScorecard": passing,
            "sourceCutScorecardCandidates": [passing, reviewed_expansion],
            "sourceCutCandidates": base_candidate_rows,
        },
    )

    assert [row["candidateId"] for row in bake.source_cut_deterministic_confirmation_candidates(boundary_repair_ranking)] == ["A", "B"]


def _write_source_clearance_fixture(tmp_path, *, derived=False, authorized_parent="A"):
    workspace = tmp_path / "candidate"
    segment_dir = workspace / "segment_detection"
    segment_dir.mkdir(parents=True)
    selected_segment = workspace / "input" / "selected_segment.mp4"
    selected_segment.parent.mkdir()
    selected_segment.write_bytes(b"retained source segment")
    selected_start, selected_end = (2.0, 6.0) if derived else (0.0, 8.0)
    image_dir = workspace / "review"
    image_dir.mkdir()
    contact_sheet = image_dir / "contact_sheet.jpg"
    sample_first = image_dir / "frame_000.jpg"
    sample_last = image_dir / "frame_007.jpg"
    contact_sheet.write_bytes(b"review contact sheet")
    sample_first.write_bytes(b"first sampled frame")
    sample_last.write_bytes(b"last sampled frame")
    review_candidate = bake.SourceCutCandidate(
        "A", DetectionWindow(0, 0.0, 8.0), [contact_sheet],
        sample_frame_paths=[sample_first, sample_last],
    )
    candidate = bake.source_cut_candidates_payload([review_candidate])[0]
    frame_evidence = bake.source_cut_review_frame_evidence(
        [review_candidate], source_frame_count=8,
    )
    row = {
        "id": "A",
        "passed": not derived,
        "score": 0.9,
        "confidence": 0.9,
        "identityMatch": "match",
        "rejectionReasons": (
            ["source_cut_model_rejected", "source_cut_partial_movement"]
            if derived else []
        ),
    }
    attempts = []
    selected_id = "A"
    if derived:
        selected_id = "A-CYCLE-1"
        attempts.append({
            "candidateId": selected_id,
            "startSeconds": selected_start,
            "endSeconds": selected_end,
            "passed": True,
            "candidateVideoSha256": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
            "authorizedParentCandidateId": authorized_parent,
            "authorizedParentStartSeconds": 0.0,
            "authorizedParentEndSeconds": 8.0,
        })
    ranking = bake.LoopRanking(
        score=0.9,
        reasons=[],
        raw_response="reviewed source cut",
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutReviewVideoPath": str(selected_segment.resolve()),
            "sourceCutReviewVideoSha256": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
            "sourceCutReviewVideoSha256After": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
            "sourceCutOriginalVideoPath": str(selected_segment.resolve()),
            "sourceCutOriginalVideoSha256": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
            "sourceCutOriginalVideoSha256After": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
            "sourceCutCandidates": [candidate],
            "sourceCutReviewFrameInputs": frame_evidence,
            "sourceCutReviewFrameInputsAfter": frame_evidence,
            "sourceCutScorecardCandidates": [row],
            "selectedCandidateId": selected_id,
            "selectedScorecard": row if not derived else None,
            "sourceCutDeterministicConfirmationAttempts": attempts,
        },
    )
    source_manifest = {
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "preWhamSourceValidationEnabled": True,
        "sourcePrepReason": "pre_wham_source_window_choice",
        "exerciseName": "Example",
        "sourceVideoPath": str(selected_segment),
        "detectionSourceVideoPath": str(selected_segment),
        "selectedSegmentPath": str(selected_segment),
        "selectedSegmentSha256": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
        "selectedSpan": {"startSeconds": selected_start, "endSeconds": selected_end},
        "exerciseMotionContractEnabled": False,
        "exactSourcePhaseValidation": {
            "validationPolicyVersion": bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
            "passed": True,
            "sourceVideoPath": str(selected_segment),
            "sourceVideoSha256": hashlib.sha256(selected_segment.read_bytes()).hexdigest(),
        },
        "sourceCutRanking": bake.ranking_to_manifest(ranking),
    }
    source_manifest_path = segment_dir / "segment_selection.json"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    return workspace, selected_segment, source_manifest_path


def test_retained_source_clearance_rechecks_scorecard_and_source_bytes(tmp_path):
    workspace, selected_segment, _ = _write_source_clearance_fixture(tmp_path)

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)

    assert clearance["status"] == "cleared"
    assert clearance["authority"] == "source_scorecard_pass"
    assert clearance["selectedSegmentSha256"] == hashlib.sha256(selected_segment.read_bytes()).hexdigest()
    reviewed_image = workspace / "review" / "contact_sheet.jpg"
    reviewed_image.write_bytes(b"changed reviewed image")
    changed_image = bake.source_selection_clearance_for_workspace(workspace, required=True)
    assert changed_image["status"] == "needs_source_review"
    assert changed_image["reason"] == "source_cut_review_frame_inputs_unbound"
    reviewed_image.write_bytes(b"review contact sheet")
    selected_segment.write_bytes(b"changed source bytes")
    changed = bake.source_selection_clearance_for_workspace(workspace, required=True)
    assert changed["status"] == "needs_source_review"
    assert changed["reason"] == "selected_segment_bytes_changed_since_source_selection"


def test_retained_clearance_cannot_rehash_a_replaced_selected_segment(tmp_path):
    workspace, selected_segment, source_manifest_path = _write_source_clearance_fixture(tmp_path)
    selected_segment.write_bytes(b"replaced after source review")
    source_manifest = json.loads(source_manifest_path.read_text())
    source_manifest["exactSourcePhaseValidation"]["sourceVideoSha256"] = hashlib.sha256(
        selected_segment.read_bytes()
    ).hexdigest()
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)

    assert clearance["status"] == "needs_source_review"
    assert clearance["reason"] == "selected_segment_bytes_changed_since_source_selection"


def test_exact_phase_manifest_commits_the_final_materialized_segment_hash(tmp_path):
    workspace, selected_segment, manifest_path = _write_source_clearance_fixture(tmp_path)
    confirmed_temp = workspace / "pre_wham_source_candidates" / "source_candidate_A" / "selected_segment.mp4"
    confirmed_temp.parent.mkdir(parents=True)
    confirmed_temp.write_bytes(selected_segment.read_bytes())
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation = dict(source_manifest["exactSourcePhaseValidation"])
    validation.update({
        "sourceVideoPath": str(confirmed_temp),
        "sourceVideoSha256": hashlib.sha256(confirmed_temp.read_bytes()).hexdigest(),
    })
    shutil.copy2(confirmed_temp, selected_segment)
    source_manifest["selectedSegmentSha256"] = hashlib.sha256(b"stale pre-materialization hash").hexdigest()
    source_manifest["exactSourcePhaseValidation"] = validation
    manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    bake.update_pre_wham_exact_phase_validation_manifest(
        candidate_workspace=workspace,
        validation=validation,
    )

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["selectedSegmentSha256"] == hashlib.sha256(selected_segment.read_bytes()).hexdigest()
    assert updated["exactSourcePhaseValidation"]["sourceVideoPath"] == str(selected_segment.resolve())
    confirmed_temp.unlink()
    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)
    assert clearance["status"] == "cleared", clearance


def test_materialized_clearance_binds_selected_segment_not_review_ancestor_or_source_section(tmp_path):
    workspace, selected_segment, _ = _write_source_clearance_fixture(tmp_path)
    original_source = workspace / "source" / "source.mp4"
    original_source.parent.mkdir(parents=True)
    original_source.write_bytes(b"full original source video")
    source_manifest_path = workspace / "segment_detection" / "segment_selection.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["sourceVideoPath"] = str(original_source)
    source_manifest["detectionSourceVideoPath"] = str(original_source)
    source_ranking = bake.ranking_from_manifest(source_manifest["sourceCutRanking"])
    source_ranking.payload.update({
        "sourceCutReviewVideoPath": str(original_source.resolve()),
        "sourceCutReviewVideoSha256": hashlib.sha256(original_source.read_bytes()).hexdigest(),
        "sourceCutReviewVideoSha256After": hashlib.sha256(original_source.read_bytes()).hexdigest(),
        "sourceCutOriginalVideoPath": str(original_source.resolve()),
        "sourceCutOriginalVideoSha256": hashlib.sha256(original_source.read_bytes()).hexdigest(),
        "sourceCutOriginalVideoSha256After": hashlib.sha256(original_source.read_bytes()).hexdigest(),
    })
    source_manifest["sourceCutRanking"] = bake.ranking_to_manifest(source_ranking)
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    precursor_review = tmp_path / "precursor-review.webm"
    precursor_review.write_bytes(b"generated review video bytes")
    item = SimpleNamespace(
        candidate={"sourceCandidateWorkspace": str(workspace)},
        candidate_workspace=workspace,
        exercise_name="Example",
        source_review_video_path=None,
    )
    clearance = bake.source_selection_clearance_for_review_item(item, required=True)
    assert clearance["status"] == "cleared"
    assert original_source.read_bytes() != selected_segment.read_bytes()

    item.source_review_video_path = precursor_review
    assert bake.source_selection_clearance_for_review_item(item, required=True)["status"] == "cleared"

    retained_dir = tmp_path / "retained-selected"
    retained_dir.mkdir()
    item.candidate_workspace = retained_dir
    retained_clearance = bake.source_selection_clearance_for_review_item(item, required=True)
    assert retained_clearance["status"] == "cleared"

    retained_copy = retained_dir / "example_selected_input.mp4"
    retained_copy.write_bytes(selected_segment.read_bytes())
    retained_manifest = {
        "selected": {
            "exerciseName": "Example",
            "sourceSelectionClearance": retained_clearance,
            "candidate": {},
        },
    }
    assert acceptance.source_selection_clearance_is_current(
        retained_manifest,
        source_policy_version=bake.SOURCE_SELECTION_POLICY_VERSION,
        selected_source_path=retained_copy,
        expected_exercise_name="Example",
    )
    retained_copy.write_bytes(b"tampered selected-section copy")
    assert not acceptance.source_selection_clearance_is_current(
        retained_manifest,
        source_policy_version=bake.SOURCE_SELECTION_POLICY_VERSION,
        selected_source_path=retained_copy,
        expected_exercise_name="Example",
    )

    wrong_segment = retained_dir / "input" / "selected_segment.mp4"
    wrong_segment.parent.mkdir()
    wrong_segment.write_bytes(b"different selected segment")
    changed = bake.source_selection_clearance_for_review_item(item, required=True)
    assert changed["status"] == "needs_source_review"
    assert changed["reason"] == "reviewed_selected_segment_bytes_differ_from_clearance"


@pytest.mark.parametrize("mismatch", ["exercise_name", "contract"])
def test_materialized_clearance_is_bound_to_the_review_target_and_contract(tmp_path, mismatch):
    workspace, selected_segment, _ = _write_source_clearance_fixture(tmp_path)
    item = SimpleNamespace(
        candidate={"sourceCandidateWorkspace": str(workspace)},
        candidate_workspace=workspace,
        exercise_name="Different Exercise" if mismatch == "exercise_name" else "Example",
        source_review_video_path=selected_segment,
    )
    ranking = None
    if mismatch == "contract":
        ranking = bake.LoopRanking(
            score=0.9,
            reasons=[],
            payload={"exerciseMotionContract": {
                "exerciseName": "Example",
                "advisoryText": "A different target contract.",
            }},
        )

    clearance = bake.source_selection_clearance_for_review_item(
        item, required=True, ranking=ranking,
    )

    assert clearance["status"] == "needs_source_review"
    assert clearance["reason"] == "source_selection_target_or_contract_mismatch"


@pytest.mark.parametrize("authorized_parent", ["A", "missing-parent"])
def test_retained_cycle_clearance_requires_exact_attempt_and_authorized_parent(
    tmp_path, authorized_parent
):
    workspace, _selected_segment, _ = _write_source_clearance_fixture(
        tmp_path,
        derived=True,
        authorized_parent=authorized_parent,
    )

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)

    assert clearance["status"] == ("cleared" if authorized_parent == "A" else "needs_source_review")
    if authorized_parent == "A":
        assert clearance["authorizedCandidateId"] == "A"
        assert clearance["confirmedCandidateId"] == "A-CYCLE-1"


@pytest.mark.parametrize("semantic_defect", ["missing", "low_confidence", "uncertain_identity"])
def test_exact_pose_cannot_clear_unreviewed_or_uncertain_parent_for_any_backend(
    tmp_path, semantic_defect,
):
    workspace, _selected_segment, source_manifest_path = _write_source_clearance_fixture(
        tmp_path,
        derived=True,
    )
    source_manifest = json.loads(source_manifest_path.read_text())
    ranking_manifest = source_manifest["sourceCutRanking"]
    ranking_payload = ranking_manifest["payload"]
    ranking_payload["sourceCutScorecardBackend"] = "qwen-caption"
    if semantic_defect == "missing":
        ranking_payload["sourceCutScorecardCandidates"] = []
    else:
        scorecard = ranking_payload["sourceCutScorecardCandidates"][0]
        if semantic_defect == "low_confidence":
            scorecard["confidence"] = 0.5
        else:
            scorecard["identityMatch"] = "unclear"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)

    assert clearance["status"] == "needs_source_review"
    assert clearance["reason"] == "selected_interval_lacks_current_semantic_clearance"


def test_qwen_positive_scorecard_still_requires_semantic_identity_and_confidence(tmp_path):
    workspace, _selected_segment, source_manifest_path = _write_source_clearance_fixture(tmp_path)
    source_manifest = json.loads(source_manifest_path.read_text())
    ranking_payload = source_manifest["sourceCutRanking"]["payload"]
    ranking_payload["sourceCutScorecardBackend"] = "qwen-caption"
    ranking_payload["sourceCutScorecardCandidates"][0]["identityMatch"] = "unclear"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=True)

    assert clearance["status"] == "needs_source_review"
    assert clearance["reason"] == "selected_interval_lacks_current_semantic_clearance"


def test_source_validation_disabled_cannot_override_normal_source_lineage(tmp_path):
    workspace, _selected_segment, source_manifest_path = _write_source_clearance_fixture(tmp_path)
    source_manifest = json.loads(source_manifest_path.read_text())
    source_manifest["preWhamSourceValidationEnabled"] = False
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(workspace, required=False, explicitly_disabled=True)

    assert clearance["status"] == "needs_source_review"
    assert clearance["reason"] == "source_validation_configuration_conflicts_with_source_lineage"


def test_explicit_raw_skip_requires_retained_nonvalidated_lineage(tmp_path):
    workspace = tmp_path / "raw-candidate"
    segment_dir = workspace / "segment_detection"
    segment_dir.mkdir(parents=True)
    selected_segment = workspace / "input" / "selected_segment.mp4"
    selected_segment.parent.mkdir()
    selected_segment.write_bytes(b"raw segment")
    (segment_dir / "segment_selection.json").write_text(json.dumps({
        "sourcePrepReason": "ranked_best_chunk",
        "preWhamSourceValidationEnabled": False,
        "selectedSegmentPath": str(selected_segment),
    }), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(
        workspace,
        required=False,
        explicitly_disabled=True,
    )

    assert clearance["status"] == "not_required"
    assert clearance["explicitlyDisabled"] is True

    item = SimpleNamespace(
        candidate={"sourceCandidateWorkspace": str(workspace)},
        candidate_workspace=workspace,
        exercise_name="Example",
        source_review_video_path=tmp_path / "unrelated-review-source.mp4",
    )
    item.source_review_video_path.write_bytes(b"not part of raw source selection")
    retained_clearance = bake.source_selection_clearance_for_review_item(
        item, required=False, explicitly_disabled=True,
    )
    assert retained_clearance["status"] == "not_required"


def test_bodyweight_source_cut_does_not_ask_for_named_equipment():
    questions = bake.source_cut_systemone_questions(required_equipment="none")

    assert "required_equipment" not in questions
    assert questions["overall_confidence"]["criteria"]["C04"].startswith("Confidence 0.85")


def test_typed_boundary_questions_match_completion_policy_and_equipment_roles():
    questions = bake.source_cut_systemone_questions(
        required_equipment="barbell, squat rack",
        equipment_policy=(
            "Every listed equipment role is mandatory.\n"
            "- Barbell: exact active implement must be visibly engaged.\n"
            "- Squat rack: setup fixture evidence is required."
        ),
    )

    start = questions["start_boundary"]
    finish = questions["finish_boundary"]
    assert "mid-repetition only when a complete repetition is visible" in start["instructions"]
    assert "mid-hold or mid-travel boundary is clean" in start["instructions"]
    assert "meaningful start must be visible" in start["instructions"]
    assert "natural finish must be visible" in finish["instructions"]
    assert "cut through a required phase" not in start["instructions"] + finish["instructions"]

    equipment = questions["required_equipment"]
    assert "Every listed equipment role is mandatory" in equipment["instructions"]
    assert "Every listed role condition is visibly satisfied" in equipment["criteria"]["engaged"]
    assert "At least one listed role is clearly not satisfied" in equipment["criteria"]["absent"]
    assert "At least one listed role cannot be verified" in equipment["criteria"]["unclear"]


def test_shared_clef_source_cut_request_preserves_production_state_and_schema(
    tmp_path, monkeypatch
):
    candidate = _candidate(tmp_path)
    candidate.frame_paths[0].write_bytes(b"retained candidate sheet")
    observed = {}
    decisions = _decisions()

    def request_choice_decisions(**kwargs):
        observed.update(kwargs)
        return {
            "decisions": decisions,
            "rawSystemOneResponse": {"mock": "native result"},
        }

    monkeypatch.setattr(clef_systemone, "request_choice_decisions", request_choice_decisions)
    prompt = (
        "Source-cut decision policy.\n"
        "Return JSON only with exactly one row in this schema: {candidate schema}"
    )

    raw = bake.request_clef_source_cut_scorecard(
        base_url="http://127.0.0.1:8091",
        model="retained-clef-model",
        candidate=candidate,
        prompt=prompt,
        required_equipment="barbell",
        equipment_policy="Barbell active implement and squat rack setup fixture are separately required.",
        timeout_seconds=47.0,
    )

    payload = json.loads(raw)
    assert observed["base_url"] == "http://127.0.0.1:8091"
    assert observed["model"] == "retained-clef-model"
    assert observed["frame_paths"] == candidate.frame_paths
    assert observed["state"] == {
        "purpose": "Image-grounded typed review of one source-cut candidate.",
        "candidateId": "A",
        "candidateWindow": {"startSeconds": 0.0, "endSeconds": 4.0},
        "candidateDecisionPolicy": "Source-cut decision policy.",
        "imageOrder": "Images are this candidate's contact sheets in the supplied chronological order.",
        "limits": [
            "Classify only this candidate; do not select a winner across candidates.",
            "Treat uncertainty as a reason to withhold approval.",
            "Use the provided typed choices; do not infer hidden phases or equipment.",
        ],
    }
    assert observed["questions"] == bake.source_cut_systemone_questions(
        required_equipment="barbell",
        equipment_policy="Barbell active implement and squat rack setup fixture are separately required.",
    )
    assert observed["timeout_seconds"] == 47.0
    assert payload["candidates"][0]["clefTypedDecisionSummary"]["choices"] == {
        name: answer["choice"] for name, answer in decisions.items()
    }
    assert payload["clefSystemOne"]["rawSystemOneResponse"] == {"mock": "native result"}


def test_production_clef_caption_adapter_uses_shared_request_helper(tmp_path, monkeypatch):
    candidate = _candidate(tmp_path)
    signature = tuple(str(path.resolve()).casefold() for path in candidate.frame_paths)
    observed = []

    def shared_request(**kwargs):
        observed.append(kwargs)
        return "shared response"

    monkeypatch.setattr(bake, "request_clef_source_cut_scorecard", shared_request)

    raw = bake.clef_source_cut_caption_images_for_candidate(
        frame_paths=candidate.frame_paths,
        prompt="production prompt",
        candidates_by_frame_signature={signature: candidate},
        base_url="http://127.0.0.1:8091",
        model="retained-clef-model",
        required_equipment="barbell",
        equipment_policy="Active implement role policy",
        timeout_seconds=90.0,
        request_timeout_seconds=36.0,
    )

    assert raw == "shared response"
    assert observed == [{
        "base_url": "http://127.0.0.1:8091",
        "model": "retained-clef-model",
        "candidate": candidate,
        "prompt": "production prompt",
        "required_equipment": "barbell",
        "equipment_policy": "Active implement role policy",
        "timeout_seconds": 36.0,
    }]


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


def test_production_cli_rejects_clef_backend_options(tmp_path):
    from pathlib import Path
    from exercise_motion_pkg.cli import build_parser

    parser = build_parser()
    base_args = [
        "bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path), "--wham-repo-path", str(tmp_path),
        "--body-model-root", str(tmp_path),
    ]
    with pytest.raises(SystemExit):
        parser.parse_args([*base_args, "--visual-decision-backend", "clef-systemone"])
    with pytest.raises(SystemExit):
        parser.parse_args([*base_args, "--final-output-review-backend", "clef-systemone"])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "detect-segment", "--video-path", str(tmp_path / "source.mp4"),
            "--out-json", str(tmp_path / "segment.json"), "--frames-dir", str(tmp_path / "frames"),
            "--visual-decision-backend", "clef-systemone",
        ])

    for script_name in (
        "run_exercise_motion_workout_plan.ps1",
        "run_exercise_motion_bake_and_rank.ps1",
        "run_exercise_motion_youtube_bake_and_rank.ps1",
    ):
        script = (Path(__file__).resolve().parents[1] / "scripts" / script_name).read_text(
            encoding="utf-8"
        )
        assert "clef-systemone" not in script
        assert "ClefSystemOne" not in script


def test_production_visual_backend_defaults_to_qwen_and_manifest_defaults_are_independent(tmp_path):
    from exercise_motion_pkg.cli import build_parser, build_bake_and_rank_request

    args = build_parser().parse_args([
        "bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path), "--wham-repo-path", str(tmp_path),
        "--body-model-root", str(tmp_path),
    ])
    request = build_bake_and_rank_request(args)
    assert request.visual_decision_backend == "qwen-chat"
    assert bake.effective_final_output_review_backend(request) == "qwen-chat"
    assert DetectionSettings().visual_decision_backend == "qwen-chat"
    with pytest.raises(ValueError, match="Qwen-only"):
        DetectionSettings(visual_decision_backend="clef-systemone")
    detect_args = build_parser().parse_args([
        "detect-segment", "--video-path", str(tmp_path / "source.mp4"),
        "--out-json", str(tmp_path / "segment.json"),
        "--frames-dir", str(tmp_path / "frames"),
    ])
    assert not hasattr(detect_args, "visual_decision_backend")

    for stale_manifest in (
        {"finalOutputReviewBackend": "clef-systemone"},
        {"visualDecisionBackend": "clef-systemone"},
    ):
        with pytest.raises(ValueError, match="Qwen-only"):
            bake.bake_and_rank_request_from_selection_manifest(
                stale_manifest,
                workspace=tmp_path,
                min_selected_score=None,
                review_frames=None,
                max_review_windows=None,
            )

    with pytest.raises(ValueError, match="Qwen-only"):
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
            wham_repo_path=None,
            body_model_root=None,
            visual_decision_backend="clef-systemone",
        )
    with pytest.raises(ValueError, match="Qwen-only"):
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
            wham_repo_path=None,
            body_model_root=None,
            final_output_review_backend="clef-systemone",
        )


def test_qwen_support_result_records_actual_backend():
    result = segment_detection.classify_support_dominance_from_frames(
        frame_paths=[],
        exercise_name="Squat",
        caption_images=lambda **_kwargs: json.dumps({
            "supportDominance": "foot_dominant",
            "confidence": 0.9,
            "uncertain": False,
            "reason": "Feet remain the main support.",
        }),
        visual_decision_backend="qwen-chat",
    )

    assert result.support_dominance == "foot_dominant"
    assert result.model_output["backend"] == "qwen_chat"


@pytest.mark.parametrize("operation_fails", [False, True])
def test_managed_clef_owner_releases_server_and_nested_lease(tmp_path, monkeypatch, operation_fails):
    from exercise_motion_pkg import child_process

    process = object()
    stopped = []
    launched = []
    monkeypatch.setenv("EXERCISE_MOTION_CLEF_GPU_LAYERS", "22")
    monkeypatch.setenv("EXERCISE_MOTION_CLEF_FLASH_ATTN", "on")

    class FakeProcessOwner:
        def close(self):
            pass

    monkeypatch.setattr(child_process, "ChildProcessOwner", lambda _process: FakeProcessOwner())
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
        command = launched[0]
        context_size = int(command[command.index("--ctx-size") + 1])
        assert context_size == 8192
        assert int(command[command.index("--batch-size") + 1]) >= max(context_size, 4267)
        assert int(command[command.index("--ubatch-size") + 1]) >= max(context_size, 4267)
        assert command[command.index("--n-gpu-layers") + 1] == "22"
        assert command[command.index("--flash-attn") + 1] == "on"
        assert clef_systemone._ACTIVE_MANAGED_CLEF_ENDPOINT.get() is None


def test_managed_clef_server_profile_defaults_and_normalizes(monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_CLEF_GPU_LAYERS", raising=False)
    monkeypatch.delenv("EXERCISE_MOTION_CLEF_FLASH_ATTN", raising=False)
    assert clef_systemone.managed_clef_server_profile() == {
        "gpuLayers": 99,
        "flashAttention": "auto",
    }

    monkeypatch.setenv("EXERCISE_MOTION_CLEF_GPU_LAYERS", "22")
    monkeypatch.setenv("EXERCISE_MOTION_CLEF_FLASH_ATTN", "ON")
    assert clef_systemone.managed_clef_server_profile() == {
        "gpuLayers": 22,
        "flashAttention": "on",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EXERCISE_MOTION_CLEF_GPU_LAYERS", "-1"),
        ("EXERCISE_MOTION_CLEF_GPU_LAYERS", "22gpu"),
        ("EXERCISE_MOTION_CLEF_GPU_LAYERS", "2147483648"),
        ("EXERCISE_MOTION_CLEF_FLASH_ATTN", "sometimes"),
    ],
)
def test_managed_clef_server_profile_rejects_invalid_environment(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        clef_systemone.managed_clef_server_profile()


def test_production_request_rejects_clef_final_review(tmp_path):
    with pytest.raises(ValueError, match="Qwen-only"):
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
            wham_repo_path=None,
            body_model_root=None,
            final_output_review_backend="clef-systemone",
        )

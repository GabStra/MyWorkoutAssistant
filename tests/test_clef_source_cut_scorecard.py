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


def test_child_sample_inventory_binds_final_exposure_using_preceding_pts_interval(
    monkeypatch, tmp_path,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "child-review"
    output_dir.mkdir()
    sample_paths = [output_dir / f"frame_{index:02d}.jpg" for index in (1, 2)]
    for index, path in enumerate(sample_paths):
        path.write_bytes(f"sample-{index}".encode())
    sheet = output_dir / "contact_sheet_01.jpg"
    sheet.write_bytes(b"sheet")
    (output_dir / "contact_sheet_evidence.json").write_text(json.dumps({
        "schemaVersion": 1,
        "sheets": {
            sheet.name: {
                "sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
                "frames": [
                    {"number": 1, "timestampSeconds": 0.0},
                    # This request decodes to the final PTS at 4.0 seconds.
                    {"number": 2, "timestampSeconds": 3.9},
                ],
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(
        "exercise_motion_pkg.source_frame_clock._read_decoded_frame_timestamps",
        # The embedded PTS clock starts at 7s while the review window and
        # contact-sheet timestamps use video-local time starting at 0s.
        lambda *args, **kwargs: ([7.0, 8.0, 11.0], 0.001),
    )

    inventory = bake.source_cut_child_sample_inventory(
        output_dir=output_dir,
        source_video_path=source,
        candidate_window=DetectionWindow(0, 0.0, 4.1),
    )
    assert [item["sourceFrameIndex"] for item in inventory] == [0, 2]
    assert inventory[-1]["sourceTimeSec"] == 4.0

    # A seek that maps to the penultimate frame still fails the required final
    # included-exposure check; the corrected interval bound does not relax it.
    manifest_path = output_dir / "contact_sheet_evidence.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sheets"][sheet.name]["frames"][-1]["timestampSeconds"] = 0.9
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="omit an included source-window endpoint"):
        bake.source_cut_child_sample_inventory(
            output_dir=output_dir,
            source_video_path=source,
            candidate_window=DetectionWindow(0, 0.0, 4.1),
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


def test_source_cut_equipment_roles_keep_active_load_and_support_outside_rack_setup(tmp_path):
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
    }
    assert bake.two_scale_required_equipment_names("Barbell Floor Press", contract) == ["barbell", "bench"]
    assert "visibly held, worn, attached, or connected" in policy
    assert "body-support surface" in policy
    assert "setup fixture" not in policy
    assert len(contract["motionContext"]["requiredAccessories"]) == 2
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
        "normalizedName": "dumbbell",
        "role": "active_implement",
        "minimumObjectCount": 2,
    }]
    assert bake.two_scale_required_equipment_names("Dumbbell Overhead Press", contract) == ["dumbbell"]


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
        "preReconstructionSourceValidationEnabled": True,
        "sourcePrepReason": "pre_reconstruction_source_window_choice",
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
    confirmed_temp = workspace / "pre_reconstruction_source_candidates" / "source_candidate_A" / "selected_segment.mp4"
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

    bake.update_pre_reconstruction_exact_phase_validation_manifest(
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


def test_retained_clearance_accepts_equivalent_utc_offset_without_rewriting_receipt(tmp_path):
    workspace, selected_segment, source_manifest_path = _write_source_clearance_fixture(tmp_path)
    retained_contract = {
        "exerciseName": "Example",
        "advisoryText": "Approved exercise definition.",
        "motionContext": {
            "exerciseDefinition": {
                "review": {
                    "approvedAtUtc": "2026-10-22T13:27:56.244742+02:00",
                    "reviewArtifactSha256": "review-artifact-a",
                },
            },
        },
    }
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["exerciseMotionContract"] = retained_contract
    source_ranking = bake.ranking_from_manifest(source_manifest["sourceCutRanking"])
    source_ranking.payload["exerciseMotionContract"] = retained_contract
    source_manifest["sourceCutRanking"] = bake.ranking_to_manifest(source_ranking)
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    current_contract = json.loads(json.dumps(retained_contract))
    current_contract["motionContext"]["exerciseDefinition"]["review"][
        "approvedAtUtc"
    ] = "2026-10-22T11:27:56.244742+00:00"

    clearance = bake.source_selection_clearance_for_workspace(
        workspace,
        required=True,
        expected_exercise_name="Example",
        expected_contract=current_contract,
    )

    assert clearance["status"] == "cleared", clearance
    assert clearance["exerciseMotionContractSha256"] == bake.exercise_motion_contract_prompt_sha256(
        retained_contract
    )
    assert clearance["exerciseMotionContractSha256"] != bake.exercise_motion_contract_prompt_sha256(
        current_contract
    )
    retained_manifest = {
        "selected": {
            "exerciseName": "Example",
            "sourceSelectionClearance": clearance,
        },
    }
    assert acceptance.source_selection_clearance_is_current(
        retained_manifest,
        source_policy_version=bake.SOURCE_SELECTION_POLICY_VERSION,
        selected_source_path=selected_segment,
        expected_exercise_name="Example",
        expected_contract=current_contract,
    )

    changed_requirement = json.loads(json.dumps(current_contract))
    changed_requirement["advisoryText"] = "A materially different exercise requirement."
    changed_identity = json.loads(json.dumps(current_contract))
    changed_identity["exerciseName"] = "Different Example"
    for changed_contract in (changed_requirement, changed_identity):
        assert bake.source_selection_clearance_for_workspace(
            workspace,
            required=True,
            expected_exercise_name="Example",
            expected_contract=changed_contract,
        )["status"] == "needs_source_review"
        assert not acceptance.source_selection_clearance_is_current(
            retained_manifest,
            source_policy_version=bake.SOURCE_SELECTION_POLICY_VERSION,
            selected_source_path=selected_segment,
            expected_exercise_name="Example",
            expected_contract=changed_contract,
        )


@pytest.mark.parametrize("ranking_contract_state", ["current", "stale", "missing"])
def test_retained_clearance_requires_ranking_contract_to_match_expected_contract(
    tmp_path, ranking_contract_state,
):
    workspace, _selected_segment, source_manifest_path = _write_source_clearance_fixture(tmp_path)
    current_contract = {
        "exerciseName": "Example",
        "advisoryText": "Approved exercise definition.",
        "contractPolicyVersion": 39,
        "contractScope": "definition_only",
    }
    ranking_contract = json.loads(json.dumps(current_contract))
    if ranking_contract_state == "stale":
        ranking_contract["contractPolicyVersion"] = 38
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["exerciseMotionContract"] = current_contract
    ranking = bake.ranking_from_manifest(source_manifest["sourceCutRanking"])
    if ranking_contract_state == "missing":
        ranking.payload.pop("exerciseMotionContract", None)
    else:
        ranking.payload["exerciseMotionContract"] = ranking_contract
    source_manifest["sourceCutRanking"] = bake.ranking_to_manifest(ranking)
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    clearance = bake.source_selection_clearance_for_workspace(
        workspace,
        required=True,
        expected_exercise_name="Example",
        expected_contract=current_contract,
    )

    if ranking_contract_state == "current":
        assert clearance["status"] == "cleared", clearance
    else:
        assert clearance["status"] == "needs_source_review", clearance
        assert clearance["reason"] == "source_cut_ranking_contract_mismatch_or_missing"


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
    source_manifest["preReconstructionSourceValidationEnabled"] = False
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
        "preReconstructionSourceValidationEnabled": False,
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
    # `bake-and-rank` no longer accepts the removed reconstruction-repo-path
    # CLI option; Docker reconstruction uses the configured body model root.
    base_args = [
        "bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path),
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
        "--workspace", str(tmp_path),
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
            body_model_root=None,
            visual_decision_backend="clef-systemone",
        )
    with pytest.raises(ValueError, match="Qwen-only"):
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path,
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
            body_model_root=None,
            final_output_review_backend="clef-systemone",
        )


def _return_expansion_timing_fixture(tmp_path, *, child_start, child_end):
    frame_dir = tmp_path / "timing-frames"
    frame_dir.mkdir()
    sheet = frame_dir / "sheet_1.jpg"
    sheet.write_bytes(b"child parent timing sheet")
    sheet_sha256 = hashlib.sha256(sheet.read_bytes()).hexdigest()
    timestamps = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    (frame_dir / "contact_sheet_evidence.json").write_text(json.dumps({
        "sheets": {
            sheet.name: {
                "sha256": sheet_sha256,
                "frames": [
                    {"number": index, "timestampSeconds": timestamp}
                    for index, timestamp in enumerate(timestamps)
                ],
            },
        },
    }), encoding="utf-8")
    parent = {
        "candidateId": "Y",
        "startSeconds": 0.25,
        "endSeconds": 1.0,
        "framePaths": [str(sheet)],
    }
    child = {
        "candidateId": "Y-RETN-3",
        "startSeconds": child_start,
        "endSeconds": child_end,
        "exactBoundaryExpansionParentId": "Y",
        "chunking": {"strategy": "exact_pose_return_expansion"},
    }
    phase = {
        "candidateId": "Y",
        "status": "sampled",
        "expectedIds": ["phase-1"],
        "candidateWindowSourceSeconds": {"start": 0.25, "end": 1.0},
        "sampleBinsById": {
            "phase-1": {
                "sampleBins": [
                    {
                        "frameId": f"Y:{index}",
                        "sheetSha256": sheet_sha256,
                        "sourceTimestampSeconds": timestamp,
                        "sourceBinStartSeconds": timestamp,
                        "sourceBinEndSeconds": min(timestamp + 0.05, 1.0),
                    }
                    for index, timestamp in enumerate(timestamps[:4])
                ],
            },
        },
    }
    ranking = bake.LoopRanking(
        score=0.9,
        reasons=[],
        payload={
            "sourceCutCandidates": [parent],
            "sourceCutScorecardCandidates": [{
                "id": "Y",
                "passed": True,
                "requiredEquipment": "none",
                "movementTopologyEvidence": {"phaseTimingEvidence": phase},
            }],
        },
    )
    return ranking, child, sheet_sha256


def test_return_expansion_is_pose_eligible_without_inheriting_parent_approval(tmp_path):
    ranking, child, _ = _return_expansion_timing_fixture(
        tmp_path, child_start=0.25, child_end=2.23,
    )

    coverage = bake.source_cut_child_timing_coverage(ranking, child)

    assert coverage["eligible"] is True
    assert coverage["poseEligible"] is True
    assert coverage["semanticApprovalRequired"] is True
    assert coverage["semanticApprovalOwner"] == "Y-RETN-3"
    assert coverage["parentApprovalInherited"] is False


def test_contained_trim_still_requires_the_parent_to_contain_the_child(tmp_path):
    ranking, child, _ = _return_expansion_timing_fixture(
        tmp_path, child_start=0.25, child_end=2.23,
    )
    child.pop("exactBoundaryExpansionParentId")
    child["exactContractTrimParentId"] = "Y"
    child["chunking"] = {"strategy": "exact_pose_contract_boundary_trim"}

    coverage = bake.source_cut_child_timing_coverage(ranking, child)

    assert coverage["eligible"] is False
    assert "semanticApprovalRequired" not in coverage


def _child_review(child_id, window, samples):
    return {
        "id": child_id,
        "passed": True,
        "requiredEquipment": "none",
        "movementTopologyEvidence": {
            "phaseTimingEvidence": {
                "candidateId": child_id,
                "candidateWindowSourceSeconds": {"start": window[0], "end": window[1]},
                "sampleBinsById": {"phase-1": {"sampleBins": samples}},
            },
        },
    }


def test_child_semantic_approval_requires_child_window_and_extension_frame(tmp_path):
    ranking, child, sheet_sha256 = _return_expansion_timing_fixture(
        tmp_path, child_start=0.25, child_end=2.23,
    )
    coverage = bake.source_cut_child_timing_coverage(ranking, child)
    parent_only = [
        {"frameId": f"Y:{index}", "sheetSha256": sheet_sha256,
         "sourceTimestampSeconds": timestamp}
        for index, timestamp in enumerate([0.25, 0.5, 0.75, 1.0])
    ]
    with_extension = [
        *parent_only,
        {"frameId": "Y:5", "sheetSha256": sheet_sha256, "sourceTimestampSeconds": 2.0},
    ]

    relabelled_parent = bake.source_cut_child_semantic_review_approval(
        _child_review("Y-RETN-3", (0.25, 1.0), parent_only), child, coverage,
    )
    missing_tail = bake.source_cut_child_semantic_review_approval(
        _child_review("Y-RETN-3", (0.25, 2.23), parent_only), child, coverage,
    )
    approved = bake.source_cut_child_semantic_review_approval(
        _child_review("Y-RETN-3", (0.25, 2.23), with_extension), child, coverage,
    )
    no_review = bake.source_cut_child_semantic_review_approval(None, child, coverage)

    assert relabelled_parent["approved"] is False
    assert relabelled_parent["reason"] == "child_semantic_review_window_mismatch"
    assert missing_tail["approved"] is False
    assert missing_tail["reason"] == "child_semantic_review_missing_extension_evidence"
    assert approved["approved"] is True
    assert no_review["approved"] is False


def test_child_semantic_review_marks_truncated_json_invalid(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    frame = tmp_path / "child-frame.jpg"
    frame.write_bytes(b"review frame")
    overview_frame = tmp_path / "child-overview.jpg"
    overview_frame.write_bytes(b"verified PTS overview")
    child = {
        "candidateId": "Y-RETN-1",
        "startSeconds": 0.25,
        "endSeconds": 2.23,
        "exactBoundaryExpansionParentId": "Y",
    }

    def fake_render(**kwargs):
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        return [frame]

    monkeypatch.setattr(bake, "render_video_window_contact_sheet", fake_render)
    monkeypatch.setattr(
        bake,
        "build_source_cut_candidate",
        lambda **kwargs: bake.SourceCutCandidate(
            kwargs["candidate_id"], kwargs["candidate_window"], [frame],
        ),
    )
    monkeypatch.setattr(
        bake, "source_cut_review_overview",
        lambda candidate, output_dir, **kwargs: bake.replace(
            candidate, frame_paths=[overview_frame],
        ),
    )
    monkeypatch.setattr(
        bake,
        "source_cut_child_sample_inventory",
        lambda **kwargs: [
            {"sourceTimeSec": 0.25, "samplePath": str(frame), "sampleSha256": hashlib.sha256(frame.read_bytes()).hexdigest()},
            {"sourceTimeSec": 2.20, "samplePath": str(frame), "sampleSha256": hashlib.sha256(frame.read_bytes()).hexdigest()},
        ],
    )
    monkeypatch.setattr(
        bake, "invoke_cut_caption_images", lambda *args, **kwargs: '{"candidates":[{"id":"Y-RETN-1","approved":true',
    )
    monkeypatch.setattr(
        bake, "parse_source_cut_candidate_choice",
        lambda *args, **kwargs: pytest.fail("truncated JSON must not reach the permissive parser"),
    )

    review = bake.request_source_cut_child_semantic_review(
        child,
        source_video_path=source,
        exercise_name="Barbell Overhead Press",
        candidate_title="Overhead press return",
        exercise_motion_contract={},
        caption_images=lambda **kwargs: "unused",
        output_dir=tmp_path,
        frame_count=8,
    )

    receipt_path = (
        tmp_path / "source_candidate_Y-RETN-1" / "child_semantic_review"
        / f"policy-v{bake.SOURCE_CUT_CHILD_REVIEW_POLICY_VERSION}" / "semantic_review.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert review is None
    assert receipt["candidateId"] == "Y-RETN-1"
    assert receipt["candidateWindowSourceSeconds"] == {"start": 0.25, "end": 2.23}
    assert receipt["sourceVideoSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert receipt["reviewFrames"] == [{
        "path": str(overview_frame), "sha256": hashlib.sha256(overview_frame.read_bytes()).hexdigest(),
    }]
    assert receipt["rawResponse"] == '{"candidates":[{"id":"Y-RETN-1","approved":true'
    assert receipt["parsedRankingPayload"] is None
    assert receipt["status"] == "invalid_response"
    assert receipt["parseFailure"] == "invalid_json"


def test_production_caller_wires_expanded_child_review_and_rejected_child_fails(
    monkeypatch, tmp_path,
):
    (tmp_path / "detection.mp4").write_bytes(b"retained detection source")
    ranking, child, sheet_sha256 = _return_expansion_timing_fixture(
        tmp_path, child_start=0.25, child_end=2.23,
    )
    capture: dict[str, object] = {}

    def fake_refresh(payload, **kwargs):
        return payload

    def fake_rank(**kwargs):
        return ranking, 0.0, 0.0

    def fake_render(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        sheet = output_dir / "child_sheet.jpg"
        sheet.write_bytes(b"child review sheet")
        (output_dir / "contact_sheet_evidence.json").write_text(
            json.dumps({
                "sheets": {
                    sheet.name: {
                        "sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
                        "frames": [
                            {"number": 1, "timestampSeconds": 0.25},
                            {"number": 2, "timestampSeconds": 2.0},
                        ],
                    },
                },
            }),
            encoding="utf-8",
        )
        return [sheet]

    def fake_request(**kwargs):
        return json.dumps({
            "candidates": [{
                "id": kwargs["candidate"].candidate_id,
                "approved": False,
                "confidence": 0.2,
                "completeMovement": False,
                "startBoundaryClean": True,
                "finishBoundaryClean": False,
                "setupOrFiller": False,
                "namedEquipmentEngagedStatus": "not_applicable",
                "reject": ["partial_movement"],
                "note": "rejected child",
            }],
        })

    def fake_select(ranking, **kwargs):
        callback = kwargs.get("child_semantic_review")
        assert callback is not None
        capture["callback"] = callback
        review = callback(child)
        coverage = bake.source_cut_child_timing_coverage(ranking, child)
        capture["review"] = review
        capture["approval"] = bake.source_cut_child_semantic_review_approval(
            review, child, coverage,
        )
        payload = {**ranking.payload, "sourceCutChildSemanticReviewRequired": True}
        payload.pop("selectedCandidateId", None)
        return bake.LoopRanking(
            score=0.0,
            reasons=[
                "source_cut_deterministic_confirmation_failed",
                "source_cut_review_required",
            ],
            payload=payload,
        ), 0.0

    from exercise_motion_pkg import pose_prefilter

    monkeypatch.setattr(pose_prefilter, "refresh_legacy_spread_pose_evidence", fake_refresh)
    monkeypatch.setattr(bake, "expand_detection_source_for_kinematic_cut", lambda **kwargs: None)
    monkeypatch.setattr(bake, "validating_padded_ranked_source_chunk", lambda *args, **kwargs: False)
    monkeypatch.setattr(bake, "rank_source_video_cut_candidates_with_caption_images", fake_rank)
    monkeypatch.setattr(
        bake, "source_cut_deterministic_confirmation_candidates",
        lambda ranking: [child],
    )
    monkeypatch.setattr(
        bake, "exercise_motion_contract_has_specific_topology",
        lambda contract: True,
    )
    monkeypatch.setattr(bake, "render_video_window_contact_sheet", fake_render)
    monkeypatch.setattr(
        bake, "source_cut_visual_integrity_metrics",
        lambda paths: {"passed": True},
    )
    monkeypatch.setattr(bake, "request_clef_source_cut_scorecard", fake_request)
    monkeypatch.setattr(bake, "select_exact_pose_confirmed_source_cut", fake_select)
    monkeypatch.setattr(
        bake, "preserve_parent_source_window_after_pose_only_recovery",
        lambda ranking, **kwargs: ranking,
    )
    monkeypatch.setattr(
        bake, "write_pre_reconstruction_source_selection_manifest",
        lambda **kwargs: None,
    )

    with pytest.raises(bake.SourceCandidateRejected):
        bake.choose_pre_reconstruction_source_cut_or_reject(
            ranked_candidate=SimpleNamespace(
                exercise_name="squat",
                title="Squat",
                candidate={},
            ),
            candidate_workspace=tmp_path,
            source_video_path=tmp_path / "source.mp4",
            detection_source_video_path=tmp_path / "detection.mp4",
            source_window=DetectionWindow(0, 0.0, 3.0),
            detection_source_offset_seconds=0.0,
            source_chunk_hint=None,
            caption_images=lambda **kwargs: "unused",
            exercise_motion_contract={},
            source_chunk_estimate=SimpleNamespace(),
            visual_decision_backend="clef-systemone",
        )

    assert capture["callback"] is not None
    assert isinstance(capture["review"], dict)
    assert capture["review"]["passed"] is False
    assert capture["approval"]["approved"] is False
    assert capture["approval"]["reason"] == "child_semantic_review_missing_or_rejected"

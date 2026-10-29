from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_review_authority import SOURCE_REVIEW_AUTHORITY_VERSION


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _retained_fixture(tmp_path: Path):
    retained = tmp_path / "retained"
    detection = retained / "segment_detection"
    inputs = retained / "input"
    detection.mkdir(parents=True)
    inputs.mkdir()
    source = retained / "source" / "source.mp4"
    source.parent.mkdir()
    source.write_bytes(b"retained original source")
    selected = inputs / "selected_segment.mp4"
    selected.write_bytes(b"exact approved interval")
    contract = {
        "schemaVersion": 1,
        "exerciseName": "Test Movement",
        "advisoryText": "Perform the defined movement through its full range.",
        "completionMode": "distinct_end_state",
        "movementType": "repetition",
        "definingAction": "Squat down and return to standing.",
        "motionContext": {"exerciseDefinition": {"review": {
            "approvedAtUtc": "2026-10-27T09:15:00+02:00",
        }}},
    }
    ranking_payload = {
        "sourceCutOriginalVideoSha256": _sha(source),
        "sourceCutOriginalVideoSha256After": _sha(source),
        "sourceCutOriginalVideoPath": str(source.resolve()),
        "sourceCutReviewVideoSha256": _sha(source),
        "sourceCutReviewVideoSha256After": _sha(source),
        "sourceCutReviewVideoPath": str(source.resolve()),
        "sourceReviewAuthorityVersion": SOURCE_REVIEW_AUTHORITY_VERSION,
        "selectedCandidateId": "A",
        "selected_section_start_seconds": 1.0,
        "selected_section_end_seconds": 3.0,
    }
    selection = {
        "role": "pre_reconstruction_validated_source_cut",
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "sourcePrepReason": "pre_reconstruction_source_window_choice",
        "preReconstructionSourceValidationEnabled": True,
        "sourceVideoPath": str(source.resolve()),
        "selectedSegmentPath": str(selected.resolve()),
        "selectedSegmentSha256": _sha(selected),
        "exerciseName": "Test Movement",
        "exerciseMotionContractEnabled": True,
        "exerciseMotionContract": contract,
        "selectedSpan": {"startSeconds": 1.0, "endSeconds": 3.0, "confidence": 0.95},
        "selectedSpanInOriginalSource": {"startSeconds": 1.0, "endSeconds": 3.0, "confidence": 0.95},
        "sourceCutRanking": {
            "score": 0.95,
            "rawResponse": "structured approval retained",
            "reasons": ["source_candidate_scorecard_passed"],
            "payload": ranking_payload,
        },
        "exactSourcePhaseValidation": {
            "passed": True,
            "required": False,
            "validationPolicyVersion": bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
        },
    }
    selection_path = detection / "segment_selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    phase = {
        "metrics": {
            "passed": True,
            "required": False,
            "validationPolicyVersion": bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
            "sourceVideoPath": str(selected.resolve()),
        }
    }
    (detection / "exact_source_phase_validation.json").write_text(json.dumps(phase), encoding="utf-8")
    (detection / "exact_source_pose_reference.json").write_text(json.dumps({"pose": {"frames": []}}), encoding="utf-8")
    reference = {
        "schemaVersion": 1,
        "workspace": str(retained.resolve()),
        "videoId": "video-1",
        "exerciseId": "exercise-1",
        "exerciseName": "Test Movement",
        "sourceVideoSha256": _sha(source),
        "segmentSelectionSha256": _sha(selection_path),
        "selectedSegmentSha256": _sha(selected),
        "exerciseMotionContractSha256": bake.exercise_motion_contract_prompt_sha256(contract),
    }
    return retained, contract, reference


def _patch_existing_authority(monkeypatch):
    monkeypatch.setattr(bake, "source_cut_ranking_has_vlm_approval", lambda _ranking: True)
    monkeypatch.setattr(bake, "cached_source_selection_matches_validation_mode", lambda *a, **k: True)
    monkeypatch.setattr(
        bake,
        "pre_reconstruction_source_interval_authority",
        lambda **_kwargs: {"authoritative": True, "reason": "fixture_current"},
    )


def _candidate_for_retained(retained: Path, reference: dict):
    return bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="exercise-1",
        exercise_name="Test Movement",
        exercise_slug="test-movement",
        candidate={
            "videoId": "video-1",
            "videoPath": str((retained / "source" / "source.mp4").resolve()),
            "retainedSourceInterval": reference,
        },
    )


def _set_saved_contract(retained: Path, contract: dict, reference: dict) -> None:
    selection_path = retained / "segment_detection" / "segment_selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["exerciseMotionContract"] = contract
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    reference["segmentSelectionSha256"] = _sha(selection_path)
    reference["exerciseMotionContractSha256"] = bake.exercise_motion_contract_prompt_sha256(contract)


def test_retained_interval_reuses_exact_cut_without_downloading_or_redetecting(tmp_path, monkeypatch):
    _retained, contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    monkeypatch.setattr(bake, "exercise_motion_contract_from_candidate", lambda _candidate: contract)
    monkeypatch.setattr(bake, "copy_or_download_candidate_source", lambda *a, **k: pytest.fail("source download unexpectedly ran"))
    monkeypatch.setattr(
        bake,
        "validate_exact_source_with_cached_gpu_handoff",
        lambda **kwargs: {"passed": True, "metrics": {"passed": True}},
    )
    monkeypatch.setattr(bake, "promote_and_require_exact_source_phase_validation", lambda **_kwargs: None)
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="exercise-1",
        exercise_name="Test Movement",
        exercise_slug="test-movement",
        candidate={"videoId": "video-1", "videoPath": str((_retained / "source" / "source.mp4").resolve()), "retainedSourceInterval": reference},
    )
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "bake",
        body_model_root=None,
        pre_reconstruction_source_validation=True,
    )

    selected = bake.prepare_candidate_input_video(candidate, request=request)

    assert selected == request.workspace / candidate.workspace_slug / "input" / "selected_segment.mp4"
    assert selected.read_bytes() == b"exact approved interval"
    receipt = json.loads((selected.parent.parent / "segment_detection" / "segment_selection.json").read_text())
    assert receipt["selectedSegmentPath"] == str(selected.resolve())
    imported = json.loads((selected.parent.parent / "segment_detection" / "retained_source_interval_import.json").read_text())
    assert imported["videoId"] == "video-1"


def test_retained_interval_hash_mismatch_stays_unresolved(tmp_path, monkeypatch):
    _retained, contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    reference["selectedSegmentSha256"] = "0" * 64
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="exercise-1",
        exercise_name="Test Movement",
        exercise_slug="test-movement",
        candidate={"videoId": "video-1", "videoPath": str((_retained / "source" / "source.mp4").resolve()), "retainedSourceInterval": reference},
    )

    with pytest.raises(ValueError, match="approved segment bytes changed"):
        bake.materialize_retained_source_interval(
            candidate,
            candidate_workspace=tmp_path / "bake" / candidate.workspace_slug,
            exercise_motion_contract=contract,
        )


def test_retained_interval_candidate_video_must_match_approved_original(tmp_path, monkeypatch):
    retained, contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    different_source = tmp_path / "different-source.mp4"
    different_source.write_bytes(b"different video under same candidate id")
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="exercise-1",
        exercise_name="Test Movement",
        exercise_slug="test-movement",
        candidate={
            "videoId": "video-1",
            "videoPath": str(different_source),
            "retainedSourceInterval": reference,
        },
    )

    with pytest.raises(ValueError, match="prepared candidate source video does not match"):
        bake.materialize_retained_source_interval(
            candidate,
            candidate_workspace=tmp_path / "bake" / candidate.workspace_slug,
            exercise_motion_contract=contract,
        )


def test_retained_interval_self_import_preserves_original_selection_receipt(tmp_path, monkeypatch):
    retained, contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="exercise-1",
        exercise_name="Test Movement",
        exercise_slug="test-movement",
        candidate={
            "videoId": "video-1",
            "videoPath": str((retained / "source" / "source.mp4").resolve()),
            "retainedSourceInterval": reference,
        },
    )
    selection_path = retained / "segment_detection" / "segment_selection.json"
    original_receipt = selection_path.read_bytes()
    original_receipt_sha = _sha(selection_path)

    selected = bake.materialize_retained_source_interval(
        candidate,
        candidate_workspace=retained,
        exercise_motion_contract=contract,
    )

    assert selected == retained / "input" / "selected_segment.mp4"
    assert selection_path.read_bytes() == original_receipt
    assert _sha(selection_path) == original_receipt_sha == reference["segmentSelectionSha256"]


def test_retained_interval_accepts_timezone_equivalent_contract_approval(tmp_path, monkeypatch):
    retained, saved_contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    current_contract = deepcopy(saved_contract)
    current_contract["motionContext"]["exerciseDefinition"]["review"]["approvedAtUtc"] = (
        "2026-10-27T07:15:00Z"
    )

    selected = bake.materialize_retained_source_interval(
        _candidate_for_retained(retained, reference),
        candidate_workspace=tmp_path / "new-bake" / "test-movement",
        exercise_motion_contract=current_contract,
    )

    assert selected.read_bytes() == b"exact approved interval"


def test_retained_interval_rejects_changed_motion_contract_pattern(tmp_path, monkeypatch):
    retained, saved_contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    changed_contract = deepcopy(saved_contract)
    changed_contract["definingAction"] = "Pull the bar to the chest while standing."

    with pytest.raises(ValueError, match="reviewed exercise configuration no longer matches"):
        bake.materialize_retained_source_interval(
            _candidate_for_retained(retained, reference),
            candidate_workspace=tmp_path / "new-bake" / "test-movement",
            exercise_motion_contract=changed_contract,
        )


def test_retained_interval_accepts_only_provenance_header_change(tmp_path, monkeypatch):
    retained, saved_contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    saved_contract["source"] = "llm"
    saved_contract["advisoryText"] = "Source: llm\nComplete: Squat down and return to standing."
    _set_saved_contract(retained, saved_contract, reference)

    current_contract = deepcopy(saved_contract)
    current_contract["source"] = "reused_candidate_contract"
    current_contract["advisoryText"] = (
        "Source: reused candidate contract\nComplete: Squat down and return to standing."
    )

    assert bake.exercise_motion_contract_prompt_sha256(current_contract) != reference[
        "exerciseMotionContractSha256"
    ]
    assert bake.exercise_motion_contract_prompt_identity_matches(saved_contract, current_contract)

    pose_wording = deepcopy(saved_contract)
    pose_wording["validStartState"] = "Standing with the bar across the upper back."
    pose_wording["advisoryText"] = (
        "Source: Standing with the bar across the upper back.\n"
        "Complete: Squat down and return to standing."
    )
    pose_wording_without_header = deepcopy(pose_wording)
    pose_wording_without_header["advisoryText"] = "Complete: Squat down and return to standing."
    assert not bake.exercise_motion_contract_prompt_identity_matches(
        pose_wording,
        pose_wording_without_header,
    )

    selected = bake.materialize_retained_source_interval(
        _candidate_for_retained(retained, reference),
        candidate_workspace=tmp_path / "new-bake" / "test-movement",
        exercise_motion_contract=current_contract,
    )
    assert selected.read_bytes() == b"exact approved interval"


def test_retained_interval_rejects_semantic_advisory_change_after_provenance_header(
    tmp_path,
    monkeypatch,
):
    retained, saved_contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    saved_contract["source"] = "llm"
    saved_contract["advisoryText"] = "Source: llm\nComplete: Squat down and return to standing."
    _set_saved_contract(retained, saved_contract, reference)

    changed_contract = deepcopy(saved_contract)
    changed_contract["source"] = "reused_candidate_contract"
    changed_contract["advisoryText"] = (
        "Source: reused candidate contract\nComplete: Jump and land on one foot."
    )

    assert not bake.exercise_motion_contract_prompt_identity_matches(saved_contract, changed_contract)
    with pytest.raises(ValueError, match="reviewed exercise configuration no longer matches"):
        bake.materialize_retained_source_interval(
            _candidate_for_retained(retained, reference),
            candidate_workspace=tmp_path / "new-bake" / "test-movement",
            exercise_motion_contract=changed_contract,
        )


def test_retained_interval_rejects_saved_contract_receipt_tampering(tmp_path, monkeypatch):
    retained, saved_contract, reference = _retained_fixture(tmp_path)
    _patch_existing_authority(monkeypatch)
    selection_path = retained / "segment_detection" / "segment_selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["exerciseMotionContract"]["definingAction"] = "Tampered approved motion pattern."
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    reference["segmentSelectionSha256"] = _sha(selection_path)

    with pytest.raises(ValueError, match="saved approved exercise configuration receipt changed"):
        bake.materialize_retained_source_interval(
            _candidate_for_retained(retained, reference),
            candidate_workspace=tmp_path / "new-bake" / "test-movement",
            exercise_motion_contract=saved_contract,
        )


def test_retained_structured_evidence_reuses_only_exact_approved_request(tmp_path, monkeypatch):
    from exercise_motion_pkg import source_evidence
    from exercise_motion_pkg.stage_cache import save_stage

    retained, contract, reference = _retained_fixture(tmp_path)
    candidate_workspace = tmp_path / "new-bake" / "test-movement"
    imported = candidate_workspace / "segment_detection" / "retained_source_interval_import.json"
    imported.parent.mkdir(parents=True)
    imported.write_text(json.dumps({
        "sourceWorkspace": str(retained.resolve()),
        "sourceVideoSha256": reference["sourceVideoSha256"],
        "segmentSelectionSha256": reference["segmentSelectionSha256"],
        "selectedSegmentSha256": reference["selectedSegmentSha256"],
        "exerciseMotionContractSha256": reference["exerciseMotionContractSha256"],
    }), encoding="utf-8")
    source = retained / "input" / "selected_segment.mp4"
    monkeypatch.setattr(
        bake,
        "final_output_source_video_window",
        lambda _item: (source, bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0)),
    )

    sheets = []
    for group in ("uniform", "motion"):
        sheet_dir = retained / "review" / group
        sheet_dir.mkdir(parents=True)
        sheet = sheet_dir / "contact_sheet_01.jpg"
        Image.new("RGB", (16, 16), color=(120, 30, 80)).save(sheet)
        sheet_sha = _sha(sheet)
        (sheet_dir / "contact_sheet_evidence.json").write_text(json.dumps({
            "sheets": {sheet.name: {
                "sha256": sheet_sha,
                "frames": [{"number": 1, "timestampSeconds": 0.5}],
            }},
        }), encoding="utf-8")
        sheets.append(sheet)
    frame_inventory = source_evidence.evidence_inventory({
        "uniform": [sheets[0]], "motion": [sheets[1]],
    })
    prompt = "Review this exact retained source interval against the bound exercise contract."
    raw = json.dumps({"observations": []})
    source_review_dir = retained / "source-review-cache" / "retained-approval"
    source_review_dir.mkdir(parents=True)
    (source_review_dir / "source_evidence_prompt.txt").write_text(prompt, encoding="utf-8")
    validation = {
        "reviewStatus": "passed",
        "sourceEvidencePolicyVersion": source_evidence.POLICY_VERSION,
        "sourceIntervalSeconds": [0.0, 2.0],
        "exerciseMotionContract": contract,
        "frameInventory": frame_inventory,
        "uniformContactSheetPaths": [str(sheets[0])],
        "motionContactSheetPaths": [str(sheets[1])],
        "gates": {"structuredEvidence": {"reviewStatus": "passed", "rawResponse": raw}},
    }
    save_stage(source_review_dir / "checkpoint.json", "retained-approval", validation, sheets)
    item = bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Test Movement",
        candidate_title="Retained candidate",
        candidate_workspace=candidate_workspace,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={"retainedSourceInterval": reference},
    )

    reused = bake._retained_structured_source_evidence(
        item,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
        exercise_motion_contract=contract,
        prompt=prompt,
        uniform_sheet_paths=[sheets[0]],
        motion_sheet_paths=[sheets[1]],
        frame_inventory=frame_inventory,
    )

    assert reused == (raw, {"observations": []})

    # Separate retained stages may carry the same approval with different JSON
    # whitespace. That is one judgment, so reuse remains safe and avoids a
    # repeated model question.
    duplicate_dir = retained / "source-review-cache" / "duplicate-approval"
    duplicate_dir.mkdir(parents=True)
    (duplicate_dir / "source_evidence_prompt.txt").write_text(prompt, encoding="utf-8")
    duplicate = json.loads(json.dumps(validation))
    duplicate["gates"]["structuredEvidence"]["rawResponse"] = json.dumps(
        {"observations": []}, indent=2,
    )
    save_stage(duplicate_dir / "checkpoint.json", "duplicate-approval", duplicate, sheets)
    reused_duplicate = bake._retained_structured_source_evidence(
        item,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
        exercise_motion_contract=contract,
        prompt=prompt,
        uniform_sheet_paths=[sheets[0]],
        motion_sheet_paths=[sheets[1]],
        frame_inventory=frame_inventory,
    )
    assert reused_duplicate is not None
    assert json.loads(reused_duplicate[0]) == {"observations": []}

    # A corrupted duplicate is incomplete and cannot poison the intact approval.
    malformed_dir = retained / "source-review-cache" / "malformed-approval"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "source_evidence_prompt.txt").write_text(prompt, encoding="utf-8")
    malformed = json.loads(json.dumps(validation))
    malformed["gates"]["structuredEvidence"]["rawResponse"] = "not json"
    save_stage(malformed_dir / "checkpoint.json", "malformed-approval", malformed, sheets)
    assert bake._retained_structured_source_evidence(
        item,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
        exercise_motion_contract=contract,
        prompt=prompt,
        uniform_sheet_paths=[sheets[0]],
        motion_sheet_paths=[sheets[1]],
        frame_inventory=frame_inventory,
    ) is not None

    # Different parsed judgments remain ambiguous and are not reused.
    conflict_dir = retained / "source-review-cache" / "conflicting-approval"
    conflict_dir.mkdir(parents=True)
    (conflict_dir / "source_evidence_prompt.txt").write_text(prompt, encoding="utf-8")
    conflicting = json.loads(json.dumps(validation))
    conflicting["gates"]["structuredEvidence"]["rawResponse"] = json.dumps({"observations": [{"verdict": "unsupported"}]})
    save_stage(conflict_dir / "checkpoint.json", "conflicting-approval", conflicting, sheets)
    assert bake._retained_structured_source_evidence(
        item,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
        exercise_motion_contract=contract,
        prompt=prompt,
        uniform_sheet_paths=[sheets[0]],
        motion_sheet_paths=[sheets[1]],
        frame_inventory=frame_inventory,
    ) is None
    assert bake._retained_structured_source_evidence(
        item,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
        exercise_motion_contract=contract,
        prompt=prompt + " changed",
        uniform_sheet_paths=[sheets[0]],
        motion_sheet_paths=[sheets[1]],
        frame_inventory=frame_inventory,
    ) is None


def test_two_scale_review_reaggregates_retained_source_evidence_without_model_call(tmp_path, monkeypatch):
    from exercise_motion_pkg import source_evidence
    from exercise_motion_pkg.stage_cache import save_stage

    retained, contract, reference = _retained_fixture(tmp_path)
    contract.update({
        "status": "generated",
        "completionMode": "representative_cycle",
        "actionDefinitionStatus": "defined",
        "definingAction": "Move through the test movement.",
    })
    selection_path = retained / "segment_detection" / "segment_selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["exerciseMotionContract"] = contract
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    reference["segmentSelectionSha256"] = _sha(selection_path)
    reference["exerciseMotionContractSha256"] = bake.exercise_motion_contract_prompt_sha256(contract)
    reference["selectedSegmentSha256"] = _sha(retained / "input" / "selected_segment.mp4")
    source = retained / "input" / "selected_segment.mp4"
    candidate_workspace = tmp_path / "new-bake" / "test-movement"
    imported_path = candidate_workspace / "segment_detection" / "retained_source_interval_import.json"
    imported_path.parent.mkdir(parents=True)
    imported_path.write_text(json.dumps({
        "sourceWorkspace": str(retained.resolve()),
        "sourceVideoSha256": reference["sourceVideoSha256"],
        "segmentSelectionSha256": reference["segmentSelectionSha256"],
        "selectedSegmentSha256": reference["selectedSegmentSha256"],
        "exerciseMotionContractSha256": reference["exerciseMotionContractSha256"],
    }), encoding="utf-8")
    monkeypatch.setattr(
        bake,
        "final_output_source_video_window",
        lambda _item: (source, bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0)),
    )

    sheets = []
    for group in ("uniform", "motion"):
        sheet_dir = retained / "review" / group
        sheet_dir.mkdir(parents=True)
        sheet = sheet_dir / "contact_sheet_01.jpg"
        Image.new("RGB", (32, 16), color=(120, 30, 80)).save(sheet)
        sheet_sha = _sha(sheet)
        (sheet_dir / "contact_sheet_evidence.json").write_text(json.dumps({
            "sheets": {sheet.name: {
                "sha256": sheet_sha,
                "frames": [
                    {"number": 1, "timestampSeconds": 0.5},
                    {"number": 2, "timestampSeconds": 1.5},
                ],
            }},
        }), encoding="utf-8")
        sheets.append(sheet)
    frame_inventory = source_evidence.evidence_inventory({
        "uniform": [sheets[0]], "motion": [sheets[1]],
    })
    requirements = source_evidence.source_requirements(contract, [])
    uniform_ids = [frame["id"] for frame in frame_inventory if frame["sampling"] == "uniform"]
    action_ids = ["uniform:1", "uniform:2"]
    observations = []
    for requirement in requirements:
        ids = uniform_ids if requirement["id"] == "clean_interval" else action_ids
        observations.append({
            "requirementId": requirement["id"],
            "verdict": "supported",
            "evidenceFrameIds": ids,
        })
    raw = json.dumps({"observations": observations})
    prompt = source_evidence.evidence_prompt(
        requirements,
        frame_inventory,
        allow_cyclic_phase_order=source_evidence.permits_cyclic_phase_order(contract),
        cycle_choices=None,
        semantic_labels=True,
    )
    source_review_dir = retained / "source-review-cache" / "retained-approval"
    source_review_dir.mkdir(parents=True)
    (source_review_dir / "source_evidence_prompt.txt").write_text(prompt, encoding="utf-8")
    validation = {
        "reviewStatus": "passed",
        "sourceEvidencePolicyVersion": source_evidence.POLICY_VERSION,
        "sourceIntervalSeconds": [0.0, 2.0],
        "exerciseMotionContract": contract,
        "frameInventory": frame_inventory,
        "uniformContactSheetPaths": [str(sheets[0])],
        "motionContactSheetPaths": [str(sheets[1])],
        "gates": {"structuredEvidence": {"reviewStatus": "passed", "rawResponse": raw}},
    }
    save_stage(source_review_dir / "checkpoint.json", "retained-approval", validation, sheets)
    item = bake.ReviewItem(
        exercise_index=0, candidate_rank=0, loop_index=0,
        exercise_name="Test Movement", candidate_title="Retained candidate",
        candidate_workspace=candidate_workspace, preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json", review_video_path=tmp_path / "review.webm",
        duration_sec=2.0, loop_start_seconds=0.0, loop_end_seconds=2.0,
        candidate={"retainedSourceInterval": reference},
    )
    monkeypatch.setattr(bake, "final_output_motion_contact_sheets", lambda *_args, **_kwargs: [sheets[1]])
    monkeypatch.setattr(
        bake,
        "resolve_two_scale_exercise_motion_contract",
        lambda *_args, **_kwargs: (contract, None, None),
    )
    model_calls = []

    result = bake._validate_two_scale_source_uncached(
        item,
        uniform_sheet_paths=[sheets[0]],
        output_dir=tmp_path / "new-review",
        caption_images=lambda **kwargs: model_calls.append(kwargs) or pytest.fail("model review unexpectedly ran"),
        exercise_motion_contract=contract,
        source_interval=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.0),
    )

    assert result["reviewStatus"] == "passed"
    assert result["sourceEvidenceReuse"]["reparsedUnderCurrentPolicy"] is True
    assert source_evidence.aggregate_evidence(
        result["gates"]["structuredEvidence"]["response"], requirements, frame_inventory,
    )["reviewStatus"] == "passed"
    assert model_calls == []

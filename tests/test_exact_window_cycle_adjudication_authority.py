import hashlib
import json

import pytest
from types import SimpleNamespace

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import source_review_authority as authority
from exercise_motion_pkg.stage_cache import load_stage, save_stage
from exercise_motion_pkg.source_evidence import POLICY_VERSION
from exercise_motion_pkg.segment_detection import DetectionWindow


def _contract():
    return {
        "definingAction": "Stand, descend into a squat, then return to standing.",
        "requiredPhases": ["Descend with hip and knee flexion", "Rise back to standing"],
        "requiredPhasesAuthority": "structured_definition",
        "variantQualifiers": ["Barbell back squat performed from a rack."],
        "completionMode": "return_to_start",
        "movementType": "repetition",
        "source": "bake_and_rank_llm",
        "contractPolicyVersion": 39,
    }


def _review(key, checkpoint, contract, authority_binding, *, phase_passed=True, cycle_sequence=None):
    frames = [
        {"id": f"uniform:{index + 1}", "sampling": "uniform", "timestampSeconds": index * 3.0 / 23}
        for index in range(24)
    ]
    cycle = {
        "choiceId": "verified_return_cycle",
        "sequence": cycle_sequence or ["high", "low", "high"],
        "roleFrameIds": {"start": "uniform:1", "excursion": "uniform:10", "return": "uniform:24"},
        "roleTimes": {"start": 0.0, "excursion": 9 * 3.0 / 23, "return": 3.0},
        "spanChoices": [
            {"spanChoiceId": "cycle_span_1", "frameIds": ["uniform:1", "uniform:10"]},
            {"spanChoiceId": "cycle_span_2", "frameIds": ["uniform:10", "uniform:24"]},
        ],
    }
    samples = [frame["id"] for frame in frames]
    observations = [
        {"requirementId": "action", "verdict": "supported", "evidenceFrameIds": samples[0:1] + samples[9:10] + samples[23:24]},
        {"requirementId": "phase_1", "verdict": "supported", "evidenceFrameIds": [samples[0], samples[9]]},
        {"requirementId": "phase_2", "verdict": "supported", "evidenceFrameIds": [samples[9], samples[23]]},
        {"requirementId": "variant_1", "verdict": "supported", "evidenceFrameIds": [samples[0]]},
        {"requirementId": "equipment_1", "verdict": "supported", "evidenceFrameIds": [samples[0]], "observedObjectCount": 1},
        {"requirementId": "equipment_2", "verdict": "supported", "evidenceFrameIds": [samples[0]], "observedObjectCount": 1},
        {"requirementId": "completion", "verdict": "supported", "evidenceFrameIds": [samples[0], samples[9], samples[23]]},
        {"requirementId": "clean_interval", "verdict": "supported", "evidenceFrameIds": samples},
    ]
    return {
        "passed": True,
        "reviewStatus": "passed",
        "missingEvidenceReasons": [],
        "sourceEvidencePolicyVersion": POLICY_VERSION,
        "sourceAuthorityBinding": authority_binding,
        "sourceIntervalSeconds": authority_binding.get("sourceIntervalSeconds", [0.0, 3.0]),
        "exerciseMotionContract": contract,
        "sourceReviewCache": {"key": key, "checkpoint": str(checkpoint), "cacheHit": False},
        "sourceCycleEvidenceChoices": cycle,
        "frameInventory": frames,
        "gates": {
            "structuredEvidence": {"passed": True, "response": {"observations": observations}},
            "deterministicPoseEndpoints": {
                "passed": phase_passed,
                "returnCycleCorroborated": phase_passed,
                "returnEndpointConsistency": {"passed": phase_passed},
            },
            "actionPoseEvidence": {"passed": True},
        },
    }


def test_phase_authority_identity_ignores_cache_and_promotion_metadata_but_binds_source_bytes():
    current = {
        "passed": True,
        "validationPolicyVersion": 62,
        "sourceVideoSha256": "a" * 64,
        "sourcePoseReferenceSha256": "b" * 64,
        "sourceVideoPath": "current/selected.mp4",
        "sourcePoseReferencePath": "current/pose.json",
        "cacheStatus": "reused",
        "sourcePoseReferencePromoted": True,
        "sampleFrameIndices": [0, 12, 23],
    }
    retained = {
        **current,
        "sourceVideoPath": "retained/selected.mp4",
        "sourcePoseReferencePath": "retained/pose.json",
        "cacheStatus": "computed",
    }
    retained.pop("sourcePoseReferencePromoted")

    assert bake.exact_phase_authority_sha256(current) == bake.exact_phase_authority_sha256(retained)
    assert bake.exact_phase_authority_sha256({
        **current, "sourcePoseReferenceSha256": "c" * 64,
    }) != bake.exact_phase_authority_sha256(current)
    assert bake.exact_phase_authority_sha256({
        **current, "sourceVideoSha256": "d" * 64,
    }) != bake.exact_phase_authority_sha256(current)
    assert bake.exact_phase_authority_sha256({
        **current, "sampleFrameIndices": [0, 11, 23],
    }) != bake.exact_phase_authority_sha256(current)


def _bound_stage(tmp_path, *, phase_passed=True, cycle_sequence=None):
    contract = _contract()
    key = "a" * 64
    checkpoint = tmp_path / "cache" / key / "checkpoint.json"
    image = tmp_path / "uniform.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"reviewed contact sheet")
    binding = {
        "candidateId": "A",
        "sourceVideoSha256": "b" * 64,
        "sourceIntervalSeconds": [0.0, 3.0],
        "candidateWindowSourceSeconds": [0.0, 3.0],
        "contractIdentitySha256": "c" * 64,
        "contractPolicyVersion": 39,
        "exactPhaseReceiptSha256": "d" * 64,
        "exactPhasePolicyVersion": 62,
        "exactPhasePassed": phase_passed,
        "sourceEvidencePolicyVersion": POLICY_VERSION,
    }
    stage = _review(
        key, checkpoint, contract, binding,
        phase_passed=phase_passed, cycle_sequence=cycle_sequence,
    )
    save_stage(checkpoint, key, stage, [image])
    loaded = load_stage(checkpoint, key)
    digest = hashlib.sha256(json.dumps(loaded, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()
    binding["sourceReviewCacheKey"] = key
    receipt = {"binding": dict(binding), "stagePayloadSha256": digest}
    equipment = [
        {"name": "Barbell", "normalizedName": "barbell", "role": "active_implement", "minimumObjectCount": 1},
        {"name": "Squat Rack", "normalizedName": "squat rack", "role": "unknown_required_equipment", "minimumObjectCount": 1},
    ]
    return receipt, binding, checkpoint, contract, equipment, key


def test_current_exact_cycle_receipt_passes_full_contract_review(tmp_path):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": [
            "source_cut_model_rejected", "source_cut_partial_movement",
            "source_cut_finish_boundary_bad", "source_cut_contract_phase_timing_unresolved",
            "source_cut_contract_phase_sequence_mismatch",
        ],
    }
    result = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=binding,
        current_scorecard=scorecard,
        exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is True
    assert result["authority"] == "exact_window_cycle_adjudication"
    assert result["supportedRequirementIds"] == [
        "action", "phase_1", "phase_2", "variant_1", "equipment_1", "equipment_2", "completion", "clean_interval",
    ]


@pytest.mark.parametrize("field,value", [
    ("candidateId", "C"),
    ("sourceVideoSha256", "e" * 64),
    ("sourceIntervalSeconds", [0.46, 3.0]),
    ("contractIdentitySha256", "f" * 64),
    ("exactPhaseReceiptSha256", "1" * 64),
    ("exactPhasePolicyVersion", 61),
])
def test_changed_current_binding_fails_closed(tmp_path, field, value):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": [
            "source_cut_partial_movement", "source_cut_contract_phase_sequence_mismatch",
        ],
    }
    expected = {**binding, field: value}
    result = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=expected,
        current_scorecard=scorecard,
        exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is False


def test_phase_failure_and_noncycle_evidence_cannot_authorize(tmp_path):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path, phase_passed=False)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": ["source_cut_partial_movement", "source_cut_contract_phase_sequence_mismatch"],
    }
    result = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=binding,
        current_scorecard=scorecard,
        exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is False

    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(
        tmp_path / "bad-sequence", cycle_sequence=["low", "high", "high"],
    )
    result = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=binding,
        current_scorecard=scorecard,
        exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is False


def test_hard_scorecard_objections_remain_hard(tmp_path):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": ["source_cut_required_equipment_not_observed"],
    }
    result = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=binding,
        current_scorecard=scorecard, exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is False


def test_canonical_stage_key_and_digest_are_required(tmp_path):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": ["source_cut_partial_movement", "source_cut_contract_phase_sequence_mismatch"],
    }
    wrong_key = authority.exact_window_cycle_adjudication_clearance(
        receipt, checkpoint=checkpoint, current_cache_key="b" * 64,
        expected_binding=binding, current_scorecard=scorecard,
        exercise_motion_contract=contract, equipment_requirements=equipment,
    )
    assert wrong_key["passed"] is False
    wrong_digest = {**receipt, "stagePayloadSha256": "e" * 64}
    changed_stage = authority.exact_window_cycle_adjudication_clearance(
        wrong_digest, checkpoint=checkpoint, current_cache_key=key,
        expected_binding=binding, current_scorecard=scorecard,
        exercise_motion_contract=contract, equipment_requirements=equipment,
    )
    assert changed_stage["passed"] is False


def test_same_duration_transplanted_stage_rejects_other_source_and_window(tmp_path):
    receipt, binding, checkpoint, contract, equipment, key = _bound_stage(tmp_path)
    scorecard = {
        "id": "A", "passed": False, "identityMatch": "match", "confidence": 0.95,
        "rejectionReasons": [
            "source_cut_partial_movement", "source_cut_contract_phase_sequence_mismatch",
        ],
    }
    rebound = {
        **binding,
        "sourceVideoSha256": "e" * 64,
        "candidateWindowSourceSeconds": [4.0, 7.0],
    }
    transplanted_receipt = {**receipt, "binding": rebound}
    result = authority.exact_window_cycle_adjudication_clearance(
        transplanted_receipt, checkpoint=checkpoint, current_cache_key=key, expected_binding=rebound,
        current_scorecard=scorecard,
        exercise_motion_contract=contract,
        equipment_requirements=equipment,
    )
    assert result["passed"] is False
    assert result["reason"] == "exact_cycle_adjudication_stage_authority_binding_mismatch"


def test_production_reader_rejects_rebound_same_duration_stage(tmp_path, monkeypatch):
    workspace = tmp_path / "candidate"
    segment_dir = workspace / "segment_detection"
    segment_dir.mkdir(parents=True)
    selected = workspace / "input" / "selected_segment.mp4"
    selected.parent.mkdir()
    selected.write_bytes(b"original A clip")
    sha = bake.file_sha256(selected)
    contract = {**_contract(), "exerciseName": "Barbell Back Squat"}
    phase = {
        "required": True, "passed": True, "validationPolicyVersion": 62,
        "sourceVideoPath": str(selected.resolve()), "sourceVideoSha256": sha,
    }
    image_dir = workspace / "review"
    image_dir.mkdir()
    sheet = image_dir / "contact_sheet.jpg"
    first = image_dir / "frame_first.jpg"
    last = image_dir / "frame_last.jpg"
    for path in (sheet, first, last):
        path.write_bytes(path.name.encode())
    candidate_obj = bake.SourceCutCandidate(
        "A", DetectionWindow(0, 0.0, 3.05), [sheet], sample_frame_paths=[first, last],
    )
    candidate = bake.source_cut_candidates_payload([candidate_obj])[0]
    frame_inputs = bake.source_cut_review_frame_evidence([candidate_obj], source_frame_count=31)
    scorecard = {
        "id": "A", "passed": False, "confidence": 0.95, "identityMatch": "match",
        "rejectionReasons": [
            "source_cut_partial_movement", "source_cut_contract_phase_sequence_mismatch",
        ],
    }
    cache_key = "a" * 64
    equipment = [
        {"name": "Barbell", "normalizedName": "barbell", "role": "active_implement", "minimumObjectCount": 1},
        {"name": "Squat Rack", "normalizedName": "squat rack", "role": "unknown_required_equipment", "minimumObjectCount": 1},
    ]
    checkpoint = workspace / "source-review-cache" / cache_key / "checkpoint.json"
    authority_binding = {
        "candidateId": "A", "sourceVideoSha256": sha,
        "sourceIntervalSeconds": [0.0, 3.05],
        "candidateWindowSourceSeconds": [0.0, 3.05],
        "contractIdentitySha256": bake.exercise_motion_contract_prompt_sha256(contract),
        "contractPolicyVersion": 39,
        "exactPhaseReceiptSha256": bake.exact_phase_authority_sha256(phase),
        "exactPhasePolicyVersion": 62, "exactPhasePassed": True,
        "sourceEvidencePolicyVersion": POLICY_VERSION,
        "sourceReferenceReviewContextSha256": None,
    }
    stage = _review(cache_key, checkpoint, contract, authority_binding)
    save_stage(checkpoint, cache_key, stage, [sheet])
    loaded = load_stage(checkpoint, cache_key)
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    receipt = {
        "binding": {**authority_binding, "sourceReviewCacheKey": cache_key},
        "stagePayloadSha256": hashlib.sha256(canonical(loaded).encode()).hexdigest(),
        "checkpoint": str(checkpoint),
    }
    attempt = {
        "candidateId": "A", "startSeconds": 0.0, "endSeconds": 3.05,
        "passed": True, "candidateVideoSha256": sha, "validation": phase,
        "materializedVideoPath": str(selected), "exactWindowCycleAdjudication": receipt,
    }
    payload = {
        "exerciseMotionContract": contract,
        "sourceCutReviewVideoPath": str(selected.resolve()),
        "sourceCutReviewVideoSha256": sha, "sourceCutReviewVideoSha256After": sha,
        "sourceCutOriginalVideoPath": str(selected.resolve()),
        "sourceCutOriginalVideoSha256": sha, "sourceCutOriginalVideoSha256After": sha,
        "sourceCutCandidates": [candidate],
        "sourceCutReviewFrameInputs": frame_inputs,
        "sourceCutReviewFrameInputsAfter": frame_inputs,
        "sourceCutScorecardCandidates": [scorecard], "selectedCandidateId": "A",
        "selectedScorecard": scorecard,
        "sourceCutDeterministicConfirmationAttempts": [attempt],
        "sourceCutExactWindowCycleAdjudication": receipt,
    }
    ranking = bake.LoopRanking(0.0, [], payload=payload)
    manifest = {
        "sourceSelectionPolicyVersion": bake.SOURCE_SELECTION_POLICY_VERSION,
        "preReconstructionSourceValidationEnabled": True,
        "sourcePrepReason": "pre_reconstruction_source_window_choice",
        "exerciseName": contract["exerciseName"], "exerciseMotionContract": contract,
        "exerciseMotionContractEnabled": False,
        "sourceVideoPath": str(selected), "detectionSourceVideoPath": str(selected),
        "selectedSegmentPath": str(selected), "selectedSegmentSha256": sha,
        "selectedSpan": {"startSeconds": 0.0, "endSeconds": 3.05},
        "exactSourcePhaseValidation": phase,
        "sourceCutRanking": bake.ranking_to_manifest(ranking),
    }
    manifest_path = segment_dir / "segment_selection.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(bake, "cached_source_selection_matches_validation_mode", lambda *a, **k: True)
    monkeypatch.setattr(bake, "source_cut_review_frame_inputs_are_current", lambda *a, **k: True)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda *_a, **_k: SimpleNamespace(
        duration_seconds=3.0666666667, frame_count=92, fps=30.0,
    ))
    monkeypatch.setattr(bake, "two_scale_equipment_role_requirements", lambda *_a, **_k: equipment)
    authority_results = []
    original_clearance = authority.exact_window_cycle_adjudication_clearance
    def capture_clearance(*args, **kwargs):
        result = original_clearance(*args, **kwargs)
        authority_results.append(result)
        return result
    monkeypatch.setattr(authority, "exact_window_cycle_adjudication_clearance", capture_clearance)

    accepted = bake.source_selection_clearance_for_workspace(
        workspace, required=True, expected_exercise_name=contract["exerciseName"],
        expected_contract=contract,
    )
    assert accepted["status"] == "cleared", (accepted.get("reason"), authority_results)
    assert accepted["authority"] == "exact_window_cycle_adjudication"

    receipt["binding"]["sourceIntervalSeconds"] = [0.0, 3.0]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    mismatched_interval = bake.source_selection_clearance_for_workspace(
        workspace, required=True, expected_exercise_name=contract["exerciseName"],
        expected_contract=contract,
    )
    assert mismatched_interval["status"] == "needs_source_review"
    assert mismatched_interval["reason"] == "selected_interval_lacks_current_semantic_clearance"
    receipt["binding"]["sourceIntervalSeconds"] = [0.0, 3.05]

    selected.write_bytes(b"unrelated C clip")
    changed_sha = bake.file_sha256(selected)
    manifest["selectedSegmentSha256"] = changed_sha
    manifest["selectedSpan"] = {"startSeconds": 4.0, "endSeconds": 7.0}
    phase = {**phase, "sourceVideoSha256": changed_sha}
    manifest["exactSourcePhaseValidation"] = phase
    payload["sourceCutReviewVideoSha256"] = changed_sha
    payload["sourceCutReviewVideoSha256After"] = changed_sha
    payload["sourceCutOriginalVideoSha256"] = changed_sha
    payload["sourceCutOriginalVideoSha256After"] = changed_sha
    candidate.update(startSeconds=4.0, endSeconds=7.0)
    attempt.update(startSeconds=4.0, endSeconds=7.0, candidateVideoSha256=changed_sha, validation=phase)
    rebound = {
        **authority_binding, "sourceVideoSha256": changed_sha,
        "sourceIntervalSeconds": [0.0, 3.0],
        "candidateWindowSourceSeconds": [4.0, 7.0],
        "exactPhaseReceiptSha256": bake.exact_phase_authority_sha256(phase),
    }
    receipt["binding"] = {**rebound, "sourceReviewCacheKey": cache_key}
    attempt["exactWindowCycleAdjudication"] = receipt
    payload["sourceCutExactWindowCycleAdjudication"] = receipt
    manifest["sourceCutRanking"] = bake.ranking_to_manifest(ranking)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rejected = bake.source_selection_clearance_for_workspace(
        workspace, required=True, expected_exercise_name=contract["exerciseName"],
        expected_contract=contract,
    )
    assert rejected["status"] == "needs_source_review"


def test_current_canonical_legacy_stage_is_migrated_without_review_call(tmp_path, monkeypatch):
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"legacy source A")
    workspace = tmp_path / "candidate_workspace"
    workspace.mkdir()
    sheet = tmp_path / "review" / "contact_sheet.jpg"
    sheet.parent.mkdir()
    sheet.write_bytes(b"current sheet")
    (sheet.parent / "contact_sheet_evidence.json").write_text("{}", encoding="utf-8")
    contract = _contract()
    phase = {
        "required": True, "passed": True, "validationPolicyVersion": 62,
        "sourceVideoPath": str(video.resolve()), "sourceVideoSha256": bake.file_sha256(video),
    }
    candidate = {
        "sourceCandidateId": "A",
        "sourceCandidateWindowSourceSeconds": [10.0, 13.0],
    }
    item = bake.ReviewItem(
        exercise_index=0, candidate_rank=0, loop_index=-1,
        exercise_name="Back Squat", candidate_title="", candidate_workspace=workspace,
        preview_html_path=workspace / "preview.html", skeleton_path=workspace / "skeleton.json",
        review_video_path=video, duration_sec=3.0, loop_start_seconds=0.0, loop_end_seconds=3.0,
        candidate=candidate, source_review_video_path=video,
    )

    class CaptionClient:
        settings = SimpleNamespace(model="fixture")

        def __call__(self, **_kwargs):
            raise AssertionError("A cached source review must not call the reviewer.")

    caption = CaptionClient()
    monkeypatch.setattr(
        bake, "final_output_source_video_window",
        lambda _item: (video, DetectionWindow(0, 0.0, 3.0)),
    )
    monkeypatch.setattr(bake, "source_review_model_identity", lambda _settings: {"model": "fixture"})
    calls = []

    def fake_uncached(_item, *, uniform_sheet_paths, exercise_motion_contract, **_kwargs):
        calls.append("review")
        return {
            "passed": True, "reviewStatus": "passed", "missingEvidenceReasons": [], "error": None,
            "sourceEvidencePolicyVersion": POLICY_VERSION,
            "sourceIntervalSeconds": [0.0, 3.0], "exerciseMotionContract": exercise_motion_contract,
            "uniformContactSheetPaths": [str(path) for path in uniform_sheet_paths],
            "motionContactSheetPaths": [], "sourceCycleRoleImagePaths": [],
            "sourceActionReviewImagePaths": [],
            "gates": {
                "structuredEvidence": {"passed": True}, "actionPoseEvidence": {"passed": True},
                "deterministicPoseEndpoints": {
                    "passed": True, "returnCycleCorroborated": True,
                    "returnEndpointConsistency": {"passed": True},
                },
            },
        }

    monkeypatch.setattr(bake, "_validate_two_scale_source_uncached", fake_uncached)
    legacy = bake.validate_two_scale_source_with_caption_images(
        item, uniform_sheet_paths=[sheet], output_dir=tmp_path / "cache",
        caption_images=caption, exercise_motion_contract=contract,
        source_pose_endpoint_features={"returnCycleCorroborated": True},
        source_phase_metrics=phase,
    )
    assert legacy["sourceReviewCache"]["cacheHit"] is False
    assert len(calls) == 1
    cache_only_hit = bake.validate_two_scale_source_with_caption_images(
        item, uniform_sheet_paths=[sheet], output_dir=tmp_path / "cache",
        caption_images=caption, exercise_motion_contract=contract,
        source_pose_endpoint_features={"returnCycleCorroborated": True},
        source_phase_metrics=phase, cache_only=True,
    )
    assert cache_only_hit["sourceReviewCache"]["cacheHit"] is True
    assert cache_only_hit["sourceReviewCache"]["key"] == legacy["sourceReviewCache"]["key"]
    assert len(calls) == 1

    binding = {
        "candidateId": "A", "sourceVideoSha256": bake.file_sha256(video),
        "sourceIntervalSeconds": [0.0, 3.0],
        "candidateWindowSourceSeconds": [10.0, 13.0],
        "contractIdentitySha256": bake.exercise_motion_contract_prompt_sha256(contract),
        "contractPolicyVersion": 39,
        "exactPhaseReceiptSha256": bake.exact_phase_authority_sha256(phase),
        "exactPhasePolicyVersion": 62, "exactPhasePassed": True,
        "sourceEvidencePolicyVersion": POLICY_VERSION,
    }
    migrated = bake.validate_two_scale_source_with_caption_images(
        item, uniform_sheet_paths=[sheet], output_dir=tmp_path / "cache",
        caption_images=caption, exercise_motion_contract=contract,
        source_pose_endpoint_features={"returnCycleCorroborated": True},
        source_phase_metrics=phase, source_authority_binding=binding,
    )
    assert len(calls) == 1
    assert migrated["sourceAuthorityBinding"] == binding
    assert migrated["sourceReviewCache"]["derivedFromLegacyStage"] is True
    assert migrated["sourceReviewCache"]["legacyStageKey"] == legacy["sourceReviewCache"]["key"]

    video.write_bytes(b"same duration unrelated source C")
    phase = {**phase, "sourceVideoSha256": bake.file_sha256(video)}
    wrong_binding = {
        **binding, "sourceVideoSha256": bake.file_sha256(video),
        "exactPhaseReceiptSha256": bake.exact_phase_authority_sha256(phase),
    }

    def reject_reuse(_item, **_kwargs):
        raise AssertionError("A nonmatching legacy stage must not be reused.")

    monkeypatch.setattr(bake, "_validate_two_scale_source_uncached", reject_reuse)
    with pytest.raises(AssertionError, match="nonmatching legacy stage"):
        bake.validate_two_scale_source_with_caption_images(
            item, uniform_sheet_paths=[sheet], output_dir=tmp_path / "cache",
            caption_images=caption, exercise_motion_contract=contract,
            source_pose_endpoint_features={"returnCycleCorroborated": True},
            source_phase_metrics=phase, source_authority_binding=wrong_binding,
        )


def test_selector_rejects_phase_failed_c_then_accepts_bound_cycle_review_a(tmp_path, monkeypatch):
    contract = _contract()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"retained source")
    source_review_workspace = tmp_path / "candidate_workspace"
    source_review_workspace.mkdir()
    sheet = tmp_path / "uniform.jpg"
    sheet.write_bytes(b"bound review image")
    candidate_c = {"candidateId": "C", "startSeconds": 0.4, "endSeconds": 3.0}
    candidate_a = {"candidateId": "A", "startSeconds": 0.0, "endSeconds": 3.0}
    ranking = bake.LoopRanking(0.98, [], payload={
        "selectedCandidateId": "C",
        "sourceCutCandidates": [candidate_c, candidate_a],
        "sourceCutScorecardCandidates": [
            {"id": "C", "passed": True, "rejectionReasons": [], "requiredEquipment": "none"},
            {"id": "A", "passed": False, "rejectionReasons": ["source_cut_cycle_boundary_only"], "requiredEquipment": "none"},
        ],
    })
    cache_key = "a" * 64
    candidate_video = tmp_path / "exact-a.mp4"
    candidate_video.write_bytes(b"materialized A")
    phase_a = {
        "required": True, "passed": True, "validationPolicyVersion": 62,
        "sourceVideoSha256": bake.file_sha256(candidate_video),
    }
    binding = {
        "candidateId": "A", "sourceVideoSha256": bake.file_sha256(candidate_video),
        "sourceIntervalSeconds": [0.0, 3.0],
        "candidateWindowSourceSeconds": [0.0, 3.0],
        "contractIdentitySha256": bake.exercise_motion_contract_prompt_sha256(contract),
        "contractPolicyVersion": 39,
        "exactPhaseReceiptSha256": bake.exact_phase_authority_sha256(phase_a),
        "exactPhasePolicyVersion": 62, "exactPhasePassed": True,
        "sourceEvidencePolicyVersion": POLICY_VERSION,
    }
    checkpoint = source_review_workspace / "source-review-cache" / cache_key / "checkpoint.json"
    stage = _review(cache_key, checkpoint, contract, binding)
    save_stage(checkpoint, cache_key, stage, [sheet])
    reviewed: list[str] = []

    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda *_args: SimpleNamespace(fps=30.0, frame_count=93, duration_seconds=3.1))
    monkeypatch.setattr(bake, "source_cut_deterministic_confirmation_candidates", lambda _ranking: [candidate_c, candidate_a])
    monkeypatch.setattr(bake, "source_cut_confirmation_candidate_is_eligible", lambda _candidate: True)
    monkeypatch.setattr(bake, "source_cut_child_timing_coverage", lambda *_args: {"eligible": True})
    monkeypatch.setattr(bake, "materialize_source_cut_candidate_for_exact_validation", lambda *, candidate, **_kwargs: (candidate_video if candidate["candidateId"] == "A" else tmp_path / "exact-c.mp4", "fixture"))
    (tmp_path / "exact-c.mp4").write_bytes(b"materialized C")
    monkeypatch.setattr(
        bake, "validate_exact_source_with_cached_gpu_handoff",
        lambda **kwargs: phase_a if kwargs["source_video_path"].name == "exact-a.mp4" else {
            "required": True, "passed": False,
            "reason": "source_pose_one_way_partial_repetition_phase",
        },
    )
    monkeypatch.setattr(bake, "exact_pose_single_cycle_refinement_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bake, "source_cut_return_phase_expansion_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bake, "source_cut_endpoint_contract_trim_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bake, "source_cut_scorecard_rejections_are_cycle_boundary_only", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bake, "confirm_pre_reconstruction_named_equipment", lambda **_kwargs: {"passed": True})
    verified_bindings = []

    def accept_bound_review(receipt, **_kwargs):
        verified_bindings.append(receipt["binding"])
        return {"passed": True, "authority": "exact_window_cycle_adjudication"}

    monkeypatch.setattr(authority, "exact_window_cycle_adjudication_clearance", accept_bound_review)

    def exact_review(candidate, _video, _phase):
        reviewed.append(candidate["candidateId"])
        return {"sourceReviewCache": {"checkpoint": str(checkpoint), "key": cache_key}}

    confirmed, _ = bake.select_exact_pose_confirmed_source_cut(
        ranking, detection_source_video_path=source, exercise_name="Barbell Back Squat",
        exercise_motion_contract=contract, caption_images=lambda **_kwargs: "{}",
        output_dir=tmp_path / "selection", exact_cycle_semantic_review=exact_review,
        source_review_workspace=source_review_workspace,
    )

    assert [attempt["candidateId"] for attempt in confirmed.payload["sourceCutDeterministicConfirmationAttempts"]] == ["C", "A"]
    assert confirmed.payload["sourceCutDeterministicConfirmationAttempts"][0]["passed"] is False
    assert confirmed.payload.get("selectedCandidateId") == "A", confirmed.payload["sourceCutDeterministicConfirmationAttempts"]
    assert reviewed == ["A"]
    assert verified_bindings[0]["candidateId"] == "A"
    assert verified_bindings[0]["candidateWindowSourceSeconds"] == [0.0, 3.0]
    assert confirmed.payload["sourceCutScorecardCandidates"] == ranking.payload["sourceCutScorecardCandidates"]

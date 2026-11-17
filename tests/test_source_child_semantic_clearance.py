"""Model-free, portable checks for retained child semantic clearance.

The portable cases synthesise a receipt and stub only the raw-response parser,
so the consumer's binding, reparse-equality, prompt and sample-coverage logic is
exercised without a model, GPU, or external scratch artifact. The optional
host-retained case skips when the review workspace is absent.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import exercise_motion_pkg.bake_and_rank as br

REPO = Path(__file__).resolve().parents[1]
HOST_WORKSPACE = (
    REPO
    / ".scratch"
    / "prepared-definition-authority-v36"
    / "replay"
    / "workspace"
    / "dumbbell-woodchopper-001-rf-2l8z40dg"
)
CHILD_ID = "D-RETN-1"
EXERCISE_NAME = "Dumbbell Woodchopper"
TIMESTAMPS = [0.0, 0.82265, 1.52778, 1.88035, 2.35043, 2.703]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    start, end = 0.0, 2.703
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    segment = tmp_path / "candidate" / "candidate.mp4"
    segment.parent.mkdir(parents=True)
    segment.write_bytes(b"selected segment")
    frame = tmp_path / "sheet.jpg"
    frame.write_bytes(b"contact sheet")
    frame_sha = _sha256_bytes(frame.read_bytes())
    contract = {"definingAction": "Swing the tool down and return to the start."}
    candidate = br.SourceCutCandidate(
        candidate_id=CHILD_ID,
        window=br.DetectionWindow(index=0, start_seconds=start, end_seconds=end),
        frame_paths=[frame],
        sample_frame_paths=[frame],
    )
    child_prompt = br.build_source_cut_child_review_prompt(
        exercise_name=EXERCISE_NAME,
        candidate_title="",
        candidate=candidate,
        exercise_motion_contract=contract,
        extension=True,
    )
    response_row = {
        "id": CHILD_ID,
        "approved": True,
        "confidence": 0.95,
        "completeMovement": True,
        "startBoundaryClean": True,
        "finishBoundaryClean": True,
        "setupOrFiller": False,
        "namedEquipmentEngagedStatus": "engaged",
        "reject": [],
        "note": "Complete visible repetition.",
        "identityMatch": "match",
        "identityEvidence": "Visible tool swing.",
        "boundaryEvidence": "",
        "qualityEvidence": "Clear view.",
        "equipmentEvidence": [{"requirementId": "equipment_1", "evidenceFrameIds": ["D-RETN-1:1"]}],
    }
    positive_raw = json.dumps({"candidates": [response_row]})
    negative_row = {
        **response_row,
        "approved": False,
        "completeMovement": False,
        "reject": ["partial_movement"],
        "boundaryEvidence": "Return not shown.",
    }
    negative_raw = json.dumps({"candidates": [negative_row]})
    samples = [
        {
            "frameId": f"sheet:{index}",
            "sheetSha256": frame_sha,
            "sourceTimestampSeconds": timestamp,
        }
        for index, timestamp in enumerate(TIMESTAMPS)
    ]
    row = {
        "id": CHILD_ID,
        "passed": True,
        "identityMatch": "match",
        "confidence": 0.95,
        "rejectionReasons": [],
        "movementTopologyEvidence": {
            "phaseTimingEvidence": {
                "candidateId": CHILD_ID,
                "candidateWindowSourceSeconds": {"start": start, "end": end},
                "maximumAllowedAdjacentSampleGapSeconds": 1.0,
                "sampleBinsById": {"phase-1": {"sampleBins": samples}},
            }
        },
    }
    receipt = {
        "childReviewPolicyVersion": br.SOURCE_CUT_CHILD_REVIEW_POLICY_VERSION,
        "candidateId": CHILD_ID,
        "candidateWindowSourceSeconds": {"start": start, "end": end},
        "sourceVideoSha256": _sha256_bytes(source.read_bytes()),
        "status": "parsed",
        "reviewFrames": [{"path": str(frame), "sha256": frame_sha}],
        "prompt": child_prompt,
        "rawResponse": positive_raw,
        "matchingCandidateRow": row,
    }
    receipt_path = (
        segment.parent / br.SOURCE_CUT_CHILD_REVIEW_RECEIPT_RELATIVE_PATH
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    attempt = {
        "passed": True,
        "candidateId": CHILD_ID,
        "startSeconds": start,
        "endSeconds": end,
        "candidateVideoSha256": _sha256_bytes(segment.read_bytes()),
        "materializedVideoPath": str(segment),
        "childSemanticApproval": {
            "approved": True,
            "candidateId": CHILD_ID,
            "semanticApprovalOwner": CHILD_ID,
        },
    }
    parser_state = {"row": copy.deepcopy(row)}

    def fake_parser(raw, *args, **kwargs):
        parsed_row = copy.deepcopy(parser_state["row"])
        if raw != positive_raw:
            parsed_row["passed"] = False
        return br.LoopRanking(
            0, [], payload={"sourceCutScorecardCandidates": [parsed_row]}
        )

    monkeypatch.setattr(br, "parse_source_cut_candidate_choice", fake_parser)
    return {
        "attempt": attempt,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "parser_state": parser_state,
        "positive_raw": positive_raw,
        "negative_raw": negative_raw,
        "kwargs": {
            "selected_candidate_id": CHILD_ID,
            "selected_start_seconds": start,
            "selected_end_seconds": end,
            "selected_segment_sha256": _sha256_bytes(segment.read_bytes()),
            "detection_source_video_path": source,
            "expected_exercise_name": EXERCISE_NAME,
            "expected_contract": contract,
        },
    }


def _reject_reason(fixture: dict, **overrides) -> str:
    kwargs = {**fixture["kwargs"], **overrides}
    with pytest.raises(br.SourceCutChildReviewClearanceError) as excinfo:
        br.source_cut_child_semantic_review_clearance(fixture["attempt"], **kwargs)
    return excinfo.value.reason


def test_retained_child_receipt_clears_selected_extension(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    evidence = br.source_cut_child_semantic_review_clearance(
        fixture["attempt"], **fixture["kwargs"]
    )
    assert evidence["authority"] == "exact_child_semantic_review"
    assert evidence["candidateId"] == CHILD_ID
    assert evidence["sampleCount"] == len(TIMESTAMPS)
    assert evidence["sampleSpanSeconds"] == {"start": 0.0, "end": 2.703}
    assert (
        evidence["reparsedMatchingCandidateRowSha256"]
        == evidence["matchingCandidateRowSha256"]
    )


def test_tampered_raw_response_is_rejected(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    tampered = copy.deepcopy(fixture["receipt"])
    tampered["rawResponse"] = "{"  # truncated JSON cannot be repaired into a decision
    assert (
        _reject_reason(fixture, receipt_override=tampered)
        == "child_semantic_review_raw_response_invalid"
    )


def test_stored_row_is_not_trusted_without_reparse_match(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    tampered = copy.deepcopy(fixture["receipt"])
    tampered["matchingCandidateRow"]["passed"] = False
    assert (
        _reject_reason(fixture, receipt_override=tampered)
        == "child_semantic_review_row_not_passed"
    )


def test_contract_or_prompt_drift_is_rejected(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    assert (
        _reject_reason(
            fixture,
            receipt_override=fixture["receipt"],
            expected_exercise_name="Unrelated Exercise",
        )
        == "child_semantic_review_contract_prompt_mismatch"
    )


def test_source_video_hash_is_bound(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    tampered = copy.deepcopy(fixture["receipt"])
    tampered["sourceVideoSha256"] = "0" * 64
    assert (
        _reject_reason(fixture, receipt_override=tampered)
        == "child_semantic_review_source_video_hash_mismatch"
    )


@pytest.mark.parametrize(
    ("timestamps", "reason"),
    [
        ([0.0, 1.88, 2.35, 2.703], "child_semantic_review_sample_gap_exceeded"),
        ([0.0, 0.9, 1.8, 2.2], "child_semantic_review_end_not_sampled"),
        ([0.3, 0.9, 1.8, 2.703], "child_semantic_review_start_not_sampled"),
        ([0.0, 0.0, 1.0, 2.703], "child_semantic_review_duplicate_samples"),
    ],
)
def test_sample_coverage_rejects_holes_edges_and_duplicates(timestamps, reason):
    with pytest.raises(br.SourceCutChildReviewClearanceError) as excinfo:
        br.source_cut_child_review_sample_coverage(
            timestamps, start_seconds=0.0, end_seconds=2.703, maximum_gap=1.0
        )
    assert excinfo.value.reason == reason


def test_sample_coverage_accepts_valid_sorted_samples():
    coverage = br.source_cut_child_review_sample_coverage(
        list(reversed(TIMESTAMPS)),
        start_seconds=0.0,
        end_seconds=2.703,
        maximum_gap=1.0,
    )
    assert coverage["sampleCount"] == len(TIMESTAMPS)
    assert coverage["maximumObservedAdjacentSampleGapSeconds"] <= 1.0


def test_receipt_correction_response_reparse_is_considered(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    receipt = copy.deepcopy(fixture["receipt"])
    receipt["rawResponse"] = fixture["negative_raw"]
    receipt["citationCorrectionRawResponses"] = [fixture["positive_raw"]]
    evidence = br.source_cut_child_semantic_review_clearance(
        fixture["attempt"], receipt_override=receipt, **fixture["kwargs"]
    )
    assert evidence["authority"] == "exact_child_semantic_review"


@pytest.mark.skipif(
    not (HOST_WORKSPACE / "segment_detection" / "segment_selection.json").is_file(),
    reason="retained host review workspace is not present",
)
def test_host_retained_wood_child_receipt_requires_v2_refresh():
    manifest = json.loads(
        (HOST_WORKSPACE / "segment_detection" / "segment_selection.json").read_text(
            encoding="utf-8"
        )
    )
    clearance = br.source_selection_clearance_for_workspace(
        HOST_WORKSPACE,
        required=True,
        expected_exercise_name=manifest.get("exerciseName"),
        expected_contract=manifest.get("exerciseMotionContract"),
    )
    assert clearance["status"] == "needs_source_review", clearance
    assert clearance["reason"] == "source_selection_validation_evidence_stale_or_incomplete", clearance

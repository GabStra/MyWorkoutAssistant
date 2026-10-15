import json

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.segment_detection import DetectionWindow


def _candidate(tmp_path):
    return bake.SourceCutCandidate(
        "A",
        DetectionWindow(0, 0.0, 4.0),
        [tmp_path / "frames.jpg"],
    )


def _row(**changes):
    row = {
        "id": "A",
        "approved": True,
        "confidence": 0.95,
        "completeMovement": True,
        "startBoundaryClean": True,
        "finishBoundaryClean": True,
        "setupOrFiller": False,
        "namedEquipmentEngagedStatus": "not_applicable",
        "reject": [],
        "note": "Complete visible repetition.",
        "identityMatch": "match",
        "identityEvidence": "The target exercise action is visible.",
        "boundaryEvidence": "The visible endpoint is upright at lockout.",
        "qualityEvidence": "",
    }
    row.update(changes)
    return row


def test_approval_boundary_prose_is_discarded_but_rejection_rationale_and_raw_are_preserved(tmp_path):
    candidate = _candidate(tmp_path)
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Barbell Rack Pull",
        candidate_title="ignored title",
        candidate=candidate,
    )
    assert "For an approved candidate, boundaryEvidence must be an empty string" in prompt

    approved_raw = json.dumps({"candidates": [_row()]})
    approved = bake.build_source_cut_scorecard_ranking(
        {"candidates": [_row()]},
        [candidate],
        has_contract=False,
        raw=approved_raw,
    )
    approved_row = approved.payload["sourceCutScorecardCandidates"][0]
    assert approved_row["passed"] is True
    assert approved_row["boundaryEvidence"] == ""
    assert approved.raw_response == approved_raw

    rejection_rationale = "The cut ends before the return phase."
    rejected_payload = _row(
        approved=False,
        completeMovement=False,
        reject=["partial_movement"],
        boundaryEvidence=rejection_rationale,
        note="Partial movement.",
    )
    rejected_raw = json.dumps({"candidates": [rejected_payload]})
    rejected = bake.build_source_cut_scorecard_ranking(
        {"candidates": [rejected_payload]},
        [candidate],
        has_contract=False,
        raw=rejected_raw,
    )
    rejected_row = rejected.payload["sourceCutScorecardCandidates"][0]
    assert rejected_row["passed"] is False
    assert rejected_row["boundaryEvidence"] == rejection_rationale
    assert rejected.raw_response == rejected_raw

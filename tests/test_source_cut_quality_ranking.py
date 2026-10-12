from exercise_motion_pkg.bake_and_rank import (
    LoopRanking,
    SourceCutCandidate,
    build_source_cut_scorecard_ranking,
    shortest_passing_cut_ranking,
)
from exercise_motion_pkg.segment_detection import DetectionWindow


def _candidate(candidate_id: str, start: float, end: float) -> SourceCutCandidate:
    return SourceCutCandidate(
        candidate_id=candidate_id,
        window=DetectionWindow(index=0, start_seconds=start, end_seconds=end),
        frame_paths=[],
    )


def _legacy_scorecard(candidate_id: str, **overrides: float) -> dict[str, object]:
    return {
        "id": candidate_id,
        "exercise_match": 0.99,
        "full_movement": 0.99,
        "start_visible": 0.99,
        "finish_visible": 0.99,
        "mechanics_consistency": 0.99,
        "start_state_ready": 0.99,
        "start_boundary_clean": 0.99,
        "finish_boundary_clean": 0.99,
        "setup_or_filler": 0.01,
        "source_quality": 0.99,
        "confidence": 0.99,
        **overrides,
    }


def _rank_legacy(candidates: list[SourceCutCandidate], rows: list[dict[str, object]]) -> LoopRanking:
    return build_source_cut_scorecard_ranking(
        {"candidates": rows}, candidates, has_contract=False, raw="{}"
    )


def test_source_scorecard_prefers_more_complete_movement_before_shorter_duration() -> None:
    short = _candidate("short", 0.0, 5.0)
    complete = _candidate("complete", 10.0, 17.0)

    ranking = _rank_legacy(
        [short, complete],
        [
            _legacy_scorecard("short", full_movement=0.91),
            _legacy_scorecard("complete", full_movement=0.99),
        ],
    )

    assert ranking.payload["selectedCandidateId"] == "complete"


def test_source_scorecard_prefers_stronger_endpoints_before_shorter_duration() -> None:
    short = _candidate("short", 0.0, 5.0)
    clean = _candidate("clean", 10.0, 17.0)

    ranking = _rank_legacy(
        [short, clean],
        [
            _legacy_scorecard("short", start_boundary_clean=0.91, finish_boundary_clean=0.92),
            _legacy_scorecard("clean", start_boundary_clean=0.99, finish_boundary_clean=0.99),
        ],
    )

    assert ranking.payload["selectedCandidateId"] == "clean"


def test_shortest_passing_cut_uses_scorecard_quality_and_keeps_missing_quality_compatible() -> None:
    short = LoopRanking(
        score=0.95,
        reasons=[],
        payload={
            "selected_section_start_seconds": 0.0,
            "selected_section_end_seconds": 5.0,
            "selectedScorecard": {
                "completeMovement": True,
                "startBoundaryClean": True,
                "finishBoundaryClean": False,
            },
        },
    )
    complete = LoopRanking(
        score=0.90,
        reasons=[],
        payload={
            "selected_section_start_seconds": 10.0,
            "selected_section_end_seconds": 17.0,
            "selectedScorecard": {
                "completeMovement": True,
                "startBoundaryClean": True,
                "finishBoundaryClean": True,
                "movementTopologyEvidence": {
                    "startStateMatch": "match",
                    "endStateMatch": "match",
                },
            },
        },
    )

    assert shortest_passing_cut_ranking([short, complete]) is complete

    legacy_short = LoopRanking(
        score=0.95,
        reasons=[],
        payload={"selected_section_start_seconds": 0.0, "selected_section_end_seconds": 5.0},
    )
    legacy_long = LoopRanking(
        score=0.90,
        reasons=[],
        payload={"selected_section_start_seconds": 10.0, "selected_section_end_seconds": 17.0},
    )
    assert shortest_passing_cut_ranking([legacy_short, legacy_long]) is legacy_short


def test_partial_endpoint_evidence_falls_back_to_duration_order() -> None:
    partial_short = LoopRanking(
        score=0.95,
        reasons=[],
        payload={
            "selected_section_start_seconds": 0.0,
            "selected_section_end_seconds": 5.0,
            "selectedScorecard": {
                "completeMovement": True,
                "startBoundaryClean": True,
            },
        },
    )
    fully_observed_long = LoopRanking(
        score=0.90,
        reasons=[],
        payload={
            "selected_section_start_seconds": 10.0,
            "selected_section_end_seconds": 17.0,
            "selectedScorecard": {
                "completeMovement": True,
                "startBoundaryClean": True,
                "finishBoundaryClean": False,
            },
        },
    )

    # One candidate lacks finish evidence, so endpoint scores are incomparable.
    assert shortest_passing_cut_ranking([partial_short, fully_observed_long]) is partial_short

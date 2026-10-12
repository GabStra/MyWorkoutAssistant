import json

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.segment_detection import DetectionWindow
from exercise_motion_pkg.source_review_authority import SOURCE_REVIEW_AUTHORITY_VERSION


def test_batch_rejection_authority_uses_each_candidates_original_row(monkeypatch, tmp_path):
    candidates = [
        bake.SourceCutCandidate(
            candidate_id=candidate_id,
            window=DetectionWindow(index=index, start_seconds=float(index), end_seconds=float(index + 2)),
            frame_paths=[tmp_path / f"{candidate_id}.jpg"],
        )
        for index, candidate_id in enumerate(("A", "B"))
    ]

    def rejection_row(candidate_id):
        return {
            "id": candidate_id,
            "approved": False,
            "confidence": 0.95,
            "completeMovement": False,
            "startBoundaryClean": True,
            "finishBoundaryClean": True,
            "setupOrFiller": False,
            "reject": ["partial_movement"],
            "boundaryEvidence": "The movement ends before its return phase.",
            "note": "Partial movement.",
        }

    calls = []

    def caption_images(**kwargs):
        frame_names = [path.name for path in kwargs["frame_paths"]]
        calls.append(frame_names)
        if len(frame_names) == 2:
            rows = [rejection_row("A"), rejection_row("B")]
        else:
            rows = [rejection_row(frame_names[0][0])]
        return json.dumps({"candidates": rows})

    def parser(raw, candidate):
        return bake.parse_source_cut_candidate_choice(
            raw, [candidate], require_identity_evidence=True
        )

    monkeypatch.setattr(
        bake,
        "review_source_cut_boundaries",
        lambda *, candidate, ranking, **_kwargs: (ranking, []),
    )
    monkeypatch.setattr(bake, "write_cut_candidate_vlm_review_debug", lambda **_kwargs: None)

    result = bake.rank_cut_candidate_batch_with_caption_images(
        candidates=candidates,
        caption_images=caption_images,
        prompt_builder=lambda batch: f"Review {[item.candidate_id for item in batch]}",
        single_candidate_prompt_builder=lambda candidate: f"Review {candidate.candidate_id}",
        parser=parser,
    )

    assert calls == [["A.jpg", "B.jpg"], ["A.jpg"], ["B.jpg"]]
    assert len(result.rankings) == 2
    assert all(
        ranking.payload["sourceReviewAssessment"]["status"] == "model_rejected"
        and ranking.payload["sourceReviewAssessment"]["reviews"][0]["approved"] is False
        for ranking in result.rankings
    )
    assert all(ranking.payload["sourceReviewAuthorityVersion"] == SOURCE_REVIEW_AUTHORITY_VERSION
               for ranking in result.rankings)

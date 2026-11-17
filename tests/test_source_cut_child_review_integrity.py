from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import exercise_motion_pkg.bake_and_rank as bake
import exercise_motion_pkg.source_frame_clock as source_frame_clock


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _response_row(candidate_id: str, approved: bool) -> dict:
    return {
        "id": candidate_id,
        "approved": approved,
        "confidence": 0.95,
        "completeMovement": approved,
        "startBoundaryClean": True,
        "finishBoundaryClean": True,
        "setupOrFiller": False,
        "namedEquipmentEngagedStatus": "unclear",
        "reject": [] if approved else ["partial_movement"],
        "note": "A visible cycle is present." if approved else "Only one phase is visible.",
        "identityMatch": "match",
        "identityEvidence": "The exercise action is visible.",
        "boundaryEvidence": "" if approved else "The return is not shown.",
        "qualityEvidence": "The footage is clear.",
    }


def _retained_sample_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sample_dir = tmp_path / "retained"
    sample_dir.mkdir()
    sample_paths = []
    for number in range(1, 25):
        path = sample_dir / f"frame_{number:02d}.jpg"
        path.write_bytes(f"sample-{number}".encode())
        sample_paths.append(path)
    sheet = sample_dir / "contact_sheet_01.jpg"
    sheet.write_bytes(b"verified contact sheet")
    start = 60 / 30
    end = 125 / 30
    requests = [start + (end - 0.05 - start) * index / 23 for index in range(24)]
    manifest = {
        "schemaVersion": 1,
        "sheets": {
            sheet.name: {
                "sha256": _sha(sheet),
                "frames": [
                    {"number": number, "timestampSeconds": timestamp}
                    for number, timestamp in enumerate(requests, start=1)
                ],
            }
        },
    }
    (sample_dir / "contact_sheet_evidence.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"source identity fixture")
    source_pts = [index / 30 for index in range(160)]
    monkeypatch.setattr(
        source_frame_clock, "_read_decoded_frame_timestamps",
        lambda *args, **kwargs: (source_pts, 1 / 30),
    )
    window = bake.DetectionWindow(index=0, start_seconds=start, end_seconds=end)
    inventory = bake.source_cut_child_sample_inventory(
        output_dir=sample_dir,
        source_video_path=source_video,
        candidate_window=window,
    )
    return sample_dir, sample_paths, inventory, window


def test_child_overview_uses_retained_endpoint_samples_and_actual_pts(tmp_path, monkeypatch):
    sample_dir, sample_paths, inventory, window = _retained_sample_inventory(
        tmp_path, monkeypatch,
    )
    assert inventory[0]["sourceFrameIndex"] == 60
    assert inventory[-1]["sourceFrameIndex"] == 124
    assert all(60 <= row["sourceFrameIndex"] < 125 for row in inventory)

    captured: dict[str, object] = {}

    def capture_sheet(**kwargs):
        captured.update(kwargs)
        output = kwargs["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"overview")
        return output

    monkeypatch.setattr(bake, "build_frame_contact_sheet", capture_sheet)
    candidate = bake.SourceCutCandidate(
        candidate_id="HIP-EARLY-CYCLE-60-125",
        window=window,
        frame_paths=[sample_dir / "contact_sheet_01.jpg", sample_dir / "contact_sheet_02.jpg"],
        sample_frame_paths=sample_paths,
    )
    actual_pts = [float(row["sourceTimeSec"]) for row in inventory]
    reviewed = bake.source_cut_review_overview(
        candidate, sample_dir / "overview", sample_timestamps=actual_pts,
    )
    assert reviewed.frame_paths == [sample_dir / "overview" / "source_review_overview.jpg"]
    assert captured["frame_paths"][0] == sample_paths[0]
    assert captured["frame_paths"][-1] == sample_paths[-1]
    assert captured["timestamps"][0] == pytest.approx(60 / 30)
    assert captured["timestamps"][-1] == pytest.approx(124 / 30)
    assert all(window.start_seconds <= value < window.end_seconds for value in captured["timestamps"])


@pytest.mark.parametrize("approved", [True, False])
def test_truncated_child_positive_or_negative_is_invalid_response(approved):
    candidate = bake.SourceCutCandidate(
        candidate_id="HIP-EARLY-CYCLE-60-125",
        window=bake.DetectionWindow(index=0, start_seconds=2.0, end_seconds=4.0),
        frame_paths=[Path("unused.jpg")],
    )
    raw = json.dumps({"candidates": [_response_row(candidate.candidate_id, approved)]})[:-1]
    calls = []
    ranking, error = bake.parse_source_cut_child_scorecard_response(
        raw, candidate,
        lambda *_args: calls.append(True),
        required_fields=bake.source_cut_child_scorecard_required_fields(
            candidate, equipment_required=False,
        ),
    )
    assert ranking is None
    assert error == "invalid_json"
    assert calls == []


def test_complete_child_json_reaches_existing_scorecard_parser():
    candidate = bake.SourceCutCandidate(
        candidate_id="HIP-EARLY-CYCLE-60-125",
        window=bake.DetectionWindow(index=0, start_seconds=2.0, end_seconds=4.0),
        frame_paths=[Path("unused.jpg")],
    )
    raw = json.dumps({"candidates": [_response_row(candidate.candidate_id, False)]})
    expected = bake.LoopRanking(0, [], payload={"sourceCutScorecardCandidates": []})
    ranking, error = bake.parse_source_cut_child_scorecard_response(
        raw, candidate, lambda *_args: expected,
        required_fields=bake.source_cut_child_scorecard_required_fields(
            candidate, equipment_required=False,
        ),
    )
    assert ranking is expected
    assert error is None


_HIP_CHILD_ID = "HIP-EARLY-CYCLE-60-125"
_HIP_PHASES = [
    "Extend the hips with feet planted and upper back supported",
    "Lower the hips under control",
]


def _child_review_contract() -> dict:
    return {
        "exerciseName": "Barbell Hip Thrust",
        "definingAction": (
            "Extend the hips with feet planted and upper back supported, "
            "then lower the hips under control."
        ),
        "completionMode": "return_to_start",
        "requiredPhases": list(_HIP_PHASES),
        "actionDefinitionStatus": "defined",
    }


def _child_review_alias_row(*, phase_02_frame_id: str = "A:3") -> dict:
    return {
        "id": "A",
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
        "identityEvidence": "Visible barbell hip thrust.",
        "boundaryEvidence": "",
        "qualityEvidence": "Clear view of hips and feet.",
        "phaseEvidence": [
            {
                "phaseId": "phase_01",
                "visible": True,
                "evidence": "Hips extend.",
                "evidenceFrameIds": ["A:1", "A:2"],
            },
            {
                "phaseId": "phase_02",
                "visible": True,
                "evidence": "Hips lower.",
                "evidenceFrameIds": [phase_02_frame_id, "A:4"],
            },
        ],
        "equipmentEvidence": [
            {"requirementId": "equipment_1", "evidenceFrameIds": ["A:1", "A:4"]},
        ],
    }


def _request_child_review_with_alias_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response_row: dict,
) -> tuple[dict | None, dict, dict]:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    rendered = tmp_path / "rendered_sheet.jpg"
    rendered.write_bytes(b"rendered sheet")
    overview = tmp_path / "overview" / "source_review_overview.jpg"
    overview.parent.mkdir(parents=True, exist_ok=True)
    overview.write_bytes(b"overview")
    timestamps = [0.1, 0.9, 1.7, 2.2]
    (overview.parent / "contact_sheet_evidence.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "sheets": {
                overview.name: {
                    "sha256": _sha(overview),
                    "frames": [
                        {"number": number, "timestampSeconds": timestamp}
                        for number, timestamp in enumerate(timestamps, start=1)
                    ],
                },
            },
        }),
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_render(**kwargs):
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        return [rendered]

    def fake_request(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        captured["candidateId"] = kwargs["candidate"].candidate_id
        return json.dumps({"candidates": [response_row]})

    monkeypatch.setattr(bake, "render_video_window_contact_sheet", fake_render)
    monkeypatch.setattr(
        bake, "build_source_cut_candidate",
        lambda **kwargs: bake.SourceCutCandidate(
            kwargs["candidate_id"], kwargs["candidate_window"], [rendered],
        ),
    )
    monkeypatch.setattr(
        bake, "source_cut_review_overview",
        lambda candidate, output_dir, **kwargs: bake.replace(
            candidate, frame_paths=[overview],
        ),
    )
    monkeypatch.setattr(
        bake, "source_cut_child_sample_inventory",
        lambda **kwargs: [
            {"sourceTimeSec": timestamp, "samplePath": str(overview),
             "sampleSha256": _sha(overview)}
            for timestamp in timestamps
        ],
    )
    monkeypatch.setattr(bake, "request_clef_source_cut_scorecard", fake_request)

    review = bake.request_source_cut_child_semantic_review(
        {"candidateId": _HIP_CHILD_ID, "startSeconds": 0.0, "endSeconds": 2.3},
        source_video_path=source,
        exercise_name="Barbell Hip Thrust",
        candidate_title="Barbell Hip Thrust",
        exercise_motion_contract=_child_review_contract(),
        caption_images=lambda **kwargs: "unused",
        output_dir=tmp_path,
        frame_count=8,
        visual_decision_backend="clef-systemone",
    )
    receipt_path = (
        tmp_path / f"source_candidate_{_HIP_CHILD_ID}" / "child_semantic_review"
        / f"policy-v{bake.SOURCE_CUT_CHILD_REVIEW_POLICY_VERSION}" / "semantic_review.json"
    )
    return review, json.loads(receipt_path.read_text(encoding="utf-8")), captured


def test_child_review_prompt_uses_short_aliases_and_trusted_phases(tmp_path):
    sheet = tmp_path / "overview.jpg"
    sheet.write_bytes(b"overview")
    (tmp_path / "contact_sheet_evidence.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "sheets": {
                sheet.name: {
                    "sha256": _sha(sheet),
                    "frames": [{"number": 1, "timestampSeconds": 0.1}],
                },
            },
        }),
        encoding="utf-8",
    )
    candidate = bake.SourceCutCandidate(
        candidate_id=_HIP_CHILD_ID,
        window=bake.DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.3),
        frame_paths=[sheet],
    )
    prompt = bake.build_source_cut_child_review_prompt(
        exercise_name="Barbell Hip Thrust",
        candidate_title="Barbell Hip Thrust",
        candidate=candidate,
        exercise_motion_contract=_child_review_contract(),
        extension=False,
    )
    assert '"id":"A:1"' in prompt
    assert _HIP_CHILD_ID not in prompt
    assert "Target exercise: Barbell Hip Thrust" in prompt
    for phase in _HIP_PHASES:
        assert phase in prompt


def test_child_review_alias_roundtrip_returns_real_candidate_and_frame_ids(tmp_path, monkeypatch):
    review, receipt, captured = _request_child_review_with_alias_response(
        tmp_path, monkeypatch, _child_review_alias_row(),
    )

    assert captured["candidateId"] == "A"
    assert review is not None
    assert review["id"] == _HIP_CHILD_ID
    topology = review["movementTopologyEvidence"]
    assert topology["phaseTimingEvidence"]["candidateId"] == _HIP_CHILD_ID
    assert topology["phaseEvidence"][0]["evidenceFrameIds"] == [
        f"{_HIP_CHILD_ID}:1", f"{_HIP_CHILD_ID}:2",
    ]
    assert topology["phaseEvidence"][1]["evidenceFrameIds"] == [
        f"{_HIP_CHILD_ID}:3", f"{_HIP_CHILD_ID}:4",
    ]
    assert receipt["frameAliasMap"] == {
        "A:1": f"{_HIP_CHILD_ID}:1",
        "A:2": f"{_HIP_CHILD_ID}:2",
        "A:3": f"{_HIP_CHILD_ID}:3",
        "A:4": f"{_HIP_CHILD_ID}:4",
    }
    assert '"id": "A"' in receipt["modelRawResponse"]
    assert '"A:1"' in receipt["modelRawResponse"]
    assert '"A:1"' not in receipt["rawResponse"]
    assert f'"{_HIP_CHILD_ID}:1"' in receipt["rawResponse"]
    assert receipt["status"] == "parsed"


def test_child_review_unknown_alias_is_rejected_as_invalid_transport(tmp_path, monkeypatch):
    review, receipt, _ = _request_child_review_with_alias_response(
        tmp_path, monkeypatch,
        _child_review_alias_row(phase_02_frame_id="A:99"),
    )

    assert review is None
    assert receipt["status"] == "invalid_response"
    assert receipt["parseFailure"] == "child_review_unknown_alias"
    assert receipt["parsedRankingPayload"] is None

import json

import pytest

from scripts.analyze_exercise_motion_source_funnel import summarize_source_funnel


def write_selection_manifest(path, *, candidate_seconds):
    path.write_text(
        json.dumps(
            {
                "selected": {"candidate": {"videoId": path.stem}},
                "timings": {
                    "totalSeconds": candidate_seconds,
                    "sourceFunnel": {
                        "processedCandidateCount": 1,
                        "firstCandidate": {
                            "sourcePassed": True,
                            "accepted": True,
                            "rejectionTags": [],
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_wall_throughput_uses_explicit_whole_run_duration(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_selection_manifest(first, candidate_seconds=250.041)
    write_selection_manifest(second, candidate_seconds=534.643)

    summary = summarize_source_funnel(
        [first, second],
        label="retained-run",
        wall_seconds=1282.0,
    )

    assert summary["selectedCount"] == 2
    assert summary["acceptedOutputsPerWallHour"] == 5.616
    assert summary["armWallSeconds"] == 1282.0
    assert summary["summedCandidateProcessingSeconds"] == 784.684
    assert "totalSeconds" not in summary
    assert all("candidateProcessingSeconds" in row for row in summary["rows"])


def test_wall_throughput_is_omitted_without_whole_run_duration(tmp_path):
    manifest = tmp_path / "selection.json"
    write_selection_manifest(manifest, candidate_seconds=100.0)

    summary = summarize_source_funnel([manifest], label="no-wall-measure")

    assert summary["acceptedOutputsPerWallHour"] is None
    assert summary["armWallSeconds"] is None


@pytest.mark.parametrize("wall_seconds", [0.0, -1.0, float("inf"), float("nan")])
def test_wall_duration_must_be_finite_and_positive(tmp_path, wall_seconds):
    with pytest.raises(ValueError, match="finite positive"):
        summarize_source_funnel([], label="invalid", wall_seconds=wall_seconds)

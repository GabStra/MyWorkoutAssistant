from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank


def _candidate(
    samples: list[dict[str, object]],
    completion_mode: str = "active_travel",
) -> bake_and_rank.RankedCandidate:
    return bake_and_rank.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="loaded-carry",
        exercise_name="Loaded carry",
        exercise_slug="loaded-carry",
        candidate={
            "videoId": "carry-source",
            "title": "Loaded carry",
            "durationSeconds": 24,
            "exerciseMotionContract": {"completionMode": completion_mode},
            "visionPayload": {
                "bestChunkStartSeconds": 0,
                "bestChunkEndSeconds": 8,
                "bestChunkScore": 0.99,
                "bestChunkSource": "pose_prefilter",
                "reviewedChunks": [
                    {"startSeconds": 1, "endSeconds": 9, "score": 0.98, "valid": True}
                ],
                "posePrefilter": {
                    "validChunks": [
                        {"startSeconds": 12, "endSeconds": 20, "score": 0.95}
                    ],
                    "dominantPoseSamples": samples,
                    "sampleFps": 2,
                },
            },
        },
    )


def _pose_sample(time_seconds: float) -> dict[str, object]:
    return {
        "timeSeconds": time_seconds,
        "keypoints": {
            "left_hip": [0.45, 0.5],
            "right_hip": [0.55, 0.5],
            "left_shoulder": [0.45, 0.3],
            "right_shoulder": [0.55, 0.3],
            "left_knee": [0.4, 0.7],
            "right_knee": [0.6, 0.7],
            "left_ankle": [0.4, 0.9],
            "right_ankle": [0.6, 0.9],
        },
    }


@pytest.mark.parametrize("completion_mode", ["active_travel", "distinct_end_state", "stable_hold"])
def test_pose_fallback_searches_each_contiguous_source_run(monkeypatch, completion_mode: str) -> None:
    times = [index * 0.25 for index in range(8)] + [10 + index * 0.25 for index in range(8)]
    samples = [_pose_sample(time) for time in times]
    candidate = _candidate(samples, completion_mode)
    proposal_calls: list[tuple[float, ...]] = []
    proposal_modes: list[str] = []

    def propose(**kwargs):
        times = tuple(float(sample["timeSeconds"]) for sample in kwargs["dominant_pose_samples"])
        proposal_calls.append(times)
        proposal_modes.append(kwargs["contract"]["completionMode"])
        if times[0] == 10:
            return [
                SimpleNamespace(
                    start_seconds=10.0,
                    end_seconds=11.75,
                    policy=completion_mode,
                    confidence=0.95,
                    stats={},
                ),
                SimpleNamespace(
                    start_seconds=10.25,
                    end_seconds=11.0,
                    policy=completion_mode,
                    confidence=0.8,
                    stats={},
                ),
            ]
        return []

    monkeypatch.setattr(bake_and_rank, "propose_source_cut", propose)

    variants = bake_and_rank.observed_complete_source_window_variants(candidate)

    assert proposal_calls == [
        tuple(index * 0.25 for index in range(8)),
        tuple(10 + index * 0.25 for index in range(8)),
    ]
    assert proposal_modes == [completion_mode, completion_mode]
    assert [(variant.hint.start_seconds, variant.hint.end_seconds) for variant in variants] == [
        (10.0, 11.75),
        (10.25, 11.0),
    ]
    assert variants[0].source == "pose_prefilter_source_proposal"


def test_pose_fallback_keeps_sibling_when_reviewed_window_exists(monkeypatch) -> None:
    candidate = _candidate([_pose_sample(float(time)) for time in range(21)])
    request = bake_and_rank.BakeAndRankRequest(
        candidates_json=Path("candidates.json"), workspace=Path("workspace"), body_model_root=None
    )
    monkeypatch.setattr(bake_and_rank, "observed_complete_source_window_variants", lambda _candidate: [])
    monkeypatch.setattr(
        bake_and_rank,
        "active_travel_locomotion_metrics_from_source_pose_payload",
        lambda *_args, **_kwargs: {"passed": True, "supportCenterRangeRatio": 0.1},
    )

    variants = bake_and_rank.collect_source_window_variants(candidate, request=request)

    windows = [(variant.hint.start_seconds, variant.hint.end_seconds) for variant in variants]
    assert windows[:2] == [(0.0, 8.0), (1.0, 9.0)]
    assert (12.0, 20.0) in windows


def test_complete_current_window_keeps_priority_and_retains_later_proposal(monkeypatch) -> None:
    candidate = _candidate([_pose_sample(index * 0.25) for index in range(81)])
    candidate.candidate["exerciseMotionContract"].update(
        {"completionMode": "return_to_start", "requiresReturnToStart": True}
    )
    request = bake_and_rank.BakeAndRankRequest(
        candidates_json=Path("candidates.json"), workspace=Path("workspace"), body_model_root=None
    )
    monkeypatch.setattr(
        bake_and_rank,
        "source_pose_skeleton_payload_for_window",
        lambda _pose, *, candidate_window, **_kwargs: {
            "frames": [{"sourceTimeSec": candidate_window.start_seconds}],
            "jointNames": ["pelvis"],
            "rootJoint": "pelvis",
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda payload, **_kwargs: {
            "passed": True,
            "endpointPhaseDeltaRatio": 0.1 if payload["frames"][0]["sourceTimeSec"] in (0.0, 10.0) else 0.5,
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "propose_source_cut",
        lambda **_kwargs: [
            SimpleNamespace(
                start_seconds=10.0,
                end_seconds=12.0,
                policy="cycle_return_to_start",
                confidence=0.9,
                stats={},
            ),
            SimpleNamespace(
                start_seconds=12.0,
                end_seconds=13.0,
                policy="cycle_return_to_start",
                confidence=0.9,
                stats={},
            ),
        ],
    )

    variants = bake_and_rank.collect_source_window_variants(candidate, request=request)

    windows = [(variant.hint.start_seconds, variant.hint.end_seconds) for variant in variants]
    assert windows[:2] == [(0.0, 8.0), (1.0, 9.0)]
    assert (10.0, 12.0) in windows
    observed = [variant for variant in variants if variant.source == "observed_complete_source_cycle"]
    assert [(variant.hint.start_seconds, variant.hint.end_seconds) for variant in observed] == [
        (10.0, 12.0),
        (12.0, 13.0),
    ]


def test_fast_complete_pose_proposal_bypasses_discovery_duration_floor(monkeypatch) -> None:
    candidate = _candidate([_pose_sample(index * 0.25) for index in range(81)])
    candidate.candidate["exerciseMotionContract"].update(
        {"completionMode": "return_to_start", "requiresReturnToStart": True}
    )
    request = bake_and_rank.BakeAndRankRequest(
        candidates_json=Path("candidates.json"), workspace=Path("workspace"), body_model_root=None
    )
    monkeypatch.setattr(
        bake_and_rank,
        "source_pose_skeleton_payload_for_window",
        lambda _pose, *, candidate_window, **_kwargs: {
            "frames": [{"sourceTimeSec": candidate_window.start_seconds}],
            "jointNames": ["pelvis"],
            "rootJoint": "pelvis",
        },
    )
    monkeypatch.setattr(
        bake_and_rank,
        "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda *_args, **_kwargs: {"passed": True, "endpointPhaseDeltaRatio": 0.1},
    )
    monkeypatch.setattr(
        bake_and_rank,
        "propose_source_cut",
        lambda **_kwargs: [SimpleNamespace(
            start_seconds=10.0,
            end_seconds=10.935,
            policy="cycle_return_to_start",
            confidence=0.95,
            stats={},
        )],
    )

    variants = bake_and_rank.collect_source_window_variants(candidate, request=request)

    assert any(
        variant.hint.start_seconds == 10.0 and variant.hint.end_seconds == 10.935
        for variant in variants
    )


def test_current_hint_does_not_join_phase_evidence_across_missing_samples(monkeypatch):
    candidate = _candidate([], "return_to_start")
    candidate.candidate["exerciseMotionContract"]["requiresReturnToStart"] = True
    monkeypatch.setattr(
        bake_and_rank, "source_pose_skeleton_payload_for_window",
        lambda *args, **kwargs: {"frames": [{"sourceTimeSec": 0.0}, {"sourceTimeSec": 5.0}]},
    )
    monkeypatch.setattr(
        bake_and_rank, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
        lambda *args, **kwargs: {"passed": True},
    )
    assert not bake_and_rank.source_window_pose_phase_is_complete(candidate)

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from exercise_motion_pkg import bake_and_rank as bake


def _pose_prefilter_payload(
    *,
    max_significant_person_count: int = 1,
    multi_person_ratio: float = 0.0,
) -> dict[str, Any]:
    samples = []
    for index in range(6):
        samples.append(
            {
                "timeSeconds": index / 8.0,
                "confidence": 0.9,
                "bbox": [0.2, 0.2, 0.8, 0.9],
                "keypoints": {
                    "left_hip": [0.4, 0.5, 0.9],
                    "right_hip": [0.6, 0.5, 0.9],
                    "left_shoulder": [0.35, 0.3, 0.9],
                    "right_shoulder": [0.65, 0.3, 0.9],
                },
            }
        )
    return {
        "model": "yolo26x-pose.pt",
        "resolvedModelPath": "/models/yolo26x-pose.pt",
        "sampleFps": 8.0,
        "sampledFrameCount": len(samples),
        "maxSignificantPersonCount": max_significant_person_count,
        "multiPersonRatio": multi_person_ratio,
        "singlePersonRatio": 1.0 - multi_person_ratio,
        "blockingIssues": [],
        "dominantPoseSamples": samples,
        "dominantPoseSampleCoordinateSpace": "normalized_image_xy",
        "imageWidth": 640,
        "imageHeight": 480,
    }


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_path: Path,
    yolo_calls: list[Path],
    phase_calls: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> None:
    pose_payload = payload or _pose_prefilter_payload()
    model_path.write_bytes(b"pose model artifact v1")
    from exercise_motion_pkg import pose_prefilter

    monkeypatch.setattr(pose_prefilter, "resolve_pose_model_path", lambda _model: str(model_path))

    def fake_yolo(**kwargs: Any) -> SimpleNamespace:
        yolo_calls.append(Path(kwargs["video_path"]))
        return SimpleNamespace(payload=pose_payload)

    def fake_phase(**kwargs: Any) -> dict[str, Any]:
        contract = kwargs["ranking_payload"]["exerciseMotionContract"]
        frames = kwargs["source_pose_payload"]["frames"]
        phase_calls.append(
            {
                "contract": contract,
                "frames": frames,
                "poseSampleCount": kwargs.get("pose_sample_count"),
            }
        )
        return {
            "passed": True,
            "contractReturn": bool(
                (contract.get("observableMotionSpec") or {}).get("requiresReturnToStart")
            ),
            "frameCount": len(frames),
        }

    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda _: SimpleNamespace(duration_seconds=8.0))
    monkeypatch.setattr(bake, "run_yolo_pose_prefilter", fake_yolo)
    monkeypatch.setattr(bake, "source_pose_phase_completeness_metrics", fake_phase)


def _measurement_files(measurement_dir: Path) -> list[Path]:
    return sorted(measurement_dir.glob("*.json"))


def test_changed_contract_reuses_identical_measurement_without_yolo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"same exact source bytes")
    measurement_dir = tmp_path / "exact_source_pose_measurements"
    yolo_calls: list[Path] = []
    phase_calls: list[dict[str, Any]] = []
    model_path = tmp_path / "yolo26x-pose.pt"
    _install_fakes(monkeypatch, model_path=model_path, yolo_calls=yolo_calls, phase_calls=phase_calls)

    first = bake.source_video_phase_completeness_metrics(
        source_video_path=video,
        exercise_name="Pull-Up",
        ranking_payload={
            "exerciseMotionContract": {
                "observableMotionSpec": {"requiresReturnToStart": True},
            }
        },
        pose_measurement_cache_dir=measurement_dir,
    )
    second = bake.source_video_phase_completeness_metrics(
        source_video_path=video,
        exercise_name="Pull-Up",
        ranking_payload={
            "exerciseMotionContract": {
                "observableMotionSpec": {"requiresReturnToStart": False},
            }
        },
        pose_measurement_cache_dir=measurement_dir,
    )

    assert len(yolo_calls) == 1
    assert len(phase_calls) == 2
    assert phase_calls[0]["frames"] == phase_calls[1]["frames"]
    assert phase_calls[0]["poseSampleCount"] == 6
    assert first["contractReturn"] is True
    assert second["contractReturn"] is False

    files = _measurement_files(measurement_dir)
    assert len(files) == 1
    stored_text = files[0].read_text(encoding="utf-8")
    stored = json.loads(stored_text)
    assert stored["sourceVideoSha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert stored["personCount"]["sampledFrameCount"] == 6
    assert stored["personCount"]["maxSignificantPersonCount"] == 1
    assert stored["personCount"]["multiPersonRatio"] == 0.0
    assert stored["sourcePosePayload"]["frames"] == phase_calls[0]["frames"]
    assert "exerciseMotionContract" not in stored_text


def test_cached_multiple_person_measurement_still_fails_single_person_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"same exact source bytes")
    measurement_dir = tmp_path / "exact_source_pose_measurements"
    yolo_calls: list[Path] = []
    phase_calls: list[dict[str, Any]] = []
    model_path = tmp_path / "yolo26x-pose.pt"
    _install_fakes(monkeypatch, model_path=model_path, yolo_calls=yolo_calls, phase_calls=phase_calls)
    contract = {"observableMotionSpec": {"requiresReturnToStart": True}}

    bake.source_video_phase_completeness_metrics(
        source_video_path=video,
        exercise_name="Pull-Up",
        ranking_payload={"exerciseMotionContract": contract},
        pose_measurement_cache_dir=measurement_dir,
    )
    measurement_path = _measurement_files(measurement_dir)[0]
    stored = json.loads(measurement_path.read_text(encoding="utf-8"))
    stored["personCount"]["sampledFrameCount"] = 6
    stored["personCount"]["maxSignificantPersonCount"] = 2
    stored["personCount"]["multiPersonRatio"] = 0.25
    stored["personCount"]["singlePersonRatio"] = 0.75
    measurement_path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(bake.SourceCandidateRejected) as error:
        bake.source_video_phase_completeness_metrics(
            source_video_path=video,
            exercise_name="Pull-Up",
            ranking_payload={"exerciseMotionContract": contract},
            pose_measurement_cache_dir=measurement_dir,
        )

    assert "source_multiple_people_detected" in error.value.reason_tags
    assert len(yolo_calls) == 1
    assert len(phase_calls) == 1


def test_incomplete_or_incompatible_measurement_fails_closed_to_recompute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"same exact source bytes")
    measurement_dir = tmp_path / "exact_source_pose_measurements"
    yolo_calls: list[Path] = []
    phase_calls: list[dict[str, Any]] = []
    model_path = tmp_path / "yolo26x-pose.pt"
    _install_fakes(monkeypatch, model_path=model_path, yolo_calls=yolo_calls, phase_calls=phase_calls)
    contract = {"observableMotionSpec": {"requiresReturnToStart": True}}

    def measure(source_video_path: Path = video) -> dict[str, Any] | None:
        return bake.source_video_phase_completeness_metrics(
            source_video_path=source_video_path,
            exercise_name="Pull-Up",
            ranking_payload={"exerciseMotionContract": contract},
            pose_measurement_cache_dir=measurement_dir,
        )

    measure()
    measurement_path = _measurement_files(measurement_dir)[0]

    stored = json.loads(measurement_path.read_text(encoding="utf-8"))
    del stored["personCount"]["maxSignificantPersonCount"]
    measurement_path.write_text(json.dumps(stored), encoding="utf-8")
    measure()
    assert len(yolo_calls) == 2

    stored = json.loads(measurement_path.read_text(encoding="utf-8"))
    stored["measurementIdentity"]["posePrefilter"]["sampleFps"] = 9.0
    measurement_path.write_text(json.dumps(stored), encoding="utf-8")
    measure()
    assert len(yolo_calls) == 3

    measurement_path.write_text("not json", encoding="utf-8")
    measure()
    assert len(yolo_calls) == 4

    for mutate in (
        lambda counts: counts.update(maxSignificantPersonCount=0),
        lambda counts: counts.pop("singlePersonRatio"),
        lambda counts: counts.update(singlePersonRatio=0.2, multiPersonRatio=0.2),
        lambda counts: counts.update(singlePersonRatio=0.0),
    ):
        stored = json.loads(measurement_path.read_text(encoding="utf-8"))
        mutate(stored["personCount"])
        measurement_path.write_text(json.dumps(stored), encoding="utf-8")
        calls_before = len(yolo_calls)
        measure()
        assert len(yolo_calls) == calls_before + 1
        assert len(phase_calls) == len(yolo_calls)

    other_video = tmp_path / "other.mp4"
    other_video.write_bytes(b"different source bytes")
    measure(other_video)
    assert len(yolo_calls) == 9
    assert len(phase_calls) == 9


def test_cache_identity_changes_when_model_bytes_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"same exact source bytes")
    measurement_dir = tmp_path / "exact_source_pose_measurements"
    model_path = tmp_path / "yolo26x-pose.pt"
    yolo_calls: list[Path] = []
    phase_calls: list[dict[str, Any]] = []
    _install_fakes(monkeypatch, model_path=model_path, yolo_calls=yolo_calls, phase_calls=phase_calls)
    ranking_payload = {"exerciseMotionContract": {"observableMotionSpec": {}}}

    def measure() -> None:
        bake.source_video_phase_completeness_metrics(
            source_video_path=video,
            exercise_name="Pull-Up",
            ranking_payload=ranking_payload,
            pose_measurement_cache_dir=measurement_dir,
        )

    measure()
    identity_before = bake.exact_source_pose_measurement_identity(
        source_video_path=video, duration_seconds=8.0
    )
    model_path.write_bytes(b"pose model artifact v2")
    identity_after = bake.exact_source_pose_measurement_identity(
        source_video_path=video, duration_seconds=8.0
    )
    assert identity_before["posePrefilter"]["modelArtifactSha256"] != identity_after["posePrefilter"]["modelArtifactSha256"]
    measure()
    assert len(yolo_calls) == 2

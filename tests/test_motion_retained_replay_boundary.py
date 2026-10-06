import hashlib
import json
from types import SimpleNamespace

import pytest

from motion_retained_replay_boundary import patch_module, verified_file


def test_retained_replay_rejects_changed_input_bytes(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"original")
    fixture = {"sourceVideoPath": str(video),
               "sourceVideoPathSha256": hashlib.sha256(video.read_bytes()).hexdigest()}
    assert verified_file(fixture, "sourceVideoPath") == video
    video.write_bytes(b"replacement")
    with pytest.raises(AssertionError, match="input changed"):
        verified_file(fixture, "sourceVideoPath")


def test_retained_replay_seeds_only_hash_pinned_usable_contract_cache(
    tmp_path, monkeypatch
):
    from exercise_motion_pkg import youtube
    from scripts.run_motion_retained_replay import seed_replay_contract_cache

    exercise = SimpleNamespace(exercise_id="press")
    source_dir = tmp_path / "source-cache"
    source_dir.mkdir()
    source_cache = source_dir / "press.json"
    source_cache.write_text('{"contract":"validated"}', encoding="utf-8")
    source_digest = hashlib.sha256(source_cache.read_bytes()).hexdigest()
    monkeypatch.setattr(youtube, "load_workout_plan_exercises", lambda *_args, **_kwargs: [exercise])
    monkeypatch.setattr(
        youtube,
        "exercise_motion_contract_cache_path",
        lambda item, settings: settings.exercise_motion_contract_cache_dir / f"{item.exercise_id}.json",
    )
    monkeypatch.setattr(
        youtube,
        "load_cached_exercise_motion_contract",
        lambda item, settings: (
            {"cacheStatus": "reused"}
            if (settings.exercise_motion_contract_cache_dir / f"{item.exercise_id}.json").is_file()
            else None
        ),
    )
    config = {
        "workoutPlanPath": str(tmp_path / "plan.json"),
        "exerciseMotionContractCacheSeed": {
            "sourceDir": str(source_dir),
            "sha256ByExerciseId": {"press": source_digest},
        },
    }

    seeded = seed_replay_contract_cache(config, tmp_path / "workspace")

    target_cache = tmp_path / "workspace/exercise-motion-contract-cache/press.json"
    assert target_cache.read_bytes() == source_cache.read_bytes()
    assert seeded == [{"exerciseId": "press", "cachePath": str(target_cache.resolve()), "sha256": source_digest}]
    config["exerciseMotionContractCacheSeed"]["sha256ByExerciseId"]["press"] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        seed_replay_contract_cache(config, tmp_path / "another-workspace")


def test_retained_replay_keeps_real_review_owner_and_rejects_unpinned_discovery():
    review_owner = object()
    module = SimpleNamespace(LlamaCppVisionRanker=review_owner,
                             parse_yt_dlp_search_results=lambda payload: payload["entries"])
    config = {"exerciseFixtures": {"press": {
        "exerciseName": "Overhead Press", "videoId": "pinned-video",
        "candidateTitle": "Actual source", "channel": "Actual channel", "durationSeconds": 3,
    }}}
    patch_module("exercise_motion_pkg.youtube", module, config, lambda *a, **k: None)
    assert module.LlamaCppVisionRanker is review_owner
    assert module.search_youtube('"Overhead Press" demonstration', 1)[0]["id"] == "pinned-video"
    with pytest.raises(AssertionError, match="Unpinned discovery"):
        module.search_youtube("A different movement", 1)


def test_retained_replay_uses_pinned_clip_when_final_validation_has_no_staged_video(
    tmp_path, monkeypatch
):
    from exercise_motion_pkg import bake_and_rank, pipeline, video_utils

    source = tmp_path / "source.mp4"
    raw = tmp_path / "motion.json"
    source.write_bytes(b"pinned source bytes")
    raw.write_text("{}", encoding="utf-8")

    def file_sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    workspace = tmp_path / "workspace"
    candidate_workspace = workspace / "press"
    evidence = candidate_workspace / "segment_detection"
    evidence.mkdir(parents=True)
    (evidence / "exact_source_pose_reference.json").write_text("{}", encoding="utf-8")
    (evidence / "segment_selection.json").write_text(json.dumps({
        "sourceVideoPath": str(source),
        "selectedSegmentPath": str(source),
        "selectedSpanInOriginalSource": {"startSeconds": 0.0, "endSeconds": 3.9},
    }), encoding="utf-8")
    monkeypatch.setattr(
        video_utils, "read_basic_video_metadata",
        lambda _path: SimpleNamespace(frame_count=117, fps=30.0),
    )
    monkeypatch.setattr(
        bake_and_rank, "exercise_motion_contract_from_candidate", lambda _candidate: None
    )
    monkeypatch.setattr(pipeline, "run_generation_pipeline", lambda request: request)
    fixture = {
        "videoId": "pinned-video", "exerciseName": "Overhead Press",
        "sourceVideoPath": str(source), "sourceVideoPathSha256": file_sha256(source),
        "normalizedMotionPath": str(raw), "normalizedMotionPathSha256": file_sha256(raw),
        "upstreamIdentity": {"extractor": "GVHMR"},
    }
    module = SimpleNamespace()
    config = {"exerciseFixtures": {"press": fixture}}
    patch_module("exercise_motion_pkg.bake_and_rank", module, config, lambda *_a, **_k: None)
    candidate = SimpleNamespace(
        exercise_id="press", workspace_slug="press", candidate={}, exercise_name="Overhead Press",
    )
    request = SimpleNamespace(
        workspace=workspace, motion_reconstruction_backend="wham",
        structural_refinement_enabled=True, motion_tuning_enabled=True,
    )

    result = module.generate_candidate_motion(candidate, request=request)

    assert result.video_path == source.resolve()
    assert result.normalized_motion_json == raw.resolve()


@pytest.mark.parametrize("defect", [None, "missing", "different_bytes"])
def test_retained_replay_checks_reviewed_package_outputs(tmp_path, defect):
    from scripts.run_motion_retained_replay import verify_replay_outputs
    from scripts import build_workout_plan_movement_package as builder
    from test_build_workout_plan_movement_package import write_reviewed_movement

    workspace = tmp_path / "workspace"
    path = workspace / "press/selected/movement.json"
    manifest = path.with_name("selection_manifest.json")
    write_reviewed_movement(path, manifest)
    summary = {"exercises": [{"exerciseId": "press", "status": "completed",
                               "selectedWearSkeletonPath": str(path),
                               "selectionManifestPath": str(manifest)}]}
    (workspace / "workout_motion_generation_summary.json").write_text(json.dumps(summary))
    text = builder.read_text_file(path)
    reference = {"movementId": "exercise-motion:press",
                 "contentHash": hashlib.sha256(text.encode()).hexdigest()}
    package = {"workouts": [{"workoutComponents": [{"type": "Exercise", "id": "press",
                                                     "movementRef": reference}]}],
               "exerciseMovements": [{"movementRef": reference,
                                       "compressedJsonBase64": builder.gzip_base64(text)}]}
    if defect == "missing":
        package["exerciseMovements"] = []
    elif defect == "different_bytes":
        package["exerciseMovements"][0]["compressedJsonBase64"] = builder.gzip_base64(text + " ")
    (tmp_path / "package.json").write_text(json.dumps(package))
    if defect:
        with pytest.raises(ValueError, match="package"):
            verify_replay_outputs(tmp_path, {"press"})
    else:
        verify_replay_outputs(tmp_path, {"press"})


def test_existing_workspace_replay_reruns_selected_generation(tmp_path, monkeypatch):
    from exercise_motion_pkg import video_utils
    from scripts import run_motion_retained_replay as replay

    source = tmp_path / "source.mp4"
    source.write_bytes(b"pinned source bytes")
    existing_workspace = tmp_path / "existing-workspace"
    existing_workspace.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "mode": "fresh_reconstruction_real_review",
        "workoutPlanPath": str(tmp_path / "plan.json"),
        "exerciseFixtures": {
            "press": {
                "sourceVideoPath": str(source),
                "sourceVideoPathSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(
        video_utils, "read_basic_video_metadata",
        lambda _path: SimpleNamespace(frame_count=10, fps=30.0),
    )
    monkeypatch.setattr(replay, "seed_replay_contract_cache", lambda *_args: [])
    monkeypatch.setattr(replay, "verify_replay_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        replay, "run_bounded_process",
        lambda command, **_kwargs: (0, False),
    )

    run_root = tmp_path / "run"
    assert replay.run_replay(
        config_path,
        run_root,
        python_command=None,
        timeout_seconds=300,
        existing_workspace_root=existing_workspace,
    ) == 0

    command = json.loads((run_root / "command.json").read_text(encoding="utf-8"))
    assert "-ReuseExistingSelected" not in command
    assert "-DisableMotionProcessingResume" in command
    assert "-WorkspaceRoot" in command
    result = json.loads((run_root / "process_result.json").read_text(encoding="utf-8"))
    assert "attempt outputs isolated" in result["reconstructionBoundary"]

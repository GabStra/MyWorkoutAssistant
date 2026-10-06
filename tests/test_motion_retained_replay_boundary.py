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

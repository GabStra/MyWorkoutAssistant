from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def write_fake_motion_cli(tmp_path: Path) -> tuple[Path, Path]:
    fake_cli = tmp_path / "fake_motion_cli.py"
    fake_cli.write_text(
        textwrap.dedent(
            r"""
            import json
            import os
            import sys
            from pathlib import Path


            def arg_value(args, name, default=None):
                try:
                    return args[args.index(name) + 1]
                except ValueError:
                    return default


            def slugify(value):
                result = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
                while "--" in result:
                    result = result.replace("--", "-")
                return result or "exercise"


            def append_log(command):
                log_path = os.environ.get("FAKE_MOTION_CLI_LOG")
                if log_path:
                    with open(log_path, "a", encoding="utf-8") as handle:
                        handle.write(command + "\n")


            args = sys.argv[1:]
            command = args[2] if len(args) >= 3 and args[0] == "-m" and args[1] == "exercise_motion_pkg.cli" else None
            append_log(command or "unknown")

            if command == "list-workout-plan-exercises":
                out_json = Path(arg_value(args, "--out-json"))
                plan = json.loads(Path(arg_value(args, "--workout-plan-json")).read_text(encoding="utf-8"))
                exercises = []
                for item in plan["exercises"]:
                    name = item["name"]
                    exercise_id = item["id"]
                    exercises.append(
                        {
                            "exerciseId": exercise_id,
                            "exerciseName": name,
                            "slug": slugify(exercise_id),
                            "sourceExerciseName": name,
                            "equipmentQualifiedExerciseName": name,
                        }
                    )
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps({"exercises": exercises}), encoding="utf-8")
                raise SystemExit(0)

            if command == "find-youtube-videos":
                out_json = Path(arg_value(args, "--out-json"))
                plan = json.loads(Path(arg_value(args, "--workout-plan-json")).read_text(encoding="utf-8"))
                exercise = plan["exercises"][0]
                name = exercise["name"]
                exercise_id = exercise["id"]
                slug = slugify(exercise_id)
                candidate = {
                    "title": f"{name} tutorial",
                    "url": f"https://www.youtube.com/watch?v={slug[:11].ljust(11, 'x')}",
                    "webpageUrl": f"https://www.youtube.com/watch?v={slug[:11].ljust(11, 'x')}",
                    "videoId": slug[:11].ljust(11, "x"),
                    "status": "recommended",
                    "finalScore": 0.95,
                    "visionPayload": {"bestChunkScore": 0.95, "validChunkCount": 1, "scoredChunkCount": 1},
                }
                manifest = {
                    "schemaVersion": 1,
                    "ranking": {"searchElapsedSeconds": 0.01, "posePrefilterEnabled": False},
                    "exercises": [
                        {
                            "exerciseId": exercise_id,
                            "exerciseName": name,
                            "slug": slug,
                            "candidates": [candidate],
                        }
                    ],
                }
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(manifest), encoding="utf-8")
                raise SystemExit(0)

            if command == "bake-and-rank":
                candidates_json = Path(arg_value(args, "--candidates-json"))
                workspace = Path(arg_value(args, "--workspace"))
                payload = json.loads(candidates_json.read_text(encoding="utf-8"))
                exercise = payload["exercises"][0]
                selected_dir = workspace / "fake_selected"
                selected_dir.mkdir(parents=True, exist_ok=True)
                skeleton_path = selected_dir / "wear_skeleton.json"
                review_video_path = selected_dir / "review.webm"
                input_video_path = selected_dir / "input.mp4"
                preview_html_path = selected_dir / "preview.html"
                source_preview_html_path = selected_dir / "motion_preview.html"
                skeleton_path.write_text("{}", encoding="utf-8")
                review_video_path.write_bytes(b"webm")
                input_video_path.write_bytes(b"mp4")
                preview_html_path.write_text("<html></html>", encoding="utf-8")
                source_preview_html_path.write_text("<html>interactive</html>", encoding="utf-8")
                selected = {
                    "exerciseName": exercise["exerciseName"],
                    "candidateTitle": exercise["candidates"][0]["title"],
                    "selectedWearSkeletonPath": str(skeleton_path),
                    "selectedReviewVideoPath": str(review_video_path),
                    "selectedInputVideoPath": str(input_video_path),
                    "selectedPreviewHtmlPath": str(preview_html_path),
                    "sourcePreviewHtmlPath": str(source_preview_html_path),
                    "selectedSectionStartSeconds": 1.25,
                    "selectedSectionEndSeconds": 4.75,
                    "settingsOptions": {
                        "autoWorldAlignment": True,
                        "sceneInverted": True,
                        "lockPlantedFeet": True,
                        "lockPlantedHands": False,
                    },
                    "wearSkeletonSettingsBaked": True,
                    "selectionScore": 0.9,
                }
                manual_review = os.environ.get("FAKE_MOTION_MANUAL_REVIEW") == "1"
                selection = {
                    "schemaVersion": 1,
                    "sourceCandidatesJson": str(candidates_json),
                    "timings": {
                        "totalSeconds": 0.2,
                        "candidateProcessingSeconds": 0.1,
                        "processedCandidateCount": 1,
                        "readyCandidateCount": 1,
                        "reviewRankingSeconds": 0.01,
                        "selectionMaterializationSeconds": 0.01,
                    },
                    "candidateResults": [
                        {
                            "status": "ready_for_selection",
                            "whamCacheStatus": "generated",
                            "generationTimings": {
                                "sourcePreparationSeconds": 0.01,
                                "wham": {"elapsedSeconds": 0.02, "dockerLockWaitSeconds": 0.0},
                            },
                            "timings": {"previewBakeSeconds": 0.03},
                        }
                    ],
                    "selectedResultCount": 0 if manual_review else 1,
                    "selectedResults": [] if manual_review else [selected],
                    "selected": None if manual_review else selected,
                    "manualReviewFallback": (
                        {
                            **selected,
                            "selectionStatus": "needs_manual_review",
                            "rejectionReason": "automatic_acceptance_gate_failed",
                        }
                        if manual_review
                        else None
                    ),
                }
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "selection_manifest.json").write_text(json.dumps(selection), encoding="utf-8")
                raise SystemExit(0)

            raise SystemExit(f"unexpected command: {command}")
            """
        ).lstrip(),
        encoding="utf-8",
    )

    fake_cmd = tmp_path / "fake_python.cmd"
    fake_cmd.write_text(f'@echo off\r\n"{sys.executable}" "{fake_cli}" %*\r\n', encoding="utf-8")
    return fake_cli, fake_cmd


def write_workout_plan(tmp_path: Path, exercise_count: int = 3) -> Path:
    exercises = [
        {"id": "bench", "name": "Barbell Bench Press"},
        {"id": "squat", "name": "Barbell Back Squat"},
        {"id": "pullup", "name": "Weighted Pull-Up"},
    ][:exercise_count]
    workout_plan = tmp_path / "workout_plan.json"
    workout_plan.write_text(json.dumps({"exercises": exercises}), encoding="utf-8")
    return workout_plan


def test_workout_plan_wrappers_disable_total_wall_clock_timeouts_by_default() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "scripts/run_exercise_motion_workout_plan.ps1",
        "scripts/run_exercise_motion_youtube_bake_and_rank.ps1",
    ):
        script = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "[double]$CandidateTimeoutSeconds = 0.0" in script
        assert "[double]$ExerciseTimeoutSeconds = 0.0" in script
        assert '"--candidate-timeout-seconds", "$CandidateTimeoutSeconds"' in script
        assert '"--exercise-timeout-seconds", "$ExerciseTimeoutSeconds"' in script


def test_workout_plan_wrapper_starts_with_initial_suitable_target() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert script.count('$targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)') == 2
    assert '$targetSuitableCount = [Math]::Max(1, $MaxTargetSuitableCount)' not in script


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_pipelines_discovery_and_bake(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-WhamRepoPath",
            str(wham_repo),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-BakeWorkers",
            "1",
            "-DiscoveryWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-NoWhamDocker",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreWhamSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    first_bake_index = commands.index("bake-and-rank")
    assert commands.count("find-youtube-videos") == 3
    assert commands.count("bake-and-rank") == 3
    assert commands[:first_bake_index].count("find-youtube-videos") < 3

    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["processingOrder"] == "pipelined_discovery_and_bake"
    assert summary["speedProfile"] == "fast"
    assert summary["discoveryWorkers"] == 1
    assert summary["bakeWorkers"] == 1
    assert summary["parallelism"]["llamaCppParallel"] == 1
    assert summary["parallelism"]["activeDiscoveryWorkerBudget"] == 1
    assert summary["parallelism"]["discoveryVisionLlmWorkers"] == 1
    assert summary["parallelism"]["requestedVisionLlmWorkers"] is None
    assert summary["parallelism"]["reviewLlmWorkers"] == 1
    assert summary["parallelism"]["segmentClassificationWorkers"] == 1
    assert summary["parallelism"]["visionDownloadWorkers"] == 8
    assert summary["parallelism"]["gpuDiscoveryStages"] == []
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "allow"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 4
    assert summary["llamaCppRuntime"]["ctxSize"] == 8192
    assert summary["llamaCppRuntime"]["fitCtx"] == 8192
    assert summary["llamaCppRuntime"]["batchSize"] == 256
    assert summary["llamaCppRuntime"]["ubatchSize"] == 512
    assert summary["llamaCppRuntime"]["imageMaxTokens"] == 2048
    assert summary["llamaCppRuntime"]["mtmdBatchMaxTokens"] == 768
    assert summary["smplifyEnabled"] is False
    assert summary["effectiveCandidateBudget"]["candidateReviewTargetSuitableCount"] == 1
    assert summary["effectiveCandidateBudget"]["fallbackCandidates"] == 6
    assert [item["status"] for item in summary["exercises"]] == ["completed", "completed", "completed"]
    for exercise in summary["exercises"]:
        assert [attempt["stage"] for attempt in exercise["attempts"]] == [
            "initial_discovery",
            "pre_discovered_candidates",
            "bake",
        ]
        assert exercise["timings"]["discoveryAttempts"] == 1
        assert exercise["timings"]["bakeAttempts"] == 1
        assert exercise["timings"]["selection"]["whamGeneratedCount"] == 1
        assert exercise["timings"]["selection"]["whamRunSeconds"] == pytest.approx(0.02)
        selected = exercise["selectedResults"][0]
        selected_preview_html = Path(selected["selectedPreviewHtmlPath"])
        selected_preview_video = Path(selected["selectedPreviewVideoPath"])
        selected_source_video = Path(selected["selectedSourceVideoPath"])
        selected_interactive_preview_html = Path(selected["selectedInteractivePreviewHtmlPath"])
        selected_skeleton = Path(selected["selectedWearSkeletonPath"])
        html = selected_preview_html.read_text(encoding="utf-8")
        assert selected_interactive_preview_html.exists()
        assert selected_interactive_preview_html.read_text(encoding="utf-8") == "<html>interactive</html>"
        assert selected_interactive_preview_html.name in html
        assert "startSeconds=1.250000" in html
        assert "endSeconds=4.750000" in html
        assert "options=" in html
        assert "%22sceneInverted%22%3Atrue" in html
        assert "%22lockPlantedFeet%22%3Atrue" in html
        assert "%22cameraYawDegrees%22%3A45" in html
        assert "%22cameraPitchDegrees%22%3A30" in html
        assert selected_preview_video.name in html
        assert selected_source_video.name in html
        assert selected_skeleton.name in html
        assert "fake_selected" not in html


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_publishes_manual_review_fallback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    env = os.environ.copy()
    env["FAKE_MOTION_MANUAL_REVIEW"] = "1"

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-WhamRepoPath",
            str(wham_repo),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-BakeWorkers",
            "1",
            "-DiscoveryWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-NoWhamDocker",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreWhamSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    exercise = summary["exercises"][0]
    assert exercise["status"] == "needs_manual_review"
    manual_review_dir = workspace / "bench" / "manual-review"
    assert Path(exercise["selectionManifestPath"]) == manual_review_dir / "selection_manifest.json"
    assert Path(exercise["selectedWearSkeletonPath"]).exists()
    assert Path(exercise["selectedPreviewVideoPath"]).exists()
    assert Path(exercise["selectedPreviewHtmlPath"]).exists()
    assert Path(exercise["selectedSourceVideoPath"]).exists()
    html = Path(exercise["selectedPreviewHtmlPath"]).read_text(encoding="utf-8")
    assert "Manual review" in html
    assert Path(exercise["selectedPreviewVideoPath"]).name in html
    assert Path(exercise["selectedSourceVideoPath"]).name in html


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_serializes_cuda_yolo_discovery_against_bake_by_default(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=2)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-WhamRepoPath",
            str(wham_repo),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-BakeWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-NoWhamDocker",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPreWhamSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["processingOrder"] == "pipelined_discovery_and_bake"
    assert summary["discoveryWorkers"] == 1
    assert summary["parallelism"]["gpuDiscoveryStages"] == ["yolo_pose_prefilter"]
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "avoid"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 1


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_rejects_non_cuda_pose_prefilter_device(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-WhamRepoPath",
            str(wham_repo),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-PosePrefilterDevice",
            "cpu",
            "-NoWhamDocker",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPreWhamSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "YOLO pose prefilter must use CUDA" in result.stdout + result.stderr

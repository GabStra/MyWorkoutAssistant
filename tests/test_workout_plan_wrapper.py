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
            import hashlib
            import json
            import os
            import sys
            import time
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
                if "--prefetch-only" in args:
                    source_plan_path = Path(arg_value(args, "--workout-plan-json"))
                    manifest.update(
                        {
                            "kind": "youtube_candidate_prefetch",
                            "sourcePlanPath": str(source_plan_path),
                            "sourcePlanSha256": hashlib.sha256(source_plan_path.read_bytes()).hexdigest(),
                            "equipmentJsonPath": None,
                            "equipmentSha256": None,
                        }
                    )
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(manifest), encoding="utf-8")
                raise SystemExit(0)

            if command == "prefetch-youtube-sources":
                candidates_json = Path(arg_value(args, "--candidates-json"))
                out_json = Path(arg_value(args, "--out-json"))
                source_cache = Path(arg_value(args, "--youtube-source-cache-dir"))
                payload = json.loads(candidates_json.read_text(encoding="utf-8"))
                candidate = payload["exercises"][0]["candidates"][0]
                source_cache.mkdir(parents=True, exist_ok=True)
                source_path = source_cache / f"{candidate['videoId']}.mp4"
                source_path.write_bytes(b"source")
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "results": [
                                {
                                    "videoId": candidate["videoId"],
                                    "status": "downloaded",
                                    "path": str(source_path),
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                raise SystemExit(0)

            if command == "bake-and-rank":
                staged_wave_manifest = arg_value(args, "--staged-wave-manifest")
                if staged_wave_manifest:
                    wave = json.loads(Path(staged_wave_manifest).read_text(encoding="utf-8-sig"))
                    wave_workspace = Path(wave["workspace"])
                    wave_workspace.mkdir(parents=True, exist_ok=True)
                    item_states = [
                        {
                            "exerciseId": item["exerciseId"],
                            "exerciseName": item["exerciseName"],
                            "status": "pending",
                            "source": {"status": "prepared", "attempts": []},
                            "wham": {"status": "pending"},
                            "finalValidation": {"status": "pending"},
                        }
                        for item in wave["items"]
                    ]
                    checkpoint = {
                        "schemaVersion": 1,
                        "waveId": wave["waveId"],
                        "stage": "wham_generation",
                        "elapsedSeconds": 0.1,
                        "items": item_states,
                    }
                    (wave_workspace / "staged_wave_checkpoint.json").write_text(
                        json.dumps(checkpoint), encoding="utf-8"
                    )
                    time.sleep(2.5)
                    for state in item_states:
                        state["status"] = "retry_required"
                        state["wham"] = {"status": "failed", "error": "fake staged retry"}
                    report = {
                        **checkpoint,
                        "stage": "completed",
                        "items": item_states,
                        "completedExerciseCount": 0,
                        "retryExerciseCount": len(item_states),
                        "retryExerciseIds": [state["exerciseId"] for state in item_states],
                    }
                    (wave_workspace / "staged_wave_report.json").write_text(
                        json.dumps(report), encoding="utf-8"
                    )
                    raise SystemExit(0)

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
                three_module_path = selected_dir / "three.module.0.169.0.js"
                segment_detection_dir = selected_dir / "segment_detection"
                segment_detection_dir.mkdir(parents=True, exist_ok=True)
                source_pose_reference_path = segment_detection_dir / "exact_source_pose_reference.json"
                exact_source_validation_path = segment_detection_dir / "exact_source_phase_validation.json"
                segment_selection_path = segment_detection_dir / "segment_selection.json"
                skeleton_path.write_text(
                    json.dumps(
                        {
                            "selectedPreviewSettings": {
                                "cameraYawDegrees": 90.0,
                                "cameraPitchDegrees": 35.264389682754654,
                            },
                            "wearDisplay": {
                                "viewYawDegrees": 135.0,
                                "viewPitchDegrees": 35.264389682754654,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                review_video_path.write_bytes(b"webm")
                input_video_path.write_bytes(b"mp4")
                preview_html_path.write_text("<html></html>", encoding="utf-8")
                source_preview_html_path.write_text("<html>interactive</html>", encoding="utf-8")
                three_module_path.write_text("export const WebGLRenderer = class {};", encoding="utf-8")
                source_pose_reference_path.write_text(
                    json.dumps({"schemaVersion": 1, "pose": {"frames": []}}), encoding="utf-8"
                )
                exact_source_validation = {
                    "validationPolicyVersion": 1,
                    "passed": True,
                    "metrics": {"sourcePoseReferencePath": str(source_pose_reference_path)},
                }
                exact_source_validation_path.write_text(
                    json.dumps(exact_source_validation), encoding="utf-8"
                )
                segment_selection_path.write_text(
                    json.dumps({"exactSourcePhaseValidation": exact_source_validation}), encoding="utf-8"
                )
                selected = {
                    "exerciseName": exercise["exerciseName"],
                    "candidateTitle": exercise["candidates"][0]["title"],
                    "selectedWearSkeletonPath": str(skeleton_path),
                    "selectedReviewVideoPath": str(review_video_path),
                    "selectedInputVideoPath": str(input_video_path),
                    "selectedPreviewHtmlPath": str(preview_html_path),
                    "sourcePreviewHtmlPath": str(source_preview_html_path),
                    "candidateWorkspace": str(selected_dir),
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


def test_youtube_discovery_wrappers_keep_semantic_gate_budget_independent_of_attempt_max() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    youtube_bake = (repo_root / "scripts/run_exercise_motion_youtube_bake_and_rank.ps1").read_text(encoding="utf-8")
    workout_plan = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    for script in (youtube_bake, workout_plan):
        assert "--semantic-gate-candidates-per-exercise\" -Value \"$attemptMaxCandidates\"" not in script
        assert "--semantic-gate-max-candidates-per-exercise\" -Value \"$attemptMaxCandidates\"" not in script
        assert '"--semantic-gate-max-candidates-per-exercise", "$SemanticGateMaxCandidatesPerExercise"' in script


def test_youtube_bake_wrapper_passes_exercise_motion_contract_cache_dir() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_youtube_bake_and_rank.ps1").read_text(encoding="utf-8")

    assert "[string]$ExerciseMotionContractCacheDir" in script
    assert '"--exercise-motion-contract-cache-dir", $contractCachePath' in script
    assert 'Join-Path $repoRoot "build\\exercise_motion\\exercise-library\\exercise-motion-contract-cache"' in script
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


def test_motion_wrappers_default_structured_vlm_calls_to_deterministic_decoding() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "scripts/run_exercise_motion_workout_plan.ps1",
        "scripts/run_exercise_motion_youtube_bake_and_rank.ps1",
        "scripts/run_exercise_motion_bake_and_rank.ps1",
        "scripts/run_exercise_motion_generation.ps1",
        "scripts/run_exercise_segment_detection.ps1",
    ):
        script = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "[double]$LlamaCppTemperature = 0.0" in script
        assert "[Nullable[double]]$LlamaCppTopP = 1.0" in script
        assert "[Nullable[int]]$LlamaCppTopK = 0" in script


def test_workout_plan_wrapper_starts_with_initial_suitable_target() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert script.count('$targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)') == 2
    assert '$targetSuitableCount = [Math]::Max(1, $MaxTargetSuitableCount)' not in script


def test_workout_plan_wrapper_acknowledges_ctrl_c_immediately() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    interrupt = (repo_root / "scripts/motion_run_interrupt.ps1").read_text(encoding="utf-8")

    assert "motion_run_interrupt.ps1" in script
    assert "MotionRunInterrupt" in interrupt
    assert "RegisterOnce" in interrupt
    assert "Register-MotionInterruptHandler -Silent" not in script
    assert "TryAcknowledge" in interrupt
    assert "Ctrl+C received. Stopping the motion run" in interrupt
    assert "Stopping background jobs and the motion extractor..." in script
    assert "Motion run stopped." in script
    assert "if (Test-MotionRunCancelRequested) {" in script
    assert "exit 130" in script


def test_workout_plan_defer_after_first_attempt_allows_two_final_rejections() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert "$MaxFinalOutputRejections = 2" in script
    assert "if ($DeferAfterFirstAttempt)" in script


def test_workout_plan_wrapper_mobile_package_output_is_strict_and_completion_gated() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[string]$MobilePackageOutputJson = ""' in script
    assert 'Mobile package was not created because these requested exercises are incomplete' in script
    assert '-WorkoutPlanPackageJson $resolvedWorkoutPlanJson' in script
    assert '-MotionSummaryJson $summaryPath' in script
    assert '-OutputJson $resolvedRequestedMobilePackageOutputJson' in script
    assert '-StrictIdMatch' in script


def test_workout_plan_wrapper_supports_incremental_mobile_packages() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[string]$IncrementalMobilePackageOutputJson = ""' in script
    assert 'Update-IncrementalMobilePackage -SuccessfulCount $successfulItems.Count' in script
    assert '-MotionSummaryJson $progressCheckpointPath' in script
    assert '-AllowEmpty' in script


def test_workout_plan_wrapper_defaults_youtube_search_timeout_to_sixty_seconds() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[double]$YouTubeSearchTimeoutSeconds = 60.0' in script
    assert '"--youtube-search-timeout-seconds", "$YouTubeSearchTimeoutSeconds"' in script


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_builds_mobile_package_directly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    mobile_package = tmp_path / "workout_plan_with_movements.json"
    incremental_mobile_package = tmp_path / "workout_plan_with_incremental_movements.json"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    plan_payload = json.loads(workout_plan.read_text(encoding="utf-8"))
    plan_payload.update(
        {
            "name": "Generated Plan",
            "workouts": [
                {
                    "workoutComponents": [
                        {
                            "type": "Exercise",
                            "id": "bench",
                            "name": "Barbell Bench Press",
                            "sets": [],
                        }
                    ]
                }
            ],
            "equipments": [],
            "accessoryEquipments": [],
        }
    )
    workout_plan.write_text(json.dumps(plan_payload), encoding="utf-8")
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
            "-MobilePackageOutputJson",
            str(mobile_package),
            "-IncrementalMobilePackageOutputJson",
            str(incremental_mobile_package),
            "-WhamRepoPath",
            str(wham_repo),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-NoWhamDocker",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreWhamSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Mobile package updated: 1 approved movement(s) at {incremental_mobile_package}" in result.stdout
    assert f"Mobile workout-plan package: {mobile_package}" in result.stdout
    package = json.loads(mobile_package.read_text(encoding="utf-8"))
    exercise = package["workouts"][0]["workoutComponents"][0]
    assert exercise["movementRef"]["movementId"] == "exercise-motion:bench"
    assert len(package["exerciseMovements"]) == 1
    incremental_package = json.loads(incremental_mobile_package.read_text(encoding="utf-8"))
    incremental_exercise = incremental_package["workouts"][0]["workoutComponents"][0]
    assert incremental_exercise["movementRef"]["movementId"] == "exercise-motion:bench"
    assert len(incremental_package["exerciseMovements"]) == 1


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
    assert "movements ready" in result.stdout
    commands = command_log.read_text(encoding="utf-8").splitlines()
    first_bake_index = commands.index("bake-and-rank")
    assert commands.count("find-youtube-videos") == 3
    assert commands.count("bake-and-rank") == 3
    assert commands.count("prefetch-youtube-sources") == 3
    assert "prefetch-youtube-sources" in commands[:first_bake_index]

    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["processingOrder"] == "pipelined_discovery_source_download_and_bake"
    assert summary["speedProfile"] == "fast"
    assert summary["discoveryWorkers"] == 1
    assert summary["bakeWorkers"] == 1
    assert summary["parallelism"]["llamaCppParallel"] == 4
    assert summary["parallelism"]["llamaCppThreadsHttp"] == 8
    assert summary["parallelism"]["activeDiscoveryWorkerBudget"] == 1
    assert summary["parallelism"]["discoveryVisionLlmWorkers"] == 4
    assert summary["parallelism"]["requestedVisionLlmWorkers"] is None
    assert summary["parallelism"]["reviewLlmWorkers"] == 4
    assert summary["parallelism"]["semanticGateLlmWorkers"] == 4
    assert summary["parallelism"]["segmentClassificationWorkers"] == 4
    assert summary["parallelism"]["visionDownloadWorkers"] == 8
    assert summary["parallelism"]["gpuDiscoveryStages"] == []
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "allow"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 4
    assert summary["llamaCppRuntime"]["ctxSize"] == 32768
    assert summary["llamaCppRuntime"]["fitCtx"] == 32768
    assert summary["llamaCppRuntime"]["batchSize"] == 256
    assert summary["llamaCppRuntime"]["ubatchSize"] == 512
    assert summary["llamaCppRuntime"]["imageMaxTokens"] == 2048
    assert summary["llamaCppRuntime"]["mtmdBatchMaxTokens"] == 768
    assert summary["smplifyEnabled"] is False
    assert summary["effectiveCandidateBudget"]["candidateReviewTargetSuitableCount"] == 2
    assert summary["effectiveCandidateBudget"]["fallbackCandidates"] == 6
    assert [item["status"] for item in summary["exercises"]] == ["completed", "completed", "completed"]
    for exercise in summary["exercises"]:
        exercise_log = Path(exercise["logPath"]).read_text(encoding="utf-8")
        assert "workout-plan movement run started; run id " in exercise_log
        assert "initial discovery attempt 1 finished with exit code 0" in exercise_log
        assert "bake attempt 1 finished with exit code 0; selected 1/1 result(s)" in exercise_log
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
        assert (selected_interactive_preview_html.parent / "three.module.0.169.0.js").exists()
        assert selected_interactive_preview_html.name in html
        assert "startSeconds=1.250000" in html
        assert "endSeconds=4.750000" in html
        assert "options=" in html
        assert "%22sceneInverted%22%3Atrue" in html
        assert "%22lockPlantedFeet%22%3Atrue" in html
        assert "%22cameraYawDegrees%22%3A90" in html
        assert "%22cameraPitchDegrees%22%3A35.264389682754654" in html
        assert "%22cameraYawDegrees%22%3A45" not in html
        assert selected_preview_video.name in html
        assert selected_source_video.name in html
        assert selected_skeleton.name in html
        assert "fake_selected" not in html
        retained_audit_dir = Path(selected["selectedSourceAuditDirectory"])
        retained_pose_path = retained_audit_dir / "exact_source_pose_reference.json"
        retained_validation_path = retained_audit_dir / "exact_source_phase_validation.json"
        retained_selection_path = retained_audit_dir / "segment_selection.json"
        assert retained_pose_path.exists()
        assert retained_validation_path.exists()
        assert retained_selection_path.exists()
        retained_validation = json.loads(retained_validation_path.read_text(encoding="utf-8-sig"))
        assert Path(retained_validation["metrics"]["sourcePoseReferencePath"]) == retained_pose_path
        retained_selection = json.loads(retained_selection_path.read_text(encoding="utf-8-sig"))
        assert Path(
            retained_selection["exactSourcePhaseValidation"]["metrics"]["sourcePoseReferencePath"]
        ) == retained_pose_path


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_reports_staged_wham_progress(tmp_path: Path) -> None:
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
            "-StagedWaveSize",
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
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Extracting motion: 0 of 1 done" in result.stdout
    assert "1 still running" in result.stdout


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_reuses_exact_unchanged_candidate_prefetch(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    command = [
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
        "-CpuPrefetchDuringBake",
        "-NoWhamDocker",
        "-SkipVisionRanking",
        "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner",
        "-SkipPosePrefilter",
        "-SkipPreWhamSourceValidation",
        "-SkipFinalOutputValidation",
    ]

    first = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert first_commands.count("find-youtube-videos") == 2

    second = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    all_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert all_commands.count("find-youtube-videos") == 3
    assert "reused unchanged CPU/network candidate prefetch" in (
        workspace / "bench" / "bake.log"
    ).read_text(encoding="utf-8")
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["exercises"][0]["timings"]["prefetchReused"] is True
    assert summary["exercises"][0]["timings"]["prefetchSeconds"] == pytest.approx(0.0)

    changed = subprocess.run(
        [*command, "-ResultsPerQuery", "99"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr
    changed_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert changed_commands.count("find-youtube-videos") == 5
    changed_summary = json.loads(
        (workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8")
    )
    assert changed_summary["exercises"][0]["timings"]["prefetchReused"] is False


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_resumes_from_durable_discovery_and_source_downloads(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    wham_repo = tmp_path / "WHAM"
    body_models = wham_repo / "dataset" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    command = [
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
        "-ArtifactRetention",
        "full",
        "-NoWhamDocker",
        "-SkipVisionRanking",
        "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner",
        "-SkipPosePrefilter",
        "-SkipPreWhamSourceValidation",
        "-SkipFinalOutputValidation",
    ]

    first = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert first_commands.count("find-youtube-videos") == 1
    assert first_commands.count("prefetch-youtube-sources") == 1
    assert first_commands.count("bake-and-rank") == 1

    second = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    second_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert second_commands.count("find-youtube-videos") == 1
    assert second_commands.count("prefetch-youtube-sources") == 1
    assert second_commands.count("bake-and-rank") == 2
    second_summary = json.loads(
        (workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8")
    )
    timings = second_summary["exercises"][0]["timings"]
    assert timings["discoveryReused"] is True
    assert timings["primarySourceDownloadReused"] is True

    source_report = json.loads(
        (workspace / "bench" / "youtube_source_prefetch.json").read_text(encoding="utf-8")
    )
    Path(source_report["results"][0]["path"]).unlink()
    third = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert third.returncode == 0, third.stdout + third.stderr
    third_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert third_commands.count("find-youtube-videos") == 1
    assert third_commands.count("prefetch-youtube-sources") == 2
    assert third_commands.count("bake-and-rank") == 3

    fresh = subprocess.run(
        [*command, "-DisableStageResume"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    fresh_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert fresh_commands.count("find-youtube-videos") == 2
    assert fresh_commands.count("prefetch-youtube-sources") == 3
    assert fresh_commands.count("bake-and-rank") == 4


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
def test_workout_plan_wrapper_avoids_cuda_discovery_overlap_with_bake_by_default(tmp_path: Path) -> None:
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
    assert summary["processingOrder"] == "pipelined_discovery_source_download_and_bake"
    assert summary["discoveryWorkers"] == 1
    assert summary["bakeWorkers"] == 2
    assert summary["parallelism"]["gpuDiscoveryStages"] == ["yolo_pose_prefilter"]
    assert summary["parallelism"]["globalGpuLockEnabled"] is True
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "avoid"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 1
    for exercise_workspace in workspace.iterdir():
        if not exercise_workspace.is_dir() or not (exercise_workspace / "bake.log").exists():
            continue
        assert (exercise_workspace / "source_download.primary.log").exists()
        assert "full-source download prefetch" not in (
            exercise_workspace / "bake.log"
        ).read_text(encoding="utf-8")


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


def test_staged_fallback_retries_rotate_between_exercises() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert "YieldAfterUnsuccessfulBake" in script
    assert 'status = "retry_pending"' in script
    assert "$pendingLegacyBakeItems.Enqueue($retryWorkItem)" in script
    assert "individualRetryPassCount" in script

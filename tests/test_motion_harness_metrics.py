import hashlib
import json
import re
from pathlib import Path

from scripts import motion_speed_harness


def _write_wave_report(workspace, wave_id, cumulative_handoffs):
    wave_dir = workspace / "staged-waves" / wave_id
    wave_dir.mkdir(parents=True)
    snapshot = {
        "sharedVisionQuiesceCount": cumulative_handoffs,
        "sharedVisionRestartRequestCount": cumulative_handoffs,
    }
    report = {
        "waveId": wave_id,
        "items": [],
        "metrics": {
            "phaseTimings": {},
            "sourceVisionSession": {
                "visionRankerStartupCount": 2,
                "sharedVisionSession": snapshot,
            },
            "finalVisionSession": {
                "visionRankerStartupCount": 1,
                "sharedVisionSession": snapshot,
            },
        },
    }
    (wave_dir / "staged_wave_report.json").write_text(json.dumps(report), encoding="utf-8")


def test_shared_session_cumulative_counters_are_not_summed_across_snapshots(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_wave_report(workspace, "wave-1", cumulative_handoffs=4)
    _write_wave_report(workspace, "wave-2", cumulative_handoffs=5)

    metrics = motion_speed_harness.extract_metrics({"workspace": str(workspace)})

    assert metrics["sharedQuiesceCount"] == 5
    assert metrics["sharedRestartRequests"] == 5
    assert metrics["visionStartups"] == 6


def test_metric_input_snapshot_excludes_later_waves_and_mutated_manifests(tmp_path):
    workspace = tmp_path / "workspace"
    first_wave = workspace / "staged-waves" / "run-one-wave-1"
    candidate_workspace = workspace / "exercise" / "candidate"
    (first_wave).mkdir(parents=True)
    selected_video = candidate_workspace / "input" / "selected_segment.mp4"
    selected_video.parent.mkdir(parents=True)
    selected_video.write_bytes(b"fixture video")
    manifest_path = candidate_workspace / "manifest.json"
    manifest_path.write_text(json.dumps({
        "timings": {
            "whamRunSeconds": 31.0,
            "wham": {
                "backend": "gvhmr",
                "returncode": 0,
                "elapsedSeconds": 29.0,
                "phaseTimings": {"inference": {"predictionSeconds": 5.0}},
            },
        },
    }), encoding="utf-8")
    (first_wave / "staged_wave_report.json").write_text(json.dumps({
        "waveId": "run-one-wave-1",
        "items": [],
        "metrics": {
            "phaseTimings": {"sourceValidationSeconds": 2.0},
            "resourceBudget": {"cpuFitSlots": 4},
            "sourceVisionSession": {"visionRequestCount": 3},
            "reviewQuestionCache": {"cacheHits": 2},
        },
    }), encoding="utf-8")
    (first_wave / "staged_wave_checkpoint.json").write_text(json.dumps({
        "waveId": "run-one-wave-1",
        "items": [{
            "wham": {"attempts": [{
                "elapsedSeconds": 50.0,
                "selectedVideoPath": str(selected_video),
            }]},
        }],
    }), encoding="utf-8")
    (workspace / "scheduler_timeline.json").write_text(json.dumps({
        "runStartedAtUtc": "2026-10-04T10:00:00Z",
        "items": [],
        "waves": [],
    }), encoding="utf-8")

    snapshot_path = tmp_path / "arm-one" / "metrics-input-snapshot.json"
    snapshot_path.parent.mkdir(parents=True)
    (snapshot_path.parent / "resource-samples.jsonl").write_text("\n".join([
        json.dumps({
            "elapsedSeconds": 20,
            "cpuUtilizationPercent": 71.0,
            "systemMemoryUsedBytes": 8_000,
            "systemMemoryUsedPercent": 62.0,
            "gpus": [{"utilizationPercent": 93.0, "memoryUsedMiB": 6_000, "memoryTotalMiB": 12_000}],
        }),
        json.dumps({
            "elapsedSeconds": 40,
            "cpuUtilizationPercent": 65.0,
            "systemMemoryUsedBytes": 9_000,
            "systemMemoryUsedPercent": 68.0,
            "gpus": [{"utilizationPercent": 78.0, "memoryUsedMiB": 7_000, "memoryTotalMiB": 12_000}],
        }),
    ]) + "\n", encoding="utf-8")
    motion_speed_harness.capture_metric_input_snapshot(workspace, snapshot_path)

    # A later replay appends another wave and rewrites the candidate manifest
    # at the same path. Neither may change the original arm's extracted result.
    later_wave = workspace / "staged-waves" / "run-two-wave-1"
    _write_wave_report(workspace, "run-two-wave-1", cumulative_handoffs=9)
    (later_wave / "staged_wave_checkpoint.json").write_text(json.dumps({
        "waveId": "run-two-wave-1",
        "items": [{
            "wham": {"attempts": [{
                "elapsedSeconds": 60.0,
                "selectedVideoPath": str(selected_video),
            }]},
        }],
    }), encoding="utf-8")
    manifest_path.write_text(json.dumps({
        "timings": {"whamRunSeconds": 99.0},
    }), encoding="utf-8")
    (workspace / "scheduler_timeline.json").write_text(json.dumps({
        "runStartedAtUtc": "2026-10-04T20:00:00Z",
        "items": [],
        "waves": [],
    }), encoding="utf-8")

    metrics = motion_speed_harness.extract_metrics({
        "workspace": str(workspace),
        "metricInputSnapshotPath": str(snapshot_path),
    })

    assert metrics["waves"] == 1
    assert metrics["waveIds"] == ["run-one-wave-1"]
    assert metrics["candidateGenerationAttempts"] == 1
    assert metrics["candidateGenerationAttemptSeconds"] == 50.0
    assert metrics["candidateGenerationTimingSamples"] == 1
    assert metrics["reconstructionStageWallSeconds"] == 31.0
    assert metrics["reconstructionStageCalls"] == 1
    assert metrics["reconstructionRunnerCalls"] == 1
    assert metrics["reconstructionRunnerCallSeconds"] == 29.0
    assert metrics["reconstructionPredictionSeconds"] == 5.0
    assert metrics["resourceMetricsByWave"][0]["resourceBudget"] == {"cpuFitSlots": 4}
    assert metrics["visionMetricsByWave"][0]["reviewQuestionCache"] == {"cacheHits": 2}
    assert metrics["resourceSampleCount"] == 2
    assert metrics["resourceHighWater"]["cpuUtilizationPercentMax"] == 71.0
    assert metrics["resourceHighWater"]["gpuUtilizationPercentMax"] == 93.0
    assert metrics["resourceHighWater"]["gpuMemoryUsedMiBMax"] == 7_000
    timeline = motion_speed_harness.load_scheduler_timeline({
        "workspace": str(workspace),
        "metricInputSnapshotPath": str(snapshot_path),
    })
    assert timeline["runStartedAtUtc"] == "2026-10-04T10:00:00Z"


def test_cached_reconstruction_timings_do_not_count_as_runner_calls(tmp_path):
    workspace = tmp_path / "workspace"
    wave_dir = workspace / "staged-waves" / "run-one-wave-1"
    _write_wave_report(workspace, "run-one-wave-1", cumulative_handoffs=0)
    (wave_dir / "staged_wave_checkpoint.json").write_text(json.dumps({
        "waveId": "run-one-wave-1",
        "items": [{
            "wham": {"attempts": [{
                "status": "prepared",
                "elapsedSeconds": 10.0,
                "reconstructionTimings": {
                    "wham": {"elapsedSeconds": 0.0, "cacheStatus": "reused"},
                },
            }]},
        }],
    }), encoding="utf-8")

    metrics = motion_speed_harness.extract_metrics({"workspace": str(workspace)})

    assert metrics["candidateGenerationTimingSamples"] == 1
    assert metrics["reconstructionStageCalls"] == 0
    assert metrics["reconstructionStageWallSeconds"] == 0.0
    assert metrics["reconstructionRunnerCalls"] == 0
    assert metrics["reconstructionRunnerCallSeconds"] == 0.0
    assert metrics["reconstructionBackends"] == {}


def test_generation_checkpoint_timings_survive_candidate_pruning(tmp_path):
    workspace = tmp_path / "workspace"
    wave_dir = workspace / "staged-waves" / "run-one-wave-1"
    _write_wave_report(workspace, "run-one-wave-1", cumulative_handoffs=0)
    missing_video = workspace / "pruned-candidate" / "input" / "selected_segment.mp4"
    (wave_dir / "staged_wave_checkpoint.json").write_text(json.dumps({
        "waveId": "run-one-wave-1",
        "items": [{
            "wham": {"attempts": [{
                "status": "prepared",
                "elapsedSeconds": 50.0,
                "selectedVideoPath": str(missing_video),
                "reconstructionTimings": {
                    "whamRunSeconds": 31.0,
                    "wham": {
                        "backend": "gvhmr",
                        "elapsedSeconds": 29.0,
                        "phaseTimings": {
                            "inference": {"predictionSeconds": 5.0},
                        },
                    },
                },
            }]},
        }],
    }), encoding="utf-8")
    snapshot_path = tmp_path / "arm" / "metrics-input-snapshot.json"
    snapshot_path.parent.mkdir()
    motion_speed_harness.capture_metric_input_snapshot(workspace, snapshot_path)

    metrics = motion_speed_harness.extract_metrics({
        "workspace": str(workspace),
        "metricInputSnapshotPath": str(snapshot_path),
    })

    assert metrics["candidateGenerationAttempts"] == 1
    assert metrics["candidateGenerationAttemptSeconds"] == 50.0
    assert metrics["candidateGenerationTimingSamples"] == 1
    assert metrics["reconstructionBackends"] == {"gvhmr": 1}
    assert metrics["reconstructionStageWallSeconds"] == 31.0
    assert metrics["reconstructionRunnerCallSeconds"] == 29.0
    assert metrics["reconstructionPredictionSeconds"] == 5.0


def test_effective_configuration_requires_requested_wave_size_and_arm_settings():
    metrics = {
        "sharedLlamaServerEnabled": True,
        "effectiveMaxConcurrentStagedWaves": 1,
        "stagedWaveSize": 2,
        "stagedWavesEnabled": True,
        "overlapHighWater": 1,
        "stagedWaveWorkerMode": "workspace_scoped_persistent_serial_queue",
        "waves": 1,
        "cpuPrefetchDuringBake": True,
        "prefetchWorkers": 8,
        "prefetchQueueDepth": 40,
    }

    assert motion_speed_harness.effective_configuration_error("shared", metrics, 2) is None
    assert "expected 1" in motion_speed_harness.effective_configuration_error(
        "shared", dict(metrics, effectiveMaxConcurrentStagedWaves=2), 2
    )
    assert "overlap high-water=2" in motion_speed_harness.effective_configuration_error(
        "shared", dict(metrics, overlapHighWater=2), 2
    )
    assert "stagedWaveSize=2" in motion_speed_harness.effective_configuration_error(
        "shared", metrics, 1
    )


def test_disabled_wave_mode_and_prefetch_settings_are_checked():
    metrics = {
        "sharedLlamaServerEnabled": True,
        "effectiveMaxConcurrentStagedWaves": 1,
        "stagedWaveSize": 0,
        "stagedWavesEnabled": False,
        "overlapHighWater": 0,
        "stagedWaveWorkerMode": "disabled",
        "waves": 0,
        "cpuPrefetchDuringBake": False,
        "prefetchWorkers": 3,
        "prefetchQueueDepth": 12,
    }

    assert motion_speed_harness.effective_configuration_error(
        "shared", metrics, 0, False, 3, 12
    ) is None
    assert "stagedWavesEnabled=True" in motion_speed_harness.effective_configuration_error(
        "shared", dict(metrics, stagedWavesEnabled=True), 0, False, 3, 12
    )
    assert "prefetchWorkers=8" in motion_speed_harness.effective_configuration_error(
        "shared", dict(metrics, prefetchWorkers=8), 0, False, 3, 12
    )


def test_runner_command_passes_production_prefetch_and_arm_local_preview_cache(tmp_path):
    first_arm = tmp_path / "baseline"
    second_arm = tmp_path / "shared"
    plan = tmp_path / "plan.json"

    first_command = motion_speed_harness.build_runner_command(
        "baseline", first_arm, plan, 8, 300
    )
    second_command = motion_speed_harness.build_runner_command(
        "shared", second_arm, plan, 0, 300,
        cpu_prefetch_during_bake=False,
        prefetch_workers=3,
        prefetch_queue_depth=12,
    )

    assert "-CpuPrefetchDuringBake" in first_command
    assert first_command[first_command.index("-PrefetchWorkers") + 1] == "8"
    assert first_command[first_command.index("-PrefetchQueueDepth") + 1] == "40"
    first_preview = Path(first_command[first_command.index("-YouTubePreviewCacheDir") + 1])
    second_preview = Path(second_command[second_command.index("-YouTubePreviewCacheDir") + 1])
    first_source = Path(first_command[first_command.index("-YouTubeSourceCacheDir") + 1])
    second_source = Path(second_command[second_command.index("-YouTubeSourceCacheDir") + 1])
    assert first_preview == first_arm / "cache" / "youtube-preview-cache"
    assert second_preview == second_arm / "cache" / "youtube-preview-cache"
    assert first_preview != second_preview
    assert first_source == first_arm / "cache" / "youtube-source-cache"
    assert second_source == second_arm / "cache" / "youtube-source-cache"
    assert first_source != second_source
    assert "-CpuPrefetchDuringBake" not in second_command
    assert second_command[second_command.index("-PrefetchWorkers") + 1] == "3"
    assert second_command[second_command.index("-PrefetchQueueDepth") + 1] == "12"
    assert second_command[second_command.index("-StagedWaveSize") + 1] == "0"


def test_qwen_visual_arm_is_opt_in_and_keeps_clef_final_review(tmp_path):
    parser = motion_speed_harness.build_argument_parser()
    assert parser.parse_args([]).arms == "qwen-full"

    command = motion_speed_harness.build_runner_command(
        "qwen-visual", tmp_path / "qwen-visual", tmp_path / "plan.json", 8, 300
    )

    assert "-WarmWhamWorker:$true" in command
    assert "-KeepLlamaCppServer:$true" in command
    assert command[command.index("-VisualDecisionBackend") + 1] == "qwen-chat"
    assert command[command.index("-FinalOutputReviewBackend") + 1] == "clef-systemone"
    assert motion_speed_harness.ARM_EFFECTIVE_SETTINGS["qwen-visual"] == {
        "sharedLlamaServerEnabled": False,
        "effectiveMaxConcurrentStagedWaves": 1,
    }
    assert motion_speed_harness.ARM_BACKEND_SETTINGS["qwen-visual"] == {
        "visualDecisionBackend": "qwen-chat",
        "finalOutputReviewBackend": "clef-systemone",
    }


def test_qwen_full_is_default_and_clef_comparison_arms_keep_explicit_identity(tmp_path):
    parser = motion_speed_harness.build_argument_parser()
    assert parser.parse_args([]).arms == "qwen-full"

    qwen_command = motion_speed_harness.build_runner_command(
        "qwen-full", tmp_path / "qwen-full", tmp_path / "plan.json", 8, 300
    )
    assert qwen_command[qwen_command.index("-VisualDecisionBackend") + 1] == "qwen-chat"
    assert qwen_command[qwen_command.index("-FinalOutputReviewBackend") + 1] == "qwen-chat"

    for arm in ("baseline", "shared"):
        command = motion_speed_harness.build_runner_command(
            arm, tmp_path / arm, tmp_path / "plan.json", 8, 300
        )
        assert command[command.index("-VisualDecisionBackend") + 1] == "clef-systemone"
        assert command[command.index("-FinalOutputReviewBackend") + 1] == "clef-systemone"

    assert motion_speed_harness.ARM_BACKEND_SETTINGS["qwen-full"] == {
        "visualDecisionBackend": "qwen-chat",
        "finalOutputReviewBackend": "qwen-chat",
    }
    assert motion_speed_harness.ARM_REVIEW_ARTIFACT_SETTINGS["qwen-full"] == {
        "sourceCutScorecardBackends": ["qwen-chat"],
        "supportDominanceBackends": ["qwen_chat"],
        "finalOutputValidationBackends": ["llama_cpp_vision"],
    }

    workspace = tmp_path / "workspace"
    selected = workspace / "rdl" / "selected"
    segment_detection = selected / "segment_detection"
    final_decisions = workspace / "staged-waves" / "wave-1" / "final-decisions"
    segment_detection.mkdir(parents=True)
    final_decisions.mkdir(parents=True)
    (segment_detection / "segment_selection.json").write_text(json.dumps({
        "sourceCutRanking": {
            "payload": {"sourceCutScorecardBackend": "qwen-chat"},
        },
    }), encoding="utf-8")
    (selected / "selection_manifest.json").write_text("{}", encoding="utf-8")
    (final_decisions / "decision.json").write_text(json.dumps({
        "reviewItem": {
            "supportDominanceModelOutput": {"backend": "qwen_chat"},
        },
        "selected": {
            "ranking": {
                "payload": {
                    "finalOutputValidation": {
                        "visualReview": {"backend": "llama_cpp_vision"},
                    },
                },
            },
        },
    }), encoding="utf-8")

    metrics = motion_speed_harness.extract_metrics({"workspace": str(workspace)})
    assert metrics["sourceCutScorecardBackends"] == ["qwen-chat"]
    assert metrics["supportDominanceBackends"] == ["qwen_chat"]
    assert metrics["finalOutputValidationBackends"] == ["llama_cpp_vision"]
    effective_metrics = {
        **metrics,
        "sharedLlamaServerEnabled": False,
        "effectiveMaxConcurrentStagedWaves": 1,
        "stagedWaveSize": 8,
        "stagedWavesEnabled": True,
        "overlapHighWater": 1,
        "stagedWaveWorkerMode": "workspace_scoped_persistent_serial_queue",
        "waves": 1,
        "cpuPrefetchDuringBake": True,
        "prefetchWorkers": 8,
        "prefetchQueueDepth": 40,
    }
    assert motion_speed_harness.effective_configuration_error(
        "qwen-full", effective_metrics, 8
    ) is None
    assert "support-classification artifact backend" in (
        motion_speed_harness.effective_configuration_error(
            "qwen-full", dict(effective_metrics, supportDominanceBackends=["clef_flash_systemone"]), 8
        )
    )


def test_production_powerShell_entrypoints_default_source_and_final_review_to_qwen():
    for script_name in (
        "run_exercise_motion_workout_plan.ps1",
        "run_exercise_motion_bake_and_rank.ps1",
        "run_exercise_motion_youtube_bake_and_rank.ps1",
    ):
        source = (motion_speed_harness.REPO_ROOT / "scripts" / script_name).read_text(
            encoding="utf-8"
        )
        assert re.search(
            r'\$VisualDecisionBackend\s*=\s*"qwen-chat"', source
        ), script_name
        assert re.search(
            r'\$FinalOutputReviewBackend\s*=\s*"qwen-chat"', source
        ), script_name


def test_qwen_visual_qualification_uses_completed_review_artifacts(tmp_path):
    workspace = tmp_path / "workspace"
    selected = workspace / "rdl" / "selected"
    segment_detection = selected / "segment_detection"
    final_decisions = workspace / "staged-waves" / "wave-1" / "final-decisions"
    segment_detection.mkdir(parents=True)
    final_decisions.mkdir(parents=True)
    (segment_detection / "segment_selection.json").write_text(json.dumps({
        "sourceCutRanking": {
            "payload": {"sourceCutScorecardBackend": "qwen-chat"},
        },
    }), encoding="utf-8")
    (selected / "selection_manifest.json").write_text("{}", encoding="utf-8")
    (final_decisions / "decision.json").write_text(json.dumps({
        "selected": {
            "ranking": {
                "payload": {
                    "finalOutputValidation": {
                        "visualReview": {"backend": "clef_flash_systemone"},
                    },
                },
            },
        },
    }), encoding="utf-8")

    metrics = motion_speed_harness.extract_metrics({"workspace": str(workspace)})

    assert metrics["sourceCutScorecardBackends"] == ["qwen-chat"]
    assert metrics["finalOutputValidationBackends"] == ["clef_flash_systemone"]
    effective_metrics = {
        **metrics,
        "sharedLlamaServerEnabled": False,
        "effectiveMaxConcurrentStagedWaves": 1,
        "stagedWaveSize": 8,
        "stagedWavesEnabled": True,
        "overlapHighWater": 1,
        "stagedWaveWorkerMode": "workspace_scoped_persistent_serial_queue",
        "waves": 1,
        "cpuPrefetchDuringBake": True,
        "prefetchWorkers": 8,
        "prefetchQueueDepth": 40,
    }
    assert motion_speed_harness.effective_configuration_error(
        "qwen-visual", effective_metrics, 8
    ) is None
    assert "source-review artifact backend" in motion_speed_harness.effective_configuration_error(
        "qwen-visual", dict(effective_metrics, sourceCutScorecardBackends=["clef-systemone"]), 8
    )
    assert "rendered-validation artifact backend" in motion_speed_harness.effective_configuration_error(
        "qwen-visual", dict(effective_metrics, finalOutputValidationBackends=["llama_cpp_vision"]), 8
    )


def test_parser_allows_zero_wave_size_and_prefetch_overrides_and_rejects_invalid_values():
    parser = motion_speed_harness.build_argument_parser()
    defaults = parser.parse_args(["--arms", "baseline"])
    assert defaults.staged_wave_size == 8
    assert defaults.cpu_prefetch_during_bake is True
    assert defaults.prefetch_workers == 8
    assert defaults.prefetch_queue_depth == 40
    assert defaults.source_frame_decode_cache == "off"
    assert defaults.browser_frame_batch == "on"

    overridden = parser.parse_args([
        "--arms", "baseline", "--staged-wave-size", "0",
        "--disable-cpu-prefetch", "--prefetch-workers", "3",
        "--prefetch-queue-depth", "12",
    ])
    assert overridden.staged_wave_size == 0
    assert overridden.cpu_prefetch_during_bake is False
    assert overridden.prefetch_workers == 3
    assert overridden.prefetch_queue_depth == 12

    enabled_cache = parser.parse_args([
        "--arms", "baseline", "--source-frame-decode-cache", "on", "--browser-frame-batch", "on",
    ])
    assert enabled_cache.source_frame_decode_cache == "on"
    assert enabled_cache.browser_frame_batch == "on"

    for invalid_args in (
        ["--arms", "baseline", "--staged-wave-size", "-1"],
        ["--arms", "baseline", "--prefetch-workers", "0"],
        ["--arms", "baseline", "--prefetch-queue-depth", "0"],
    ):
        try:
            parser.parse_args(invalid_args)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"parser accepted invalid arguments: {invalid_args}")


def test_extract_metrics_records_stable_accepted_artifact_and_frame_hashes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skeleton_path = workspace / "selected.json"
    skeleton_path.write_text(json.dumps({
        "frameCount": 2,
        "fps": 30,
        "durationSec": 1 / 15,
        "frames": [{"time": 0, "joints": {"root": [0, 0, 0]}},
                   {"time": 1 / 30, "joints": {"root": [1, 0, 0]}}],
    }), encoding="utf-8")
    summary = {
        "stagedWaveWorkerMode": "disabled",
        "stagedWavesEnabled": False,
        "stagedWaveSize": 0,
        "maxConcurrentStagedWaves": 1,
        "runningStagedWaveCountHighWater": 0,
        "parallelism": {
            "cpuPrefetchDuringBake": True,
            "prefetchWorkers": 8,
            "prefetchQueueDepth": 40,
        },
        "exercises": [{
            "exerciseId": "exercise-id",
            "exerciseName": "Test Exercise",
            "status": "completed",
            "selectedWearSkeletonPath": str(skeleton_path),
        }],
    }
    (workspace / "workout_motion_generation_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )

    metrics = motion_speed_harness.extract_metrics({"workspace": str(workspace)})
    movement = metrics["acceptedMovementArtifacts"][0]["movements"][0]
    assert movement["artifactSha256"] == motion_speed_harness.sha256_file(skeleton_path)
    assert len(movement["frameSequenceSha256"]) == 64
    assert movement["frameCount"] == movement["declaredFrameCount"] == 2
    assert metrics["acceptedMovementArtifactErrors"] == []
    assert metrics["stagedWaveWorkerMode"] == "disabled"
    assert metrics["cpuPrefetchDuringBake"] is True
    assert metrics["prefetchWorkers"] == 8
    assert metrics["prefetchQueueDepth"] == 40


def test_current_shared_overlap_arm_is_rejected_before_model_run():
    assert "serial" in motion_speed_harness.UNSUPPORTED_ARMS["shared-overlap"]
    assert "clamps MaxConcurrentStagedWaves to 1" in motion_speed_harness.UNSUPPORTED_ARMS[
        "shared-overlap"
    ]


def test_default_harness_wave_size_matches_production_library_wrapper():
    harness_args = motion_speed_harness.build_argument_parser().parse_args(
        ["--fixtures", "fixture_manifest.json", "--arms", "shared"]
    )
    library_wrapper = (
        motion_speed_harness.REPO_ROOT / "scripts" / "run_exercise_motion_library.ps1"
    ).read_text(encoding="utf-8")
    library_default = re.search(
        r"\[int\]\$StagedWaveSize\s*=\s*(\d+)",
        library_wrapper,
    )

    assert library_default is not None
    assert harness_args.staged_wave_size == int(library_default.group(1))
    assert harness_args.cpu_prefetch_during_bake is True
    assert harness_args.prefetch_workers == 8
    assert harness_args.prefetch_queue_depth == 40


def test_fixture_source_cache_is_arm_local_and_hash_verified(tmp_path):
    source = tmp_path / "pinned-source.mp4"
    source.write_bytes(b"fixed source bytes")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    sidecar = source.with_name(f"{source.name}.source.json")
    sidecar_payload = {
        "schemaVersion": 1,
        "cacheKey": source.stem,
        "sizeBytes": source.stat().st_size,
        "contentSha256": source_sha256,
    }
    sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")
    manifest = {
        "exercises": [{
            "sourceCachePath": str(source),
            "sourceSha256": source_sha256,
        }],
    }

    first = motion_speed_harness.stage_fixture_source_cache(
        manifest, tmp_path / "arm-one" / "cache" / "youtube-source-cache"
    )
    second = motion_speed_harness.stage_fixture_source_cache(
        manifest, tmp_path / "arm-two" / "cache" / "youtube-source-cache"
    )

    first_copy = first / source.name
    second_copy = second / source.name
    assert first_copy.read_bytes() == second_copy.read_bytes() == b"fixed source bytes"
    assert first_copy != second_copy
    assert motion_speed_harness.sha256_file(first_copy) == source_sha256
    assert motion_speed_harness.sha256_file(second_copy) == source_sha256
    assert json.loads(first_copy.with_name(f"{first_copy.name}.source.json").read_text()) == sidecar_payload
    assert json.loads(second_copy.with_name(f"{second_copy.name}.source.json").read_text()) == sidecar_payload

    sidecar.unlink()
    try:
        motion_speed_harness.stage_fixture_source_cache(
            manifest, tmp_path / "arm-four" / "cache" / "youtube-source-cache"
        )
    except SystemExit as exc:
        assert "Fixture source cache identity sidecar" in str(exc)
    else:
        raise AssertionError("fixture source cache accepted a source with no identity sidecar")

    source.write_bytes(b"mutated source bytes")
    try:
        motion_speed_harness.stage_fixture_source_cache(
            manifest, tmp_path / "arm-three" / "cache" / "youtube-source-cache"
        )
    except SystemExit as exc:
        assert "Fixture source SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("fixture source cache accepted bytes with the wrong SHA-256")


def test_fixture_manifest_preflight_rejects_missing_or_invalid_source_sidecar(tmp_path):
    source = tmp_path / "pinned-source.mp4"
    source.write_bytes(b"fixed source bytes")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    seed = tmp_path / "exercise_plan.json"
    seed.write_text("{}", encoding="utf-8")
    candidates = tmp_path / "candidates.json"
    candidates.write_text("{}", encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text("{}", encoding="utf-8")
    contract_cache = tmp_path / "contract-cache"
    contract_cache.mkdir()
    manifest_path = tmp_path / "fixture_manifest.json"
    manifest_path.write_text(json.dumps({
        "kind": "motion_fixed_fixture_set",
        "contractCacheSnapshotPath": str(contract_cache),
        "contractCacheSnapshotSha256": motion_speed_harness.sha256_directory_contents(
            contract_cache
        ),
        "exercises": [{
            "slug": "pull-up",
            "workspaceSeedPath": str(seed),
            "workspaceSeedSha256": motion_speed_harness.sha256_file(seed),
            "sourceCachePath": str(source),
            "sourceSha256": source_sha256,
            "preparedCandidatesPath": str(candidates),
            "preparedCandidatesSha256": motion_speed_harness.sha256_file(candidates),
            "contractPath": str(contract),
            "contractSha256": motion_speed_harness.sha256_file(contract),
        }],
    }), encoding="utf-8")
    sidecar = source.with_name(f"{source.name}.source.json")

    for payload in (None, {"schemaVersion": 1, "cacheKey": source.stem}):
        if payload is None:
            sidecar.unlink(missing_ok=True)
        else:
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
        try:
            motion_speed_harness.load_fixture_manifest(manifest_path)
        except SystemExit as exc:
            assert "Fixture source cache identity sidecar" in str(exc)
        else:
            raise AssertionError("fixture preflight accepted a missing or invalid source sidecar")


def test_fixture_contract_motion_context_must_match_mini_library(tmp_path):
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps({
        "exerciseDefinitions": [{
            "id": "deadlift-id",
            "name": "Romanian Deadlift",
            "exerciseType": "Strength",
            "exerciseCategory": "Hinge",
            "muscleGroups": ["hamstrings"],
            "equipmentId": "barbell-id",
        }],
        "equipments": [{
            "id": "barbell-id",
            "type": "barbell",
            "name": "Barbell",
            "capabilities": ["loadable_plates"],
        }],
    }), encoding="utf-8")
    mini_library_path = tmp_path / "mini_library.json"
    motion_speed_harness.build_mini_library(
        library_path, {"romanian-deadlift"}, mini_library_path
    )
    from exercise_motion_pkg.youtube import load_workout_plan_exercises

    actual_context = load_workout_plan_exercises(mini_library_path)[0].motion_context
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps({"motionContext": actual_context}), encoding="utf-8")
    manifest = {"exercises": [{
        "slug": "romanian-deadlift",
        "exerciseId": "deadlift-id",
        "contractPath": str(contract_path),
    }]}

    motion_speed_harness.validate_fixture_contract_motion_contexts(manifest, mini_library_path)

    contract_path.write_text(json.dumps({
        "motionContext": {**actual_context, "primaryEquipment": {
            **actual_context["primaryEquipment"], "capabilities": []
        }}
    }), encoding="utf-8")
    try:
        motion_speed_harness.validate_fixture_contract_motion_contexts(manifest, mini_library_path)
    except SystemExit as exc:
        assert "motion context mismatch" in str(exc)
        assert "romanian-deadlift" in str(exc)
    else:
        raise AssertionError("fixture preflight accepted a contract with stale equipment capabilities")


def test_artifact_parity_compares_full_artifact_and_frame_identities():
    reference = [{
        "exerciseId": "exercise-id",
        "exerciseName": "Test Exercise",
        "movements": [{
            "artifactSha256": "a" * 64,
            "frameSequenceSha256": "b" * 64,
            "frameCount": 20,
        }],
    }]

    assert motion_speed_harness.accepted_artifact_parity_error(reference, reference) is None
    changed_frames = [{
        **reference[0],
        "movements": [{**reference[0]["movements"][0], "frameSequenceSha256": "c" * 64}],
    }]
    assert "accepted artifact/frame identities differ" in (
        motion_speed_harness.accepted_artifact_parity_error(reference, changed_frames)
    )
    missing_exercise = []
    assert "accepted exercise identities differ" in (
        motion_speed_harness.accepted_artifact_parity_error(reference, missing_exercise)
    )

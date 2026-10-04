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


def test_parser_allows_zero_wave_size_and_prefetch_overrides_and_rejects_invalid_values():
    parser = motion_speed_harness.build_argument_parser()
    defaults = parser.parse_args(["--arms", "baseline"])
    assert defaults.staged_wave_size == 8
    assert defaults.cpu_prefetch_during_bake is True
    assert defaults.prefetch_workers == 8
    assert defaults.prefetch_queue_depth == 40

    overridden = parser.parse_args([
        "--arms", "baseline", "--staged-wave-size", "0",
        "--disable-cpu-prefetch", "--prefetch-workers", "3",
        "--prefetch-queue-depth", "12",
    ])
    assert overridden.staged_wave_size == 0
    assert overridden.cpu_prefetch_during_bake is False
    assert overridden.prefetch_workers == 3
    assert overridden.prefetch_queue_depth == 12

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

    source.write_bytes(b"mutated source bytes")
    try:
        motion_speed_harness.stage_fixture_source_cache(
            manifest, tmp_path / "arm-three" / "cache" / "youtube-source-cache"
        )
    except SystemExit as exc:
        assert "Fixture source SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("fixture source cache accepted bytes with the wrong SHA-256")


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

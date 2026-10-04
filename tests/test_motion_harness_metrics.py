import json
import re

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
        "overlapHighWater": 1,
        "stagedWaveWorkerMode": "workspace_scoped_persistent_serial_queue",
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

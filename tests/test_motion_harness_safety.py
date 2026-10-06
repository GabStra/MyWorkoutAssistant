import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_motion_fixed_fixtures, motion_speed_harness


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _make_fixture_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    base_workspace = tmp_path / "base-workspace"
    selected = base_workspace / "test-exercise" / "selected"
    (selected / "debug").mkdir(parents=True)
    source_cache = tmp_path / "source-cache"
    source_cache.mkdir()
    (source_cache / "test-video.mp4").write_bytes(b"fixed source bytes")
    contract_cache = tmp_path / "contract-cache"
    contract_cache.mkdir()
    _write_json(contract_cache / "cached-contract.json", {"cache": "fixed"})

    contract = {"schemaVersion": 1, "movementType": "repetition"}
    candidate = {
        "videoId": "test-video",
        "status": "recommended",
        "visionScore": 0.9,
        "visionPayload": {
            "target_identity_match": True,
            "exerciseMotionContract": contract,
        },
    }
    _write_json(
        selected / "debug" / "youtube_candidates.full.json",
        {
            "generatedAt": "2026-10-04T00:00:00Z",
            "exercises": [{
                "exerciseId": "exercise-id",
                "exerciseName": "Test Exercise",
                "candidates": [candidate],
            }],
        },
    )
    for name in (
        "test_exercise_wear_skeleton.json",
        "test_exercise_selected_preview.webm",
        "test_exercise_selected_input.mp4",
        "selection_manifest.json",
    ):
        (selected / name).write_bytes(name.encode("utf-8"))
    _write_json(selected / "revalidation.json", {"status": "valid"})
    (base_workspace / "test-exercise" / "exercise_plan.json").write_text(
        '{"exercise":"Test Exercise"}\n', encoding="utf-8"
    )
    return base_workspace, source_cache, contract_cache, tmp_path / "fixtures"


def test_fixture_builder_pins_seed_and_contract_cache_used_by_both_arms(tmp_path, monkeypatch):
    base_workspace, source_cache, contract_cache, fixture_dir = _make_fixture_inputs(tmp_path)
    monkeypatch.setattr(
        build_motion_fixed_fixtures,
        "DEFAULT_EXERCISES",
        (("test-exercise", "test-video", "exercise-id", "test-video.mp4"),),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_motion_fixed_fixtures.py",
            "--output-dir", str(fixture_dir),
            "--base-workspace", str(base_workspace),
            "--source-cache-dir", str(source_cache),
            "--contract-cache-dir", str(contract_cache),
        ],
    )

    build_motion_fixed_fixtures.main()
    manifest_path = fixture_dir / "fixture_manifest.json"
    manifest = motion_speed_harness.load_fixture_manifest(manifest_path)
    exercise = manifest["exercises"][0]
    assert motion_speed_harness.sha256_file(Path(exercise["workspaceSeedPath"])) == (
        exercise["workspaceSeedSha256"]
    )
    cache_snapshot = Path(manifest["contractCacheSnapshotPath"])
    assert motion_speed_harness.sha256_directory_contents(cache_snapshot) == (
        manifest["contractCacheSnapshotSha256"]
    )

    staged_cache = motion_speed_harness.stage_fixture_contract_cache(
        manifest, tmp_path / "run-contract-cache"
    )
    arm_dir = tmp_path / "arm"
    prepared_manifest, seeded_slugs = motion_speed_harness.assemble_workspace_fixtures(
        arm_dir, manifest, staged_cache
    )
    assert prepared_manifest.is_file()
    assert seeded_slugs == ["test-exercise"]
    assert motion_speed_harness.sha256_file(
        arm_dir / "isolated" / "exercise_motion" / "workspace" /
        "test-exercise" / "exercise_plan.json"
    ) == exercise["workspaceSeedSha256"]
    arm_cache = (
        arm_dir / "isolated" / "exercise_motion" / "workspace" /
        "exercise-motion-contract-cache"
    )
    assert motion_speed_harness.sha256_directory_contents(arm_cache) == (
        manifest["contractCacheSnapshotSha256"]
    )

    seed_path = Path(exercise["workspaceSeedPath"])
    seed_path.write_text("mutated seed\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Fixture SHA-256 mismatch"):
        motion_speed_harness.load_fixture_manifest(manifest_path)


def test_fixture_loader_rejects_changed_contract_cache_snapshot(tmp_path):
    base_workspace, source_cache, contract_cache, fixture_dir = _make_fixture_inputs(tmp_path)
    exercise = build_motion_fixed_fixtures.build_exercise_fixture(
        base_workspace,
        source_cache,
        contract_cache,
        fixture_dir,
        "test-exercise",
        "test-video",
        "exercise-id",
        "test-video.mp4",
    )
    snapshot = fixture_dir / "contract-cache"
    import shutil
    shutil.copytree(contract_cache, snapshot)
    manifest_path = fixture_dir / "fixture_manifest.json"
    _write_json(manifest_path, {
        "kind": "motion_fixed_fixture_set",
        "exercises": [exercise],
        "contractCacheSnapshotPath": str(snapshot),
        "contractCacheSnapshotSha256": motion_speed_harness.sha256_directory_contents(snapshot),
    })

    (snapshot / "cached-contract.json").write_text("changed\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="contract-cache SHA-256 mismatch"):
        motion_speed_harness.load_fixture_manifest(manifest_path)


def test_prewarm_confirms_ready_marker_and_worker_container_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_speed_harness, "HARNESS_ROOT", tmp_path)
    mounted_state_dirs = []

    def fake_docker_run(args, **kwargs):
        if args[1] == "run":
            state_mount = next(
                value.split(":/worker_state", 1)[0]
                for index, value in enumerate(args[:-1])
                if value.endswith(":/worker_state")
            )
            state_dir = Path(state_mount)
            mounted_state_dirs.append(state_dir)
            _write_json(state_dir / "ready.json", {
                "status": "ready", "loadSeconds": 12.5, "gpuName": "test-gpu",
            })
            return SimpleNamespace(returncode=0, stdout="fake-container-id", stderr="")
        if args[1] == "inspect":
            state_dir = mounted_state_dirs[0]
            if (state_dir / "stop").exists():
                _write_json(state_dir / "stopped.json", {"status": "stopped"})
                return SimpleNamespace(returncode=0, stdout="exited", stderr="")
            return SimpleNamespace(returncode=0, stdout="running", stderr="")
        if args[1] == "rm":
            return SimpleNamespace(returncode=0, stdout="fake-container-id", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(motion_speed_harness.subprocess, "run", fake_docker_run)
    result = motion_speed_harness.prewarm_gvhmr_worker(timeout_seconds=1.0)

    assert result["ready"] is True
    assert result["startupStatus"] == "ready"
    assert result["readyAfterSeconds"] is not None
    assert result["workerLoadSeconds"] == 12.5
    assert result["cleanShutdown"] is True
    assert result["shutdownConfirmed"] is True


def test_failed_prewarm_is_recorded_and_prevents_starting_any_arm(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_speed_harness, "HARNESS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(motion_speed_harness, "capture_run_identity", lambda: {})

    def build_library(_library, _slugs, destination):
        destination.write_text("{}", encoding="utf-8")
        return ["test-exercise"]

    monkeypatch.setattr(motion_speed_harness, "build_mini_library", build_library)
    monkeypatch.setattr(motion_speed_harness, "prewarm_gvhmr_worker", lambda: {
        "attempted": True,
        "ready": False,
        "startupStatus": "timeout",
        "cleanShutdown": False,
        "shutdownConfirmed": True,
    })
    monkeypatch.setattr(
        motion_speed_harness, "run_arm",
        lambda *args, **kwargs: pytest.fail("arm must not start after failed prewarm"),
    )
    monkeypatch.setattr(
        sys, "argv", ["motion_speed_harness.py", "--arms", "baseline", "--exercises", "test-exercise"]
    )

    with pytest.raises(SystemExit, match="no comparison arm was started"):
        motion_speed_harness.main()

    run_root = next((tmp_path / "runs").iterdir())
    prewarm = json.loads((run_root / "prewarm.json").read_text(encoding="utf-8"))
    assert prewarm["startupStatus"] == "timeout"
    assert json.loads((run_root / "results.json").read_text(encoding="utf-8")) == []


def test_process_tree_termination_waits_and_aborts_later_arms(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 1234
        returncode = None

        def __init__(self):
            self.wait_called = False

        def wait(self, timeout=None):
            self.wait_called = True
            self.returncode = 137
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        motion_speed_harness.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    shutdown = motion_speed_harness._kill_process_tree(process)
    assert shutdown["confirmed"] is True
    assert process.wait_called is True
    assert shutdown["rootProcessExited"] is True

    monkeypatch.setattr(motion_speed_harness, "HARNESS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(motion_speed_harness, "capture_run_identity", lambda: {})

    def build_library(_library, _slugs, destination):
        destination.write_text("{}", encoding="utf-8")
        return ["test-exercise"]

    arm_calls = []

    def timed_out_arm(arm, arm_dir, *_args, **_kwargs):
        arm_calls.append(arm)
        return {
            "arm": arm,
            "exitCode": "timeout",
            "terminationStatus": "timeout",
            "shutdownConfirmed": True,
            "shutdownStatus": "confirmed",
            "wallSeconds": 2700,
            "workspace": str(arm_dir / "isolated" / "exercise_motion" / "workspace"),
            "log": str(arm_dir / "run.log"),
            "runnerArgs": [],
        }

    monkeypatch.setattr(motion_speed_harness, "build_mini_library", build_library)
    monkeypatch.setattr(motion_speed_harness, "assemble_workspace", lambda *args: 0)
    monkeypatch.setattr(motion_speed_harness, "run_arm", timed_out_arm)
    monkeypatch.setattr(
        sys, "argv", [
            "motion_speed_harness.py", "--arms", "baseline,shared",
            "--exercises", "test-exercise", "--skip-prewarm",
        ],
    )

    motion_speed_harness.main()
    assert arm_calls == ["baseline"]
    run_root = next((tmp_path / "runs").iterdir())
    results = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    assert len(results) == 1
    assert results[0]["shutdownStatus"] == "confirmed"


@pytest.mark.parametrize(
    ("exit_code", "statuses", "expected_error"),
    [
        (1, {"completed": 1}, "runner exited with code 1"),
        (
            0,
            {"no_selection": 1},
            "only 0 of 1 exercises completed; statuses={'no_selection': 1}",
        ),
        (0, {}, "runner summary has no terminal exercise statuses"),
    ],
)
def test_unqualified_arm_aborts_remaining_arms_and_keeps_artifacts(
    tmp_path, monkeypatch, exit_code, statuses, expected_error
):
    monkeypatch.setattr(motion_speed_harness, "HARNESS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(motion_speed_harness, "capture_run_identity", lambda: {})

    def build_library(_library, _slugs, destination):
        destination.write_text("{}", encoding="utf-8")
        return ["test-exercise"]

    monkeypatch.setattr(motion_speed_harness, "build_mini_library", build_library)
    monkeypatch.setattr(motion_speed_harness, "assemble_workspace", lambda *_args: 0)
    monkeypatch.setattr(
        motion_speed_harness,
        "extract_metrics",
        lambda _result: {"statuses": statuses},
    )
    monkeypatch.setattr(motion_speed_harness, "effective_configuration_error", lambda *_args: None)
    monkeypatch.setattr(motion_speed_harness, "load_scheduler_timeline", lambda _result: [])
    monkeypatch.setattr(motion_speed_harness, "_log_tail", lambda _path: "failed arm")

    arm_calls = []
    workspaces = []

    def failed_arm(arm, arm_dir, *_args, **_kwargs):
        arm_calls.append(arm)
        workspace = arm_dir / "isolated" / "exercise_motion" / "workspace"
        retained = workspace / "test-exercise" / "diagnostic.json"
        retained.parent.mkdir(parents=True)
        retained.write_text("{}", encoding="utf-8")
        workspaces.append(retained)
        return {
            "arm": arm,
            "exitCode": exit_code,
            "terminationStatus": "exited",
            "shutdownConfirmed": True,
            "shutdownStatus": "confirmed",
            "wallSeconds": 300,
            "workspace": str(workspace),
            "log": str(arm_dir / "run.log"),
            "runnerArgs": [],
        }

    monkeypatch.setattr(motion_speed_harness, "run_arm", failed_arm)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "motion_speed_harness.py",
            "--arms", "baseline,shared",
            "--exercises", "test-exercise",
            "--skip-prewarm",
        ],
    )

    motion_speed_harness.main()

    assert arm_calls == ["baseline"]
    assert workspaces[0].is_file()
    run_root = next((tmp_path / "runs").iterdir())
    results = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    assert len(results) == 1
    assert results[0]["qualificationError"] == expected_error

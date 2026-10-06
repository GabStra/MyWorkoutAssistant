"""Run the real generator script with pinned source IO and raw reconstructions.

Source and final visual reviews use the configured production models. The
retained reconstruction boundary is recorded separately from inference/cache
coverage. This runner is opt-in and does not alter production defaults.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def verify_replay_outputs(run_root: Path, exercise_ids: set[str]) -> None:
    """Require reviewed production artifacts and their exact packaged bytes."""
    from scripts import build_workout_plan_movement_package as builder

    summary_path = run_root / "workspace/workout_motion_generation_summary.json"
    summary = builder.load_json_file(summary_path)
    package = builder.load_json_file(run_root / "package.json")
    items = {str(item.get("exerciseId")): item
             for item in builder.iter_motion_summary_items(summary)}
    exercises = {str(item.get("id")): item
                 for item, _ in builder.iter_package_exercises(package)}
    backups = builder.existing_backups_by_key(package)
    for exercise_id in exercise_ids:
        item = items.get(exercise_id)
        if not item or not builder.is_approved_summary_item(item):
            raise ValueError(f"Replay has no approved output: {exercise_id}")
        path = builder.revalidated_selection_motion_path(
            item, summary_path=summary_path, summary=summary)
        if path is None:
            raise ValueError(f"Replay selected artifact is missing: {exercise_id}")
        builder.validate_selected_movement(path, item, summary_path=summary_path, summary=summary)
        reference = exercises.get(exercise_id, {}).get("movementRef", {})
        key = (reference.get("movementId"), reference.get("contentHash"))
        backup = backups.get(key)
        if not backup:
            raise ValueError(f"Replay package movement is missing: {exercise_id}")
        decoded = gzip.decompress(base64.b64decode(backup["compressedJsonBase64"], validate=True))
        if (decoded != builder.read_text_file(path).encode("utf-8")
                or hashlib.sha256(decoded).hexdigest() != reference.get("contentHash")):
            raise ValueError(f"Replay packaged movement differs from reviewed output: {exercise_id}")


def seed_replay_contract_cache(config: dict, workspace_root: Path) -> list[dict[str, str]]:
    """Copy only hash-pinned, semantically usable contracts into a fresh replay workspace."""
    seed = config.get("exerciseMotionContractCacheSeed")
    if not seed:
        return []
    if not isinstance(seed, dict) or not isinstance(seed.get("sourceDir"), str):
        raise ValueError("Contract cache seed must specify a sourceDir")
    expected_hashes = seed.get("sha256ByExerciseId")
    if not isinstance(expected_hashes, dict):
        raise ValueError("Contract cache seed must pin a SHA-256 for each exercise")

    from exercise_motion_pkg.youtube import (
        YouTubeRankingSettings,
        exercise_motion_contract_cache_path,
        load_cached_exercise_motion_contract,
        load_workout_plan_exercises,
    )

    source_dir = Path(seed["sourceDir"]).resolve()
    source_settings = YouTubeRankingSettings(exercise_motion_contract_cache_dir=source_dir)
    target_dir = (workspace_root / "exercise-motion-contract-cache").resolve()
    target_settings = YouTubeRankingSettings(exercise_motion_contract_cache_dir=target_dir)
    exercises = load_workout_plan_exercises(Path(config["workoutPlanPath"]))
    by_id = {exercise.exercise_id: exercise for exercise in exercises}
    seeded: list[dict[str, str]] = []
    for exercise_id, expected_hash in expected_hashes.items():
        exercise = by_id.get(str(exercise_id))
        if exercise is None:
            raise ValueError(f"Contract cache seed references an exercise outside the plan: {exercise_id}")
        source_path = exercise_motion_contract_cache_path(exercise, source_settings)
        if source_path is None or not source_path.is_file():
            raise ValueError(f"Pinned contract cache is missing for {exercise_id}")
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_digest.lower() != str(expected_hash).lower():
            raise ValueError(f"Pinned contract cache changed for {exercise_id}: {source_path}")
        if load_cached_exercise_motion_contract(exercise, source_settings) is None:
            raise ValueError(f"Pinned contract cache is no longer usable for {exercise_id}")

        target_path = exercise_motion_contract_cache_path(exercise, target_settings)
        if target_path is None:
            raise ValueError(f"Could not resolve replay contract cache path for {exercise_id}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())
        if load_cached_exercise_motion_contract(exercise, target_settings) is None:
            raise ValueError(f"Seeded contract cache failed replay validation for {exercise_id}")
        seeded.append({
            "exerciseId": str(exercise_id),
            "cachePath": str(target_path),
            "sha256": source_digest,
        })
    return seeded


def run_bounded_process(command, *, environment, stdout, stderr, timeout_seconds):
    """Bound the entire replay, including model waits outside stage budgets."""
    with subprocess.Popen(command, cwd=REPO_ROOT, env=environment,
                          stdout=stdout, stderr=stderr) as process:
        try:
            return process.wait(timeout=timeout_seconds), False
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                # The PID belongs to the child we launched; leave foreign services alone.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=stderr, stderr=stderr, check=False, timeout=30)
            else:
                process.kill()
            process.wait(timeout=30)
            return 124, True


def run_replay(config_path: Path, run_root: Path, python_command: str | None,
               timeout_seconds: float = 2400) -> int:
    if timeout_seconds <= 0:
        raise ValueError("Replay timeout must be positive")
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from motion_retained_replay_boundary import verified_file
    from exercise_motion_pkg.video_utils import read_basic_video_metadata

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("mode") != "retained_reconstruction_real_review":
        raise ValueError("Replay requires retained_reconstruction_real_review mode")
    fixtures = config["exerciseFixtures"]
    if not fixtures:
        raise ValueError("No retained exercise fixtures")
    for fixture in fixtures.values():
        video = verified_file(fixture, "sourceVideoPath")
        raw_path = verified_file(fixture, "normalizedMotionPath")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        metadata = read_basic_video_metadata(video)
        if len(raw["frames"]) != metadata.frame_count or abs(float(raw["fps"]) - metadata.fps) > 0.001:
            raise ValueError(f"Retained source/reconstruction timeline mismatch: {video}")
        if not fixture.get("upstreamIdentity"):
            raise ValueError("Retained reconstruction upstream identity is required")
    run_root.mkdir(parents=True, exist_ok=False)
    config["callsPath"] = str((run_root / "boundary_calls.jsonl").resolve())
    workspace_root = run_root / "workspace"
    config["seededExerciseMotionContracts"] = seed_replay_contract_cache(config, workspace_root)
    local_config = run_root / "replay_config.json"
    local_config.write_text(json.dumps(config, indent=2), encoding="utf-8")
    startup = run_root / "python_startup"
    startup.mkdir()
    (startup / "sitecustomize.py").write_text(
        f"import sys\nsys.path.insert(0, {str(REPO_ROOT / 'tests')!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from motion_process_e2e_bootstrap import install_import_patches\ninstall_import_patches()\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["EXERCISE_MOTION_PROCESS_E2E_CONFIG"] = str(local_config.resolve())
    environment["PYTHONPATH"] = str(startup.resolve()) + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(REPO_ROOT / "scripts/run_exercise_motion_workout_plan.ps1"),
        "-AllowDirtyWorktree", "-WorkoutPlanJson", config["workoutPlanPath"],
        "-WorkspaceRoot", str(workspace_root.resolve()),
        "-MobilePackageOutputJson", str((run_root / "package.json").resolve()),
        "-SourceOutcomeIndexJson", str((run_root / "source_outcome_index.json").resolve()),
        "-YouTubeSourceCacheDir", str((run_root / "youtube-source-cache").resolve()),
        "-YouTubePreviewCacheDir", str((run_root / "youtube-preview-cache").resolve()),
        "-SharedLlamaServer", "-DiscoveryWorkers", "1",
        "-RequireWhamCache", "-SkipLlamaCppQueryPlanner", "-NoExerciseNameRewrite",
        "-SkipPosePrefilter", "-SkipExerciseMotionContractPrefetch", "-SkipSourceSegmentDetection",
        "-TwoScaleSourceValidation", "-StagedWaveSize", "1",
        "-MaxConcurrentStagedWaves", "1", "-ResultsPerQuery", "1",
        "-CandidateReviewBatchSize", "1", "-CandidateReviewTargetSuitableCount", "1",
        "-VisionCandidatesPerExercise", "1", "-SemanticGateCandidatesPerExercise", "1",
        "-SemanticGateMaxCandidatesPerExercise", "1", "-MaxCandidates", "1",
        "-MaxSourceWindowAttempts", "1", "-MaxReconstructionCandidateAttempts", "1",
        "-MaxSelectedResults", "1", "-MaxAdaptivePreviewSettings", "1",
        "-DiscoveryTimeBudgetSeconds", "600",
        "-LlamaCppServerStartupTimeoutSeconds", "120",
        "-LlamaCppRequestTimeoutSeconds", "120",
        "-CandidateTimeoutSeconds", "300", "-ExerciseTimeoutSeconds", "600",
        "-ProgressIntervalSeconds", "5", "-ArtifactRetention", "debug",
    ]
    # Let the production wrapper select EXERCISE_MOTION_PYTHON or its CUDA
    # default. Passing this runner's sys.executable would silently override
    # that selection with a CPU-only interpreter on many developer machines.
    if python_command:
        command.extend(["-PythonCommand", python_command])
    (run_root / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    with (run_root / "stdout.log").open("w", encoding="utf-8") as stdout, \
            (run_root / "stderr.log").open("w", encoding="utf-8") as stderr:
        exit_code, timed_out = run_bounded_process(
            command, environment=environment, stdout=stdout, stderr=stderr,
            timeout_seconds=timeout_seconds)
    verification_error = None
    if exit_code == 0:
        try:
            verify_replay_outputs(run_root, set(fixtures))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            verification_error = str(exc)
            exit_code = 1
    (run_root / "process_result.json").write_text(json.dumps({
        "exitCode": exit_code,
        "timedOut": timed_out,
        "timeoutSeconds": timeout_seconds,
        "productionScriptE2EPassed": exit_code == 0,
        "outputVerificationError": verification_error,
        "reconstructionBoundary": "hash-bound retained raw motion; inference/cache lookup not covered",
        "visualReviewBoundary": "production models; no fabricated positive review responses",
    }, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--python", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=2400)
    args = parser.parse_args()
    raise SystemExit(run_replay(args.config.resolve(), args.run_root.resolve(), args.python,
                               args.timeout_seconds))

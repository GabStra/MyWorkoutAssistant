"""Speed-config harness for bounded pipeline tuning.

Assembles a fresh mini workspace from retained exercise workspaces and runs
the staged workout-plan runner once per configuration arm. Candidate discovery
and source selection may still run; a small exercise list does not guarantee a
short run, entry into staged processing, or an accepted movement. Reports
include wall time, per-phase timings, wave size, source workers, vision-server
startup counts, co-resident operations, shared-server quiesce metrics, overlap
high-water mark, GVHMR attempt durations, and terminal statuses.

Usage:
  python scripts/motion_speed_harness.py --arms baseline,shared,shared-overlap
  python scripts/motion_speed_harness.py --arms baseline --exercises slug-a,slug-b
  python scripts/motion_speed_harness.py --fixtures <fixture_manifest.json> --arms baseline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_exercise_motion_workout_plan.ps1"
DEFAULT_LIBRARY_JSON = Path(r"C:\Users\gabri\Downloads\my_exercise_library.json")
DEFAULT_BASE_WORKSPACE = REPO_ROOT / "build/exercise_motion/exercise-library"
DEFAULT_SOURCE_OUTCOME_INDEX = REPO_ROOT / "build/exercise_motion/source_outcome_index.json"
DEFAULT_SOURCE_CACHE_DIR = REPO_ROOT / "build/exercise_motion/youtube-source-cache"
HARNESS_ROOT = REPO_ROOT / "build/exercise_motion/speed-harness"
SMOKE_CHECK_ROOT = HARNESS_ROOT / "smoke-check"
DEFAULT_MOTION_PYTHON = r"C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
PATH_TEXT_SUFFIXES = {".html", ".json", ".jsonl", ".md", ".toml", ".txt", ".yaml", ".yml"}

# Small default smoke pair. It may fail discovery before reaching staged
# processing; use a fixed, verified source fixture for throughput comparisons.
DEFAULT_EXERCISES = (
    "dumbbell-incline-bench-press",
    "pike-push-up",
)

ARMS: dict[str, list[str]] = {
    # Library-equivalent defaults: warm GVHMR worker + YOLO co-residency.
    "baseline": ["-WarmWhamWorker:$true", "-KeepLlamaCppServer:$true"],
    # + one supervisor-owned shared llama server for all vision consumers.
    "shared": ["-WarmWhamWorker:$true", "-KeepLlamaCppServer:$true", "-SharedLlamaServer"],
    # + overlapping waves (next wave's source validation during final validation).
    "shared-overlap": [
        "-WarmWhamWorker:$true", "-KeepLlamaCppServer:$true", "-SharedLlamaServer",
        "-MaxConcurrentStagedWaves", "2",
    ],
}


def slugify(name: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", name.strip().lower())).strip("-")


def build_mini_library(library_json: Path, slugs: set[str], destination: Path) -> list[str]:
    payload = json.loads(library_json.read_text(encoding="utf-8"))
    matched: list[str] = []
    definitions = []
    for definition in payload.get("exerciseDefinitions", []):
        if slugify(str(definition.get("name", ""))) in slugs:
            definitions.append(definition)
            matched.append(slugify(str(definition.get("name", ""))))
    missing = sorted(slugs - set(matched))
    if missing:
        raise SystemExit(f"Exercises not found in {library_json}: {', '.join(missing)}")
    movements = payload.get("exerciseMovements")
    if isinstance(movements, list):
        movements = [m for m in movements if slugify(str(m.get("exerciseName", m.get("name", "")))) in slugs]
    mini = {
        "format": payload.get("format"),
        "schemaVersion": payload.get("schemaVersion"),
        "exerciseDefinitions": definitions,
        "exerciseMovements": movements,
        "equipments": payload.get("equipments", []),
        "accessoryEquipments": payload.get("accessoryEquipments", []),
    }
    destination.write_text(json.dumps(mini, indent=1), encoding="utf-8")
    return matched


def _rewrite_absolute_workspace_references(
    workspace: Path,
    path_mappings: list[tuple[Path, Path]],
) -> int:
    replacements: list[tuple[str, str]] = []
    for source, destination in path_mappings:
        source_text = str(source.resolve())
        destination_text = str(destination.resolve())
        for source_variant, destination_variant in (
            (source_text, destination_text),
            (source_text.replace("\\", "/"), destination_text.replace("\\", "/")),
            (source_text.replace("\\", "\\\\"), destination_text.replace("\\", "\\\\")),
        ):
            if source_variant not in {old for old, _ in replacements}:
                replacements.append((source_variant, destination_variant))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    rewritten_files = 0
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in PATH_TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        updated = text
        for source_text, destination_text in replacements:
            updated = updated.replace(source_text, destination_text)
        if updated != text:
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
            rewritten_files += 1
    return rewritten_files


def assemble_workspace(arm_dir: Path, slugs: list[str], base_workspace: Path) -> int:
    if arm_dir.exists():
        shutil.rmtree(arm_dir)
    # The production pipeline places its content-addressed WHAM cache under
    # the nearest ancestor named "exercise_motion". Give each arm its own
    # such root so a preceding arm cannot warm the next arm's cache.
    workspace = arm_dir / "isolated" / "exercise_motion" / "workspace"
    workspace.mkdir(parents=True)
    path_mappings: list[tuple[Path, Path]] = []
    for slug in slugs:
        source = base_workspace / slug
        if not source.is_dir():
            raise SystemExit(f"Missing exercise workspace: {source}")
        destination = workspace / slug
        shutil.copytree(source, destination)
        path_mappings.append((source, destination))
    contract_cache = base_workspace / "exercise-motion-contract-cache"
    if contract_cache.is_dir():
        contract_destination = workspace / "exercise-motion-contract-cache"
        shutil.copytree(contract_cache, contract_destination)
        path_mappings.append((contract_cache, contract_destination))
    return _rewrite_absolute_workspace_references(workspace, path_mappings)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_fixture_manifest(manifest_path: Path) -> dict:
    """Load a fixture manifest and re-verify every recorded SHA-256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "motion_fixed_fixture_set":
        raise SystemExit(f"{manifest_path}: not a motion_fixed_fixture_set manifest")
    exercises = manifest.get("exercises") or []
    if not exercises:
        raise SystemExit(f"{manifest_path}: manifest lists no exercises")
    for exercise in exercises:
        checks = [
            (exercise["sourceCachePath"], exercise["sourceSha256"]),
            (exercise["preparedCandidatesPath"], exercise["preparedCandidatesSha256"]),
            (exercise["contractPath"], exercise["contractSha256"]),
        ] + [(ref["path"], ref["sha256"]) for ref in exercise.get("referenceFiles", [])]
        for path_text, expected in checks:
            path = Path(path_text)
            if not path.is_file():
                raise SystemExit(f"Fixture file missing: {path}")
            actual = sha256_file(path)
            if actual != expected:
                raise SystemExit(
                    f"Fixture SHA-256 mismatch for {path}: expected {expected}, got {actual}"
                )
    print(f"[harness] fixtures verified: {len(exercises)} exercises", flush=True)
    return manifest


def assemble_workspace_fixtures(
    arm_dir: Path, manifest: dict, base_workspace: Path
) -> tuple[Path, list[str]]:
    """Seed a fresh per-exercise workspace set from the fixed fixture set.

    Seeds only exercise_plan.json per slug (no completed selections,
    reconstruction results, terminal verdicts, or old staged reports), copies
    the contract cache snapshot, and stages an arm-local prepared-candidates
    manifest with the pinned candidates copied next to it.
    """
    if arm_dir.exists():
        shutil.rmtree(arm_dir)
    workspace = arm_dir / "isolated" / "exercise_motion" / "workspace"
    workspace.mkdir(parents=True)
    seeds_root = Path(manifest["workspaceSeedsRoot"])
    fixtures_dir = arm_dir / "fixtures"
    fixtures_dir.mkdir()
    manifest_items: list[dict] = []
    for exercise in manifest["exercises"]:
        slug = exercise["slug"]
        seed = seeds_root / slug / "exercise_plan.json"
        if not seed.is_file():
            raise SystemExit(f"Missing fixture workspace seed: {seed}")
        destination = workspace / slug
        destination.mkdir()
        shutil.copy2(seed, destination / "exercise_plan.json")
        candidates_destination = fixtures_dir / slug / "youtube_candidates.json"
        candidates_destination.parent.mkdir(parents=True)
        # Copy arm-local so the staged manifest never points outside this arm.
        shutil.copy2(exercise["preparedCandidatesPath"], candidates_destination)
        manifest_items.append({
            "exerciseId": exercise["exerciseId"],
            "exerciseName": exercise["exerciseName"],
            "exerciseSlug": slug,
            "candidatesJson": candidates_destination.resolve().as_posix(),
            "expectedVideoId": exercise["expectedVideoId"],
        })
    contract_cache = base_workspace / "exercise-motion-contract-cache"
    if contract_cache.is_dir():
        shutil.copytree(contract_cache, workspace / "exercise-motion-contract-cache")
    prepared_manifest_path = fixtures_dir / "prepared_candidates_manifest.json"
    prepared_manifest_path.write_text(
        json.dumps({
            "schemaVersion": 1,
            "kind": "prepared_exercise_candidates",
            "items": manifest_items,
        }, indent=1),
        encoding="utf-8",
    )
    return prepared_manifest_path, [item["exerciseSlug"] for item in manifest_items]


def resolve_motion_python() -> str:
    return os.environ.get("EXERCISE_MOTION_PYTHON") or DEFAULT_MOTION_PYTHON


def capture_run_identity() -> dict:
    """Run-identity facts captured once at run start (plan section 2)."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    diff = subprocess.run(["git", "diff"], cwd=REPO_ROOT, capture_output=True, check=False)
    python_command = resolve_motion_python()
    version = subprocess.run(
        [python_command, "--version"], capture_output=True, text=True, check=False,
    )
    return {
        "gitCommit": commit.stdout.strip() or None,
        "gitDiffSha256": hashlib.sha256(diff.stdout).hexdigest(),
        "pythonCommand": python_command,
        "pythonVersion": (version.stdout or version.stderr).strip() or None,
    }


def _parse_utc(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_scheduler_timeline(arm_result: dict) -> dict | None:
    """Parse the runner-written scheduler timeline into compact metrics.

    Missing or unparsable timeline is retained as null, not an error.
    """
    timeline_path = Path(arm_result["workspace"]) / "scheduler_timeline.json"
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    started = _parse_utc(timeline.get("runStartedAtUtc"))
    items = []
    for item in timeline.get("items") or []:
        entry = {
            key: item.get(key)
            for key in (
                "exerciseId", "exerciseSlug", "readyAtUtc", "enqueuedAtUtc",
                "admittedAtUtc", "firstAcceptedAtUtc", "materializedAtUtc", "finalStatus",
            )
        }
        if started is not None:
            for source_key, target_key in (
                ("firstAcceptedAtUtc", "secondsToFirstAccepted"),
                ("materializedAtUtc", "secondsToFirstMaterialized"),
            ):
                moment = _parse_utc(item.get(source_key))
                if moment is not None:
                    entry[target_key] = round((moment - started).total_seconds(), 3)
        items.append(entry)
    wave_admissions = [
        {
            "waveId": wave.get("waveId"),
            "admissionReason": wave.get("admissionReason"),
            "concurrentWaveCountAtAdmission": wave.get("concurrentWaveCountAtAdmission"),
        }
        for wave in timeline.get("waves") or []
    ]
    return {
        "runStartedAtUtc": timeline.get("runStartedAtUtc"),
        "items": items,
        "waveAdmissions": wave_admissions,
    }


def _log_tail(log_path: Path, lines: int = 12) -> str:
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<no log>"
    return "\n".join(content[-lines:])


def build_runner_command(
    arm: str, arm_dir: Path, plan_json: Path, staged_wave_size: int,
    staged_wave_max_wait_seconds: int, extra_runner_args: list[str] | None = None,
) -> list[str]:
    args = [
        "pwsh", "-NoProfile", "-File", str(RUNNER),
        "-WorkoutPlanJson", str(plan_json),
        "-WorkspaceRoot", str(arm_dir / "isolated" / "exercise_motion" / "workspace"),
        "-IncrementalMobilePackageOutputJson", str(arm_dir / "movements_out.json"),
        "-MotionReconstructor", "gvhmr",
        "-StagedWaveSize", str(staged_wave_size),
        "-StagedWaveMaxWaitSeconds", str(staged_wave_max_wait_seconds),
        "-SourceOutcomeIndexJson", str(arm_dir / "source_outcome_index.json"),
    ] + ARMS[arm]
    if extra_runner_args:
        args += list(extra_runner_args)
    return args


def run_arm(arm: str, arm_dir: Path, plan_json: Path, timeout_seconds: float,
            staged_wave_size: int, staged_wave_max_wait_seconds: int,
            stall_seconds: float = 180.0,
            extra_runner_args: list[str] | None = None) -> dict:
    source_index = arm_dir / "source_outcome_index.json"
    if DEFAULT_SOURCE_OUTCOME_INDEX.is_file():
        shutil.copy2(DEFAULT_SOURCE_OUTCOME_INDEX, source_index)
    log_path = arm_dir / "run.log"
    args = build_runner_command(
        arm, arm_dir, plan_json, staged_wave_size, staged_wave_max_wait_seconds,
        extra_runner_args=extra_runner_args,
    )
    started = time.perf_counter()
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(args, stdout=log_handle, stderr=subprocess.STDOUT)
    status = "running"
    last_size = -1
    last_growth = time.perf_counter()
    try:
        while process.poll() is None:
            time.sleep(5.0)
            try:
                size = log_path.stat().st_size
            except OSError:
                size = last_size
            if size != last_size:
                last_size = size
                last_growth = time.perf_counter()
            elif time.perf_counter() - last_growth > stall_seconds:
                # The runner logs continuously (queue snapshots, heartbeats);
                # a silent log means the arm is wedged, not working.
                status = "stalled"
                _kill_process_tree(process)
                print(f"[harness] {arm}: STALLED (log silent {stall_seconds:.0f}s). Tail:\n{_log_tail(log_path)}", flush=True)
                break
            if time.perf_counter() - started > timeout_seconds:
                status = "timeout"
                _kill_process_tree(process)
                print(f"[harness] {arm}: TIMEOUT after {timeout_seconds:.0f}s. Tail:\n{_log_tail(log_path)}", flush=True)
                break
    finally:
        log_handle.close()
    elapsed = time.perf_counter() - started
    exit_code = process.returncode if status == "running" else status
    return {
        "arm": arm,
        "exitCode": exit_code,
        "wallSeconds": round(elapsed, 1),
        "workspace": str(arm_dir / "isolated" / "exercise_motion" / "workspace"),
        "whamCacheRoot": str(arm_dir / "isolated" / "exercise_motion" / "wham-cache"),
        "log": str(log_path),
        "runnerArgs": args,
    }


def _kill_process_tree(process: subprocess.Popen) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
        capture_output=True, check=False,
    )


def extract_metrics(arm_result: dict) -> dict:
    workspace = Path(arm_result["workspace"])
    metrics: dict = {
        "phases": {"source": 0.0, "generation": 0.0, "final": 0.0},
        "waves": 0,
        "maxExercisesPerWave": 0,
        "sourceValidationWorkersHighWater": 0,
        "visionStartups": 0,
        "visionStartupSeconds": 0.0,
        "visionQueueWaitSeconds": 0.0,
        "coResidentOps": 0,
        "coResidentDeclined": 0,
        "sharedQuiesceCount": 0,
        "sharedRestartRequests": 0,
        "gvhmrAttempts": 0,
        "gvhmrAttemptSeconds": 0.0,
    }
    for report_path in sorted(workspace.glob("staged-waves/*/staged_wave_report.json")):
        metrics["waves"] += 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        m = report.get("metrics", {})
        metrics["maxExercisesPerWave"] = max(
            metrics["maxExercisesPerWave"], len(report.get("items") or [])
        )
        metrics["sourceValidationWorkersHighWater"] = max(
            metrics["sourceValidationWorkersHighWater"],
            int(m.get("sourceValidationWorkers") or 0),
        )
        timings = m.get("phaseTimings", {})
        metrics["phases"]["source"] += timings.get("sourceValidationSeconds", 0.0)
        metrics["phases"]["generation"] += timings.get("whamGenerationSeconds", 0.0)
        metrics["phases"]["final"] += timings.get("finalValidationSeconds", 0.0)
        for phase in ("sourceVisionSession", "finalVisionSession"):
            session = m.get(phase) or {}
            metrics["visionStartups"] += session.get("visionRankerStartupCount", 0)
            metrics["visionStartupSeconds"] += session.get("visionRankerStartupSeconds", 0.0)
            metrics["visionQueueWaitSeconds"] += session.get("visionQueueWaitSeconds", 0.0)
            metrics["coResidentOps"] += session.get("coResidentGpuOperationCount", 0)
            metrics["coResidentDeclined"] += session.get("coResidentGpuDeclinedCount", 0)
            shared = session.get("sharedVisionSession") or session
            metrics["sharedQuiesceCount"] += (shared.get("sharedVisionQuiesceCount") or 0)
            metrics["sharedRestartRequests"] += (shared.get("sharedVisionRestartRequestCount") or 0)
    for checkpoint_path in sorted(workspace.glob("staged-waves/*/staged_wave_checkpoint.json")):
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in checkpoint.get("items", []):
            wham = item.get("wham") or {}
            timing = wham.get("timing") or wham.get("timings") or {}
            candidates = [
                attempt for attempt in (wham.get("attempts") or [])
                if isinstance(attempt, dict) and isinstance(attempt.get("elapsedSeconds"), (int, float))
            ]
            for attempt in candidates:
                metrics["gvhmrAttempts"] += 1
                metrics["gvhmrAttemptSeconds"] += float(attempt.get("elapsedSeconds", 0.0))
    summary_path = workspace / "workout_motion_generation_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        statuses: dict[str, int] = {}
        for exercise in summary.get("exercises", []):
            status = str(exercise.get("status", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
        metrics["statuses"] = statuses
        metrics["overlapHighWater"] = summary.get("runningStagedWaveCountHighWater")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", default=",".join(ARMS), help="Comma-separated arm names")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--exercises", default=None,
        help="Comma-separated slugs; unused (and mutually exclusive) with --fixtures",
    )
    source_group.add_argument(
        "--fixtures", type=Path, default=None,
        help="fixture_manifest.json from build_motion_fixed_fixtures.py; pins verified "
             "candidates, seeds exercise_plan.json-only workspaces, and stages a "
             "prepared-candidates manifest per arm",
    )
    parser.add_argument(
        "--smoke-check", action="store_true",
        help="With --fixtures: verify fixtures, assemble the first requested arm, print "
             "the exact runner command, and exit without running any model",
    )
    parser.add_argument("--library-json", type=Path, default=DEFAULT_LIBRARY_JSON)
    parser.add_argument("--base-workspace", type=Path, default=DEFAULT_BASE_WORKSPACE)
    parser.add_argument("--timeout-seconds", type=float, default=45 * 60.0)
    parser.add_argument(
        "--staged-wave-size",
        type=int,
        default=1,
        help="Exercises per staged wave; production library default is 8.",
    )
    parser.add_argument(
        "--staged-wave-max-wait-seconds",
        type=int,
        default=300,
        help="Partial-wave wait before flushing; production library default is 300.",
    )
    parser.add_argument("--keep-workspaces", action="store_true")
    args = parser.parse_args()

    arm_names = [name.strip() for name in args.arms.split(",") if name.strip()]
    unknown = [name for name in arm_names if name not in ARMS]
    if unknown:
        raise SystemExit(f"Unknown arms: {', '.join(unknown)}; available: {', '.join(ARMS)}")
    if args.staged_wave_size < 1:
        raise SystemExit("--staged-wave-size must be at least 1")
    if args.staged_wave_max_wait_seconds < 1:
        raise SystemExit("--staged-wave-max-wait-seconds must be at least 1")
    if args.smoke_check and args.fixtures is None:
        raise SystemExit("--smoke-check requires --fixtures")

    fixture_manifest = None
    if args.fixtures is not None:
        fixture_manifest = load_fixture_manifest(args.fixtures.resolve())
        slugs = [exercise["slug"] for exercise in fixture_manifest["exercises"]]
        if len(set(slugs)) != len(slugs):
            raise SystemExit(f"Duplicate slugs in fixture manifest: {slugs}")
    else:
        if args.exercises is None:
            args.exercises = ",".join(DEFAULT_EXERCISES)
        slugs = [slug.strip() for slug in args.exercises.split(",") if slug.strip()]

    run_identity = capture_run_identity()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = SMOKE_CHECK_ROOT if args.smoke_check else HARNESS_ROOT / stamp
    if args.smoke_check and run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    plan_json = run_root / "mini_library.json"
    matched = build_mini_library(args.library_json, set(slugs), plan_json)
    print(f"[harness] {len(matched)} exercises: {', '.join(matched)}", flush=True)
    library_plan_sha = sha256_file(plan_json)
    fixture_manifest_sha = sha256_file(args.fixtures) if args.fixtures is not None else None

    results = []
    requested_arms = arm_names[:1] if args.smoke_check else arm_names
    for arm in requested_arms:
        arm_dir = run_root / arm
        print(f"\n[harness] === arm '{arm}' ===", flush=True)
        fixture_args: list[str] = []
        if fixture_manifest is not None:
            prepared_manifest_path, seeded = assemble_workspace_fixtures(
                arm_dir, fixture_manifest, args.base_workspace
            )
            fixture_args = [
                "-PreparedCandidatesManifest", str(prepared_manifest_path),
                "-YouTubeSourceCacheDir", str(DEFAULT_SOURCE_CACHE_DIR),
            ]
            print(f"[harness] seeded exercise_plan.json only for: {', '.join(seeded)}", flush=True)
            print(f"[harness] staged prepared-candidates manifest: {prepared_manifest_path}", flush=True)
        else:
            rewritten_paths = assemble_workspace(arm_dir, matched, args.base_workspace)
            print(f"[harness] remapped workspace paths in {rewritten_paths} copied text files", flush=True)
        if args.smoke_check:
            command = build_runner_command(
                arm, arm_dir, plan_json, args.staged_wave_size,
                args.staged_wave_max_wait_seconds, extra_runner_args=fixture_args,
            )
            workspace = arm_dir / "isolated" / "exercise_motion" / "workspace"
            for slug in matched:
                seeded_files = sorted(path.name for path in (workspace / slug).iterdir())
                print(f"[harness] seed {slug}: {seeded_files}", flush=True)
            print("\n[harness] smoke-check runner command (not executed):", flush=True)
            print(subprocess.list2cmdline(command), flush=True)
            print("\n[harness] smoke-check OK", flush=True)
            return
        arm_result = run_arm(
            arm,
            arm_dir,
            plan_json,
            args.timeout_seconds,
            staged_wave_size=args.staged_wave_size,
            staged_wave_max_wait_seconds=args.staged_wave_max_wait_seconds,
            extra_runner_args=fixture_args or None,
        )
        arm_result.update(run_identity)
        arm_result["fixtureManifestPath"] = str(args.fixtures) if args.fixtures is not None else None
        arm_result["fixtureManifestSha256"] = fixture_manifest_sha
        arm_result["libraryPlanSha256"] = library_plan_sha
        arm_result["workspacePathsRemapped"] = (
            None if fixture_manifest is not None else rewritten_paths
        )
        if isinstance(arm_result.get("exitCode"), int) and arm_result["exitCode"] != 0:
            print(f"[harness] {arm}: FAILED (exit {arm_result['exitCode']}). Tail:\n{_log_tail(Path(arm_result['log']))}", flush=True)
            if arm_result["wallSeconds"] < 120:
                # A config error fails every arm identically; abort instead of
                # burning the remaining arms on it.
                results.append(arm_result)
                print("[harness] aborting remaining arms (early failure = config error).", flush=True)
                break
        arm_result["metrics"] = extract_metrics(arm_result)
        arm_result["schedulerTimeline"] = load_scheduler_timeline(arm_result)
        results.append(arm_result)
        m = arm_result["metrics"]
        print(
            f"[harness] {arm}: wall={arm_result['wallSeconds']}s exit={arm_result['exitCode']} "
            f"waves={m['waves']} phases(s/g/f)={m['phases']['source']:.0f}/{m['phases']['generation']:.0f}/{m['phases']['final']:.0f} "
            f"waveItems={m['maxExercisesPerWave']} sourceWorkers={m['sourceValidationWorkersHighWater']} "
            f"startups={m['visionStartups']}/{m['visionStartupSeconds']:.0f}s coRes={m['coResidentOps']} "
            f"quiesce={m['sharedQuiesceCount']} overlapHW={m.get('overlapHighWater')} "
            f"gvhmr={m['gvhmrAttempts']}x{m['gvhmrAttemptSeconds']:.0f}s statuses={m.get('statuses')}",
            flush=True,
        )
        statuses = m.get("statuses") or {}
        all_completed = bool(statuses) and set(statuses) == {"completed"}
        if not args.keep_workspaces and arm_result.get("exitCode") == 0 and all_completed:
            # Failed or rejected runs need their per-exercise discovery and
            # selection artifacts for diagnosis. Only discard inputs after a
            # clean arm that completed every exercise.
            workspace = Path(arm_result["workspace"])
            for slug in matched:
                target = workspace / slug
                if target.is_dir():
                    shutil.rmtree(target)
            arm_result["workspaceArtifactsRetained"] = False
        else:
            arm_result["workspaceArtifactsRetained"] = True

    results_path = run_root / "results.json"
    results_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\n[harness] results: {results_path}", flush=True)


if __name__ == "__main__":
    main()

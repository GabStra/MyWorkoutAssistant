"""Speed-config harness for bounded pipeline tuning.

Assembles a fresh mini workspace from retained exercise workspaces and runs
the staged workout-plan runner once per configuration arm. Candidate discovery
and source selection may still run; a small exercise list does not guarantee a
short run, entry into staged processing, or an accepted movement. Reports
include wall time, per-phase timings, wave size, source workers, vision-server
startup counts, co-resident operations, shared-server quiesce metrics, overlap
high-water mark, per-wave browser task metrics, separate candidate-generation and
GVHMR timings, and terminal statuses.

Usage:
  python scripts/motion_speed_harness.py --arms baseline,shared
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
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_exercise_motion_workout_plan.ps1"
DEFAULT_LIBRARY_JSON = Path(r"C:\Users\gabri\Downloads\my_exercise_library.json")
DEFAULT_BASE_WORKSPACE = REPO_ROOT / "build/exercise_motion/exercise-library"
DEFAULT_SOURCE_OUTCOME_INDEX = REPO_ROOT / "build/exercise_motion/source_outcome_index.json"
DEFAULT_SOURCE_CACHE_DIR = REPO_ROOT / "build/exercise_motion/youtube-source-cache"
HARNESS_ROOT = REPO_ROOT / "build/exercise_motion/speed-harness"
DEFAULT_MOTION_PYTHON = r"C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
GVHMR_DOCKER_IMAGE = "myworkoutassistant/gvhmr:torch2.3-cu121"
DEFAULT_STAGED_WAVE_SIZE = 8
DEFAULT_PREFETCH_WORKERS = 8
DEFAULT_PREFETCH_QUEUE_DEPTH = 40
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
}

UNSUPPORTED_ARMS = {
    "shared-overlap": (
        "the current workspace-scoped persistent staged-wave service is serial "
        "and the runner clamps MaxConcurrentStagedWaves to 1; no overlap would occur"
    ),
}

ARM_EFFECTIVE_SETTINGS = {
    "baseline": {"sharedLlamaServerEnabled": False, "effectiveMaxConcurrentStagedWaves": 1},
    "shared": {"sharedLlamaServerEnabled": True, "effectiveMaxConcurrentStagedWaves": 1},
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


def sha256_directory_contents(directory: Path) -> str:
    """Hash file names and contents in a directory tree, independent of order."""
    if not directory.is_dir():
        raise SystemExit(f"Fixture directory missing: {directory}")
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative_path = path.relative_to(directory).as_posix().encode("utf-8")
        content_digest = bytes.fromhex(sha256_file(path))
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(content_digest)
    return digest.hexdigest()


def load_fixture_manifest(manifest_path: Path) -> dict:
    """Load a fixture manifest and re-verify every recorded SHA-256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "motion_fixed_fixture_set":
        raise SystemExit(f"{manifest_path}: not a motion_fixed_fixture_set manifest")
    exercises = manifest.get("exercises") or []
    if not exercises:
        raise SystemExit(f"{manifest_path}: manifest lists no exercises")
    cache_path_text = manifest.get("contractCacheSnapshotPath")
    cache_sha256 = manifest.get("contractCacheSnapshotSha256")
    if not isinstance(cache_path_text, str) or not isinstance(cache_sha256, str):
        raise SystemExit(
            f"{manifest_path}: fixture does not pin the contract-cache snapshot; "
            "rebuild it with build_motion_fixed_fixtures.py"
        )
    cache_path = Path(cache_path_text)
    actual_cache_sha256 = sha256_directory_contents(cache_path)
    if actual_cache_sha256 != cache_sha256:
        raise SystemExit(
            f"Fixture contract-cache SHA-256 mismatch for {cache_path}: "
            f"expected {cache_sha256}, got {actual_cache_sha256}"
        )
    for exercise in exercises:
        seed_path_text = exercise.get("workspaceSeedPath")
        seed_sha256 = exercise.get("workspaceSeedSha256")
        if not isinstance(seed_path_text, str) or not isinstance(seed_sha256, str):
            raise SystemExit(
                f"{manifest_path}: fixture '{exercise.get('slug', '<unknown>')}' "
                "does not pin exercise_plan.json; rebuild it with "
                "build_motion_fixed_fixtures.py"
            )
        checks = [
            (exercise["sourceCachePath"], exercise["sourceSha256"]),
            (exercise["preparedCandidatesPath"], exercise["preparedCandidatesSha256"]),
            (exercise["contractPath"], exercise["contractSha256"]),
            (seed_path_text, seed_sha256),
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
    arm_dir: Path, manifest: dict, contract_cache_snapshot: Path | None = None
) -> tuple[Path, list[str]]:
    """Seed a fresh per-exercise workspace set from the fixed fixture set.

    Seeds only exercise_plan.json per slug (no completed selections,
    reconstruction results, terminal verdicts, or old staged reports), copies
    the pinned contract-cache snapshot, and stages an arm-local prepared-candidates
    manifest with the pinned candidates copied next to it.
    """
    if arm_dir.exists():
        shutil.rmtree(arm_dir)
    workspace = arm_dir / "isolated" / "exercise_motion" / "workspace"
    workspace.mkdir(parents=True)
    expected_cache_sha256 = manifest["contractCacheSnapshotSha256"]
    if contract_cache_snapshot is None:
        contract_cache_snapshot = Path(manifest["contractCacheSnapshotPath"])
    actual_cache_sha256 = sha256_directory_contents(contract_cache_snapshot)
    if actual_cache_sha256 != expected_cache_sha256:
        raise SystemExit(
            f"Fixture contract-cache SHA-256 mismatch before arm assembly for "
            f"{contract_cache_snapshot}: expected {expected_cache_sha256}, "
            f"got {actual_cache_sha256}"
        )
    fixtures_dir = arm_dir / "fixtures"
    fixtures_dir.mkdir()
    manifest_items: list[dict] = []
    for exercise in manifest["exercises"]:
        slug = exercise["slug"]
        seed = Path(exercise["workspaceSeedPath"])
        expected_seed_sha256 = exercise["workspaceSeedSha256"]
        if not seed.is_file():
            raise SystemExit(f"Missing fixture workspace seed: {seed}")
        actual_seed_sha256 = sha256_file(seed)
        if actual_seed_sha256 != expected_seed_sha256:
            raise SystemExit(
                f"Fixture workspace seed SHA-256 mismatch for {seed}: "
                f"expected {expected_seed_sha256}, got {actual_seed_sha256}"
            )
        destination = workspace / slug
        destination.mkdir()
        seeded_plan = destination / "exercise_plan.json"
        shutil.copy2(seed, seeded_plan)
        copied_seed_sha256 = sha256_file(seeded_plan)
        if copied_seed_sha256 != expected_seed_sha256:
            raise SystemExit(
                f"Copied workspace seed SHA-256 mismatch for {seeded_plan}: "
                f"expected {expected_seed_sha256}, got {copied_seed_sha256}"
            )
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
    arm_contract_cache = workspace / "exercise-motion-contract-cache"
    shutil.copytree(contract_cache_snapshot, arm_contract_cache)
    copied_cache_sha256 = sha256_directory_contents(arm_contract_cache)
    if copied_cache_sha256 != expected_cache_sha256:
        raise SystemExit(
            f"Copied contract-cache SHA-256 mismatch for {arm_contract_cache}: "
            f"expected {expected_cache_sha256}, got {copied_cache_sha256}"
        )
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


def stage_fixture_contract_cache(manifest: dict, destination: Path) -> Path:
    """Copy the verified fixture cache once so every arm consumes identical bytes."""
    source = Path(manifest["contractCacheSnapshotPath"])
    expected_sha256 = manifest["contractCacheSnapshotSha256"]
    source_sha256 = sha256_directory_contents(source)
    if source_sha256 != expected_sha256:
        raise SystemExit(
            f"Fixture contract-cache SHA-256 mismatch before staging: "
            f"expected {expected_sha256}, got {source_sha256}"
        )
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite staged fixture cache: {destination}")
    shutil.copytree(source, destination)
    staged_sha256 = sha256_directory_contents(destination)
    if staged_sha256 != expected_sha256:
        raise SystemExit(
            f"Staged contract-cache SHA-256 mismatch for {destination}: "
            f"expected {expected_sha256}, got {staged_sha256}"
        )
    return destination


def stage_fixture_source_cache(manifest: dict, destination: Path) -> Path:
    """Copy pinned source videos into an arm-local cache and verify every copy."""
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite staged fixture source cache: {destination}")
    destination.mkdir(parents=True)
    copied_hashes: dict[str, str] = {}
    for exercise in manifest.get("exercises") or []:
        source = Path(exercise["sourceCachePath"])
        expected_sha256 = exercise["sourceSha256"]
        if not source.is_file():
            raise SystemExit(f"Fixture source cache file missing: {source}")
        source_sha256 = sha256_file(source)
        if source_sha256 != expected_sha256:
            raise SystemExit(
                f"Fixture source SHA-256 mismatch for {source}: "
                f"expected {expected_sha256}, got {source_sha256}"
            )

        target = destination / source.name
        previous_hash = copied_hashes.get(source.name)
        if previous_hash is not None:
            if previous_hash != expected_sha256:
                raise SystemExit(
                    f"Fixture source cache filename collision for {source.name}: "
                    f"{previous_hash} != {expected_sha256}"
                )
            continue
        shutil.copy2(source, target)
        copied_sha256 = sha256_file(target)
        if copied_sha256 != expected_sha256:
            raise SystemExit(
                f"Copied fixture source SHA-256 mismatch for {target}: "
                f"expected {expected_sha256}, got {copied_sha256}"
            )
        copied_hashes[source.name] = copied_sha256
    return destination


def resolve_motion_python() -> str:
    return os.environ.get("EXERCISE_MOTION_PYTHON") or DEFAULT_MOTION_PYTHON


def capture_run_identity() -> dict:
    """Run-identity facts captured once at run start (plan section 2)."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    untracked_digest = hashlib.sha256()
    untracked_count = 0
    for encoded_path in untracked.stdout.split(b"\0"):
        if not encoded_path:
            continue
        relative_path = os.fsdecode(encoded_path)
        path = REPO_ROOT / relative_path
        try:
            if path.is_symlink():
                file_kind = b"symlink"
                contents = os.fsencode(os.readlink(path))
            elif path.is_file():
                file_kind = b"file"
                contents = path.read_bytes()
            else:
                file_kind = b"other"
                contents = b""
        except OSError:
            file_kind = b"unreadable"
            contents = b""
        path_bytes = encoded_path
        for part in (file_kind, path_bytes, contents):
            untracked_digest.update(len(part).to_bytes(8, "big"))
            untracked_digest.update(part)
        untracked_count += 1
    python_command = resolve_motion_python()
    version = subprocess.run(
        [python_command, "--version"], capture_output=True, text=True, check=False,
    )
    tracked_diff_digest = hashlib.sha256(diff.stdout).hexdigest()
    untracked_content_digest = untracked_digest.hexdigest()
    return {
        "gitCommit": commit.stdout.strip() or None,
        "gitDiffBase": "HEAD",
        "gitDiffSha256": tracked_diff_digest,
        "gitUntrackedContentSha256": untracked_content_digest,
        "gitUntrackedFileCount": untracked_count,
        "gitWorktreeClean": not diff.stdout and untracked_count == 0,
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


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def build_runner_command(
    arm: str, arm_dir: Path, plan_json: Path, staged_wave_size: int,
    staged_wave_max_wait_seconds: int, extra_runner_args: list[str] | None = None,
    *, cpu_prefetch_during_bake: bool = True,
    prefetch_workers: int = DEFAULT_PREFETCH_WORKERS,
    prefetch_queue_depth: int = DEFAULT_PREFETCH_QUEUE_DEPTH,
    preview_cache_dir: Path | None = None,
    source_cache_dir: Path | None = None,
) -> list[str]:
    if staged_wave_size < 0:
        raise ValueError("staged_wave_size must be zero or greater")
    if prefetch_workers < 1 or prefetch_queue_depth < 1:
        raise ValueError("prefetch worker count and queue depth must be at least 1")
    if preview_cache_dir is None:
        preview_cache_dir = arm_dir / "cache" / "youtube-preview-cache"
    if source_cache_dir is None:
        source_cache_dir = arm_dir / "cache" / "youtube-source-cache"
    args = [
        "pwsh", "-NoProfile", "-File", str(RUNNER),
        "-WorkoutPlanJson", str(plan_json),
        "-WorkspaceRoot", str(arm_dir / "isolated" / "exercise_motion" / "workspace"),
        "-IncrementalMobilePackageOutputJson", str(arm_dir / "movements_out.json"),
        "-YouTubePreviewCacheDir", str(preview_cache_dir),
        "-YouTubeSourceCacheDir", str(source_cache_dir),
        "-MotionReconstructor", "gvhmr",
        "-StagedWaveSize", str(staged_wave_size),
        "-StagedWaveMaxWaitSeconds", str(staged_wave_max_wait_seconds),
        "-PrefetchWorkers", str(prefetch_workers),
        "-PrefetchQueueDepth", str(prefetch_queue_depth),
        "-SourceOutcomeIndexJson", str(arm_dir / "source_outcome_index.json"),
    ] + ARMS[arm]
    if cpu_prefetch_during_bake:
        args.append("-CpuPrefetchDuringBake")
    if extra_runner_args:
        args += list(extra_runner_args)
    return args


def prewarm_gvhmr_worker(timeout_seconds: float = 600.0) -> dict:
    """Run the production warm-worker container once until ready, then stop it.

    The worker's cold in-container startup (python imports + ViTPose/HMR2
    init, ~350-460s measured) is page-cache dominated; a silent cold start
    inside a timed arm reads as a wedge and can be stall-killed before it
    becomes ready. Warming once before the first arm gives every arm the same
    fast-start environment. Mirrors the production docker invocation in
    run_exercise_motion_workout_plan.ps1.
    """
    pkg_dir = REPO_ROOT / "exercise_motion_pkg"
    prewarm_root = HARNESS_ROOT / "prewarm" / uuid.uuid4().hex
    state_dir = prewarm_root / "gvhmr-warm-worker"
    workspace_dir = prewarm_root / "workspace"
    for child in ("jobs", "running", "results", "job_logs"):
        (state_dir / child).mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("ready.json", "heartbeat.json", "startup_error.json", "stop", "stopped.json"):
        path = state_dir / stale
        if path.exists():
            path.unlink()
    container = f"mwa-gvhmr-prewarm-{uuid.uuid4().hex[:12]}"
    args = [
        "docker", "run", "-d", "--rm", "--name", container,
        "--gpus", "all", "--shm-size", "8g",
        "-v", str(pkg_dir / "gvhmr_inference.py") + ":/worker/gvhmr_inference.py:ro",
        "-v", str(pkg_dir / "gvhmr_pkl_export.py") + ":/worker/gvhmr_pkl_export.py:ro",
        "-v", str(workspace_dir) + ":/workspace",
        "-v", str(state_dir) + ":/worker_state",
        "-v", str(pkg_dir / "gvhmr_warm_worker.py") + ":/worker/gvhmr_warm_worker.py:ro",
        "-v", str(pkg_dir / "warm_worker_retention.py") + ":/worker/warm_worker_retention.py:ro",
        "-w", "/opt/gvhmr",
        GVHMR_DOCKER_IMAGE,
        "python", "-u", "/worker/gvhmr_warm_worker.py",
        "--state-dir", "/worker_state",
    ]
    started = time.perf_counter()
    print(f"[harness] prewarming GVHMR worker (cold start ~350-460s when uncached)...", flush=True)
    run_error = None
    container_start_exit_code = None
    container_id = None
    try:
        start_result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=120,
        )
        container_start_exit_code = start_result.returncode
        container_id = (start_result.stdout or "").strip() or None
        if start_result.returncode != 0:
            run_error = (start_result.stderr or start_result.stdout or "docker run failed").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        run_error = f"{type(exc).__name__}: {exc}"

    ready_path = state_dir / "ready.json"
    ready_payload = None
    startup_status = "start_failed" if run_error else "starting"
    ready_after_seconds = None
    startup_error = None
    while run_error is None and time.perf_counter() - started < timeout_seconds:
        startup_error_path = state_dir / "startup_error.json"
        if startup_error_path.is_file():
            try:
                startup_error = json.loads(startup_error_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                startup_error = {"error": "worker published an unreadable startup_error.json"}
            startup_status = "startup_error"
            break
        if ready_path.is_file():
            try:
                candidate = json.loads(ready_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                candidate = None
            if isinstance(candidate, dict) and candidate.get("status") == "ready":
                ready_payload = candidate
                ready_after_seconds = round(time.perf_counter() - started, 1)
                startup_status = "ready"
                break
        container_status = _docker_container_status(container)
        if container_status in {"exited", "dead", "not_found"}:
            startup_status = "container_exited_before_ready"
            break
        if container_status.startswith("inspect_error") or container_status == "inspect_timeout":
            startup_status = container_status
            break
        time.sleep(2.0)
    if startup_status == "starting":
        startup_status = "timeout"

    clean_shutdown = False
    shutdown_confirmed = False
    shutdown_method = "none"
    container_status_after_shutdown = None
    if ready_payload is not None:
        shutdown_method = "stop_marker"
        (state_dir / "stop").write_text("{}", encoding="utf-8")
        stop_deadline = time.monotonic() + 180.0
        while time.monotonic() < stop_deadline:
            stopped_path = state_dir / "stopped.json"
            worker_stopped = stopped_path.is_file()
            container_status_after_shutdown = _docker_container_status(container)
            if worker_stopped and container_status_after_shutdown in {"exited", "dead", "not_found"}:
                clean_shutdown = True
                shutdown_confirmed = True
                break
            if container_status_after_shutdown in {"exited", "dead", "not_found"}:
                # The marker can be committed while docker inspect is running;
                # check once more after observing container exit.
                clean_shutdown = stopped_path.is_file()
                shutdown_confirmed = True
                break
            time.sleep(1.0)
    else:
        if startup_error is not None:
            run_error = startup_error.get("error") or str(startup_error)

    if not shutdown_confirmed:
        shutdown_method = "docker_rm_force"
        cleanup = _remove_docker_container(container)
        shutdown_confirmed = cleanup["confirmed"]
        container_status_after_shutdown = cleanup["containerStatus"]
        if cleanup.get("error") and run_error is None:
            run_error = cleanup["error"]
    elapsed = round(time.perf_counter() - started, 1)
    result = {
        "attempted": True,
        "ready": ready_payload is not None,
        "startupStatus": startup_status,
        "startupError": startup_error,
        "containerStartExitCode": container_start_exit_code,
        "containerId": container_id,
        "readyAfterSeconds": ready_after_seconds,
        "prewarmSeconds": elapsed,
        "workerLoadSeconds": (ready_payload or {}).get("loadSeconds"),
        "workerGpuName": (ready_payload or {}).get("gpuName"),
        "cleanShutdown": clean_shutdown,
        "shutdownConfirmed": shutdown_confirmed,
        "shutdownMethod": shutdown_method,
        "containerStatusAfterShutdown": container_status_after_shutdown,
        "error": run_error,
    }
    print(
        f"[harness] prewarm {'OK' if result['ready'] and clean_shutdown else 'FAILED'}: "
        f"{elapsed}s (worker load {result['workerLoadSeconds']}s; "
        f"shutdown={result['shutdownConfirmed']}/{result['cleanShutdown']})",
        flush=True,
    )
    return result


def _docker_container_status(container: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except FileNotFoundError:
        return "inspect_error:docker_unavailable"
    except subprocess.TimeoutExpired:
        return "inspect_timeout"
    if result.returncode == 0:
        return (result.stdout or "").strip() or "inspect_error:empty_status"
    combined = f"{result.stdout or ''} {result.stderr or ''}".casefold()
    if "no such object" in combined or "no such container" in combined:
        return "not_found"
    return "inspect_error:command_failed"


def _remove_docker_container(container: str) -> dict:
    error = None
    try:
        subprocess.run(
            ["docker", "rm", "-f", container],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = f"{type(exc).__name__}: {exc}"
    deadline = time.monotonic() + 30.0
    status = _docker_container_status(container)
    while status not in {"not_found", "exited", "dead"} and time.monotonic() < deadline:
        time.sleep(0.5)
        status = _docker_container_status(container)
    confirmed = status == "not_found"
    if not confirmed and error is None:
        error = f"could not confirm prewarm container removal (status={status})"
    return {"confirmed": confirmed, "containerStatus": status, "error": error}


def run_arm(arm: str, arm_dir: Path, plan_json: Path, timeout_seconds: float,
            staged_wave_size: int, staged_wave_max_wait_seconds: int,
            # The warm GVHMR worker's cold in-container startup (imports +
            # ViTPose/HMR2 init, ~350-460s measured) is silent in run.log;
            # 600s still fast-fails a real wedge inside the 45-minute budget.
            stall_seconds: float = 600.0,
            extra_runner_args: list[str] | None = None,
            cpu_prefetch_during_bake: bool = True,
            prefetch_workers: int = DEFAULT_PREFETCH_WORKERS,
            prefetch_queue_depth: int = DEFAULT_PREFETCH_QUEUE_DEPTH) -> dict:
    source_index = arm_dir / "source_outcome_index.json"
    if DEFAULT_SOURCE_OUTCOME_INDEX.is_file():
        shutil.copy2(DEFAULT_SOURCE_OUTCOME_INDEX, source_index)
    log_path = arm_dir / "run.log"
    args = build_runner_command(
        arm, arm_dir, plan_json, staged_wave_size, staged_wave_max_wait_seconds,
        extra_runner_args=extra_runner_args,
        cpu_prefetch_during_bake=cpu_prefetch_during_bake,
        prefetch_workers=prefetch_workers,
        prefetch_queue_depth=prefetch_queue_depth,
    )
    source_cache_root = DEFAULT_SOURCE_CACHE_DIR
    if "-YouTubeSourceCacheDir" in args:
        source_cache_root = Path(args[args.index("-YouTubeSourceCacheDir") + 1])
    started = time.perf_counter()
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(args, stdout=log_handle, stderr=subprocess.STDOUT)
    status = "running"
    shutdown = {"confirmed": True, "method": "normal_exit", "taskkillExitCode": None}
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
                shutdown = _kill_process_tree(process)
                print(f"[harness] {arm}: STALLED (log silent {stall_seconds:.0f}s). Tail:\n{_log_tail(log_path)}", flush=True)
                break
            if time.perf_counter() - started > timeout_seconds:
                status = "timeout"
                shutdown = _kill_process_tree(process)
                print(f"[harness] {arm}: TIMEOUT after {timeout_seconds:.0f}s. Tail:\n{_log_tail(log_path)}", flush=True)
                break
    finally:
        log_handle.close()
    elapsed = time.perf_counter() - started
    exit_code = process.returncode if status == "running" else status
    termination_status = "completed" if status == "running" else status
    return {
        "arm": arm,
        "exitCode": exit_code,
        "terminationStatus": termination_status,
        "processReturnCode": process.returncode,
        "shutdownConfirmed": bool(shutdown.get("confirmed")),
        "shutdownStatus": "confirmed" if shutdown.get("confirmed") else "unconfirmed",
        "shutdownDetails": shutdown,
        "wallSeconds": round(elapsed, 1),
        "workspace": str(arm_dir / "isolated" / "exercise_motion" / "workspace"),
        "whamCacheRoot": str(arm_dir / "isolated" / "exercise_motion" / "wham-cache"),
        "previewCacheRoot": str(arm_dir / "cache" / "youtube-preview-cache"),
        "sourceCacheRoot": str(source_cache_root),
        "log": str(log_path),
        "runnerArgs": args,
    }


def _kill_process_tree(process: subprocess.Popen, wait_timeout_seconds: float = 30.0) -> dict:
    """Force the runner tree down and wait for its root process to exit."""
    taskkill_exit_code = None
    taskkill_error = None
    try:
        taskkill = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True, text=True, check=False, timeout=wait_timeout_seconds,
        )
        taskkill_exit_code = taskkill.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        taskkill_error = f"{type(exc).__name__}: {exc}"

    try:
        process.wait(timeout=wait_timeout_seconds)
        root_exited = True
        wait_error = None
    except subprocess.TimeoutExpired as exc:
        root_exited = False
        wait_error = f"{type(exc).__name__}: {exc}"

    # One bounded retry covers a taskkill command timeout while still ensuring
    # a failed shutdown cannot silently flow into the next comparison arm.
    if not root_exited:
        try:
            retry = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, text=True, check=False, timeout=wait_timeout_seconds,
            )
            taskkill_exit_code = retry.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            taskkill_error = f"{type(exc).__name__}: {exc}"
        try:
            process.wait(timeout=wait_timeout_seconds)
            root_exited = True
            wait_error = None
        except subprocess.TimeoutExpired as exc:
            wait_error = f"{type(exc).__name__}: {exc}"

    confirmed = root_exited and taskkill_exit_code == 0
    return {
        "confirmed": confirmed,
        "method": "taskkill_tree_and_wait",
        "taskkillExitCode": taskkill_exit_code,
        "taskkillError": taskkill_error,
        "rootProcessExited": root_exited,
        "waitError": wait_error,
    }


def _metric_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def browser_task_summary(metrics: dict) -> str:
    summaries = []
    for wave in metrics.get("browserTasksByWave", []):
        wave_id = wave.get("waveId", "unknown-wave")
        for task_name, task_metrics in sorted((wave.get("byTask") or {}).items()):
            summaries.append(
                f"{wave_id}:{task_name}={task_metrics.get('jobCount', 0)}j/"
                f"{task_metrics.get('browserLaunchCount', 0)}l"
            )
    return ",".join(summaries) if summaries else "unavailable"


def arm_qualification_error(
    arm_result: dict, metrics: dict, expected_exercise_count: int
) -> str | None:
    """Reject an arm that cannot support a later comparison arm."""
    if arm_result.get("exitCode") != 0:
        return f"runner exited with code {arm_result.get('exitCode')!r}"

    statuses = metrics.get("statuses")
    if not isinstance(statuses, dict) or not statuses:
        return "runner summary has no terminal exercise statuses"
    if any(
        not isinstance(count, int) or isinstance(count, bool) or count < 0
        for count in statuses.values()
    ):
        return "runner summary has invalid terminal exercise status counts"

    completed = statuses.get("completed", 0)
    terminal_count = sum(statuses.values())
    if set(statuses) != {"completed"} or completed != expected_exercise_count:
        return (
            f"only {completed} of {expected_exercise_count} exercises completed; "
            f"statuses={statuses}"
        )
    if terminal_count != expected_exercise_count:
        return (
            f"runner reported {terminal_count} terminal exercises; "
            f"expected {expected_exercise_count}"
        )
    artifact_errors = metrics.get("acceptedMovementArtifactErrors") or []
    if artifact_errors:
        first_error = artifact_errors[0]
        return (
            "could not identify accepted movement artifact for "
            f"{first_error.get('exerciseName') or first_error.get('exerciseId')}: "
            f"{first_error.get('error')}"
        )
    artifact_rows = metrics.get("acceptedMovementArtifacts")
    if not isinstance(artifact_rows, list) or len(artifact_rows) != expected_exercise_count:
        return (
            f"runner summary has {len(artifact_rows) if isinstance(artifact_rows, list) else 0} "
            f"accepted movement identities; expected {expected_exercise_count}"
        )
    return None


def _movement_artifact_identities(summary: dict, workspace: Path) -> tuple[list[dict], list[dict]]:
    """Return stable per-exercise hashes for each accepted skeleton and its frames."""
    identities: list[dict] = []
    errors: list[dict] = []
    for exercise in summary.get("exercises") or []:
        if exercise.get("status") != "completed":
            continue
        exercise_id = exercise.get("exerciseId")
        exercise_name = exercise.get("exerciseName")
        results = exercise.get("selectedResults")
        selected_results = results if isinstance(results, list) and results else [exercise]
        movements = []
        for result_index, selected in enumerate(selected_results):
            if not isinstance(selected, dict):
                errors.append({
                    "exerciseId": exercise_id,
                    "exerciseName": exercise_name,
                    "error": f"selected result {result_index} is not an object",
                })
                continue
            skeleton_path_text = (
                selected.get("selectedWearSkeletonPath")
                or selected.get("skeletonPath")
                or (exercise.get("selectedWearSkeletonPath") if selected is exercise else None)
            )
            if not isinstance(skeleton_path_text, str) or not skeleton_path_text.strip():
                errors.append({
                    "exerciseId": exercise_id,
                    "exerciseName": exercise_name,
                    "error": f"selected result {result_index} has no skeleton path",
                })
                continue
            skeleton_path = Path(skeleton_path_text)
            if not skeleton_path.is_absolute():
                skeleton_path = (workspace / skeleton_path).resolve()
            if not skeleton_path.is_file():
                errors.append({
                    "exerciseId": exercise_id,
                    "exerciseName": exercise_name,
                    "error": f"selected skeleton is missing: {skeleton_path}",
                })
                continue
            try:
                raw_skeleton = skeleton_path.read_bytes()
                skeleton = json.loads(raw_skeleton)
                frames = skeleton.get("frames") if isinstance(skeleton, dict) else None
                if not isinstance(frames, list):
                    raise ValueError("skeleton has no frames array")
                canonical_frames = json.dumps(
                    frames,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                errors.append({
                    "exerciseId": exercise_id,
                    "exerciseName": exercise_name,
                    "error": f"could not read selected skeleton: {type(exc).__name__}: {exc}",
                })
                continue
            source = skeleton.get("source") or {}
            source_video_id = None
            if isinstance(source, dict):
                for key in ("videoId", "youtubeVideoId", "video_id"):
                    if isinstance(source.get(key), str):
                        source_video_id = source[key]
                        break
            movements.append({
                "artifactSha256": hashlib.sha256(raw_skeleton).hexdigest(),
                "frameSequenceSha256": hashlib.sha256(canonical_frames).hexdigest(),
                "frameCount": len(frames),
                "declaredFrameCount": skeleton.get("frameCount"),
                "fps": skeleton.get("fps"),
                "durationSec": skeleton.get("durationSec"),
                "sourceVideoId": source_video_id,
            })
        if movements:
            identities.append({
                "exerciseId": exercise_id,
                "exerciseName": exercise_name,
                "movements": sorted(movements, key=lambda item: item["artifactSha256"]),
            })
    identities.sort(key=lambda item: (str(item.get("exerciseId") or ""), str(item.get("exerciseName") or "")))
    errors.sort(key=lambda item: (str(item.get("exerciseId") or ""), str(item.get("error") or "")))
    return identities, errors


def accepted_artifact_parity_error(reference: list[dict], observed: list[dict]) -> str | None:
    """Check exact movement bytes and canonical frame sequences across arms/runs."""
    if reference == observed:
        return None
    reference_by_id = {str(item.get("exerciseId")): item for item in reference}
    observed_by_id = {str(item.get("exerciseId")): item for item in observed}
    missing = sorted(reference_by_id.keys() - observed_by_id.keys())
    added = sorted(observed_by_id.keys() - reference_by_id.keys())
    if missing or added:
        return f"accepted exercise identities differ (missing={missing}, added={added})"
    changed = [
        exercise_id
        for exercise_id in sorted(reference_by_id)
        if reference_by_id[exercise_id] != observed_by_id[exercise_id]
    ]
    return f"accepted artifact/frame identities differ for exercise ids {changed}"


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
        "gvhmrWorkerStartups": 0,
        "gvhmrWorkerStartupSeconds": 0.0,
        "coResidentOps": 0,
        "coResidentDeclined": 0,
        "sharedQuiesceCount": 0,
        "sharedRestartRequests": 0,
        "stagedWaveSize": None,
        "effectiveMaxConcurrentStagedWaves": None,
        "stagedWaveWorkerMode": None,
        "stagedWavesEnabled": None,
        "sharedLlamaServerEnabled": None,
        "cpuPrefetchDuringBake": None,
        "prefetchWorkers": None,
        "prefetchQueueDepth": None,
        "acceptedMovementArtifacts": [],
        "acceptedMovementArtifactErrors": [],
        "candidateGenerationAttempts": 0,
        "candidateGenerationAttemptSeconds": 0.0,
        "candidateAttemptManifests": 0,
        "gvhmrStageCalls": 0,
        "gvhmrStageWallSeconds": 0.0,
        "gvhmrRunnerCalls": 0,
        "gvhmrRunnerCallSeconds": 0.0,
        "gvhmrPredictionSamples": 0,
        "gvhmrPredictionSeconds": 0.0,
        "browserTasksByWave": [],
    }
    shared_session_snapshots: list[dict] = []
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
        browser_workers = m.get("browserWorkers") or {}
        by_task = browser_workers.get("byTask")
        if isinstance(by_task, dict) and by_task:
            metrics["browserTasksByWave"].append({
                "waveId": report.get("waveId") or report_path.parent.name,
                "byTask": by_task,
            })
        for phase in ("sourceVisionSession", "finalVisionSession"):
            session = m.get(phase) or {}
            metrics["visionStartups"] += session.get("visionRankerStartupCount", 0)
            metrics["visionStartupSeconds"] += session.get("visionRankerStartupSeconds", 0.0)
            metrics["visionQueueWaitSeconds"] += session.get("visionQueueWaitSeconds", 0.0)
            metrics["coResidentOps"] += session.get("coResidentGpuOperationCount", 0)
            metrics["coResidentDeclined"] += session.get("coResidentGpuDeclinedCount", 0)
            shared = session.get("sharedVisionSession") or session
            if isinstance(shared, dict):
                shared_session_snapshots.append(shared)
    for checkpoint_path in sorted(workspace.glob("staged-waves/*/staged_wave_checkpoint.json")):
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in checkpoint.get("items", []):
            wham = item.get("wham") or {}
            candidates = [
                attempt for attempt in (wham.get("attempts") or [])
                if isinstance(attempt, dict) and isinstance(attempt.get("elapsedSeconds"), (int, float))
            ]
            for attempt in candidates:
                # This wraps generate_candidate_motion(), including work before
                # and after GVHMR. Keep it separate from the manifest's GVHMR
                # stage, runner-call, and model-prediction measurements below.
                metrics["candidateGenerationAttempts"] += 1
                metrics["candidateGenerationAttemptSeconds"] += float(attempt["elapsedSeconds"])
                selected_video = attempt.get("selectedVideoPath")
                if not selected_video:
                    continue
                candidate_workspace = Path(selected_video).parent.parent
                manifest_path = candidate_workspace / "manifest.json"
                if not manifest_path.is_file():
                    continue
                try:
                    candidate_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                metrics["candidateAttemptManifests"] += 1
                generation_timings = candidate_manifest.get("timings") or {}
                stage_seconds = _metric_seconds(generation_timings.get("whamRunSeconds"))
                if stage_seconds is not None:
                    metrics["gvhmrStageCalls"] += 1
                    metrics["gvhmrStageWallSeconds"] += stage_seconds
                runner_timings = generation_timings.get("wham") or {}
                runner_seconds = _metric_seconds(runner_timings.get("elapsedSeconds"))
                if runner_seconds is not None:
                    metrics["gvhmrRunnerCalls"] += 1
                    metrics["gvhmrRunnerCallSeconds"] += runner_seconds
                phase_timings = runner_timings.get("phaseTimings") or {}
                inference_timings = phase_timings.get("inference") or {}
                prediction_seconds = _metric_seconds(inference_timings.get("predictionSeconds"))
                if prediction_seconds is not None:
                    metrics["gvhmrPredictionSamples"] += 1
                    metrics["gvhmrPredictionSeconds"] += prediction_seconds
    summary_path = workspace / "workout_motion_generation_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        statuses: dict[str, int] = {}
        for exercise in summary.get("exercises", []):
            status = str(exercise.get("status", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
        metrics["statuses"] = statuses
        metrics["overlapHighWater"] = summary.get("runningStagedWaveCountHighWater")
        metrics["stagedWaveSize"] = summary.get("stagedWaveSize")
        metrics["stagedWavesEnabled"] = summary.get("stagedWavesEnabled")
        metrics["effectiveMaxConcurrentStagedWaves"] = summary.get("maxConcurrentStagedWaves")
        metrics["stagedWaveWorkerMode"] = summary.get("stagedWaveWorkerMode")
        metrics["sharedLlamaServerEnabled"] = summary.get("sharedLlamaServerEnabled")
        parallelism = summary.get("parallelism") or {}
        metrics["cpuPrefetchDuringBake"] = parallelism.get("cpuPrefetchDuringBake")
        metrics["prefetchWorkers"] = parallelism.get("prefetchWorkers")
        metrics["prefetchQueueDepth"] = parallelism.get("prefetchQueueDepth")
        (
            metrics["acceptedMovementArtifacts"],
            metrics["acceptedMovementArtifactErrors"],
        ) = _movement_artifact_identities(summary, workspace)
    # These are cumulative coordinator snapshots, repeated in source/final
    # phase reports and across waves. Summing snapshots double-counts events;
    # the largest observed cumulative value is the run total.
    metrics["sharedQuiesceCount"] = max(
        (int(snapshot.get("sharedVisionQuiesceCount") or 0) for snapshot in shared_session_snapshots),
        default=0,
    )
    metrics["sharedRestartRequests"] = max(
        (int(snapshot.get("sharedVisionRestartRequestCount") or 0) for snapshot in shared_session_snapshots),
        default=0,
    )
    run_log = arm_result.get("log")
    if run_log and Path(run_log).is_file():
        try:
            log_text = Path(run_log).read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        startup_seconds = [
            float(match.group(1))
            for match in re.finditer(r"Motion extractor ready in ([0-9]+(?:\.[0-9]+)?)s", log_text)
        ]
        metrics["gvhmrWorkerStartups"] = len(startup_seconds)
        metrics["gvhmrWorkerStartupSeconds"] = sum(startup_seconds)
    return metrics


def effective_configuration_error(
    arm: str,
    metrics: dict,
    requested_wave_size: int,
    cpu_prefetch_during_bake: bool = True,
    prefetch_workers: int = DEFAULT_PREFETCH_WORKERS,
    prefetch_queue_depth: int = DEFAULT_PREFETCH_QUEUE_DEPTH,
) -> str | None:
    expected = ARM_EFFECTIVE_SETTINGS.get(arm)
    if expected is None:
        return f"no effective-setting contract is defined for arm '{arm}'"
    for key, value in expected.items():
        observed = metrics.get(key)
        if observed is None:
            return f"runner summary is missing effective setting {key}"
        if observed != value:
            return f"effective setting {key}={observed!r}, expected {value!r}"
    if metrics.get("stagedWaveSize") != requested_wave_size:
        return (
            f"effective stagedWaveSize={metrics.get('stagedWaveSize')!r}, "
            f"requested {requested_wave_size}"
        )
    expected_staged_enabled = requested_wave_size > 0
    if metrics.get("stagedWavesEnabled") is not expected_staged_enabled:
        return (
            f"effective stagedWavesEnabled={metrics.get('stagedWavesEnabled')!r}, "
            f"expected {expected_staged_enabled} for wave size {requested_wave_size}"
        )
    requested_prefetch = {
        "cpuPrefetchDuringBake": cpu_prefetch_during_bake,
        "prefetchWorkers": prefetch_workers,
        "prefetchQueueDepth": prefetch_queue_depth,
    }
    for key, value in requested_prefetch.items():
        observed = metrics.get(key)
        if observed != value:
            return f"effective {key}={observed!r}, requested {value!r}"
    expected_high_water = expected["effectiveMaxConcurrentStagedWaves"]
    expected_high_water = expected_high_water if expected_staged_enabled else 0
    if metrics.get("overlapHighWater") != expected_high_water:
        return (
            f"observed overlap high-water={metrics.get('overlapHighWater')!r}, "
            f"expected {expected_high_water}"
        )
    expected_worker_mode = (
        "workspace_scoped_persistent_serial_queue" if expected_staged_enabled else "disabled"
    )
    if metrics.get("stagedWaveWorkerMode") != expected_worker_mode:
        return (
            f"unexpected staged-wave worker mode {metrics.get('stagedWaveWorkerMode')!r}; "
            f"expected {expected_worker_mode!r}"
        )
    if not expected_staged_enabled and metrics.get("waves") != 0:
        return f"disabled staged waves reported {metrics.get('waves')!r} wave reports"
    return None


def build_argument_parser() -> argparse.ArgumentParser:
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
        type=_non_negative_int,
        default=DEFAULT_STAGED_WAVE_SIZE,
        help="Exercises per staged wave; 0 disables staged waves.",
    )
    parser.add_argument(
        "--staged-wave-max-wait-seconds",
        type=_positive_int,
        default=300,
        help="Partial-wave wait before flushing; production library default is 300.",
    )
    prefetch_group = parser.add_mutually_exclusive_group()
    prefetch_group.add_argument(
        "--cpu-prefetch-during-bake",
        dest="cpu_prefetch_during_bake",
        action="store_true",
        help="Enable production-library CPU/network candidate prefetch (default).",
    )
    prefetch_group.add_argument(
        "--disable-cpu-prefetch",
        dest="cpu_prefetch_during_bake",
        action="store_false",
        help="Disable CPU/network candidate prefetch for this measurement.",
    )
    parser.set_defaults(cpu_prefetch_during_bake=True)
    parser.add_argument(
        "--prefetch-workers",
        type=_positive_int,
        default=DEFAULT_PREFETCH_WORKERS,
        help="Prefetch workers; production library default is 8.",
    )
    parser.add_argument(
        "--prefetch-queue-depth",
        type=_positive_int,
        default=DEFAULT_PREFETCH_QUEUE_DEPTH,
        help="Prefetch queue depth; production library default is 40.",
    )
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument(
        "--skip-prewarm", action="store_true",
        help="Do not run the one-shot GVHMR worker pre-warm before the first arm",
    )
    parser.add_argument(
        "--allow-dirty-worktree", action="store_true",
        help="Pass -AllowDirtyWorktree to the runner; the run still records the full source identity",
    )
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()

    arm_names = [name.strip() for name in args.arms.split(",") if name.strip()]
    unknown = [name for name in arm_names if name not in ARMS and name not in UNSUPPORTED_ARMS]
    if unknown:
        raise SystemExit(f"Unknown arms: {', '.join(unknown)}; available: {', '.join(ARMS)}")
    unsupported = [name for name in arm_names if name in UNSUPPORTED_ARMS]
    if unsupported:
        details = "; ".join(f"{name}: {UNSUPPORTED_ARMS[name]}" for name in unsupported)
        raise SystemExit(f"Unsupported measurement arm: {details}")
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
    run_root = HARNESS_ROOT / f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_root.mkdir(parents=True, exist_ok=False)
    plan_json = run_root / "mini_library.json"
    matched = build_mini_library(args.library_json, set(slugs), plan_json)
    print(f"[harness] {len(matched)} exercises: {', '.join(matched)}", flush=True)
    library_plan_sha = sha256_file(plan_json)
    fixture_manifest_sha = sha256_file(args.fixtures) if args.fixtures is not None else None

    contract_cache_snapshot = None
    if fixture_manifest is not None:
        contract_cache_snapshot = stage_fixture_contract_cache(
            fixture_manifest, run_root / "fixture-contract-cache"
        )
    elif not args.smoke_check:
        # Non-fixture runs do not make a cross-arm claim about this cache, but
        # each workspace still gets an isolated copy through the legacy path.
        contract_cache_snapshot = None

    results = []
    if args.smoke_check:
        prewarm_result = {
            "attempted": False,
            "ready": None,
            "startupStatus": "skipped_for_smoke_check",
            "cleanShutdown": None,
            "shutdownConfirmed": None,
        }
    elif args.skip_prewarm:
        prewarm_result = {
            "attempted": False,
            "ready": None,
            "startupStatus": "explicitly_skipped",
            "cleanShutdown": None,
            "shutdownConfirmed": None,
        }
    else:
        try:
            prewarm_result = prewarm_gvhmr_worker()
        except Exception as exc:
            prewarm_result = {
                "attempted": True,
                "ready": False,
                "startupStatus": "prewarm_exception",
                "cleanShutdown": False,
                "shutdownConfirmed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    if not args.smoke_check:
        (run_root / "prewarm.json").write_text(
            json.dumps(prewarm_result, indent=1), encoding="utf-8"
        )
        if prewarm_result.get("attempted") and (
            prewarm_result.get("ready") is not True
            or prewarm_result.get("cleanShutdown") is not True
            or prewarm_result.get("shutdownConfirmed") is not True
        ):
            (run_root / "results.json").write_text("[]", encoding="utf-8")
            raise SystemExit(
                "GVHMR prewarm did not reach readiness and confirm a clean shutdown; "
                f"no comparison arm was started. See {run_root / 'prewarm.json'}"
            )
    requested_arms = arm_names[:1] if args.smoke_check else arm_names
    parity_reference_arm: str | None = None
    parity_reference_artifacts: list[dict] | None = None
    for arm in requested_arms:
        arm_dir = run_root / arm
        print(f"\n[harness] === arm '{arm}' ===", flush=True)
        fixture_args: list[str] = []
        arm_cache_root = arm_dir / "cache"
        preview_cache_dir = arm_cache_root / "youtube-preview-cache"
        source_cache_dir = arm_cache_root / "youtube-source-cache"
        if fixture_manifest is not None:
            prepared_manifest_path, seeded = assemble_workspace_fixtures(
                arm_dir, fixture_manifest, contract_cache_snapshot
            )
            source_cache_dir = stage_fixture_source_cache(
                fixture_manifest, source_cache_dir
            )
            fixture_args = [
                "-PreparedCandidatesManifest", str(prepared_manifest_path),
            ]
            print(f"[harness] seeded exercise_plan.json only for: {', '.join(seeded)}", flush=True)
            print(f"[harness] staged prepared-candidates manifest: {prepared_manifest_path}", flush=True)
            print(f"[harness] staged pinned source cache: {source_cache_dir}", flush=True)
        else:
            rewritten_paths = assemble_workspace(arm_dir, matched, args.base_workspace)
            print(f"[harness] remapped workspace paths in {rewritten_paths} copied text files", flush=True)
            source_cache_dir.mkdir(parents=True, exist_ok=True)
        preview_cache_dir.mkdir(parents=True, exist_ok=True)
        if args.allow_dirty_worktree:
            fixture_args.append("-AllowDirtyWorktree")
        if args.smoke_check:
            command = build_runner_command(
                arm, arm_dir, plan_json, args.staged_wave_size,
                args.staged_wave_max_wait_seconds,
                extra_runner_args=fixture_args,
                cpu_prefetch_during_bake=args.cpu_prefetch_during_bake,
                prefetch_workers=args.prefetch_workers,
                prefetch_queue_depth=args.prefetch_queue_depth,
                preview_cache_dir=preview_cache_dir,
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
            cpu_prefetch_during_bake=args.cpu_prefetch_during_bake,
            prefetch_workers=args.prefetch_workers,
            prefetch_queue_depth=args.prefetch_queue_depth,
        )
        arm_result.update(run_identity)
        arm_result["requestedConfiguration"] = {
            "stagedWaveSize": args.staged_wave_size,
            "stagedWaveMaxWaitSeconds": args.staged_wave_max_wait_seconds,
            "cpuPrefetchDuringBake": args.cpu_prefetch_during_bake,
            "prefetchWorkers": args.prefetch_workers,
            "prefetchQueueDepth": args.prefetch_queue_depth,
        }
        arm_result["cacheRoots"] = {
            "youtubePreview": str(preview_cache_dir),
            "youtubeSource": str(source_cache_dir),
        }
        arm_result["prewarmOutcome"] = prewarm_result
        arm_result["fixtureManifestPath"] = str(args.fixtures) if args.fixtures is not None else None
        arm_result["fixtureManifestSha256"] = fixture_manifest_sha
        arm_result["libraryPlanSha256"] = library_plan_sha
        arm_result["workspacePathsRemapped"] = (
            None if fixture_manifest is not None else rewritten_paths
        )
        if arm_result.get("terminationStatus") in {"stalled", "timeout"} or not arm_result.get("shutdownConfirmed"):
            results.append(arm_result)
            print(
                f"[harness] aborting remaining arms after {arm_result.get('terminationStatus')} "
                f"({arm_result.get('shutdownStatus')}); no later arm will run",
                flush=True,
            )
            break
        if isinstance(arm_result.get("exitCode"), int) and arm_result["exitCode"] != 0:
            print(f"[harness] {arm}: FAILED (exit {arm_result['exitCode']}). Tail:\n{_log_tail(Path(arm_result['log']))}", flush=True)
        arm_result["metrics"] = extract_metrics(arm_result)
        config_error = effective_configuration_error(
            arm,
            arm_result["metrics"],
            args.staged_wave_size,
            cpu_prefetch_during_bake=args.cpu_prefetch_during_bake,
            prefetch_workers=args.prefetch_workers,
            prefetch_queue_depth=args.prefetch_queue_depth,
        )
        arm_result["effectiveConfigurationValid"] = config_error is None
        if config_error:
            arm_result["effectiveConfigurationError"] = config_error
            print(f"[harness] {arm}: INVALID MEASUREMENT CONFIGURATION: {config_error}", flush=True)
        arm_result["schedulerTimeline"] = load_scheduler_timeline(arm_result)
        qualification_error = arm_qualification_error(
            arm_result, arm_result["metrics"], expected_exercise_count=len(matched)
        )
        arm_result["qualificationError"] = qualification_error
        parity_error = None
        if config_error is None and qualification_error is None:
            current_artifacts = arm_result["metrics"]["acceptedMovementArtifacts"]
            if parity_reference_artifacts is None:
                parity_reference_arm = arm
                parity_reference_artifacts = current_artifacts
                arm_result["acceptedArtifactParityComparedWithArm"] = None
                arm_result["acceptedArtifactParityValid"] = None
            else:
                parity_error = accepted_artifact_parity_error(
                    parity_reference_artifacts, current_artifacts
                )
                arm_result["acceptedArtifactParityComparedWithArm"] = parity_reference_arm
                arm_result["acceptedArtifactParityValid"] = parity_error is None
                if parity_error:
                    arm_result["acceptedArtifactParityError"] = parity_error
        results.append(arm_result)
        if config_error:
            print("[harness] aborting remaining arms; this run cannot support a comparison.", flush=True)
            break
        if qualification_error:
            print(
                f"[harness] aborting remaining arms after unqualified {arm}: "
                f"{qualification_error}; failed workspace artifacts are retained",
                flush=True,
            )
            break
        if parity_error:
            print(
                f"[harness] aborting after accepted-output parity failure against "
                f"'{parity_reference_arm}': {parity_error}",
                flush=True,
            )
            break
        m = arm_result["metrics"]
        print(
            f"[harness] {arm}: wall={arm_result['wallSeconds']}s exit={arm_result['exitCode']} "
            f"waves={m['waves']} phases(s/g/f)={m['phases']['source']:.0f}/{m['phases']['generation']:.0f}/{m['phases']['final']:.0f} "
            f"waveItems={m['maxExercisesPerWave']} sourceWorkers={m['sourceValidationWorkersHighWater']} "
            f"startups={m['visionStartups']}/{m['visionStartupSeconds']:.0f}s coRes={m['coResidentOps']} "
            f"quiesce={m['sharedQuiesceCount']} overlapHW={m.get('overlapHighWater')} "
            f"candidateGen={m['candidateGenerationAttempts']}x{m['candidateGenerationAttemptSeconds']:.0f}s "
            f"gvhmrStartup={m['gvhmrWorkerStartups']}x{m['gvhmrWorkerStartupSeconds']:.0f}s "
            f"gvhmrStage={m['gvhmrStageCalls']}x{m['gvhmrStageWallSeconds']:.0f}s "
            f"runner={m['gvhmrRunnerCalls']}x{m['gvhmrRunnerCallSeconds']:.0f}s "
            f"predict={m['gvhmrPredictionSamples']}x{m['gvhmrPredictionSeconds']:.1f}s "
            f"browserTasks={browser_task_summary(m)} statuses={m.get('statuses')}",
            flush=True,
        )
        statuses = m.get("statuses") or {}
        all_completed = qualification_error is None
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

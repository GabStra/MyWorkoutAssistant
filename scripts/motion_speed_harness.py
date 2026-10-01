"""Speed-config harness: minimal, repeatable live runs for pipeline tuning.

Assembles a fresh mini workspace from a fixed set of pending exercises (each
with already-prepared sources), runs the staged workout-plan runner once per
configuration arm, and extracts the metrics that decide the best defaults:
wall time, per-phase timings, vision-server startup counts, co-resident op
counts, shared-server quiesce metrics, overlap high-water mark, and GVHMR
attempt durations.

Usage:
  python scripts/motion_speed_harness.py --arms baseline,shared,shared-overlap
  python scripts/motion_speed_harness.py --arms baseline --exercises slug-a,slug-b
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_exercise_motion_workout_plan.ps1"
DEFAULT_LIBRARY_JSON = Path(r"C:\Users\gabri\Downloads\my_exercise_library.json")
DEFAULT_BASE_WORKSPACE = REPO_ROOT / "build/exercise_motion/exercise-library"
DEFAULT_SOURCE_OUTCOME_INDEX = REPO_ROOT / "build/exercise_motion/source_outcome_index.json"
HARNESS_ROOT = REPO_ROOT / "build/exercise_motion/speed-harness"

# Quick default set (2 single-exercise waves): enough to exercise source
# validation, the shared-server lifecycle, quiesce, generation, and wave
# overlap while keeping an arm in single-digit minutes. Use --exercises with
# the 4/8-exercise confirmation sets for wall-time comparisons of finalists.
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


def assemble_workspace(arm_dir: Path, slugs: list[str], base_workspace: Path) -> None:
    if arm_dir.exists():
        shutil.rmtree(arm_dir)
    workspace = arm_dir / "workspace"
    workspace.mkdir(parents=True)
    for slug in slugs:
        source = base_workspace / slug
        if not source.is_dir():
            raise SystemExit(f"Missing exercise workspace: {source}")
        shutil.copytree(source, workspace / slug)
    contract_cache = base_workspace / "exercise-motion-contract-cache"
    if contract_cache.is_dir():
        shutil.copytree(contract_cache, workspace / "exercise-motion-contract-cache")


def run_arm(arm: str, arm_dir: Path, plan_json: Path, timeout_seconds: float) -> dict:
    extra = ARMS[arm]
    source_index = arm_dir / "source_outcome_index.json"
    if DEFAULT_SOURCE_OUTCOME_INDEX.is_file():
        shutil.copy2(DEFAULT_SOURCE_OUTCOME_INDEX, source_index)
    output_json = arm_dir / "movements_out.json"
    log_path = arm_dir / "run.log"
    args = [
        "pwsh", "-NoProfile", "-File", str(RUNNER),
        "-WorkoutPlanJson", str(plan_json),
        "-WorkspaceRoot", str(arm_dir / "workspace"),
        "-IncrementalMobilePackageOutputJson", str(output_json),
        "-MotionReconstructor", "gvhmr",
        "-StagedWaveSize", "1",
        "-StagedWaveMaxWaitSeconds", "120",
        "-SourceOutcomeIndexJson", str(source_index),
    ] + extra
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
        completed = subprocess.run(args, stdout=log_handle, stderr=subprocess.STDOUT, timeout=timeout_seconds)
    elapsed = time.perf_counter() - started
    return {
        "arm": arm,
        "exitCode": completed.returncode,
        "wallSeconds": round(elapsed, 1),
        "workspace": str(arm_dir / "workspace"),
        "log": str(log_path),
    }


def extract_metrics(arm_result: dict) -> dict:
    workspace = Path(arm_result["workspace"])
    metrics: dict = {
        "phases": {"source": 0.0, "generation": 0.0, "final": 0.0},
        "waves": 0,
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
    parser.add_argument("--exercises", default=",".join(DEFAULT_EXERCISES))
    parser.add_argument("--library-json", type=Path, default=DEFAULT_LIBRARY_JSON)
    parser.add_argument("--base-workspace", type=Path, default=DEFAULT_BASE_WORKSPACE)
    parser.add_argument("--timeout-seconds", type=float, default=45 * 60.0)
    parser.add_argument("--keep-workspaces", action="store_true")
    args = parser.parse_args()

    arm_names = [name.strip() for name in args.arms.split(",") if name.strip()]
    unknown = [name for name in arm_names if name not in ARMS]
    if unknown:
        raise SystemExit(f"Unknown arms: {', '.join(unknown)}; available: {', '.join(ARMS)}")
    slugs = [slug.strip() for slug in args.exercises.split(",") if slug.strip()]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = HARNESS_ROOT / stamp
    run_root.mkdir(parents=True, exist_ok=True)
    plan_json = run_root / "mini_library.json"
    matched = build_mini_library(args.library_json, set(slugs), plan_json)
    print(f"[harness] {len(matched)} exercises: {', '.join(matched)}", flush=True)

    results = []
    for arm in arm_names:
        arm_dir = run_root / arm
        print(f"\n[harness] === arm '{arm}' ===", flush=True)
        assemble_workspace(arm_dir, matched, args.base_workspace)
        try:
            arm_result = run_arm(arm, arm_dir, plan_json, args.timeout_seconds)
        except subprocess.TimeoutExpired:
            arm_result = {"arm": arm, "exitCode": "timeout", "wallSeconds": args.timeout_seconds,
                          "workspace": str(arm_dir / "workspace"), "log": str(arm_dir / "run.log")}
        arm_result["metrics"] = extract_metrics(arm_result)
        results.append(arm_result)
        m = arm_result["metrics"]
        print(
            f"[harness] {arm}: wall={arm_result['wallSeconds']}s exit={arm_result['exitCode']} "
            f"waves={m['waves']} phases(s/g/f)={m['phases']['source']:.0f}/{m['phases']['generation']:.0f}/{m['phases']['final']:.0f} "
            f"startups={m['visionStartups']}/{m['visionStartupSeconds']:.0f}s coRes={m['coResidentOps']} "
            f"quiesce={m['sharedQuiesceCount']} overlapHW={m.get('overlapHighWater')} "
            f"gvhmr={m['gvhmrAttempts']}x{m['gvhmrAttemptSeconds']:.0f}s statuses={m.get('statuses')}",
            flush=True,
        )
        if not args.keep_workspaces and arm_result.get("exitCode") == 0:
            # Keep logs and reports; drop the bulky exercise copies.
            workspace = Path(arm_result["workspace"])
            for slug in matched:
                target = workspace / slug
                if target.is_dir():
                    shutil.rmtree(target)

    results_path = run_root / "results.json"
    results_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\n[harness] results: {results_path}", flush=True)


if __name__ == "__main__":
    main()

"""Concurrency check for the body fit lane change.

Refines the same synthetic clip twice: once sequentially, once in two
threads. Reports wall times and whether accept/reject decisions stayed
identical across the two modes.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench_structural_refinement import build_clip
from exercise_motion_pkg.structural_refinement import refine_motion_clip_structurally


def run_once() -> tuple[dict, float]:
    clip, source = build_clip(seed=7)
    started = time.perf_counter()
    refined = refine_motion_clip_structurally(
        clip, source_pose_payload=source,
        rigid_paired_hands_required=False, horizontal_torso_required=False)
    return json.loads(json.dumps(refined.metadata, default=str)), time.perf_counter() - started


def decisions(metadata: dict) -> dict:
    out = {}
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if any(s in k.lower() for s in ("accepted", "applied", "passed", "severe", "reason")):
                    out[path + "/" + k] = v
                else:
                    walk(v, path + "/" + k)
    walk(metadata)
    return out


def main() -> None:
    meta_a, seconds_a = run_once()
    meta_b, seconds_b = run_once()
    sequential = seconds_a + seconds_b

    results = [None, None]
    def worker(index: int) -> None:
        results[index] = run_once()
    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    concurrent = time.perf_counter() - started

    single_meta, _ = results[0]
    concurrent_meta, _ = results[1]
    same_as_sequential = decisions(meta_a) == decisions(single_meta)
    decision_diff = {
        k for k in decisions(meta_a)
        if decisions(meta_a)[k] != decisions(concurrent_meta).get(k)
    }
    print(json.dumps({
        "sequentialWallSeconds": round(sequential, 1),
        "perRunSeconds": [round(seconds_a, 1), round(seconds_b, 1)],
        "concurrentWallSeconds": round(concurrent, 1),
        "speedup": round(sequential / concurrent, 2),
        "concurrentSingleRunSeconds": round(results[0][1], 1),
        "threadResultsIdenticalDecisions": same_as_sequential,
        "sequentialVsConcurrentDecisionDiffCount": len(decision_diff),
    }, indent=2))


if __name__ == "__main__":
    main()

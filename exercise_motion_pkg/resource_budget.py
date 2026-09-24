"""Leave interactive coding headroom while motion generation runs."""
from __future__ import annotations

import os


# Keep Cursor/IDE/Chrome usable on the same machine as library generation.
CODING_HEADROOM_LOGICAL_CORES = 4
# Measured 2026-09-24 on 16 logical cores: 4 concurrent deadline-bound fits
# run each fit only ~13% slower while tripling throughput, with identical
# accept/reject decisions (scripts/bench_refine_concurrency.py). The previous
# value of 2 left the dominant stage half idle.
DEFAULT_CPU_FIT_SLOTS = 4
DEFAULT_BROWSER_WORKER_CAP = 4
# Overlap WHAM CPU prep while the GPU lock still serializes extraction. Four
# workers match the measured 4-lane fit pool: with three, one fit slot idles
# whenever a worker is inside the GPU-serialized WHAM stage, and the fit is
# the long pole (113-360s vs ~30-60s of WHAM per candidate).
DEFAULT_STAGED_GENERATION_CPU_WORKERS = 4


def logical_core_count() -> int:
    return max(1, os.cpu_count() or 2)


def usable_logical_cores() -> int:
    return max(1, logical_core_count() - CODING_HEADROOM_LOGICAL_CORES)


def cpu_fit_slot_limit() -> int:
    # Each fit is Python-heavy; keep spare cores for browser workers + coding.
    # EXERCISE_MOTION_FIT_LANES overrides for machines with more/less spare
    # capacity than the defaults assume.
    override = os.environ.get("EXERCISE_MOTION_FIT_LANES")
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value >= 1:
            return value
    return max(1, min(DEFAULT_CPU_FIT_SLOTS, usable_logical_cores() // 3))


def final_validation_worker_limit(configured_parallelism: int, ready_count: int) -> int:
    """Final bake/fit lanes never exceed shared CPU fit slots."""
    return min(
        max(1, int(configured_parallelism)),
        max(1, int(cpu_fit_slot_limit())),
        max(1, int(ready_count)),
    )


def render_prefetch_worker_limit(ready_count: int) -> int:
    """Speculative post-WHAM bake/fit prep shares the same CPU fit slots."""
    return min(max(1, int(cpu_fit_slot_limit())), max(1, int(ready_count)))


def browser_worker_limit() -> int:
    return max(1, min(DEFAULT_BROWSER_WORKER_CAP, usable_logical_cores() // 2))


def staged_generation_cpu_workers() -> int:
    return max(1, min(DEFAULT_STAGED_GENERATION_CPU_WORKERS, usable_logical_cores() // 3))

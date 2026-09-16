"""Leave interactive coding headroom while motion generation runs."""
from __future__ import annotations

import os


# Keep Cursor/IDE/Chrome usable on the same machine as library generation.
CODING_HEADROOM_LOGICAL_CORES = 4
# Two concurrent fits on a 16-core box; smaller machines fall back to 1.
DEFAULT_CPU_FIT_SLOTS = 2
DEFAULT_BROWSER_WORKER_CAP = 4
# Overlap WHAM CPU prep while the GPU lock still serializes extraction.
DEFAULT_STAGED_GENERATION_CPU_WORKERS = 3


def logical_core_count() -> int:
    return max(1, os.cpu_count() or 2)


def usable_logical_cores() -> int:
    return max(1, logical_core_count() - CODING_HEADROOM_LOGICAL_CORES)


def cpu_fit_slot_limit() -> int:
    # Each fit is Python-heavy; keep spare cores for browser workers + coding.
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

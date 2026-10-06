"""Leave interactive coding headroom while motion generation runs."""
from __future__ import annotations

import os


# Keep Cursor/IDE/Chrome usable on the same machine as library generation.
CODING_HEADROOM_LOGICAL_CORES = 4
# The checked-in concurrency benchmark compares two synthetic structural
# refinements, not four production controlled-motion fits. Keep this as a
# bounded host policy; its production throughput optimum has not been measured.
DEFAULT_CPU_FIT_SLOTS = 4
MACHINE_FIT_LANES_ENV_VAR = "EXERCISE_MOTION_MACHINE_FIT_LANES"
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


def machinewide_cpu_fit_slot_limit() -> int:
    """Return the shared per-user fit capacity across generator processes.

    The host-derived default is stable across separate workspaces. Existing
    per-process overrides may lower it, and the machine-wide override can only
    lower it further; neither setting can create more global lanes than the
    measured host default.
    """
    host_default = max(1, min(DEFAULT_CPU_FIT_SLOTS, usable_logical_cores() // 3))
    configured_process_limit = max(1, int(cpu_fit_slot_limit()))
    override = os.environ.get(MACHINE_FIT_LANES_ENV_VAR)
    if override:
        try:
            configured_machine_limit = int(override)
        except ValueError:
            configured_machine_limit = 0
        if configured_machine_limit >= 1:
            return max(1, min(host_default, configured_process_limit, configured_machine_limit))
    return max(1, min(host_default, configured_process_limit))


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
    # Workers exist to feed the CPU fit pool, so they follow any
    # EXERCISE_MOTION_FIT_LANES override; with the defaults this is unchanged.
    return max(1, min(cpu_fit_slot_limit(), usable_logical_cores() // 2))

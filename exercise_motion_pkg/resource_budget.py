"""Scale motion fitting to the host CPU while bounding shared concurrency."""
from __future__ import annotations

import os


CODING_HEADROOM_LOGICAL_CORES = 0
MACHINE_FIT_LANES_ENV_VAR = "EXERCISE_MOTION_MACHINE_FIT_LANES"
RENDER_PREFETCH_ENV_VAR = "EXERCISE_MOTION_RENDER_PREFETCH"


def logical_core_count() -> int:
    return max(1, os.cpu_count() or 2)


def usable_logical_cores() -> int:
    return max(1, logical_core_count() - CODING_HEADROOM_LOGICAL_CORES)


def cpu_fit_slot_limit() -> int:
    # Browser fits run in separate Chromium processes; give each logical CPU a lane.
    override = os.environ.get("EXERCISE_MOTION_FIT_LANES")
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value >= 1:
            return value
    return logical_core_count()


def machinewide_cpu_fit_slot_limit() -> int:
    """Return the shared per-user fit capacity across generator processes.

    The host-derived default is stable across separate workspaces. Existing
    per-process overrides may lower it, and the machine-wide override can only
    lower it further; neither setting can create more global lanes than the
    host CPU count.
    """
    host_default = logical_core_count()
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


def final_validation_worker_limit(ready_count: int) -> int:
    """CPU fitting is independent of the separately bounded VLM request slots."""
    return min(
        max(1, int(cpu_fit_slot_limit())),
        max(1, int(ready_count)),
    )


def render_prefetch_worker_limit(ready_count: int) -> int:
    """Speculative post-RECONSTRUCTION bake/fit prep shares the same CPU fit slots."""
    return min(max(1, int(cpu_fit_slot_limit())), max(1, int(ready_count)))


def render_prefetch_enabled() -> bool:
    """Return whether speculative render preparation is enabled for this process."""
    setting = os.environ.get(RENDER_PREFETCH_ENV_VAR, "on").strip().casefold()
    if setting not in {"on", "off"}:
        raise ValueError(f"{RENDER_PREFETCH_ENV_VAR} must be 'on' or 'off'")
    return setting == "on"


def browser_worker_limit() -> int:
    return min(cpu_fit_slot_limit(), logical_core_count())


def staged_generation_cpu_workers() -> int:
    return min(cpu_fit_slot_limit(), logical_core_count())

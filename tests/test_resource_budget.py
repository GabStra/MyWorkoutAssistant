import pytest

from exercise_motion_pkg import resource_budget


@pytest.fixture(autouse=True)
def clear_fit_lane_overrides(monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_FIT_LANES", raising=False)
    monkeypatch.delenv("EXERCISE_MOTION_MACHINE_FIT_LANES", raising=False)


def test_resource_budget_uses_all_cpu_fit_lanes(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.usable_logical_cores() == 16
    assert resource_budget.cpu_fit_slot_limit() == 16
    assert resource_budget.browser_worker_limit() == 16
    assert resource_budget.staged_generation_cpu_workers() == 16
    assert resource_budget.machinewide_cpu_fit_slot_limit() == 16


def test_resource_budget_falls_back_on_smaller_machines(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.usable_logical_cores() == 8
    assert resource_budget.cpu_fit_slot_limit() == 8
    assert resource_budget.browser_worker_limit() == 8
    assert resource_budget.staged_generation_cpu_workers() == 8
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 1)
    assert resource_budget.cpu_fit_slot_limit() == 1
    assert resource_budget.staged_generation_cpu_workers() == 1


def test_final_validation_workers_never_exceed_fit_slots(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.final_validation_worker_limit(7) == 7
    assert resource_budget.final_validation_worker_limit(1) == 1
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.final_validation_worker_limit(12) == 8


def test_render_prefetch_workers_never_exceed_fit_slots(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.render_prefetch_worker_limit(8) == 8
    assert resource_budget.render_prefetch_worker_limit(1) == 1
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.render_prefetch_worker_limit(12) == 8


def test_fit_lane_overrides_bound_all_cpu_pools(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 28)
    assert resource_budget.machinewide_cpu_fit_slot_limit() == 28
    monkeypatch.setenv("EXERCISE_MOTION_FIT_LANES", "6")
    assert resource_budget.cpu_fit_slot_limit() == 6
    assert resource_budget.browser_worker_limit() == 6
    assert resource_budget.staged_generation_cpu_workers() == 6
    assert resource_budget.final_validation_worker_limit(28) == 6
    monkeypatch.setenv("EXERCISE_MOTION_MACHINE_FIT_LANES", "3")
    assert resource_budget.machinewide_cpu_fit_slot_limit() == 3
    monkeypatch.setenv("EXERCISE_MOTION_FIT_LANES", "invalid")
    monkeypatch.setenv("EXERCISE_MOTION_MACHINE_FIT_LANES", "100")
    assert resource_budget.cpu_fit_slot_limit() == 28
    assert resource_budget.machinewide_cpu_fit_slot_limit() == 28


def test_render_prefetch_environment_defaults_on_and_accepts_only_on_or_off(monkeypatch):
    monkeypatch.delenv("EXERCISE_MOTION_RENDER_PREFETCH", raising=False)
    assert resource_budget.render_prefetch_enabled() is True

    monkeypatch.setenv("EXERCISE_MOTION_RENDER_PREFETCH", "off")
    assert resource_budget.render_prefetch_enabled() is False
    monkeypatch.setenv("EXERCISE_MOTION_RENDER_PREFETCH", "on")
    assert resource_budget.render_prefetch_enabled() is True

    monkeypatch.setenv("EXERCISE_MOTION_RENDER_PREFETCH", "sometimes")
    with pytest.raises(ValueError, match="EXERCISE_MOTION_RENDER_PREFETCH"):
        resource_budget.render_prefetch_enabled()

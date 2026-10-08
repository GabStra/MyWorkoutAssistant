import pytest

from exercise_motion_pkg import resource_budget


def test_resource_budget_reserves_coding_cores(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.usable_logical_cores() == 12
    assert resource_budget.cpu_fit_slot_limit() == 2
    assert resource_budget.browser_worker_limit() == 4
    assert resource_budget.staged_generation_cpu_workers() == 3


def test_resource_budget_falls_back_on_smaller_machines(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.usable_logical_cores() == 4
    assert resource_budget.cpu_fit_slot_limit() == 1
    assert resource_budget.browser_worker_limit() == 2
    assert resource_budget.staged_generation_cpu_workers() == 1


def test_final_validation_workers_never_exceed_fit_slots(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.final_validation_worker_limit(8, 7) == 2
    assert resource_budget.final_validation_worker_limit(1, 7) == 1
    assert resource_budget.final_validation_worker_limit(8, 1) == 1
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.final_validation_worker_limit(8, 7) == 1


def test_render_prefetch_workers_never_exceed_fit_slots(monkeypatch):
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 16)
    assert resource_budget.render_prefetch_worker_limit(8) == 2
    assert resource_budget.render_prefetch_worker_limit(1) == 1
    monkeypatch.setattr(resource_budget, "logical_core_count", lambda: 8)
    assert resource_budget.render_prefetch_worker_limit(8) == 1


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

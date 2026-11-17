"""Reachability contract for the contact-tangent temporal restoration."""

from exercise_motion_pkg.controlled_motion import (
    temporal_restoration_deadline,
    temporal_restoration_window_open,
)


def test_retained_cable_restoration_is_not_gated_by_solve_phase_reserve():
    # Values from stage-c-budget-owner-v80 patched-fit-result.json. The main
    # solve ended at 81.197 s; the whole remaining post-solve window (38.8 s)
    # was smaller than the 48.8 s solve-phase reserve, but the restoration
    # itself only needs the 24.4 s validation reserve.
    started = 0.0
    timeout_seconds = 119.99726380000357
    validation_reserve = 24.4
    temporal_restoration_reserve = 48.8
    first_polish_iteration = 81.197

    assert timeout_seconds - first_polish_iteration < temporal_restoration_reserve
    deadline = temporal_restoration_deadline(
        started, timeout_seconds, validation_reserve)
    assert temporal_restoration_window_open(
        started, timeout_seconds, validation_reserve, first_polish_iteration)
    assert deadline <= started + timeout_seconds


def test_temporal_restoration_stops_at_its_own_validation_fence():
    started = 0.0
    timeout_seconds = 120.0
    validation_reserve = 24.4
    deadline = temporal_restoration_deadline(
        started, timeout_seconds, validation_reserve)

    assert deadline == 95.6
    assert temporal_restoration_window_open(
        started, timeout_seconds, validation_reserve, deadline - 2.0)
    assert not temporal_restoration_window_open(
        started, timeout_seconds, validation_reserve, deadline - 0.5)

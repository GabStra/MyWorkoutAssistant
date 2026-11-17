"""Focused regressions for retained-interval budget ownership and routing."""

import copy
import json
from pathlib import Path
from time import monotonic

import pytest


class _FakeFitSession:
    def __init__(self, *, budget_seconds=360., remaining_seconds=None):
        self.budget_seconds = budget_seconds
        self._remaining_seconds = remaining_seconds
        self.previously_spent = 0.
        self.started = None
        self.results = {}
        self.fit_calls = 0
        self.reused_fits = 0
        self.reused_frames = 0

    def remaining(self):
        if self._remaining_seconds is not None:
            return max(0., self._remaining_seconds)
        active = max(0., monotonic() - self.started) if self.started is not None else 0.
        return max(0., self.budget_seconds - self.previously_spent - active)

    def save(self):
        pass


def _deferred_wrap_boundary():
    return {
        'passed': False,
        'rejectionReasons': ['source_support_wrap_unrepairable'],
        'failureOwner': 'source',
    }


def _retained_route_payload():
    choice = {'startFrame': 0, 'stopFrameExclusive': 6, 'score': 1.0}
    return {
        'jointNames': ['pelvis'],
        'frames': [{'joints': {'pelvis': [0., 0., 0.]}} for _ in range(6)],
        'fps': 30.,
        'loop': {'enabled': True},
        'observedCycleProposals': [choice],
        'sourceCyclePreflight': [{'selection': choice, 'passed': True}],
    }


def test_baseline_fit_budget_provisions_one_retained_pot(monkeypatch):
    from exercise_motion_pkg import fit_runtime
    from exercise_motion_pkg.bake_and_rank import (
        baseline_source_articulation_fit_budget,
        baseline_source_articulation_fit_timeout_seconds,
    )

    monkeypatch.setattr(fit_runtime, 'current_fit_session', lambda: _FakeFitSession())

    primary, retained = baseline_source_articulation_fit_budget(
        360., variant_id='adaptive-baseline', source_support_evidence={})
    assert primary == pytest.approx(240.)
    assert retained == pytest.approx(120.)
    # The old wrapper must keep its signature and primary-cap behavior.
    assert baseline_source_articulation_fit_timeout_seconds(
        360., variant_id='adaptive-baseline', source_support_evidence={}) == pytest.approx(240.)

    primary, retained = baseline_source_articulation_fit_budget(
        360., variant_id='other', source_support_evidence={})
    assert primary == pytest.approx(360.)
    assert retained == 0.


def test_fit_cache_key_includes_only_provisioned_retained_reserve(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import fit_runtime

    session = _FakeFitSession()
    monkeypatch.setattr(fit_runtime, 'current_fit_session', lambda: session)
    calls = []

    def fake_fit(payload, **kwargs):
        calls.append(kwargs.get('retained_interval_reserve_seconds'))
        return payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'contacts': False},
        }

    monkeypatch.setattr(motion, '_fit_observed_cycles', fake_fit)
    payload = {'variant': 'baseline'}

    motion._fit_candidate_motion(
        payload, timeout_seconds=240., retained_interval_reserve_seconds=120.)
    motion._fit_candidate_motion(
        payload, timeout_seconds=240., retained_interval_reserve_seconds=120.)
    motion._fit_candidate_motion(
        payload, timeout_seconds=240., retained_interval_reserve_seconds=0.)

    # The reserve-aware result is reused; the reserve-blind key stays distinct.
    assert calls == [120., 0.]


def test_constrain_source_articulation_forwards_reserve_to_fit_and_receipt(tmp_path, monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg import controlled_motion as motion

    monkeypatch.setattr(
        bake, 'constrain_to_source_articulation_envelope',
        lambda source, proposed, **kwargs: (proposed, {'applied': False}))
    calls = []

    def fake_fit(payload, **kwargs):
        calls.append(dict(kwargs))
        return payload, {'applied': False, 'reason': 'test_stub'}

    monkeypatch.setattr(motion, 'fit_controlled_motion', fake_fit)
    payload = {
        'fps': 30.0,
        'frameCount': 2,
        'jointNames': ['pelvis'],
        'frames': [
            {
                'timeSec': time_sec,
                'sourceJoints': {'pelvis': [0., 1., 0.]},
                'joints': {'pelvis': [0., 1., 0.]},
            }
            for time_sec in (0., 1. / 30.)
        ],
    }

    result, _ = bake.constrain_baked_payload_to_source_articulation(
        payload,
        timeout_seconds=240.,
        retained_interval_reserve_seconds=120.,
        fit_input_capture_directory=tmp_path,
        fit_input_variant_identity='loop-0-adaptive-baseline',
    )

    expected_kwargs = {
        'timeout_seconds': 240.,
        'retained_interval_reserve_seconds': 120.,
    }
    assert calls == [expected_kwargs]
    receipt = json.loads(
        Path(result['controlledMotionFit']['fitInputReceipt']['path']).read_text(encoding='utf-8'))
    assert receipt['fitKwargs'] == expected_kwargs


@pytest.mark.parametrize('report_includes_unrepairable_boundary', [True, False])
def test_retained_route_spends_external_pot_and_opens_only_proven_wrap(
    monkeypatch, report_includes_unrepairable_boundary,
):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import fit_runtime, loop_cycles

    session = _FakeFitSession(remaining_seconds=117.578)
    monkeypatch.setattr(fit_runtime, 'current_fit_session', lambda: session)
    monkeypatch.setattr(motion, '_verified_support_wrap_deferral', lambda *args, **kwargs: True)
    monkeypatch.setattr(
        loop_cycles, 'cycle_boundary_motion_metrics',
        lambda *args, **kwargs: _deferred_wrap_boundary())
    monkeypatch.setattr(
        loop_cycles, 'slice_loop_cycle',
        lambda payload, choice: copy.deepcopy(payload))

    calls = []

    def fake_fit(candidate_payload, **kwargs):
        calls.append({
            'loopEnabled': bool((candidate_payload.get('loop') or {}).get('enabled')),
            'timeout': kwargs['timeout_seconds'],
        })
        report = {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'contacts': False},
        }
        if len(calls) == 1 and report_includes_unrepairable_boundary:
            report['postSupportInitializationCycleBoundary'] = {
                'deferredToFit': True,
                'rejectionReasons': ['source_support_wrap_unrepairable'],
            }
        return candidate_payload, report

    monkeypatch.setattr(motion, '_fit_controlled_motion', fake_fit)

    motion._fit_observed_cycles(
        _retained_route_payload(), timeout_seconds=240.,
        retained_interval_reserve_seconds=120.)

    assert calls[0]['loopEnabled'] is True
    assert calls[0]['timeout'] == pytest.approx(240., abs=0.5)
    assert calls[1]['timeout'] == pytest.approx(117.578)
    assert calls[1]['loopEnabled'] is (not report_includes_unrepairable_boundary)


def test_retry_gate_uses_retained_route_minimum():
    from exercise_motion_pkg.controlled_motion import controlled_retry_minimum_budget_seconds
    from exercise_motion_pkg.wave_pipeline import exhausted_candidate_fit_session

    retained_reason = 'retained_interval_skipped_insufficient_validation_budget'
    assert controlled_retry_minimum_budget_seconds({'reason': retained_reason}) == pytest.approx(120.)
    assert controlled_retry_minimum_budget_seconds({
        'reason': 'fit_validation_failed',
        'cycleSelectionAttempts': [{'reason': retained_reason}],
    }) == pytest.approx(120.)
    assert controlled_retry_minimum_budget_seconds({'reason': 'fit_timeout'}) == pytest.approx(30.)

    def manifest(reason, remaining):
        return {'candidateResults': [{
            'status': 'needs_motion_processing',
            'controlledMotionFit': {'reason': reason, 'checks': {}},
            'candidateFitBudget': {'remainingSeconds': remaining},
        }]}

    assert exhausted_candidate_fit_session(manifest(retained_reason, 117.578)) is True
    assert exhausted_candidate_fit_session(manifest(retained_reason, 120.5)) is False
    # A different open route still keeps its original 30s useful floor.
    assert exhausted_candidate_fit_session(manifest('fit_timeout', 117.578)) is False

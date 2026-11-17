"""Focused regressions for bounded candidate-repair rejection capture."""
from __future__ import annotations

from exercise_motion_pkg.controlled_motion import (
    REPAIR_REJECTED_PROPOSAL_CAPTURE_LIMIT,
    capture_rejected_fit_candidate,
    retain_bounded_rejected_fit_candidate,
)
from exercise_motion_pkg.fit_context import build_fit_context, validate_fit_context

NAMES = ['pelvis', 'left_ankle']
FPS = 30.0


def _candidate(frame_count: int = 10) -> dict:
    frames = [
        {
            'timeSec': index / FPS,
            'joints': {
                'pelvis': [0.0, 1.0 + 0.001 * index, 0.0],
                'left_ankle': [0.0, 0.1, 0.02 * index],
            },
        }
        for index in range(frame_count)
    ]
    return {
        'fps': FPS,
        'frameCount': frame_count,
        'jointNames': NAMES,
        'rootJoint': 'pelvis',
        'loop': {'enabled': False},
        'frames': frames,
        'fixedRig': {
            'version': 1,
            'jointNames': NAMES,
            'offsets': [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            'coordinates': [[0.0] * 6 for _ in range(frame_count)],
        },
    }


def _context(candidate: dict) -> dict:
    targets = [
        [list(frame['joints'][name]) for name in NAMES]
        for frame in candidate['frames']
    ]
    context = build_fit_context(
        candidate,
        fit_contact_pinned=[[True, False] for _ in candidate['frames']],
        fit_contact_targets=targets,
        joint_contact_pinned=[[True, False] for _ in candidate['frames']],
        joint_contact_targets=targets,
        temporal_reference=targets,
        jerk_limit=1e-6,
        contact_limit=0.0005,
    )
    assert context['complete'] is True
    return context


def test_bounded_capture_keeps_exact_candidate_and_complete_context():
    candidate = _candidate()
    context = _context(candidate)
    calls = []

    def callback(captured_candidate, captured_report, input_payload):
        calls.append((captured_candidate, captured_report, input_payload))
        return {'path': f'proposal-{len(calls)}.json'}

    report = {'applied': False, 'checks': {'jerk': False}}
    with capture_rejected_fit_candidate(callback):
        count, captured = retain_bounded_rejected_fit_candidate(
            candidate, report, candidate,
            fit_context_factory=lambda: context,
            diagnostics={'stage': 'candidate_repair_rejected_trial', 'alpha': 0.5},
            captured_count=0, limit=1)
        assert (count, captured) == (1, True)
        count, captured = retain_bounded_rejected_fit_candidate(
            candidate, report, candidate,
            fit_context_factory=lambda: context,
            diagnostics={'stage': 'candidate_repair_rejected_trial', 'alpha': 0.25},
            captured_count=count, limit=1)
        assert (count, captured) == (1, False)

    assert len(calls) == 1
    captured_candidate, captured_report, _ = calls[0]
    assert captured_candidate is candidate
    assert captured_report['checks'] == report['checks']
    assert captured_report['fitContext'] is context
    assert validate_fit_context(captured_candidate, context)['passed'] is True
    assert captured_report['rejectedProposal'] == {
        'stage': 'candidate_repair_rejected_trial', 'alpha': 0.5}
    assert 'rejectedProposal' not in report
    assert report['rejectedFitDiagnostic'] == {'path': 'proposal-1.json'}
    assert REPAIR_REJECTED_PROPOSAL_CAPTURE_LIMIT >= 1


def test_capture_is_dormant_without_callback_and_skips_applied_reports():
    candidate = _candidate()
    count, captured = retain_bounded_rejected_fit_candidate(
        candidate, {'applied': False}, candidate, captured_count=0, limit=2)
    assert (count, captured) == (0, False)

    calls = []
    with capture_rejected_fit_candidate(
            lambda *args: calls.append(args) or {'path': 'x'}):
        count, captured = retain_bounded_rejected_fit_candidate(
            candidate, {'applied': True}, candidate, captured_count=0, limit=2)
    assert (count, captured) == (0, False)
    assert calls == []

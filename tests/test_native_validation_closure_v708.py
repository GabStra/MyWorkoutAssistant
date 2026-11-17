"""Fresh-fit native playback binding and pre-validation solver-state retention.

v703 closed the fit-time fractional material clock but the frozen Wood replay
still crashed at the height-only playback sampler, which measured the stale
source contact tracks before the publish refresh. v708 (1) binds the native
playback metrics to a binding refreshed from the current solved pose, keeping
immutable validation on the persisted tracks, and (2) retains the actual solved
pose/evidence when playback validation cannot reconstruct it instead of erasing
the completed solve.
"""
from __future__ import annotations

import numpy as np

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.contact_interpolation import ContactFootIKUnreachable


def _source_tracks():
    return {
        'version': 2,
        'left': {
            'active': [True, True],
            'directions': [[0., 0., 1.], [0., 0., 1.]],
            'sideAxes': [[1., 0., 0.], [1., 0., 0.]],
            'anchorIds': ['anchor-a', 'anchor-a'],
            'episodes': [],
        },
    }


def test_fresh_fit_binding_refreshes_current_pose_tracks(monkeypatch):
    stored = _source_tracks()
    refreshed = {'version': 2, 'left': {'marker': 'refreshed'}}
    captured = {}

    def fake_refresh(rig, coordinates, tracks, evidence):
        captured['coordinates'] = np.asarray(coordinates, dtype=float)
        assert tracks is stored
        return refreshed

    monkeypatch.setattr(motion, '_refresh_native_foot_contact_tracks', fake_refresh)
    current = np.arange(24, dtype=float).reshape(2, 12)

    refreshed_result, binding, error = motion.establish_native_playback_contact_binding(
        None, current, stored, {}, immutable=False)

    assert refreshed_result is refreshed
    # The height, key and material playback consumers all measure this same
    # binding; it is refreshed from the current solved coordinates.
    assert binding is refreshed
    assert error is None
    np.testing.assert_array_equal(captured['coordinates'], current)


def test_immutable_binding_keeps_persisted_tracks_and_never_refreshes(monkeypatch):
    stored = _source_tracks()

    def forbidden_refresh(*_args, **_kwargs):
        raise AssertionError('immutable validation must not refresh a candidate')

    monkeypatch.setattr(motion, '_refresh_native_foot_contact_tracks', forbidden_refresh)

    refreshed, binding, error = motion.establish_native_playback_contact_binding(
        None, np.zeros((2, 12)), stored, {}, immutable=True)

    assert refreshed is None
    assert binding is stored
    assert error is None


def test_refresh_failure_keeps_persisted_binding_and_reports_error(monkeypatch):
    stored = _source_tracks()

    def broken_refresh(*_args, **_kwargs):
        raise ValueError('native material side-axis binding is unavailable')

    monkeypatch.setattr(motion, '_refresh_native_foot_contact_tracks', broken_refresh)

    refreshed, binding, error = motion.establish_native_playback_contact_binding(
        None, np.zeros((2, 12)), stored, {}, immutable=False)

    assert refreshed is None
    assert binding is stored
    assert error == 'native material side-axis binding is unavailable'


def _ik_failure():
    return ContactFootIKUnreachable(
        'right', [0],
        np.zeros((1, 3)), np.array([[.9, 0., 0.]]),
        np.array([0.]), np.array([.8]), np.array([.9]))


def test_pre_validation_ik_failure_retains_solved_state_through_replay_callback():
    names = ['pelvis', 'right_hip', 'right_knee', 'right_foot']
    result = np.arange(3 * len(names) * 3, dtype=float).reshape(3, len(names), 3) / 10.
    coordinates = np.arange(3 * (3 + 3 * 3), dtype=float).reshape(3, 12)
    fixed_rig_payload = {
        'version': 1, 'jointNames': names, 'interpolation': 'hermite',
        'coordinates': np.zeros((3, 12)).tolist(),
    }
    playback_tracks = {
        'version': 2,
        'right': {'active': [True, True, True]},
    }
    payload = {'frames': [{'joints': {}} for _ in range(3)], 'fps': 30}
    report = {}
    captured = {}

    def record(candidate, captured_report, input_payload):
        captured['candidate'] = candidate
        captured['report'] = captured_report
        captured['input'] = input_payload
        return {'path': 'rejected/pre-validation.json'}

    with motion.capture_rejected_fit_candidate(record):
        retained = motion._retain_pre_validation_solver_state(
            payload, report, error=_ik_failure(), result=result,
            coordinates=coordinates, fixed_rig_payload=fixed_rig_payload,
            names=names, playback_tracks=playback_tracks)

    # The replay callback received the actual solved artifact: exact solver
    # coordinates, the decoded pose and the current playback binding.
    assert 'candidate' in captured
    np.testing.assert_allclose(
        np.asarray(captured['candidate']['fixedRig']['coordinates']), coordinates)
    np.testing.assert_allclose(
        np.asarray([frame['joints'][name] for frame in retained['frames']
                    for name in names]).reshape(len(result), len(names), 3), result)
    assert captured['candidate']['fixedRig']['contactFootTracks'] == playback_tracks
    assert captured['input'] is payload

    # Truthful typed failure: pre-validation and explicitly unaccepted, never
    # stamped as a validated output.
    assert report['applied'] is False
    assert report['reason'] == 'contact_foot_ik_unreachable'
    assert report['preValidationSolverStateCaptured'] is True
    assert report['solverStateAcceptance'] == 'pre_validation_unaccepted'
    assert report['contactFootIKUnreachable']['side'] == 'right'
    assert report['checks']['contacts'] is False
    assert report.get('checksComplete') is not True
    assert report['rejectedFitDiagnostic'] == {'path': 'rejected/pre-validation.json'}


def test_retained_pre_validation_candidate_attaches_fit_context():
    names = ['pelvis', 'right_hip', 'right_knee', 'right_foot']
    result = np.zeros((2, len(names), 3))
    coordinates = np.zeros((2, 12))
    payload = {'frames': [{'joints': {}}, {'joints': {}}]}
    report = {}
    captured = {}

    def record(candidate, captured_report, _input_payload):
        captured['report'] = captured_report
        return {'path': 'rejected/ctx.json'}

    with motion.capture_rejected_fit_candidate(record):
        motion._retain_pre_validation_solver_state(
            payload, report, error=_ik_failure(), result=result,
            coordinates=coordinates,
            fixed_rig_payload={'version': 1, 'coordinates': coordinates.tolist()},
            names=names, playback_tracks=None,
            fit_context_for_candidate=lambda _candidate: {
                'origin': 'actual_fit',
                'stage': 'pre_validation_native_height_playback',
            })

    assert captured['report']['fitContext'] == {
        'origin': 'actual_fit',
        'stage': 'pre_validation_native_height_playback',
    }

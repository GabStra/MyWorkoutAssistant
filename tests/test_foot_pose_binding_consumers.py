from copy import deepcopy

import pytest


def test_unbound_foot_patch_cannot_enter_fit_or_calibration(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, fit_runtime

    payload = {'sourceFootSupportEvidence': {'footPatchEvidence': {
        'available': True, 'source': 'mediapipe_full_heel_forefoot', 'policyVersion': 18}}}
    original = deepcopy(payload)

    def unexpected_slot(**kwargs):
        raise AssertionError('unbound foot evidence reached the numerical fitter')

    monkeypatch.setattr(fit_runtime, 'cpu_fit_slot', unexpected_slot)
    result, report = motion.fit_controlled_motion(payload)
    assert report['reason'] == 'source_foot_patch_pose_binding_invalid'
    assert result == payload == original


@pytest.mark.parametrize('available', [False, True])
def test_cached_refresh_cannot_hide_old_binding_by_disabling_patch(monkeypatch, tmp_path, available):
    from exercise_motion_pkg import foot_contact_observation as foot
    from exercise_motion_pkg.source_support_stage import refresh_cached_foot_pose_binding

    old = {'available': True, 'source': 'mediapipe_full_heel_forefoot'}
    evidence = {'footPatchEvidence': old}
    replacement = {'footPatchEvidence': {'available': available}}
    monkeypatch.setattr(foot, 'foot_patch_pose_binding_failure',
                        lambda patch, pose: 'stale' if patch is old else None)
    monkeypatch.setattr(foot, 'load_cached_foot_landmarks', lambda path: {'available': True})
    monkeypatch.setattr(foot, 'add_observed_foot_contacts', lambda *args, **kwargs: replacement)
    result, status = refresh_cached_foot_pose_binding(evidence, tmp_path / 'source.mp4', {})
    assert status['refreshed'] is available
    assert result is (replacement if available else evidence)

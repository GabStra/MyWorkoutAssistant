import pytest

from exercise_motion_pkg import structural_refinement as refinement
from exercise_motion_pkg import articulation_trajectory
from exercise_motion_pkg.models import MotionClip, MotionFrame


@pytest.mark.parametrize('endpoint_mismatch,temporal_passed', [(True, True), (False, False), (False, True)])
def test_structural_override_cannot_hide_decisive_regressions(monkeypatch, endpoint_mismatch, temporal_passed):
    before = MotionClip(30., ['pelvis'], [MotionFrame(0., {'pelvis': (0., 0., 0.)})])
    proposed = MotionClip(30., ['pelvis'], [MotionFrame(0., {'pelvis': (.001, 0., 0.)})])

    def metrics(mismatch):
        return {
            'available': True,
            **{name: .1 for name in refinement.SOURCE_FIDELITY_PROTECTED_METRICS},
            'perAngleEndpointMetrics': {'left_elbow': {
                'mismatch': mismatch, 'conditionedSampleCount': 30,
                'outputForeshortenedSampleCount': 0,
            }},
            'perJointMedianErrorBodyRatio': {'left_wrist': .08},
        }

    reports = iter([metrics(False), metrics(endpoint_mismatch)])
    monkeypatch.setattr(refinement, 'registered_camera_pose_fidelity_metrics',
                        lambda *args, **kwargs: next(reports))
    monkeypatch.setattr(articulation_trajectory, 'temporal_quality_comparison',
                        lambda *args: {'passed': temporal_passed})
    result, transaction = refinement._accept_source_preserving_refinement_step(
        before, proposed, source_pose_payload={}, step_name='symmetry',
        preserve_rigid_constraints=True)
    expected = temporal_passed and not endpoint_mismatch
    assert transaction['accepted'] is expected
    assert refinement.source_fidelity_override_is_safe(transaction) is expected
    assert result is (proposed if expected else before)
    if endpoint_mismatch:
        assert transaction['reason'] == 'source_endpoint_pose_degraded'

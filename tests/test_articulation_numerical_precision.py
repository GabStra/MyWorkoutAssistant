import math

import pytest

from exercise_motion_pkg.contact_constraints import ANGLE_NUMERICAL_TOLERANCE_RADIANS
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import constrain_to_source_articulation_envelope


def knee_clip(angle_degrees):
    angle = math.radians(angle_degrees)
    joints = {'left_hip': (0., 1., 0.), 'left_knee': (0., 0., 0.),
              'left_ankle': (0., math.cos(angle), math.sin(angle))}
    return MotionClip(30., list(joints), [MotionFrame(i / 30., dict(joints)) for i in range(3)])


@pytest.mark.parametrize('side', [-1, 1])
@pytest.mark.parametrize('residual_scale,expected_constraint', [(0.5, False), (2., True)])
def test_solver_and_envelope_agree_at_both_angular_boundaries(side, residual_scale, expected_constraint):
    source = knee_clip(90.)
    residual = math.degrees(ANGLE_NUMERICAL_TOLERANCE_RADIANS) * residual_scale
    proposed = knee_clip(90. + side * (1. + residual))
    result, report = constrain_to_source_articulation_envelope(source, proposed)
    assert report['applied'] is expected_constraint
    if not expected_constraint:
        assert result.frames == proposed.frames
    else:
        assert report['constrainedJoints'] == ['left_knee']

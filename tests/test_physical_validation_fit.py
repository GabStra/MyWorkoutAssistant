import numpy as np

from exercise_motion_pkg.physical_validation import (
    span_rigidity_fit_residuals,
    span_rigidity_violations,
)


def test_span_fit_residuals_hold_source_width_and_flag_near_limit_drift():
    names = ['left_shoulder', 'right_shoulder', 'left_hip', 'right_hip']
    source = np.zeros((3, len(names), 3), dtype=float)
    source[:, 0, 0] = -.2
    source[:, 1, 0] = .2
    source[:, 2, 0] = -.15
    source[:, 3, 0] = .15
    targets = {
        label: target
        for label, (_, target) in span_rigidity_violations(source, names).items()
    }

    within_headroom = source.copy()
    within_headroom[1, 1, 0] += .01
    drifted = source.copy()
    drifted[1, 1, 0] += .06

    quiet_residuals, labels = span_rigidity_fit_residuals(
        within_headroom, names, targets, body_scale_m=1.8)
    drift_residuals, drift_labels = span_rigidity_fit_residuals(
        drifted, names, targets, body_scale_m=1.8)

    assert labels == drift_labels == ['shoulders', 'hips']
    assert np.max(quiet_residuals) == 0.
    assert drift_residuals[1, labels.index('shoulders')] > 0.
    assert drift_residuals[1, labels.index('hips')] == 0.

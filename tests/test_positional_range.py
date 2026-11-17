import numpy as np
import pytest
from scipy.sparse import issparse

from exercise_motion_pkg.positional_range import jacobian, positional_spans, residual

ROOT = 2
SCALE = 1.0


def _case():
    frames = 9
    target = np.zeros((frames, 4, 3), dtype=float)
    t = np.linspace(0.0, 1.0, frames)
    target[:, ROOT, 0] = 0.03 * np.sin(1.7 * t)
    target[:, ROOT, 1] = 0.015 * np.cos(1.1 * t)
    target[:, 0, 0] = np.array(
        [0.30, 0.10, 0.24, 0.16, 0.21, 0.05, 0.28, 0.12, 0.18]
    )
    target[:, 0, 1] = 0.02 * np.sin(0.9 * t)
    target[:, 1, 0] = 0.02 * np.sin(1.3 * t)
    target[:, 1, 1] = 0.01 * np.cos(0.7 * t)

    candidate = target.copy()
    candidate[:, 0, :] *= 0.22
    return candidate, target


def test_root_translation_does_not_change_relative_quantities():
    candidate, target = _case()
    t = np.linspace(0.0, 1.0, len(target))
    offset = np.column_stack((
        0.5 * np.sin(2.0 * t),
        -0.3 * t,
        0.2 * np.cos(1.1 * t),
    ))

    assert np.allclose(
        positional_spans(target + offset[:, None, :], ROOT),
        positional_spans(target, ROOT),
        rtol=0.0,
        atol=1e-12,
    )
    assert np.allclose(
        residual(candidate + offset[:, None, :], target + offset[:, None, :], ROOT, SCALE),
        residual(candidate, target, ROOT, SCALE),
        rtol=0.0,
        atol=1e-12,
    )


def test_compressed_joint_only_activates_moving_shortfall():
    candidate, target = _case()
    target_span = positional_spans(target, ROOT)
    result_span = positional_spans(candidate, ROOT)
    moving = target_span > 0.1 * SCALE

    assert moving.tolist() == [True, False, False, False]
    assert result_span[0] < 0.92 * target_span[0]
    expected = np.zeros(4)
    expected[0] = 12000.0 / SCALE * (0.92 * target_span[0] - result_span[0])
    np.testing.assert_allclose(residual(candidate, target, ROOT, SCALE), expected, atol=1e-12)
    assert np.all(residual(candidate, target, ROOT, SCALE)[1:] == 0.0)


def test_preserved_candidate_has_zero_residual_and_jacobian():
    _, target = _case()
    assert np.all(residual(target, target, ROOT, SCALE) == 0.0)
    matrix = jacobian(target, target, ROOT, SCALE)
    assert matrix.shape == (4, target.size)
    assert matrix.nnz == 0


def test_analytical_sparse_jacobian_matches_central_finite_differences():
    candidate, target = _case()
    matrix = jacobian(candidate, target, ROOT, SCALE)
    assert issparse(matrix)
    assert matrix.format == "csr"
    assert matrix.shape == (4, candidate.size)

    epsilon = 1e-6
    flat = candidate.ravel()
    numerical = np.zeros((4, flat.size))
    for column in range(flat.size):
        plus = flat.copy()
        minus = flat.copy()
        plus[column] += epsilon
        minus[column] -= epsilon
        numerical[:, column] = (
            residual(plus.reshape(candidate.shape), target, ROOT, SCALE)
            - residual(minus.reshape(candidate.shape), target, ROOT, SCALE)
        ) / (2.0 * epsilon)

    np.testing.assert_allclose(matrix.toarray(), numerical, rtol=1e-5, atol=1e-5)
    assert np.any(matrix.toarray()[0])
    assert np.all(matrix.toarray()[1:] == 0.0)

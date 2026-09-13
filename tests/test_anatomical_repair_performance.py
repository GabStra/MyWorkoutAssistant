import numpy as np

from exercise_motion_pkg.anatomical_repair import batched_forward_jacobian


def test_batched_derivatives_match_independent_forward_differences():
    values = np.array([0., -2., 1e-14, 3.])

    def residual(batch):
        return np.column_stack([np.sin(batch[:, 0]) + batch[:, 1]**2,
                                batch[:, 2]*batch[:, 3], np.exp(batch[:, 2]),
                                np.maximum(batch[:, 3] - 2., 0.)])

    actual = batched_forward_jacobian(residual, values)
    expected = []
    for column in range(len(values)):
        shifted = values.copy()
        shifted[column] += np.sqrt(np.finfo(float).eps)*(-1. if values[column] < 0 else 1.)*max(1., abs(values[column]))
        expected.append((residual(shifted[None])[0]-residual(values[None])[0]) /
                        (shifted[column]-values[column]))
    np.testing.assert_allclose(actual, np.array(expected).T, atol=1e-12)

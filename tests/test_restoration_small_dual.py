import numpy as np
from scipy.sparse import csr_matrix

from exercise_motion_pkg.trajectory_restoration import inequality_gate_restoration_step


def test_small_dual_objective_preserves_feasible_anatomy_while_reducing_jerk():
    # Three inequalities reduced from the retained Cable restoration problem:
    # two passing anatomy bounds and one failing jerk bound.
    gram = np.array([
        [17.214528150622055, 0., -303.6332371283787],
        [0., 17.33345673857938, 204.0675127375699],
        [-303.6332371283787, 204.0675127375699, 297001.0886276945],
    ])
    violations = np.array([
        -9.669219260212676e-6, -9.96222823210999e-6, .03896703638113408,
    ])

    class TranslationRig:
        width = 3

        def decode(self, coordinates):
            return np.asarray(coordinates).reshape(1, 1, 3)

        def fk_jacobian(self, coordinates):
            return csr_matrix(np.eye(3))

    jacobian = np.linalg.cholesky(gram)
    proposal, evidence = inequality_gate_restoration_step(
        np.zeros((1, 3)), TranslationRig(), np.zeros((1, 1), dtype=bool),
        violations, csr_matrix(jacobian), numerical_margin=1e-5,
        max_point_shift_meters=.004,
    )
    assert evidence['applied'], evidence
    predicted = violations + jacobian @ proposal.ravel()
    assert np.all(predicted <= 0.)
    assert np.linalg.norm(proposal) <= .004

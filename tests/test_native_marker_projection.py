import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.native_marker_projection import (
    native_heel_toe_image_residual,
)

FIXTURE = Path(__file__).parent / "fixtures" / "native_foot_geometry_v1.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _residual(ankles, balls, side_axes, side, observed, projection):
    return native_heel_toe_image_residual(
        np.asarray(ankles, dtype=float), np.asarray(balls, dtype=float),
        np.asarray(side_axes, dtype=float), side,
        np.asarray(projection, dtype=float), np.asarray(observed, dtype=float))


def test_known_projected_heel_to_toe_vector_has_zero_residual():
    case = _fixture()["neutralCase"]
    side = _fixture()["reference"]["sides"]["left"]
    projection = np.asarray([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    heel_to_toe = (np.asarray(case["expected"]["heel"])
                   - np.asarray(case["expected"]["toe"]))
    observed = (heel_to_toe @ projection.T)[None]

    residual = _residual([case["ankle"]], [case["footJoint"]],
                         [case["sideAxis"]], side, observed, projection)

    np.testing.assert_allclose(residual, np.zeros((1, 2)), atol=1e-12)


def test_translating_ankle_and_ball_together_preserves_residual():
    case = _fixture()["neutralCase"]
    side = _fixture()["reference"]["sides"]["left"]
    projection = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    observed = np.asarray([[0.0, 0.0]])
    translation = np.asarray([0.35, -0.2, 1.1])

    base = _residual([case["ankle"]], [case["footJoint"]],
                     [case["sideAxis"]], side, observed, projection)
    moved = _residual(np.asarray([case["ankle"]]) + translation,
                      np.asarray([case["footJoint"]]) + translation,
                      [case["sideAxis"]], side, observed, projection)

    np.testing.assert_allclose(moved, base, atol=1e-12)


def test_rotating_side_axis_around_unchanged_bone_changes_residual():
    case = _fixture()["neutralCase"]
    side = _fixture()["twistedRetargetGeometry"]["sides"]["left"]
    projection = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    observed = np.zeros((2, 2))
    angles = np.deg2rad([15.0, 75.0])
    side_axes = np.stack([
        [0.0, np.sin(angle), np.cos(angle)] for angle in angles])

    residual = _residual([case["ankle"]] * 2, [case["footJoint"]] * 2,
                         side_axes, side, observed, projection)

    assert not np.allclose(residual[0], residual[1], atol=1e-6)

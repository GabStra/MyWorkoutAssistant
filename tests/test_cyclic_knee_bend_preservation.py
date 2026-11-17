"""Regression: a near-reach closed-chain seed must not silently flatten a
source knee.

Retained calf-v701 evidence (see
``.scratch/goal-contact-continuation/calf-seed-owner-v704/PROOF.md``): the
right hip-ankle span is pushed to 7 um inside the thigh+shin reach at frames
0-1, collapsing the ~28 mm source knee bend to ~1.7 mm while the angular knee
envelope still reports feasible; the cyclic root then over-bends the same knee
(to ~59.5 mm) at the other seam end. ``contact_heel_repair._frame_state`` keeps
clipping distance and clamping the knee height, so feasibility alone cannot
distinguish the folded seed. The common-root selection therefore carries a
source-bend preference (``joint_plant_initialization._root_bend_deviation``)
so a bend-preserving feasible offset is chosen instead of the singular fold,
while a genuinely straight/locked leg is never forced to bend.
"""
import numpy as np

from exercise_motion_pkg.contact_heel_repair import _frame_state
from exercise_motion_pkg.foot_kinematics import _source_knee_poles
from exercise_motion_pkg.joint_plant_initialization import _root_bend_deviation
from exercise_motion_pkg.physical_validation import angles


# Retained calf-v701 right-leg bone lengths and reach.
THIGH = 0.3806853078074235
SHIN = 0.40077765131640253
REACH = THIGH + SHIN
SOURCE_DISTANCE = 0.779454          # frames 0-1 source hip-ankle span
NEAR_REACH_DISTANCE = REACH - 7e-6  # frames 0-1 initialized span (7 um margin)
OVER_BENT_DISTANCE = 0.772352       # frames 51-52 initialized span


def _along(thigh, shin, distance):
    return (thigh * thigh - shin * shin + distance * distance) / (2. * distance)


def _height(thigh, shin, distance):
    along = _along(thigh, shin, distance)
    return float(np.sqrt(max(thigh * thigh - along * along, 0.)))


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


SOURCE_BEND = _height(THIGH, SHIN, SOURCE_DISTANCE)


def _single_leg_spec(distance, *, thigh=THIGH, shin=SHIN, source_height=None,
                     knee_tolerance_degrees=10., ankle_tolerance_degrees=10.):
    if source_height is None:
        source_height = _height(thigh, shin, SOURCE_DISTANCE)
    axis = np.array([0., -1., 0.])
    perpendicular = np.array([0., 0., 1.])
    knee = axis * _along(thigh, shin, SOURCE_DISTANCE) + perpendicular * source_height
    ankle = axis * SOURCE_DISTANCE
    toe = ankle + np.array([0., 0., 0.2])
    target_ankle = axis * distance
    hip = np.zeros((1, 3))
    knee_row = knee[None, :]
    ankle_row = ankle[None, :]
    toe_row = toe[None, :]
    pole = _source_knee_poles(hip, knee_row, ankle_row)
    return {
        'side': 'right', 'indices': (0, 1, 2, 3),
        'hip': hip, 'knee': knee_row, 'ankle': ankle_row, 'toe': toe_row,
        'targetAnkle': target_ankle[None, :],
        'targetToe': (target_ankle + np.array([0., 0., 0.2]))[None, :],
        'activeContact': np.ones(1, dtype=bool),
        'activePoseTarget': np.ones(1, dtype=bool),
        'ankleFollowsRoot': np.zeros(1, dtype=bool),
        'toeFollowsRoot': np.zeros(1, dtype=bool),
        'thigh': np.array([thigh]), 'shin': np.array([shin]),
        'pole': _unit(pole), 'sourceAxis': _unit(axis)[None, :],
        'referenceKneeAngle': angles(hip, knee_row, ankle_row),
        'referenceAnkleAngle': angles(knee_row, ankle_row, toe_row),
        'kneeTolerance': np.deg2rad(knee_tolerance_degrees),
        'ankleTolerance': np.deg2rad(ankle_tolerance_degrees),
        'sourceKneeHeight': np.array([source_height]),
    }


def _bend_from_points(hip, knee, ankle):
    line = _unit(ankle - hip)
    relative = knee - hip
    return float(np.linalg.norm(relative - np.dot(relative, line) * line))


def test_near_reach_fold_is_disfavoured_by_root_bend_selection():
    # The fold is still "feasible" for the clipped frame state, and it flattens
    # the source knee to ~1.7 mm (the exact retained failure).
    spec = _single_leg_spec(NEAR_REACH_DISTANCE)
    _, folded = _frame_state([spec], 0, np.zeros(3))
    fold_bend = _bend_from_points(spec['hip'][0], folded[0], spec['targetAnkle'][0])
    assert fold_bend < 3e-3

    # The source span reproduces the source bend.
    spec = _single_leg_spec(SOURCE_DISTANCE)
    _, source = _frame_state([spec], 0, np.zeros(3))
    source_bend = _bend_from_points(spec['hip'][0], source[0], spec['targetAnkle'][0])
    np.testing.assert_allclose(source_bend, SOURCE_BEND, atol=1e-9)

    # Selection strongly prefers the source bend over the folded seed.
    fold_cost = _root_bend_deviation([spec], 0, np.zeros(3), folded)
    source_cost = _root_bend_deviation([spec], 0, np.zeros(3), source)
    assert source_cost < 1e-12
    assert fold_cost > 1e-3

    # Over-bending the same span is a legitimate support-driven adaptation and
    # is not the fold: the selection cost still grows smoothly, so the solver
    # prefers the source bend without forbidding extra knee flexion.
    spec = _single_leg_spec(OVER_BENT_DISTANCE)
    _, over = _frame_state([spec], 0, np.zeros(3))
    over_cost = _root_bend_deviation([spec], 0, np.zeros(3), over)
    assert over_cost > source_cost


def test_straight_locked_leg_is_not_forced_to_bend():
    # A genuinely straight leg near full extension must keep a ~zero bend cost:
    # no arbitrary reserve and no forced flexion for a locked/straight source.
    thigh = shin = 0.4
    distance = 0.7999996
    straight_height = _height(thigh, shin, distance)
    spec = _single_leg_spec(distance, thigh=thigh, shin=shin,
                            source_height=straight_height)
    _, knees = _frame_state([spec], 0, np.zeros(3))
    straight_bend = _bend_from_points(spec['hip'][0], knees[0], spec['targetAnkle'][0])
    np.testing.assert_allclose(straight_bend, straight_height, atol=1e-9)
    assert _root_bend_deviation([spec], 0, np.zeros(3), knees) < 1e-15

"""Rigid feet and temporally coherent leg IK for inferred toe contacts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from .models import MotionClip, MotionFrame
from .contact_constraints import (
    ANGLE_NUMERICAL_TOLERANCE_RADIANS,
    InfeasibleContactCorrection,
    contact_frame_bounds, is_stationary_contact, stationary_target_track, reachable_root_track,
    motion_support_contacts,
)

# Proposal resolution, not an anatomical range. Search the geometric domain;
# contact, rigid lengths, source knee articulation and temporal cost choose the
# pose. Final source/anatomy validation remains responsible for acceptance.
ANKLE_PROPOSAL_STEP_DEGREES = 1.0


def ankle_proposal_angles():
    return np.deg2rad(np.arange(0.0, 180.0 + ANKLE_PROPOSAL_STEP_DEGREES,
                               ANKLE_PROPOSAL_STEP_DEGREES))
KNEE_ARTICULATION_TOLERANCE_RADIANS = np.deg2rad(1.0)
# Rear shoe ring: 1.02 * 1.15 times ankle-to-toe length from the toe.
HEEL_BEHIND_ANKLE_RATIO = 1.02 * 1.15 - 1.0


def _leg_orientation(poses):
    axis = _unit(poses[:, 2] - poses[:, 0])
    bend = poses[:, 1] - poses[:, 0]
    bend -= axis * np.sum(bend * axis, axis=1, keepdims=True)
    degenerate = np.linalg.norm(bend, axis=1) < 1e-8
    # A straight knee has no bend plane. Use the foot direction only there.
    foot = poses[:, 3] - poses[:, 2]
    foot -= axis * np.sum(foot * axis, axis=1, keepdims=True)
    bend[degenerate] = foot[degenerate]
    degenerate = np.linalg.norm(bend, axis=1) < 1e-8
    basis = np.eye(3)[np.argmin(np.abs(axis), axis=1)]
    fallback = basis - axis * np.sum(basis * axis, axis=1, keepdims=True)
    bend[degenerate] = fallback[degenerate]
    bend = _unit(bend)
    return np.stack([bend, _unit(np.cross(axis, bend)), axis], axis=-1)


def blend_contact_transition_rotations(original, corrected, supported, fps, knee_bounds=None):
    """Ease an IK correction through free frames using rigid segment rotations.

    Contact targets remain exact. Interpolating joint positions would shorten
    bones; filtering the already anchored track would reintroduce sliding.
    Only the correction is blended, preserving the underlying free motion.
    """
    from scipy.spatial.transform import Rotation

    result = corrected.copy()
    contact_indexes = np.flatnonzero(supported)
    if not len(contact_indexes):
        return result
    # Contact entry/exit delimit the available swing interval. A fixed 150 ms
    # blend can compress a large correction into three frames regardless of
    # how much free motion preceded it. Fit the correction across
    # observed constraints; unobserved clip edges are not zero corrections.
    boundaries = np.unique(np.r_[0, contact_indexes, len(original) - 1])
    free_indexes = np.flatnonzero(~supported)
    original_orientation = _leg_orientation(original)
    corrected_orientation = _leg_orientation(corrected)
    leg_rotations = Rotation.from_matrix(corrected_orientation @ original_orientation.transpose(0, 2, 1)).as_rotvec()
    foot_rotations = np.zeros_like(leg_rotations)
    for boundary in contact_indexes:
        a = _unit(original[boundary, 3] - original[boundary, 2])
        b = _unit(corrected[boundary, 3] - corrected[boundary, 2])
        cross = np.cross(a, b)
        sine = np.linalg.norm(cross)
        if sine > 1e-8:
            foot_rotations[boundary] = cross / sine * np.arctan2(sine, np.dot(a, b))
    original_angles = _knee_angles(original[:, 0], original[:, 1], original[:, 2])
    corrected_angles = _knee_angles(corrected[:, 0], corrected[:, 1], corrected[:, 2])
    corrections = np.column_stack([leg_rotations, foot_rotations, corrected_angles - original_angles])
    corrections[~supported] = 0.
    for index in free_indexes:
        insertion = min(len(boundaries) - 1, np.searchsorted(boundaries, index, side="right"))
        before, after = boundaries[insertion - 1:insertion + 1]
        before_slope = (corrections[before] - corrections[before - 1]
                        if before > 0 and supported[before] and supported[before - 1]
                        else np.zeros(7))
        after_slope = (corrections[after + 1] - corrections[after]
                       if after + 1 < len(original) and supported[after] and supported[after + 1]
                       else np.zeros(7))
        if not supported[before] or not supported[after]:
            # An unobserved clip edge is not a contact target. Relax the
            # correction in physical time, independently of where a file was
            # cut, matching velocity at the only observed boundary.
            anchor = after if not supported[before] else before
            elapsed = abs(index - anchor)
            slope = -after_slope if anchor == after else before_slope
            rate = 1. / max(fps * .30, 1.)
            correction = (corrections[anchor] + (slope + rate * corrections[anchor]) * elapsed) * np.exp(-rate * elapsed)
        else:
            alpha = (index - before) / (after - before)
            span = after - before
            correction = ((2 * alpha**3 - 3 * alpha**2 + 1) * corrections[before]
                          + (alpha**3 - 2 * alpha**2 + alpha) * span * before_slope
                          + (-2 * alpha**3 + 3 * alpha**2) * corrections[after]
                          + (alpha**3 - alpha**2) * span * after_slope)
        orientation = Rotation.from_rotvec(correction[:3]).as_matrix() @ original_orientation[index]
        angle = original_angles[index]
        if knee_bounds is not None:
            angle = np.clip(angle + correction[6], knee_bounds[0][index], knee_bounds[1][index])
        thigh, shin = np.linalg.norm(np.diff(original[index, :3], axis=0), axis=1)
        distance = np.sqrt(max(1e-16, thigh**2 + shin**2 - 2 * thigh * shin * np.cos(angle)))
        along = (thigh**2 - shin**2 + distance**2) / (2 * distance)
        height = np.sqrt(max(0., thigh**2 - along**2))
        result[index, 1] = result[index, 0] + orientation[:, 2] * along + orientation[:, 0] * height
        result[index, 2] = result[index, 0] + orientation[:, 2] * distance
        result[index, 3] = result[index, 2] + Rotation.from_rotvec(correction[3:6]).apply(original[index, 3] - original[index, 2])
    return result


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-10)


def _knee_angles(hips, knees, ankles):
    return np.arccos(np.clip(np.sum(
        _unit(hips - knees) * _unit(ankles - knees), axis=-1,
    ), -1, 1))


def _source_knee_poles(hips, knees, ankles):
    """Use the observed bend, excluding the thigh's axial component.

    Projecting the whole thigh onto a changed target axis can reverse its
    apparent bend even when the source knee never changes hinge branch.
    """
    axis = _unit(ankles - hips)
    thigh = knees - hips
    return _unit(thigh - axis * np.sum(thigh * axis, axis=-1, keepdims=True))


def _transport_knee_poles(poles, source_axes, target_axes):
    """Carry the bend plane with the leg instead of projecting across it."""
    source_axes, target_axes = _unit(source_axes), _unit(target_axes)
    cross = np.cross(source_axes, target_axes)
    sine = np.linalg.norm(cross, axis=-1, keepdims=True)
    cosine = np.clip(np.sum(source_axes * target_axes, axis=-1, keepdims=True), -1., 1.)
    axis = cross / np.maximum(sine, 1e-10)
    rotated = (poles * cosine + np.cross(axis, poles) * sine
               + axis * np.sum(axis * poles, axis=-1, keepdims=True) * (1 - cosine))
    # At antipodal axes the bend itself defines the half-turn axis.
    return np.where(sine > 1e-8, rotated, poles)


def source_knee_angle_bounds(clip, *, envelope_tolerance_degrees, phase_tolerance_degrees):
    bounds = {}
    for side in ("left", "right"):
        names = [f"{side}_{part}" for part in ("hip", "knee", "ankle")]
        if any(any(name not in frame.joints for name in names) for frame in clip.frames):
            continue
        angles = _knee_angles(*[np.array([frame.joints[name] for frame in clip.frames]) for name in names])
        envelope = np.deg2rad(envelope_tolerance_degrees)
        phase = np.deg2rad(phase_tolerance_degrees)
        bounds[side] = np.column_stack([
            np.maximum(angles - phase, angles.min() - envelope),
            np.minimum(angles + phase, angles.max() + envelope),
        ]).tolist()
    return bounds


def _contact_knee_bounds(hips, knees, ankles, source_bounds=None):
    reference = _knee_angles(hips, knees, ankles)
    low = np.maximum(0., reference - KNEE_ARTICULATION_TOLERANCE_RADIANS)
    high = np.minimum(np.pi, reference + KNEE_ARTICULATION_TOLERANCE_RADIANS)
    if source_bounds is not None:
        original = np.asarray(source_bounds)
        # An intermediate bake is a proposal, not a second source of truth.
        # Enforcing another one-degree band around it can exclude repairs
        # that satisfy the original source policy and every physical contact.
        low = np.maximum(0., original[:, 0])
        high = np.minimum(np.pi, original[:, 1])
    return low, high


def _smooth_track(values: np.ndarray, fps: float, fixed: np.ndarray | None = None) -> np.ndarray:
    """Fit a continuous trajectory while exactly retaining measured contacts."""
    count = len(values)
    if count < 3:
        return values.copy()
    second_difference = np.diff(np.eye(count), n=2, axis=0)
    strength = (max(fps, 1.0) * 0.10) ** 4
    system = np.eye(count) + strength * second_difference.T @ second_difference
    fixed = np.zeros(count, dtype=bool) if fixed is None else fixed
    free = ~fixed
    result = values.copy()
    rhs = values[free] - system[np.ix_(free, fixed)] @ values[fixed]
    result[free] = np.linalg.solve(system[np.ix_(free, free)], rhs)
    return result


def stabilize_rigid_feet(clip: MotionClip) -> tuple[MotionClip, dict[str, object]]:
    frames = [MotionFrame(time_sec=f.time_sec, joints=dict(f.joints)) for f in clip.frames]
    corrected = 0
    for side in ("left", "right"):
        ankle_name, toe_name = f"{side}_ankle", f"{side}_foot"
        if not frames or any(ankle_name not in f.joints or toe_name not in f.joints for f in frames):
            continue
        ankles = np.array([f.joints[ankle_name] for f in frames])
        segments = np.array([f.joints[toe_name] for f in frames]) - ankles
        length = float(np.median(np.linalg.norm(segments, axis=1)))
        if length <= 1e-8:
            continue
        directions = _unit(segments)
        knee_name = f"{side}_knee"
        shin_vectors = (np.array([frame.joints[knee_name] for frame in frames]) - ankles
                        if all(knee_name in frame.joints for frame in frames) else None)
        if shin_vectors is not None and np.all(np.linalg.norm(shin_vectors, axis=1) > 1e-8):
            # Foot heading is relative to its shin. Smoothing world vectors
            # holds the foot back during leg swing and creates ankle snaps.
            # A transported shin frame removes that swing before fitting.
            from .temporal_quality import transport_side
            axes = _unit(shin_vectors)
            bases = []
            lateral = None
            previous_axis = None
            for axis in axes:
                if lateral is not None:
                    lateral = transport_side(lateral, previous_axis, axis)
                if lateral is None:
                    seed = np.eye(3)[int(np.argmin(np.abs(axis)))]
                    lateral = _unit(seed - axis * np.dot(seed, axis))
                bases.append(np.column_stack((lateral, axis, np.cross(lateral, axis))))
                previous_axis = axis
            bases = np.asarray(bases)
            local = np.einsum('nji,nj->ni', bases, directions)
            directions = np.einsum('nij,nj->ni', bases, _unit(_smooth_track(local, clip.fps)))
        else:
            directions = _unit(_smooth_track(directions, clip.fps))
        for index, frame in enumerate(frames):
            target = ankles[index] + directions[index] * length
            corrected += int(np.linalg.norm(target - frame.joints[toe_name]) > 1e-8)
            frame.joints[toe_name] = tuple(float(v) for v in target)
    return replace(clip, frames=frames), {
        "applied": corrected > 0,
        "strategy": "rigid_foot_shin_relative_direction_preservation",
        "correctedSampleCount": corrected,
    }


def _leg_candidates(
    hip: np.ndarray,
    toes: np.ndarray,
    headings: np.ndarray,
    ankle_angles: np.ndarray,
    knee_branches: np.ndarray,
    thigh_length: float,
    shin_length: float,
    foot_length: float,
    knee_poles: np.ndarray | None = None,
    source_axes: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Combine shin + rigid foot into an effective knee-to-toe link. Its
    # length follows from the *relative* ankle angle (law of cosines).
    # Two-bone IK then reaches the toe directly, after which the ankle is
    # recovered analytically. No orientation bound refers to world axes.
    effective_length = np.sqrt(
        shin_length**2 + foot_length**2
        - 2 * shin_length * foot_length * np.cos(ankle_angles)
    )
    reach = toes - hip
    distances = np.linalg.norm(reach, axis=-1)
    direction = _unit(reach)
    reachable = (distances > 1e-8) & (distances >= np.abs(thigh_length - effective_length) - 1e-8) & (
        distances <= thigh_length + effective_length + 1e-8
    )
    along = (thigh_length**2 - effective_length**2 + distances**2) / np.maximum(2 * distances, 1e-8)
    height = np.sqrt(np.maximum(0, thigh_length**2 - along**2))
    poles = headings if knee_poles is None else knee_poles
    if source_axes is not None:
        poles = _transport_knee_poles(poles, source_axes, direction)
    fallback_pole = poles - direction * np.sum(poles * direction, axis=-1, keepdims=True)
    bend = _unit(fallback_pole)
    knees = hip + direction * along[..., None] + bend * (height * knee_branches)[..., None]
    normal = _unit(np.cross(poles, direction))
    knee_to_toe = _unit(toes - knees)
    offset_angle = np.arctan2(
        foot_length * np.sin(ankle_angles),
        shin_length - foot_length * np.cos(ankle_angles),
    )
    shin_down = (
        knee_to_toe * np.cos(offset_angle)[..., None]
        + np.cross(normal, knee_to_toe) * np.sin(offset_angle)[..., None]
    )
    ankles = knees + shin_length * shin_down
    foot_vectors = toes - ankles
    # Reject the mirrored knee hinge as part of candidate construction.
    actual_axis = _unit(ankles - hip)
    knee_bend = (knees - hip) - actual_axis * np.sum((knees - hip) * actual_axis, axis=-1, keepdims=True)
    valid = reachable & (np.sum(knee_bend * poles, axis=-1) >= -1e-6)
    # A collapsed heading/pole can otherwise return shortened segments while
    # still satisfying the reach test. Such a construction is not rigid IK.
    valid &= np.isclose(np.linalg.norm(ankles - knees, axis=-1), shin_length,
                        rtol=1e-6, atol=1e-8)
    valid &= np.isclose(np.linalg.norm(foot_vectors, axis=-1), abs(foot_length),
                        rtol=1e-6, atol=1e-8)
    return knees, ankles, foot_vectors, valid


def _flat_leg_pose(hips, targets, headings, thigh_length, shin_length, foot_length, knee_poles=None, source_axes=None):
    ankles = targets - headings * foot_length
    reach = ankles - hips
    distance = np.linalg.norm(reach, axis=-1)
    direction = _unit(reach)
    poles = headings if knee_poles is None else knee_poles
    if source_axes is not None:
        poles = _transport_knee_poles(poles, source_axes, direction)
    bend = _unit(poles - direction * np.sum(poles * direction, axis=-1, keepdims=True))
    along = (thigh_length**2 - shin_length**2 + distance**2) / np.maximum(2 * distance, 1e-8)
    height = np.sqrt(np.maximum(0, thigh_length**2 - along**2))
    knees = hips + direction * along[..., None] + bend * height[..., None]
    angle = np.arccos(np.clip(np.sum(_unit(knees - ankles) * headings, axis=-1), -1, 1))
    return knees, ankles, angle, distance


def _fit_supported_ankle_root(root_correction, prepared, reach_constraints, fps, source_bounds=None):
    from .contact_trajectory import ContactTrajectory
    if not prepared:
        return root_correction, {}
    seed = _initial_contact_root_guess(root_correction, prepared, reach_constraints, fps, source_bounds)
    return ContactTrajectory(seed, prepared, reach_constraints, fps, source_bounds or {}).solve()


def _initial_contact_root_guess(root_correction, prepared, reach_constraints, fps, source_bounds=None):
    """Generate a starting pose; continuous trajectory constraints decide feasibility."""
    from scipy.optimize import minimize

    root = root_correction.copy()
    constraints_by_frame = [[] for _ in root]
    knee_bounds = {side: _contact_knee_bounds(leg[1], leg[2], leg[3], (source_bounds or {}).get(side))
                   for side, leg in prepared.items()}
    for indexes, offsets, radius in reach_constraints:
        for index, offset in zip(indexes, offsets):
            constraints_by_frame[index].append((offset, radius))

    def margins(value, index):
        values = [radius**2 - np.sum((value - offset)**2)
                  for offset, radius in constraints_by_frame[index]]
        for side, leg in prepared.items():
            (names, hips, knees, ankles, targets, headings, reference_angles,
             thigh, shin, foot, contact, stationary, episodes, full, heel, toe, lift_ratios) = leg
            if heel[index] or toe[index]:
                angles = ankle_proposal_angles()
                trial_knees, trial_ankles, _, valid = _leg_candidates(
                    hips[index] + value, targets[index], headings[index],
                    np.tile(angles, 2), np.repeat([1., -1.], len(angles)),
                    thigh, shin, -HEEL_BEHIND_ANKLE_RATIO * foot if heel[index] else foot,
                    knee_poles=_source_knee_poles(hips[index], knees[index], ankles[index]),
                    source_axes=ankles[index] - hips[index],
                )
                if heel[index]:
                    trial_toes = trial_ankles + (targets[index] - trial_ankles) / -HEEL_BEHIND_ANKLE_RATIO
                    clearance = (trial_toes[:, 1] - targets[index, 1]) / (1 + HEEL_BEHIND_ANKLE_RATIO)
                else:
                    clearance = trial_ankles[:, 1] - targets[index, 1]
                clearance -= foot * lift_ratios[index]
                trial_angles = _knee_angles(hips[index] + value, trial_knees, trial_ankles)
                low, high = knee_bounds[side]
                knee_margin = np.minimum(trial_angles - low[index], high[index] - trial_angles)
                # Both conditions must hold for the SAME pose. A continuous
                # margin gives the root optimizer a direction outside feasibility.
                combined_margin = np.minimum(clearance / max(foot, 1e-8), knee_margin)
                values.append(float(np.max(np.where(valid, combined_margin, -1.0))))
            if not full[index]:
                continue
            _, _, angle, distance = _flat_leg_pose(
                hips[index] + value, targets[index], headings[index], thigh, shin, foot,
                knee_poles=_source_knee_poles(hips[index], knees[index], ankles[index]),
                    source_axes=ankles[index] - hips[index],
            )
            values.append(distance - max(abs(thigh - shin), 1e-8))
            # Reachability alone permits the solver to invent a squat/extension.
            # Fit the body translation to the observed knee articulation too.
            low, high = (bound[index] for bound in knee_bounds[side])
            values.extend([
                distance**2 - (thigh**2 + shin**2 - 2 * thigh * shin * np.cos(low)),
                (thigh**2 + shin**2 - 2 * thigh * shin * np.cos(high)) - distance**2,
            ])
        return np.array(values) if values else np.ones(1)

    if all(np.min(margins(value, index)) >= -1e-7 for index, value in enumerate(root)):
        return root
    # Alternate smoothing and feasible-pose projection. Only the body moves;
    # the contact points and bone lengths remain hard constraints.
    for _ in range(4):
        reference = _smooth_track(root, fps)
        for index in range(len(root)):
            if np.min(margins(reference[index], index)) >= 0:
                root[index] = reference[index]
                continue
            # The partial-contact feasible region is non-convex. A failed
            # local search does not establish infeasibility; try the adjacent
            # accepted pose and the uncorrected pose, with the same constraints.
            seeds = [root[index]] + ([root[index - 1]] if index else []) + [np.zeros(3)]
            for seed in seeds:
                fit = minimize(
                    lambda value: float(np.sum((value - reference[index])**2)), seed,
                    jac=lambda value: 2 * (value - reference[index]), method="SLSQP",
                    constraints={"type": "ineq", "fun": lambda value: margins(value, index)},
                    options={"ftol": 1e-11, "maxiter": 80},
                )
                if np.min(margins(fit.x, index)) >= -1e-6:
                    break
            root[index] = fit.x
    return root


def solve_rigid_foot_contacts(
    clip: MotionClip,
    support_evidence: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    """Select a coherent ankle trajectory; every candidate has rigid bones.

    Height-only toe contacts leave tangential movement and heel lift free.
    Source-confirmed stationary stances keep a fixed distal anchor. A shared
    smooth body correction retains reachability without stretching limbs.
    Heading comes from the directed input trajectory and is never reversed to
    improve an angle score. Smoothness is scored on whole leg configurations,
    before selection; no independent joint filtering follows this solver.
    """
    if len(clip.frames) < 3:
        return clip, {"applied": False, "reason": "too_few_frames"}
    contacts = motion_support_contacts(support_evidence)
    toe_contacts = [
        value for value in contacts
        if isinstance(value, dict)
        and str(value.get("jointName", "")).endswith(("_foot", "_ankle"))
    ]
    if not toe_contacts:
        return clip, {"applied": False, "reason": "forefoot_contacts_unavailable"}
    frames = [MotionFrame(time_sec=f.time_sec, joints=dict(f.joints)) for f in clip.frames]
    floor = min(
        f.joints[name][1] for f in clip.frames for name in ("left_foot", "right_foot")
        if name in f.joints
    )
    count = len(frames)
    observed_surface_heights = []
    for contact in toe_contacts:
        state = contact.get("contactState")
        if state not in {"heel_only", "toe_only", "full_sole"}:
            continue
        side = str(contact["jointName"]).split("_")[0]
        start, end = contact_frame_bounds(contact, count)
        for frame in frames[start:end + 1]:
            ankle, toe = frame.joints.get(f"{side}_ankle"), frame.joints.get(f"{side}_foot")
            if ankle is not None and toe is not None:
                observed_surface_heights.append(
                    ankle[1] - HEEL_BEHIND_ANKLE_RATIO * (toe[1] - ankle[1])
                    if state == "heel_only" else toe[1]
                )
    if observed_surface_heights:
        floor = min(observed_surface_heights)
    # Post-bake corrections must use the same floor as the exported renderer.
    render_floor = clip.metadata.get("renderFloorY")
    if isinstance(render_floor, (int, float)) and np.isfinite(render_floor):
        floor = float(render_floor)
    reports: dict[str, object] = {}
    prepared = {}
    reach_constraints = []
    # A foot reach correction must not displace another established support
    # (a seat, bench, planted hand, knee, etc.). Preserve those body anchors.
    for contact in contacts:
        if not isinstance(contact, dict) or not is_stationary_contact(contact):
            continue
        name = str(contact.get("jointName", ""))
        if name.endswith(("_foot", "_ankle")) or name not in clip.joint_names:
            continue
        start, end = contact_frame_bounds(contact, count)
        indexes = np.arange(start, end + 1)
        if len(indexes):
            reach_constraints.append((indexes, np.zeros((len(indexes), 3)), 0.0))
    for side in ("left", "right"):
        if not any(str(contact["jointName"]).startswith(f"{side}_") for contact in toe_contacts):
            continue
        names = [f"{side}_{name}" for name in ("hip", "knee", "ankle", "foot")]
        if any(any(name not in f.joints for name in names) for f in frames):
            continue
        hips, knees, ankles, toes = [
            np.array([f.joints[name] for f in frames], dtype=float) for name in names
        ]
        foot_length = float(np.median(np.linalg.norm(toes - ankles, axis=1)))
        thigh_length = float(np.median(np.linalg.norm(knees - hips, axis=1)))
        shin_length = float(np.median(np.linalg.norm(ankles - knees, axis=1)))
        headings = toes - ankles
        headings[:, 1] = 0
        headings = _unit(headings)
        headings = _unit(_smooth_track(headings, clip.fps))
        reference_angles = np.arccos(np.clip(
            np.sum(_unit(knees - ankles) * _unit(toes - ankles), axis=1), -1, 1
        ))
        contact_mask = np.zeros(count, dtype=bool)
        stationary_mask = np.zeros(count, dtype=bool)
        full_sole_mask = np.zeros(count, dtype=bool)
        heel_mask = np.zeros(count, dtype=bool)
        observed_toe_mask = np.zeros(count, dtype=bool)
        anchor_ids = np.full(count, None, dtype=object)
        lift_ratios = np.zeros(count)
        for contact in toe_contacts:
            if contact["jointName"] not in names[2:]:
                continue
            start, end = contact_frame_bounds(contact, count)
            state = contact.get("contactState")
            lift_ratios[start:end + 1] = float(contact.get("minimumLiftRatio", 0))
            if contact.get("verticalOnly") is True or state in {"full_sole", "toe_only", "heel_only"}:
                contact_mask[start:end + 1] = True
            if state == "full_sole":
                full_sole_mask[start:end + 1] = True
            elif state == "heel_only":
                heel_mask[start:end + 1] = True
            elif state == "toe_only":
                observed_toe_mask[start:end + 1] = True
            if is_stationary_contact(contact):
                stationary_mask[start:end + 1] = True
                anchor_ids[start:end + 1] = contact.get("anchorGroupId")
        fixed_heading_mask = stationary_mask & full_sole_mask
        fixed_headings, _ = stationary_target_track(headings, fixed_heading_mask)
        headings = _unit(_smooth_track(fixed_headings, clip.fps, fixed_heading_mask))
        maximum_reach = thigh_length + shin_length + foot_length - 1e-4
        anchor_points = toes.copy()
        anchor_points[heel_mask] = ankles[heel_mask] - HEEL_BEHIND_ANKLE_RATIO * (toes - ankles)[heel_mask]
        fixed_targets, anchor_episodes = stationary_target_track(
            toes, stationary_mask & ~heel_mask, fps=clip.fps, anchor_ids=anchor_ids)
        heel_points = ankles - HEEL_BEHIND_ANKLE_RATIO * (toes - ankles)
        heel_targets, heel_episodes = stationary_target_track(heel_points, stationary_mask & heel_mask, fps=clip.fps)
        fixed_targets[heel_mask] = heel_targets[heel_mask]
        anchor_episodes = [{**episode, "anchorKind": "toe"} for episode in anchor_episodes]
        anchor_episodes.extend({**episode, "anchorKind": "heel"} for episode in heel_episodes)
        targets = _smooth_track(fixed_targets, clip.fps, stationary_mask)
        # Heel and toe are different material points. Never filter across a
        # change of pivot as though their coordinates belonged to one point.
        targets[heel_mask & ~stationary_mask] = anchor_points[heel_mask & ~stationary_mask]
        target_heights = anchor_points[:, 1].copy()
        target_heights[stationary_mask] = fixed_targets[stationary_mask, 1]
        target_heights[contact_mask] = floor
        targets[:, 1] = np.maximum(floor, _smooth_track(
            target_heights, clip.fps, contact_mask | stationary_mask
        ))
        indexes = np.flatnonzero((contact_mask | stationary_mask) & ~full_sole_mask & ~heel_mask)
        if len(indexes):
            reach_constraints.append((indexes, targets[indexes] - hips[indexes], maximum_reach))
        indexes = np.flatnonzero(full_sole_mask)
        if len(indexes):
            ankle_targets = targets[indexes] - headings[indexes] * foot_length
            reach_constraints.append((indexes, ankle_targets - hips[indexes], thigh_length + shin_length))
        indexes = np.flatnonzero(heel_mask)
        if len(indexes):
            heel_reach = thigh_length + shin_length + HEEL_BEHIND_ANKLE_RATIO * foot_length - 1e-4
            reach_constraints.append((indexes, targets[indexes] - hips[indexes], heel_reach))
        prepared[side] = (names, hips, knees, ankles, targets, headings, reference_angles,
                          thigh_length, shin_length, foot_length, contact_mask, stationary_mask, anchor_episodes,
                          full_sole_mask, heel_mask, observed_toe_mask, lift_ratios)
    root_correction = reachable_root_track(count, clip.fps, reach_constraints)
    source_bounds = clip.metadata.get("contactSourceKneeBounds") or {}
    root_correction, continuous_angles = _fit_supported_ankle_root(root_correction, prepared, reach_constraints, clip.fps, source_bounds)
    for index, frame in enumerate(frames):
        frame.joints.update({name: tuple(float(v) for v in np.asarray(point) + root_correction[index])
                             for name, point in frame.joints.items()})
    for side, prepared_leg in prepared.items():
        (names, hips, knees, ankles, targets, headings, reference_angles,
         thigh_length, shin_length, foot_length, contact_mask, stationary_mask, anchor_episodes,
         full_sole_mask, heel_mask, observed_toe_mask, lift_ratios) = prepared_leg
        supported = contact_mask | stationary_mask | heel_mask | observed_toe_mask
        if np.all(full_sole_mask | ~supported):
            # Flat soles have one analytic pose; free frames keep the input.
            # Hundreds of identical columns only inflate the quadratic DP.
            ankle_options, knee_branches = np.array([np.pi / 2]), np.array([1.0])
        else:
            angles = ankle_proposal_angles()
            ankle_options = np.tile(angles, 2)
            knee_branches = np.repeat([1.0, -1.0], len(angles))
        angle_grid = np.broadcast_to(ankle_options, (count, len(ankle_options)))
        if np.any(heel_mask | observed_toe_mask):
            angle_grid = np.column_stack([angle_grid, continuous_angles[side], continuous_angles[side]])
            knee_branches = np.r_[knee_branches, 1., -1.]
        hips = hips + root_correction
        knees = knees + root_correction
        ankles = ankles + root_correction
        targets += _smooth_track(
            np.where((contact_mask | stationary_mask)[:, None], 0, root_correction),
            clip.fps, contact_mask | stationary_mask,
        )
        targets[:, 1] = np.maximum(floor, targets[:, 1])
        signed_lengths = np.where(heel_mask, -HEEL_BEHIND_ANKLE_RATIO * foot_length, foot_length)
        candidate_knees, candidate_ankles, _, valid = _leg_candidates(
            hips[:, None, :], targets[:, None, :], headings[:, None, :],
            angle_grid, knee_branches[None, :], thigh_length, shin_length, signed_lengths[:, None],
            knee_poles=_source_knee_poles(hips, knees, ankles)[:, None, :],
            source_axes=(ankles - hips)[:, None, :],
        )
        if np.any(full_sole_mask):
            flat_knees, flat_ankles, _, distance = _flat_leg_pose(
                hips, targets, headings, thigh_length, shin_length, foot_length,
                knee_poles=_source_knee_poles(hips, knees, ankles),
                source_axes=ankles - hips,
            )
            candidate_knees[full_sole_mask] = flat_knees[full_sole_mask, None, :]
            candidate_ankles[full_sole_mask] = flat_ankles[full_sole_mask, None, :]
            valid[full_sole_mask] = (distance[full_sole_mask, None] <= thigh_length + shin_length + 1e-8)
        candidate_toes = candidate_ankles + (
            targets[:, None, :] - candidate_ankles
        ) * (foot_length / signed_lengths)[:, None, None]
        actual_angles = np.arccos(np.clip(np.sum(
            _unit(candidate_knees - candidate_ankles) * _unit(candidate_toes - candidate_ankles), axis=-1
        ), -1, 1))
        knee_low, knee_high = _contact_knee_bounds(hips, knees, ankles, source_bounds.get(side))
        candidate_angles = _knee_angles(hips[:, None, :], candidate_knees, candidate_ankles)
        valid &= (candidate_angles >= knee_low[:, None] - ANGLE_NUMERICAL_TOLERANCE_RADIANS) & (
            candidate_angles <= knee_high[:, None] + ANGLE_NUMERICAL_TOLERANCE_RADIANS)
        # No contact evidence means no leg IK. Keep free-motion frames exactly
        # as reconstructed, apart from the common rigid body translation.
        free = ~supported
        candidate_knees[free] = knees[free, None, :]
        candidate_ankles[free] = ankles[free, None, :]
        original_toes = np.array([f.joints[names[3]] for f in frames])
        candidate_toes[free] = original_toes[free, None, :]
        actual_angles[free] = reference_angles[free, None]
        valid[free] = True
        valid[observed_toe_mask] &= candidate_ankles[observed_toe_mask, :, 1] >= (
            targets[observed_toe_mask, None, 1] + foot_length * lift_ratios[observed_toe_mask, None] - 1e-7
        )
        valid[heel_mask] &= candidate_toes[heel_mask, :, 1] >= (
            targets[heel_mask, None, 1] + foot_length * (1 + HEEL_BEHIND_ANKLE_RATIO) * lift_ratios[heel_mask, None] - 1e-7
        )
        missing = np.flatnonzero(~np.any(valid, axis=1))
        if len(missing):
            raise InfeasibleContactCorrection(f"No reachable rigid {side} toe-contact pose at frames {missing.tolist()}; "
                             f"ankle angle ranges {np.rad2deg(actual_angles[missing]).min(axis=1).round(1).tolist()}")
        # All costs are dimensionless and compare trajectories in the same
        # units. Temporal terms compare corrections to retain exercise motion.
        ankle_correction = (candidate_ankles - ankles[:, None, :]) / shin_length
        knee_correction = (candidate_knees - knees[:, None, :]) / thigh_length
        toe_correction = (candidate_toes - original_toes[:, None, :]) / foot_length
        angle_correction = actual_angles - reference_angles[:, None]
        local_cost = (
            np.sum(ankle_correction**2, axis=-1)
            + np.sum(knee_correction**2, axis=-1)
            + np.sum(toe_correction**2, axis=-1)
            + 0.1 * angle_correction**2
        )
        local_cost[~valid] = np.inf
        costs = local_cost[0].copy()
        parents = np.zeros((count, angle_grid.shape[1]), dtype=np.int32)
        temporal_weight = (clip.fps * 0.15) ** 2
        for index in range(1, count):
            change = (
                np.sum((ankle_correction[index, :, None] - ankle_correction[index - 1, None, :])**2, axis=-1)
                + np.sum((knee_correction[index, :, None] - knee_correction[index - 1, None, :])**2, axis=-1)
                + np.sum((toe_correction[index, :, None] - toe_correction[index - 1, None, :])**2, axis=-1)
                + (actual_angles[index, :, None] - actual_angles[index - 1, None, :])**2
            )
            transitions = costs[None, :] + temporal_weight * change
            parents[index] = np.argmin(transitions, axis=1)
            costs = local_cost[index] + np.min(transitions, axis=1)
        selected = np.zeros(count, dtype=np.int32)
        selected[-1] = int(np.argmin(costs))
        for index in range(count - 1, 0, -1):
            selected[index - 1] = parents[index, selected[index]]
        indexes = np.arange(count)
        original_leg = np.stack([hips, knees, ankles, original_toes], axis=1)
        solved_leg = np.stack([hips, candidate_knees[indexes, selected],
                               candidate_ankles[indexes, selected], candidate_toes[indexes, selected]], axis=1)
        solved_leg = blend_contact_transition_rotations(original_leg, solved_leg, supported, clip.fps,
                                                        knee_bounds=(knee_low, knee_high))
        for index in range(count):
            for joint_index, name in enumerate(names[1:], start=1):
                frames[index].joints[name] = tuple(float(v) for v in solved_leg[index, joint_index])
        reports[side] = {
            "toeContactFrames": np.flatnonzero(contact_mask).tolist(),
            "stationaryContactEpisodes": anchor_episodes,
            "fullSoleFrames": np.flatnonzero(full_sole_mask).tolist(),
            "heelOnlyFrames": np.flatnonzero(heel_mask).tolist(),
            "observedToeOnlyFrames": np.flatnonzero(observed_toe_mask).tolist(),
            "footLength": foot_length,
            "thighLength": thigh_length,
            "shinLength": shin_length,
            "maximumAnkleAngleStepDegrees": float(np.max(np.abs(np.diff(np.rad2deg(actual_angles[np.arange(count), selected]))))),
        }
    return replace(clip, frames=frames), {
        "applied": bool(reports),
        "strategy": "rigid_foot_temporal_leg_ik",
        "ankleAngleReference": "shin",
        "ankleProposalStepDegrees": ANKLE_PROPOSAL_STEP_DEGREES,
        "ankleProposalDomain": "geometric_not_anatomical",
        "supportPlaneY": floor,
        "maximumRootReachCorrection": float(np.max(np.linalg.norm(root_correction, axis=1))),
        "feet": reports,
    }

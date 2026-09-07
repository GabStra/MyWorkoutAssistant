"""Rigid feet and temporally coherent leg IK for inferred toe contacts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from .models import MotionClip, MotionFrame
from .contact_constraints import (
    contact_frame_bounds, is_stationary_contact, stationary_target_track, reachable_root_track,
)

MIN_ANKLE_SEPARATION_DEGREES = 75.0
MAX_ANKLE_SEPARATION_DEGREES = 135.0
# Rear shoe ring: 1.02 * 1.15 times ankle-to-toe length from the toe.
HEEL_BEHIND_ANKLE_RATIO = 1.02 * 1.15 - 1.0


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-10)


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
        directions = _unit(_smooth_track(_unit(segments), clip.fps))
        for index, frame in enumerate(frames):
            target = ankles[index] + directions[index] * length
            corrected += int(np.linalg.norm(target - frame.joints[toe_name]) > 1e-8)
            frame.joints[toe_name] = tuple(float(v) for v in target)
    return replace(clip, frames=frames), {
        "applied": corrected > 0,
        "strategy": "rigid_foot_direction_preservation",
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
    reachable = (distances > np.abs(thigh_length - effective_length) + 1e-6) & (
        distances < thigh_length + effective_length - 1e-6
    )
    along = (thigh_length**2 - effective_length**2 + distances**2) / np.maximum(2 * distances, 1e-8)
    height = np.sqrt(np.maximum(0, thigh_length**2 - along**2))
    fallback_pole = headings - direction * np.sum(headings * direction, axis=-1, keepdims=True)
    bend = _unit(fallback_pole)
    knees = hip + direction * along[..., None] + bend * (height * knee_branches)[..., None]
    normal = _unit(np.cross(headings, direction))
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
    valid = reachable & (np.sum(knee_bend * headings, axis=-1) >= -1e-6)
    return knees, ankles, foot_vectors, valid


def _flat_leg_pose(hips, targets, headings, thigh_length, shin_length, foot_length):
    ankles = targets - headings * foot_length
    reach = ankles - hips
    distance = np.linalg.norm(reach, axis=-1)
    direction = _unit(reach)
    bend = _unit(headings - direction * np.sum(headings * direction, axis=-1, keepdims=True))
    along = (thigh_length**2 - shin_length**2 + distance**2) / np.maximum(2 * distance, 1e-8)
    height = np.sqrt(np.maximum(0, thigh_length**2 - along**2))
    knees = hips + direction * along[..., None] + bend * height[..., None]
    angle = np.arccos(np.clip(np.sum(_unit(knees - ankles) * headings, axis=-1), -1, 1))
    return knees, ankles, angle, distance


def _fit_supported_ankle_root(root_correction, prepared, reach_constraints, fps):
    """Keep the observed contact patch and ankle envelope feasible together."""
    from scipy.optimize import minimize

    root = root_correction.copy()
    constraints_by_frame = [[] for _ in root]
    for indexes, offsets, radius in reach_constraints:
        for index, offset in zip(indexes, offsets):
            constraints_by_frame[index].append((offset, radius))

    def margins(value, index):
        values = [radius**2 - np.sum((value - offset)**2)
                  for offset, radius in constraints_by_frame[index]]
        for leg in prepared.values():
            (names, hips, knees, ankles, targets, headings, reference_angles,
             thigh, shin, foot, contact, stationary, episodes, full, heel, toe, lift_ratios) = leg
            if heel[index] or (toe[index] and lift_ratios[index] > 0):
                angles = np.deg2rad(np.arange(MIN_ANKLE_SEPARATION_DEGREES, MAX_ANKLE_SEPARATION_DEGREES + 0.01, 0.5))
                _, trial_ankles, _, valid = _leg_candidates(
                    hips[index] + value, targets[index], headings[index],
                    np.tile(angles, 2), np.repeat([1., -1.], len(angles)),
                    thigh, shin, -HEEL_BEHIND_ANKLE_RATIO * foot if heel[index] else foot,
                )
                if heel[index]:
                    trial_toes = trial_ankles + (targets[index] - trial_ankles) / -HEEL_BEHIND_ANKLE_RATIO
                    clearance = (trial_toes[:, 1] - targets[index, 1]) / (1 + HEEL_BEHIND_ANKLE_RATIO)
                else:
                    clearance = trial_ankles[:, 1] - targets[index, 1]
                clearance -= foot * lift_ratios[index]
                values.append(float(np.max(np.where(valid, clearance, -1.0))))
            if not full[index]:
                continue
            _, _, angle, distance = _flat_leg_pose(
                hips[index] + value, targets[index], headings[index], thigh, shin, foot
            )
            values.extend([angle - np.deg2rad(MIN_ANKLE_SEPARATION_DEGREES),
                           np.deg2rad(MAX_ANKLE_SEPARATION_DEGREES) - angle,
                           distance - abs(thigh - shin) - 1e-4])
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
            fit = minimize(
                lambda value: float(np.sum((value - reference[index])**2)), root[index],
                jac=lambda value: 2 * (value - reference[index]), method="SLSQP",
                constraints={"type": "ineq", "fun": lambda value: margins(value, index)},
                options={"ftol": 1e-11, "maxiter": 80},
            )
            if np.min(margins(fit.x, index)) < -1e-6:
                raise ValueError(f"Full-sole support and ankle envelope conflict at frame {index}")
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
    evidence = support_evidence or {}
    contacts = list(evidence.get("contacts") or []) + list(evidence.get("supportContacts") or [])
    for side, record in (evidence.get("feet") or {}).items():
        if isinstance(record, dict) and record.get("continuousSupport"):
            contacts.append({**record, "jointName": record.get("jointName", f"{side}_ankle"),
                             "startRatio": 0.0, "endRatio": 1.0})
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
    angles = np.deg2rad(np.arange(
        MIN_ANKLE_SEPARATION_DEGREES, MAX_ANKLE_SEPARATION_DEGREES + 0.01, 0.5
    ))
    ankle_options = np.tile(angles, 2)
    knee_branches = np.repeat([1.0, -1.0], len(angles))
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
        lift_ratios = np.zeros(count)
        for contact in toe_contacts:
            if contact["jointName"] not in names[2:]:
                continue
            start, end = contact_frame_bounds(contact, count)
            state = contact.get("contactState")
            lift_ratios[start:end + 1] = float(contact.get("minimumLiftRatio", 0))
            if contact.get("verticalOnly") is True or state == "full_sole":
                contact_mask[start:end + 1] = True
            if state == "full_sole":
                full_sole_mask[start:end + 1] = True
            elif state == "heel_only":
                heel_mask[start:end + 1] = True
            elif state == "toe_only":
                observed_toe_mask[start:end + 1] = True
            if is_stationary_contact(contact):
                stationary_mask[start:end + 1] = True
        fixed_heading_mask = stationary_mask & full_sole_mask
        fixed_headings, _ = stationary_target_track(headings, fixed_heading_mask)
        headings = _unit(_smooth_track(fixed_headings, clip.fps, fixed_heading_mask))
        maximum_reach = thigh_length + np.sqrt(
            shin_length**2 + foot_length**2 - 2 * shin_length * foot_length
            * np.cos(np.deg2rad(MAX_ANKLE_SEPARATION_DEGREES))
        ) - 1e-4
        anchor_points = toes.copy()
        anchor_points[heel_mask] = ankles[heel_mask] - HEEL_BEHIND_ANKLE_RATIO * (toes - ankles)[heel_mask]
        fixed_targets, anchor_episodes = stationary_target_track(anchor_points, stationary_mask & ~heel_mask)
        heel_targets, heel_episodes = stationary_target_track(anchor_points, stationary_mask & heel_mask)
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
            reach_constraints.append((indexes, ankle_targets - hips[indexes], thigh_length + shin_length - 1e-4))
        indexes = np.flatnonzero(heel_mask)
        if len(indexes):
            heel_reach = thigh_length + np.sqrt(
                shin_length**2 + (HEEL_BEHIND_ANKLE_RATIO * foot_length)**2
                + 2 * shin_length * HEEL_BEHIND_ANKLE_RATIO * foot_length
                * np.cos(np.deg2rad(MIN_ANKLE_SEPARATION_DEGREES))
            ) - 1e-4
            reach_constraints.append((indexes, targets[indexes] - hips[indexes], heel_reach))
        prepared[side] = (names, hips, knees, ankles, targets, headings, reference_angles,
                          thigh_length, shin_length, foot_length, contact_mask, stationary_mask, anchor_episodes,
                          full_sole_mask, heel_mask, observed_toe_mask, lift_ratios)
    root_correction = reachable_root_track(count, clip.fps, reach_constraints)
    root_correction = _fit_supported_ankle_root(root_correction, prepared, reach_constraints, clip.fps)
    for index, frame in enumerate(frames):
        frame.joints.update({name: tuple(float(v) for v in np.asarray(point) + root_correction[index])
                             for name, point in frame.joints.items()})
    for side, prepared_leg in prepared.items():
        (names, hips, knees, ankles, targets, headings, reference_angles,
         thigh_length, shin_length, foot_length, contact_mask, stationary_mask, anchor_episodes,
         full_sole_mask, heel_mask, observed_toe_mask, lift_ratios) = prepared_leg
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
            ankle_options[None, :], knee_branches[None, :], thigh_length, shin_length, signed_lengths[:, None],
        )
        if np.any(full_sole_mask):
            flat_knees, flat_ankles, _, distance = _flat_leg_pose(
                hips, targets, headings, thigh_length, shin_length, foot_length
            )
            candidate_knees[full_sole_mask] = flat_knees[full_sole_mask, None, :]
            candidate_ankles[full_sole_mask] = flat_ankles[full_sole_mask, None, :]
            valid[full_sole_mask] = (distance[full_sole_mask, None] < thigh_length + shin_length)
        candidate_toes = candidate_ankles + (
            targets[:, None, :] - candidate_ankles
        ) * (foot_length / signed_lengths)[:, None, None]
        actual_angles = np.arccos(np.clip(np.sum(
            _unit(candidate_knees - candidate_ankles) * _unit(candidate_toes - candidate_ankles), axis=-1
        ), -1, 1))
        valid &= (actual_angles >= np.deg2rad(MIN_ANKLE_SEPARATION_DEGREES) - 1e-6)
        valid &= (actual_angles <= np.deg2rad(MAX_ANKLE_SEPARATION_DEGREES) + 1e-6)
        valid[observed_toe_mask] &= candidate_ankles[observed_toe_mask, :, 1] >= (
            targets[observed_toe_mask, None, 1] + foot_length * lift_ratios[observed_toe_mask, None] - 1e-7
        )
        valid[heel_mask] &= candidate_toes[heel_mask, :, 1] >= (
            targets[heel_mask, None, 1] + foot_length * (1 + HEEL_BEHIND_ANKLE_RATIO) * lift_ratios[heel_mask, None] - 1e-7
        )
        missing = np.flatnonzero(~np.any(valid, axis=1))
        if len(missing):
            raise ValueError(f"No reachable rigid {side} toe-contact pose at frames {missing.tolist()}; "
                             f"ankle angle ranges {np.rad2deg(actual_angles[missing]).min(axis=1).round(1).tolist()}")
        # All costs are dimensionless and compare trajectories in the same
        # units. Temporal terms compare corrections to retain exercise motion.
        ankle_correction = (candidate_ankles - ankles[:, None, :]) / shin_length
        knee_correction = (candidate_knees - knees[:, None, :]) / thigh_length
        angle_correction = actual_angles - reference_angles[:, None]
        local_cost = (
            np.sum(ankle_correction**2, axis=-1)
            + np.sum(knee_correction**2, axis=-1)
            + 0.1 * angle_correction**2
        )
        local_cost[~valid] = np.inf
        costs = local_cost[0].copy()
        parents = np.zeros((count, len(ankle_options)), dtype=np.int32)
        temporal_weight = (clip.fps * 0.15) ** 2
        for index in range(1, count):
            change = (
                np.sum((ankle_correction[index, :, None] - ankle_correction[index - 1, None, :])**2, axis=-1)
                + np.sum((knee_correction[index, :, None] - knee_correction[index - 1, None, :])**2, axis=-1)
                + (actual_angles[index, :, None] - actual_angles[index - 1, None, :])**2
            )
            transitions = costs[None, :] + temporal_weight * change
            parents[index] = np.argmin(transitions, axis=1)
            costs = local_cost[index] + np.min(transitions, axis=1)
        selected = np.zeros(count, dtype=np.int32)
        selected[-1] = int(np.argmin(costs))
        for index in range(count - 1, 0, -1):
            selected[index - 1] = parents[index, selected[index]]
        for index, option in enumerate(selected):
            frames[index].joints[names[1]] = tuple(float(v) for v in candidate_knees[index, option])
            frames[index].joints[names[2]] = tuple(float(v) for v in candidate_ankles[index, option])
            frames[index].joints[names[3]] = tuple(float(v) for v in candidate_toes[index, option])
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
        "minimumAnkleSeparationDegrees": MIN_ANKLE_SEPARATION_DEGREES,
        "maximumAnkleSeparationDegrees": MAX_ANKLE_SEPARATION_DEGREES,
        "supportPlaneY": floor,
        "maximumRootReachCorrection": float(np.max(np.linalg.norm(root_correction, axis=1))),
        "feet": reports,
    }

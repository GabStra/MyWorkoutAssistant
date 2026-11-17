"""Source-bound fixed-rig initialization from canonical keyframe geometry."""

from __future__ import annotations

import numpy as np

from .rig_playback import RIG_NUMERICAL_CONSISTENCY_METERS
from .support_alignment import authoritative_mirror_sides


def propose_canonical_contact_rig(coordinates, rig, execution, pinned, contact_targets,
                                 authoritative_sides=None):
    """Propose a constant-bone rig initialized to canonical key poses.

    The proposal may change bind directions, but it keeps the input rig's
    topology and bone lengths. Per-frame root translation restores the first
    observed contact anchor, after which every pinned joint must still match
    its immutable target within the rig consistency tolerance.

    The input rig and source evidence are never mutated. On any incompatibility
    the original coordinates and offsets are returned with ``applied=False``.
    """
    coordinates = np.asarray(coordinates, dtype=float)
    offsets = np.asarray(rig.offsets, dtype=float)
    names = list(rig.names)
    pinned = np.asarray(pinned, dtype=bool)
    contact_targets = np.asarray(contact_targets, dtype=float)

    def unchanged(reason, **details):
        return coordinates.copy(), offsets.copy(), {
            'applied': False,
            'reason': reason,
            **details,
        }

    if (coordinates.ndim != 2 or coordinates.shape != rig.initial.shape
            or not np.isfinite(coordinates).all()):
        return unchanged('invalid_coordinates')
    frame_count = len(coordinates)
    joint_count = len(names)
    if (pinned.shape != (frame_count, joint_count)
            or contact_targets.shape != (frame_count, joint_count, 3)
            or not np.isfinite(offsets).all()):
        return unchanged('invalid_contact_contract')
    if np.any(pinned & ~np.isfinite(contact_targets).all(axis=-1)):
        return unchanged('nonfinite_pinned_target')

    try:
        source_points = rig.decode(coordinates)
        authority = (authoritative_mirror_sides(pinned, names, execution)
                     if authoritative_sides is None else authoritative_sides)
        canonical_points = _canonical_reference(
            source_points, names, execution, authority)
    except (ValueError, KeyError, IndexError, FloatingPointError) as error:
        return unchanged('canonical_target_unavailable', detail=str(error))

    before_error = _maximum_canonical_residual(
        source_points, names, execution, authority)
    try:
        from .controlled_motion import FixedRig

        proposal = FixedRig(canonical_points, names)
    except (ValueError, KeyError, IndexError, FloatingPointError) as error:
        return unchanged('canonical_rig_construction_failed', detail=str(error))

    # The new basis may rotate bind directions, but it cannot change any bone
    # length or alter the active coordinate topology.
    topology_matches = (
        proposal.names == names
        and proposal.parents == list(rig.parents)
        and proposal.order == list(rig.order)
        and proposal.active == list(rig.active)
        and proposal.width == rig.width
        and proposal.initial.shape == coordinates.shape
    )
    if not topology_matches:
        return unchanged('rig_topology_changed')

    proposal_offsets = np.asarray(proposal.offsets, dtype=float).copy()
    old_lengths = np.linalg.norm(offsets, axis=1)
    new_lengths = np.linalg.norm(proposal_offsets, axis=1)
    nonzero = new_lengths > 1e-14
    if np.any((~nonzero) & (old_lengths > RIG_NUMERICAL_CONSISTENCY_METERS)):
        return unchanged('canonical_rig_has_zero_bone_length')
    proposal_offsets[nonzero] *= (old_lengths[nonzero] / new_lengths[nonzero])[:, None]
    proposal_offsets[~nonzero] = offsets[~nonzero]
    bone_length_error = np.abs(np.linalg.norm(proposal_offsets, axis=1) - old_lengths)
    maximum_bone_length_error = float(np.max(bone_length_error, initial=0.0))
    if maximum_bone_length_error > RIG_NUMERICAL_CONSISTENCY_METERS:
        return unchanged(
            'canonical_rig_bone_length_changed',
            maximumBoneLengthErrorMeters=maximum_bone_length_error,
        )
    proposal.offsets[:] = proposal_offsets

    proposed_coordinates = np.asarray(proposal.initial, dtype=float).copy()
    proposed_points = proposal.decode(proposed_coordinates)
    root_index = int(proposal.root)
    root_shifts = np.zeros((frame_count, 3), dtype=float)
    for frame in range(frame_count):
        pinned_joints = np.flatnonzero(pinned[frame])
        anchor = int(pinned_joints[0]) if len(pinned_joints) else root_index
        target = (contact_targets[frame, anchor] if len(pinned_joints)
                  else canonical_points[frame, root_index])
        root_shifts[frame] = target - proposed_points[frame, anchor]
    proposed_coordinates[:, :3] += root_shifts
    proposed_points = proposal.decode(proposed_coordinates)

    pin_errors = np.linalg.norm(proposed_points - contact_targets, axis=-1)
    maximum_pin_error = float(np.max(pin_errors[pinned], initial=0.0))
    if maximum_pin_error > RIG_NUMERICAL_CONSISTENCY_METERS:
        return unchanged(
            'canonical_rig_cannot_preserve_all_pins',
            pinnedJointCount=int(np.count_nonzero(pinned)),
            maximumPinErrorMeters=maximum_pin_error,
            maximumRootTranslationMeters=float(np.max(np.linalg.norm(root_shifts, axis=-1), initial=0.0)),
        )

    after_error = _maximum_canonical_residual(
        proposed_points, names, execution, authority)
    if not after_error < before_error:
        return unchanged(
            'canonical_residual_not_improved',
            canonicalResidualBeforeMeters=before_error,
            canonicalResidualAfterMeters=after_error,
            maximumPinErrorMeters=maximum_pin_error,
        )

    direction_changes = []
    for index, name in enumerate(names):
        old_length = old_lengths[index]
        if old_length <= 1e-14:
            continue
        cosine = float(np.clip(
            np.dot(offsets[index], proposal_offsets[index]) / (old_length * old_length),
            -1.0, 1.0))
        angle = float(np.degrees(np.arccos(cosine)))
        if angle > 1e-8:
            direction_changes.append({'joint': name, 'angleDegrees': angle})

    return proposed_coordinates, proposal_offsets, {
        'applied': True,
        'reason': 'canonical_rig_initialization_improved',
        'canonicalResidualBeforeMeters': before_error,
        'canonicalResidualAfterMeters': after_error,
        'canonicalResidualImprovementMeters': before_error - after_error,
        'pinnedJointCount': int(np.count_nonzero(pinned)),
        'maximumPinErrorMeters': maximum_pin_error,
        'maximumBoneLengthErrorMeters': maximum_bone_length_error,
        'maximumOffsetDirectionChangeDegrees': max(
            (item['angleDegrees'] for item in direction_changes), default=0.0),
        'offsetDirectionChanges': direction_changes,
        'maximumRootTranslationMeters': float(
            np.max(np.linalg.norm(root_shifts, axis=-1), initial=0.0)),
        'authoritativeSides': authority,
    }


def _canonical_reference(points, names, execution, authority):
    from .controlled_motion import canonical_bilateral_reference

    return canonical_bilateral_reference(
        points, names, execution, authoritative_sides=authority)


def _maximum_canonical_residual(points, names, execution, authority):
    target = _canonical_reference(points, names, execution, authority)
    return float(np.max(np.linalg.norm(np.asarray(points) - target, axis=-1), initial=0.0))

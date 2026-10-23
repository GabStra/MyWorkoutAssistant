"""Default final-bake fixed-rig trajectory fit; legacy output remains available."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from copy import deepcopy
from functools import partial
from time import monotonic
from types import SimpleNamespace
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import brentq, least_squares
from scipy.optimize._numdiff import approx_derivative, group_columns
from scipy.sparse import coo_matrix, csr_matrix, eye, kron, lil_matrix, vstack
from scipy.spatial.transform import Rotation

from .sequence_stabilization import contact_mask, frame_basis, pose_digest, unit
from .contact_constraints import (
    _airborne_epoch_track,
    _airborne_scoped_anchor_id,
    observed_ground_contact_mask,
    vertical_only_contact_mask,
    vertical_only_contact_targets,
)
from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
from .physical_validation import ARTICULATIONS, angles, body_scale, collision_clearances, collision_specs, validate_physical_motion, anatomical_structure_residuals
from .temporal_quality import (
    body_orientation_axes, body_orientation_noise, body_local_head_direction,
    introduced_joint_spikes, refresh_motion_bounds,
    third_difference_jerk_failure_evidence, transport_corrected_bone_sides,
)
from .motion_placement import contact_consistent_target, root_motion_quality, register_contact_placement, align_registered_contacts_above_floor
from .rig_interpolation import INTERPOLATION
from .rig_playback import (
    PLAYBACK_CONTACT_LIMIT_METERS,
    PLAYBACK_FLOOR_LIMIT_METERS,
    playback_reference_samples,
)

KEYFRAME_CONTACT_LIMIT_METERS = .0005
ROOT_TRAVEL_PRESERVATION_TOLERANCE_METERS = .001
ROOT_TRAVEL_MINIMUM_PRESERVED_RATIO = .9
ROOT_TRAVEL_SMALL_MOTION_BODY_RATIO = .05
ROOT_TRAVEL_FIT_WEIGHT = 2000.


def contact_iterate_is_feasible(keyframe_error, playback_error, floor_penetration,
                               *, maximum_anatomy_residual=0.):
    """Preserve contact-feasible iterates without introducing structural damage."""
    return (keyframe_error < KEYFRAME_CONTACT_LIMIT_METERS
            and playback_error < PLAYBACK_CONTACT_LIMIT_METERS
            and floor_penetration <= PLAYBACK_FLOOR_LIMIT_METERS
            and maximum_anatomy_residual <= 1e-6)


def contact_iterate_is_preferred(candidate_cost, candidate_heel_passed,
                                 best_cost, best_heel_passed):
    """Rank contact-feasible iterates by heel acceptance before soft cost."""
    if candidate_heel_passed != best_heel_passed:
        return candidate_heel_passed
    return candidate_cost < best_cost


def contact_iterate_can_challenge_best(candidate_cost, best_cost, *, has_best,
                                       heel_evidence_required, best_heel_passed):
    """Admit any feasible candidate that can improve heel quality or cost."""
    return (not has_best
            or (heel_evidence_required and not best_heel_passed)
            or candidate_cost < best_cost)


def fit_anatomy_constraint_reference(source_reference, support_corrected_reference=None):
    """Choose the same anatomy reference the final fixed-rig gate will use."""
    if support_corrected_reference is None:
        return source_reference
    source = np.asarray(source_reference, dtype=float)
    supported = np.asarray(support_corrected_reference, dtype=float)
    if source.shape != supported.shape or not np.isfinite(supported).all():
        raise ValueError('support-corrected anatomy reference is incompatible')
    return supported


def support_initialization_articulation_regressions(
        reference, candidate, names, *, fps=30., ankle_excursion_masks=None,
        ankle_evidence_masks=None):
    """Reject support initialization that changes observed leg or foot articulation."""
    source = np.asarray(reference, dtype=float)
    corrected = np.asarray(candidate, dtype=float)
    if source.shape != corrected.shape or source.ndim != 3 or source.shape[1:] != (len(names), 3):
        return [{'feature': 'shape', 'reason': 'incompatible_support_articulation'}]
    if not np.isfinite(source).all() or not np.isfinite(corrected).all():
        return [{'feature': 'coordinates', 'reason': 'nonfinite_support_articulation'}]

    regressions = []
    for label, a, b, c, tolerance in ARTICULATIONS:
        if not label.endswith(('_knee', '_ankle')) or not {a, b, c}.issubset(names):
            continue
        indices = [names.index(joint) for joint in (a, b, c)]
        delta = np.abs(angles(*(corrected[:, index] for index in indices))
                       - angles(*(source[:, index] for index in indices)))
        percentile = float(np.percentile(np.rad2deg(delta), 95))
        if percentile > tolerance:
            regressions.append({
                'feature': label, 'p95ChangeDegrees': percentile,
                'toleranceDegrees': float(tolerance),
            })
        source_angles = angles(*(source[:, index] for index in indices))
        corrected_angles = angles(*(corrected[:, index] for index in indices))
        side = label.split('_', 1)[0]
        episode_mask = (ankle_excursion_masks or {}).get(side) if label.endswith('_ankle') else None
        if episode_mask is not None:
            episode_mask = np.asarray(episode_mask, dtype=bool)
            evidence_mask = np.asarray(
                (ankle_evidence_masks or {}).get(side, np.ones(len(source), dtype=bool)),
                dtype=bool)
            if episode_mask.shape != (len(source),):
                regressions.append({
                    'feature': f'{label}_excursion',
                    'reason': 'incompatible_full_sole_excursion_mask',
                })
                continue
            if evidence_mask.shape != (len(source),):
                regressions.append({
                    'feature': f'{label}_excursion',
                    'reason': 'incompatible_source_evidence_mask',
                })
                continue
            for authority, intervals in (
                    ('full_sole', episode_mask & evidence_mask),
                    ('raw_contact_state', ~episode_mask & evidence_mask)):
                edges = np.diff(np.r_[False, intervals, False].astype(np.int8))
                for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                    source_range = float(np.ptp(source_angles[start:stop]))
                    if source_range <= np.deg2rad(20.):
                        continue
                    range_ratio = float(np.ptp(corrected_angles[start:stop]) / source_range)
                    if not support_joint_range_preserved({label: range_ratio}):
                        regressions.append({
                            'feature': f'{label}_{authority}_episode_excursion',
                            'startFrame': int(start), 'endFrame': int(stop - 1),
                            'preservedRatio': range_ratio,
                            'minimumPreservedRatio': .85,
                        })
        else:
            source_range = float(np.ptp(source_angles))
            if source_range > np.deg2rad(20.):
                range_ratio = float(np.ptp(corrected_angles) / source_range)
                if not support_joint_range_preserved({label: range_ratio}):
                    regressions.append({
                        'feature': f'{label}_excursion',
                        'preservedRatio': range_ratio,
                        'minimumPreservedRatio': .85,
                    })

    from .physical_validation import hinge_direction_events
    regressions.extend(
        {**event, 'feature': event['joint'] + '_bend_direction'}
        for event in hinge_direction_events(corrected, names, source, fps=fps)
        if event['joint'].endswith('_knee'))

    # Compare foot direction in each pose's pelvis basis so a rigid scene
    # rotation does not look like lost ankle or heel articulation.
    from .temporal_quality import body_orientation_axes
    for side in ('left', 'right'):
        ankle, foot = f'{side}_ankle', f'{side}_foot'
        if ankle not in names or foot not in names:
            continue
        orientation_tolerance = next(
            tolerance for label, _, _, _, tolerance in ARTICULATIONS
            if label == f'{side}_ankle')
        source_vector = source[:, names.index(foot)] - source[:, names.index(ankle)]
        corrected_vector = corrected[:, names.index(foot)] - corrected[:, names.index(ankle)]
        source_axes = body_orientation_axes(source, names)
        corrected_axes = body_orientation_axes(corrected, names)
        if source_axes.shape != corrected_axes.shape or source_axes.shape[1] < 2:
            continue
        source_basis = frame_basis(source_axes[:, 1], source_axes[:, 0])
        corrected_basis = frame_basis(corrected_axes[:, 1], corrected_axes[:, 0])
        source_local = np.einsum('fji,fj->fi', source_basis, source_vector)
        corrected_local = np.einsum('fji,fj->fi', corrected_basis, corrected_vector)
        source_heading = np.arctan2(source_local[:, 2], source_local[:, 0])
        corrected_heading = np.arctan2(corrected_local[:, 2], corrected_local[:, 0])
        heading_delta = np.abs(np.arctan2(
            np.sin(corrected_heading - source_heading),
            np.cos(corrected_heading - source_heading)))
        heading_p95 = float(np.percentile(np.rad2deg(heading_delta), 95))
        if heading_p95 > orientation_tolerance:
            regressions.append({
                'feature': f'{side}_foot_heading', 'p95ChangeDegrees': heading_p95,
                'toleranceDegrees': float(orientation_tolerance),
            })
        source_pitch = np.arctan2(source_local[:, 1], np.linalg.norm(source_local[:, [0, 2]], axis=1))
        corrected_pitch = np.arctan2(corrected_local[:, 1], np.linalg.norm(corrected_local[:, [0, 2]], axis=1))
        pitch_p95 = float(np.percentile(np.rad2deg(np.abs(corrected_pitch - source_pitch)), 95))
        if pitch_p95 > orientation_tolerance:
            regressions.append({
                'feature': f'{side}_heel_pitch', 'p95ChangeDegrees': pitch_p95,
                'toleranceDegrees': float(orientation_tolerance),
            })
    return regressions


SUPPORT_REFERENCE_CONTACT_LIMIT_METERS = min(
    0.001,
    PLAYBACK_CONTACT_LIMIT_METERS * 0.5,
)

CONTROLLED_MOTION_STRATEGY = 'fixed_rig_controlled_motion_v116_native_clock_target'
# Feasibility pre-flight threshold, calibrated from fit reports: every
# successful fit's target bones matched the rig within ~0.002m, while
# structurally conflicted fits measured 0.05-0.15m before burning their
# whole budget on an unsolvable problem.
FIT_INPUT_MAX_TARGET_BONE_MISMATCH_METERS = 0.04
# Soft temporal penalties compete with pose/contact fitting. Target below the
# acceptance boundary so a finite solver budget does not settle just outside it.
TEMPORAL_FIT_TARGET_RATIO = .8
CONTACT_FIT_WEIGHT = 10. / (.8 * PLAYBACK_CONTACT_LIMIT_METERS)
FLOOR_FIT_WEIGHT = 10. / (.8 * PLAYBACK_FLOOR_LIMIT_METERS)
# Leave clearance in the proposal; do not optimize against the validator's
# permitted penetration boundary at interpolated frames.
COLLISION_FIT_MARGIN_RATIO = .0025
ANATOMY_FIT_MARGIN = .0001
ANATOMY_FIT_WEIGHT = 10000.


def fit_anatomy_structure_residuals(points, names, reference):
    """Return the solver's anatomy rows using its selected hard-gate reference."""
    return anatomical_structure_residuals(
        points, names, pose_only=True, margin=ANATOMY_FIT_MARGIN,
        reference=reference)[0]


# Keep pre-solve stages from consuming the whole candidate fit budget, while
# still allowing hard anatomy/support repairs enough wall-clock to finish well.
ANATOMY_REPAIR_TIME_FRACTION = .35
ANATOMY_REPAIR_MIN_SECONDS = 75.
SUPPORT_INIT_TIME_FRACTION = .3
SUPPORT_INIT_MIN_SECONDS = 60.
# Support placement is calibrated per trajectory; each crop keeps its own poses.
SUPPORT_INIT_COLD_EVALUATIONS = 80

# Candidate-session fits below this remaining window cannot converge (measured
# converge times: ~113s for an easy clip, 160-360s budgets for typical ones),
# so starting one only burns wall time and labels the variant with a garbage
# fit. Mirrors the wave pipeline's MIN_USEFUL_CANDIDATE_FIT_REMAINING_SECONDS.
MIN_USEFUL_FIT_SECONDS = 30.
# Retained-interval validation took ~80s on a failed cyclic repair; reserve
# headroom for that validation before allowing a minimum useful solve window.
RETAINED_INTERVAL_VALIDATION_RESERVE_SECONDS = 90.
SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS = 110.
# In a saved 50-case cycle-anatomy audit, no retained fit applied at or above
# this boundary; all seven applied recoveries were below it (closest: 0.1875).
# This measures the reconstructed frame payload, not visual source-video evidence.
# Use it only after cycle fits themselves have failed the anatomy gate.
SOURCE_SPINE_FOLD_RETAINED_FIT_SKIP_FRAME_RATIO = 0.20
# Cold support LS on retained long cycles: ~0.015s per (frame × eval).
# 129 frames × 80 evals ≈ 146s; a flat 90s stage cap aborted finishable work.
SUPPORT_INIT_SECONDS_PER_FRAME_EVAL = .015
SUPPORT_INIT_SOLVE_RESERVE_FRACTION = .25
SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS = 30.
HEAD_ARTICULATION_FIT_WEIGHT = 1000.
# Under required support, contact residuals are ~50× articulation at weight 500;
# raise the soft hinge/head floors so LS cannot invent repair_articulation_distortion.
SUPPORT_ARTICULATION_FIT_WEIGHT = 8000.
SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT = 5000.
# End-of-budget polish window so Stage-B seam work is not starved by anatomy/support mins.
POLISH_RESERVE_FRACTION = .18
POLISH_RESERVE_MAX_SECONDS = 25.
POLISH_RESERVE_MIN_SECONDS = 12.
SOURCE_PROJECTION_FIT_WEIGHT = 2.0
# Native toe-only phase is direct source evidence; keep its fit row at the
# existing hard articulation scale while relaxing only the local 3D phase prior.
SOURCE_FOOT_PHASE_FIT_WEIGHT = 500.0
SOURCE_SUPPORT_RELATIVE_FIT_MULTIPLIER = 6.0
SOURCE_SUPPORT_RELATIVE_MIN_CONFIDENCE = .35
SOURCE_SUPPORT_RELATIVE_MIN_OBSERVATIONS = 3
SOURCE_SUPPORT_RELATIVE_MAX_RMS_BODY_RATIO = .12
# Treat suppression beyond half of a materially visible source excursion as a
# fit failure; movement below 8% of pelvis-to-support image distance is not
# distinguishable from small pose-estimation drift for this gate.
SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_RATIO = .5
SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_DISTANCE_RATIO = .08
SOURCE_CYCLE_BOUNDARY_FIT_MULTIPLIER = 2.0
SOURCE_CYCLE_BOUNDARY_MIN_EFFECTIVE_OBSERVATIONS = 3
SOURCE_ENDPOINT_POSTURE_FIT_MULTIPLIER = 1.5
SOURCE_ENDPOINT_POSTURE_MIN_WINDOW_SECONDS = 0.05
SOURCE_ENDPOINT_POSTURE_MAX_WINDOW_SECONDS = 0.2
REQUIRED_FIT_CHECKS = ('anatomy', 'contacts', 'sourceArticulation', 'trajectoryFit',
                       'rootTravel', 'jointRange', 'jointShake', 'settling', 'jerk',
                       'fixedRig', 'playback', 'relativeJointShake', 'bodyRotation', 'rootContinuity', 'equipment', 'motionDiscontinuity', 'bodySupport', 'supportAlignment', 'sourceSupportTrajectory')


def _hermite_probe_collision_cursors(neighbors, *, probe_period=4):
    """Find stencils where one modulo probe class names distinct frames."""
    collisions = np.zeros(len(neighbors), dtype=bool)
    for cursor_index, stencil_frames in enumerate(neighbors):
        seen_by_class: dict[int, int] = {}
        for frame in stencil_frames:
            frame = int(frame)
            probe_class = frame % probe_period
            previous_frame = seen_by_class.setdefault(probe_class, frame)
            if previous_frame != frame:
                collisions[cursor_index] = True
                break
    return collisions


def controlled_fit_processing_incomplete(report):
    """A deadline is missing processing evidence, not a failed geometry check."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if report.get('termination') in EVIDENCE_TERMINATIONS:
        return False
    if (report.get('boundedRefinement') or {}).get('stopReason') in EVIDENCE_TERMINATIONS:
        return False
    # A validated reject is decisive even when the soft LS hit its phase budget.
    if report.get('reason') == 'fit_validation_failed' and report.get('checks'):
        return False
    if report.get('reason') in {
            'loop_requires_cycle_repair', 'playback_validation_failed'} and report.get('checks'):
        return False
    if report.get('optimizerTermination') == 'objective_stalled' and report.get('checks'):
        return False
    checks = report.get('checks')
    # Finished acceptance with at least one failed check is a decisive reject.
    # Do not keep retrying just because the soft LS watchdog fired.
    if isinstance(checks, dict) and checks and any(value is False for value in checks.values()):
        return False
    return (report.get('reason') in {
                'fit_timeout', 'fit_evaluation_limit',
                'retained_interval_skipped_insufficient_validation_budget',
                'source_cycle_parent_phase_coverage_unresolved',
            }
            or report.get('optimizerTermination') in {'time_budget', 'evaluation_limit'}) or any(
        controlled_fit_processing_incomplete(attempt.get('fitReport', attempt))
        for attempt in report.get('cycleSelectionAttempts', [])
    )


def trajectory_fit_evidence(
        candidate, target, names, scale, *, root_index, pinned,
        support_evidence, source_projection_constraint, source_camera):
    """Choose placement-invariant fit evidence only with observed anchors and camera authority.

    Absolute XYZ RMS remains the compatibility fallback and is always reported.
    When retained camera projection, bilateral mapping, and genuine observed
    ground anchors establish the placement authority, root travel and free
    articulation are compared independently without recentering either track.
    """
    candidate = np.asarray(candidate, dtype=float)
    target = np.asarray(target, dtype=float)
    pinned = np.asarray(pinned, dtype=bool)
    limit = .025 * float(scale)
    compatible = (
        candidate.shape == target.shape
        and candidate.ndim == 3
        and candidate.shape[1:] == (len(names), 3)
        and pinned.shape == candidate.shape[:2]
        and 0 <= int(root_index) < len(names)
        and len(candidate) > 0
    )
    if not compatible:
        return {
            'policy': 'absolute_xyz_rms_v1', 'eligible': False,
            'eligibilityReasons': ['incompatible_fit_geometry'],
            'absoluteRmsMeters': float('inf'), 'limitMeters': limit,
            'rootDisplacementRmsMeters': None,
            'freeRelativeArticulationRmsMeters': None,
            'freeJointCoverage': {'frameCount': 0, 'coveredFrameCount': 0,
                                  'coverageRatio': 0., 'minimumFreeJointCountPerFrame': 0,
                                  'freeSampleCount': 0},
            'observedGroundAnchorSampleCount': 0,
            'passed': False,
            'finalSourceCameraPoseFidelityRequired': False,
        }

    absolute_rms = float(np.sqrt(np.mean((candidate - target) ** 2)))
    free_mask = ~pinned.copy()
    free_mask[:, int(root_index)] = False
    free_per_frame = np.count_nonzero(free_mask, axis=1)
    covered_frames = int(np.count_nonzero(free_per_frame > 0))
    free_samples = int(np.count_nonzero(free_mask))
    coverage = {
        'frameCount': int(len(candidate)),
        'coveredFrameCount': covered_frames,
        'coverageRatio': float(covered_frames / len(candidate)),
        'minimumFreeJointCountPerFrame': int(free_per_frame.min()),
        'freeSampleCount': free_samples,
    }
    root_error = ((candidate[:, int(root_index)] - candidate[0, int(root_index)])
                  - (target[:, int(root_index)] - target[0, int(root_index)]))
    root_displacement_rms = float(np.sqrt(np.mean(root_error ** 2)))
    relative_error = ((candidate - candidate[:, int(root_index):int(root_index)+1])
                      - (target - target[:, int(root_index):int(root_index)+1]))
    free_relative_rms = (float(np.sqrt(np.mean(relative_error[free_mask] ** 2)))
                         if free_samples else None)
    observed_ground = observed_ground_contact_mask(
        support_evidence, names, len(candidate)) & pinned
    anchor_sample_count = int(np.count_nonzero(observed_ground))

    mapping = source_projection_constraint.get('sourceFootRaySideMapping') or {}
    bilateral_assignment = (source_camera or {}).get('bilateralAssignment')
    expected_mapping = ({'left': 'right', 'right': 'left'}
                        if bilateral_assignment == 'swapped'
                        else {'left': 'left', 'right': 'right'})
    mapping_resolved = (
        bilateral_assignment in {'identity', 'swapped'}
        and mapping == expected_mapping
    )
    reasons = []
    if (source_projection_constraint.get('available') is not True
            or source_projection_constraint.get('cameraAuthority')
            != 'retained_source_correction_camera'):
        reasons.append('retained_source_camera_authority_unavailable')
    if not mapping_resolved:
        reasons.append('source_to_motion_side_mapping_unresolved')
    if anchor_sample_count == 0:
        reasons.append('observed_ground_contact_anchor_unavailable')
    if covered_frames != len(candidate):
        reasons.append('free_joint_coverage_incomplete')
    eligible = not reasons
    passed = (
        root_displacement_rms < limit and free_relative_rms is not None
        and free_relative_rms < limit
        if eligible else absolute_rms < limit
    )
    return {
        'policy': ('observed_anchor_root_and_free_relative_rms_v1'
                   if eligible else 'absolute_xyz_rms_v1'),
        'eligible': bool(eligible),
        'eligibilityReasons': reasons,
        'absoluteRmsMeters': absolute_rms,
        'limitMeters': limit,
        'rootDisplacementRmsMeters': root_displacement_rms,
        'freeRelativeArticulationRmsMeters': free_relative_rms,
        'freeJointCoverage': coverage,
        'observedGroundAnchorSampleCount': anchor_sample_count,
        'sourceCameraAuthority': source_projection_constraint.get('cameraAuthority'),
        'bilateralAssignment': bilateral_assignment,
        'sourceToMotionSideMapping': mapping,
        'finalSourceCameraPoseFidelityRequired': bool(eligible),
        'passed': bool(passed),
    }


def hard_trajectory_and_root_failure(checks):
    """True when both hard geometric acceptance checks already failed."""
    if not isinstance(checks, dict) or not checks:
        return False
    return checks.get('trajectoryFit') is False and checks.get('rootTravel') is False


def repeated_unreachable_support_conflict(attempts):
    """Detect a repeated hard support conflict before spending another crop fit."""
    if not isinstance(attempts, list) or len(attempts) < 2:
        return False
    previous = attempts[-2].get('fitReport') if isinstance(attempts[-2], dict) else None
    current = attempts[-1].get('fitReport') if isinstance(attempts[-1], dict) else None
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    termination = current.get('termination') or current.get('optimizerTermination')
    if termination != 'unreachable_conflict':
        termination = (current.get('boundedRefinement') or {}).get('stopReason')
    if termination != 'unreachable_conflict':
        return False
    previous_checks = previous.get('checks')
    current_checks = current.get('checks')
    if not isinstance(previous_checks, dict) or not isinstance(current_checks, dict):
        return False
    persistent_support_conflicts = ('anatomy', 'contacts', 'bodySupport')
    return all(
        previous_checks.get(name) is False and current_checks.get(name) is False
        for name in persistent_support_conflicts
    )


def cycle_selection_overlap_ratio(left, right):
    """Return frame-range overlap divided by union for two cycle proposals."""
    def interval(selection):
        if not isinstance(selection, dict):
            return None
        start = selection.get('startFrame')
        stop = selection.get('stopFrameExclusive')
        if not isinstance(start, int) or not isinstance(stop, int) or stop <= start:
            return None
        return start, stop

    left_interval, right_interval = interval(left), interval(right)
    if left_interval is None or right_interval is None:
        return 0.0
    intersection = max(
        0,
        min(left_interval[1], right_interval[1])
        - max(left_interval[0], right_interval[0]),
    )
    union = max(left_interval[1], right_interval[1]) - min(
        left_interval[0], right_interval[0]
    )
    return intersection / max(union, 1)


def repeated_unreachable_root_travel(attempts, remaining_choices):
    """Skip near-identical cycle fits after repeated independent root-travel failure."""
    if not isinstance(attempts, list) or len(attempts) < 2 or not remaining_choices:
        return False
    previous, current = attempts[-2:]
    for attempt in (previous, current):
        checks = attempt.get('checks') if isinstance(attempt, dict) else None
        selection = attempt.get('selection') if isinstance(attempt, dict) else None
        if (
            not isinstance(checks, dict)
            or checks.get('rootTravel') is not False
            or checks.get('trajectoryFit') is not True
            or not isinstance(selection, dict)
        ):
            return False
    first, second = previous['selection'], current['selection']
    if cycle_selection_overlap_ratio(first, second) < 0.90:
        return False
    return all(
        max(
            cycle_selection_overlap_ratio(choice, first),
            cycle_selection_overlap_ratio(choice, second),
        ) >= 0.90
        for choice in remaining_choices
    )


def repeated_anatomical_cycle_failure(attempts, remaining_choices):
    """Skip a near-duplicate cycle family after repeated same-anatomy failure."""
    if not isinstance(attempts, list) or len(attempts) < 2 or not remaining_choices:
        return False
    previous, current = attempts[-2:]
    selections = [attempt.get('selection') for attempt in (previous, current)
                  if isinstance(attempt, dict)]
    reports = [attempt.get('fitReport') for attempt in (previous, current)
               if isinstance(attempt, dict)]
    if len(selections) != 2 or len(reports) != 2:
        return False
    if any(not isinstance(report, dict) for report in reports):
        return False
    if any(
        not isinstance(attempt.get('checks'), dict)
        or attempt['checks'].get('anatomy') is not False
        for attempt in (previous, current)
    ):
        return False
    physical_reasons = [
        {
            str(reason)
            for reason in report.get('physicalReasons', [])
            if str(reason).startswith('anatomy_')
        }
        for report in reports
    ]
    if not physical_reasons[0] & physical_reasons[1]:
        return False
    first, second = selections
    if cycle_selection_overlap_ratio(first, second) < 0.90:
        return False
    # Keep less-overlapping alternatives available. The 0.85 bound is used
    # only after two very similar candidates failed the same physical check.
    return all(
        min(
            cycle_selection_overlap_ratio(choice, first),
            cycle_selection_overlap_ratio(choice, second),
        ) >= 0.85
        for choice in remaining_choices
    )


def source_spine_fold_frame_ratio(payload):
    """Measure spine-fold anatomy on reconstructed frames, not the source video."""
    frames = payload.get('frames') if isinstance(payload, dict) else None
    names = payload.get('jointNames') if isinstance(payload, dict) else None
    if not isinstance(frames, list) or not frames or not isinstance(names, list) or not names:
        return None
    try:
        points = np.asarray(
            [[frame['joints'][name] for name in names] for frame in frames],
            dtype=float,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if points.ndim != 3 or not np.isfinite(points).all():
        return None
    residuals, labels = anatomical_structure_residuals(points, names)
    spine_fold_columns = [
        index for index, label in enumerate(labels)
        if str(label).startswith('anatomy_spine_fold:')
    ]
    if not spine_fold_columns:
        return None
    violating_frames = np.any(residuals[:, spine_fold_columns] > 1e-6, axis=1)
    return float(np.mean(violating_frames))


def failed_check_names(checks):
    if not isinstance(checks, dict):
        return []
    return [key for key, passed in checks.items() if not passed]


def deferred_fit_update_ready(report, remaining_seconds):
    deferred = report.get('deferredStageCOptimizerBlock') or {}
    return (
        report.get('optimizerTermination') == 'solve_phase_budget'
        and (report.get('boundedRefinement') or {}).get(
            'fitUpdateDeferredToEvaluationContinuation') is True
        and deferred.get('reason') == 'deferred_to_outer_fit_continuation'
        and remaining_seconds >= 5. + float(deferred.get('minimumUpdateSeconds', float('inf')))
    )


def fit_report_improves_acceptance(previous_report, trial_report):
    """Keep a continuation only when it passes or strictly reduces failures."""
    if not isinstance(trial_report, dict):
        return False
    if trial_report.get('applied'):
        return True
    if not isinstance(previous_report, dict):
        return False
    previous_checks = previous_report.get('checks')
    trial_checks = trial_report.get('checks')
    if not isinstance(previous_checks, dict) or not previous_checks:
        return False
    if not isinstance(trial_checks, dict) or not trial_checks:
        return False
    return set(failed_check_names(trial_checks)) < set(failed_check_names(previous_checks))


def bounded_anatomy_projection_eligible(
    failed_checks: set[str],
    checks: dict,
    *,
    repairable_anatomy: bool,
    cyclic: bool,
) -> bool:
    """Gate a short anatomy projection on every independent structural check."""
    allowed_failures = {
        'anatomy', 'playback', 'motionDiscontinuity', 'jerk',
        'jointShake', 'relativeJointShake', 'settling', 'loopSeam',
    }
    if (
        not repairable_anatomy
        or 'anatomy' not in failed_checks
        or not failed_checks <= allowed_failures
    ):
        return False

    structural_gates = {
        'contacts', 'heightOnlyContacts', 'sourceArticulation', 'trajectoryFit',
        'rootTravel', 'jointRange', 'fixedRig', 'bodySupport', 'supportAlignment',
        'rootContinuity', 'equipment', 'bodyRotation',
    }
    if not all(checks.get(name) is True for name in structural_gates):
        return False
    # A bounded anatomy projection can reduce anatomy first on a cyclic near-
    # miss, then let Stage B repair the seam. Keep the seam gate present and
    # strictly validate every projected candidate before retaining it.
    return (
        not cyclic
        or checks.get('loopSeam') is True
        or ('loopSeam' in failed_checks and checks.get('loopSeam') is False)
    )


def support_reference_grossly_invalid(report, *, tolerance_multiplier=5.):
    """Identify timed-out support references far beyond repair tolerance."""
    geometry = report.get('supportReferenceGeometry', {})
    tolerance = float(geometry.get('toleranceMeters', 0.) or 0.)
    if tolerance <= 0.:
        return False
    if (float(geometry.get('maximumStationaryJointRangeMeters', 0.) or 0.)
            > tolerance * tolerance_multiplier
            or float(geometry.get('maximumSurfaceErrorMeters', 0.) or 0.)
            > tolerance * tolerance_multiplier):
        return True
    contacts = report.get('supportReferenceContacts', {})
    contact_tolerance = .0005
    return float(contacts.get('maximumErrorMeters', 0.) or 0.) > contact_tolerance * tolerance_multiplier


def support_reference_contacts_pass(maximum_error_meters):
    """Allow a near-miss initializer to reach the strict trajectory fit.

    The supported reference only seeds the solver. Final keyframe and playback
    contact checks remain stricter than this initializer tolerance.
    """
    return float(maximum_error_meters or 0.) < SUPPORT_REFERENCE_CONTACT_LIMIT_METERS


def supported_reference_projection_metrics(
    points,
    *,
    payload,
    names,
    alignment_reference,
    anatomy_reference,
    body_support,
    equipment,
    pinned,
    contact_targets,
):
    """Keep local support projections only when every seed-reference gate holds."""
    from .anatomical_repair import repair_residuals
    from .equipment_constraints import validate_grip
    from .support_alignment import validate_alignment
    from .support_geometry import validate_support_geometry

    errors, labels = repair_residuals(points, names, reference=anatomy_reference)
    failed_features = np.max(errors, axis=0) > 1e-6
    anatomy = {
        'passed': not bool(np.any(failed_features)),
        'violations': [labels[index] for index in np.flatnonzero(failed_features)],
        'residualByViolation': {
            labels[index]: float(np.max(errors[:, index]))
            for index in np.flatnonzero(failed_features)},
    }
    geometry = validate_support_geometry(payload, points, names)
    alignment = validate_alignment(points, alignment_reference, names, body_support)
    grip = validate_grip(points, names, equipment)
    contact_error = float(np.max(
        np.linalg.norm((points - contact_targets)[pinned], axis=-1), initial=0.))
    contacts = {
        'passed': support_reference_contacts_pass(contact_error),
        'maximumErrorMeters': contact_error,
        'toleranceMeters': SUPPORT_REFERENCE_CONTACT_LIMIT_METERS,
    }
    rejection_reasons = []
    if not anatomy['passed']:
        rejection_reasons.append('support_reference_anatomy_invalid')
    if not geometry['passed']:
        rejection_reasons.extend(geometry.get('rejectionReasons') or ['support_reference_geometry_invalid'])
    if not alignment['passed']:
        rejection_reasons.append(alignment.get('reason') or 'support_alignment_invalid')
    if not grip['passed']:
        rejection_reasons.append('support_equipment_invalid')
    if not contacts['passed']:
        rejection_reasons.append('support_reference_contacts_invalid')
    return {
        'passed': not rejection_reasons,
        'rejectionReasons': list(dict.fromkeys(rejection_reasons)),
        'anatomy': anatomy,
        'geometry': geometry,
        'alignment': alignment,
        'equipment': grip,
        'contacts': contacts,
    }


def support_reference_can_be_polished(report):
    """Return whether support geometry provides a sound frame for local repair.

    Equipment spacing is repaired independently after root continuity. Letting
    an initial grip miss suppress anatomy/contact polish can make the subsequent
    root-continuity gate reject before the grip projector gets a chance to run.
    """
    return all(
        isinstance(report.get(key), dict) and report[key].get('passed') is True
        for key in ('supportReferenceGeometry', 'supportReferenceAlignment')
    )


def support_reference_equipment_can_be_deferred(report, strategy):
    """Defer only the grip gate for a joint-plant seed with all support gates sound."""
    if strategy != 'bounded_joint_root_and_closed_chain_legs':
        return False
    equipment = report.get('supportReferenceEquipment')
    if not isinstance(equipment, dict) or equipment.get('passed') is not False:
        return False
    return all(
        isinstance(report.get(key), dict) and report[key].get('passed') is True
        for key in ('supportReferenceGeometry', 'supportReferenceAlignment',
                    'supportReferenceAnatomy', 'supportReferenceContacts')
    )


POLISH_STAGE_A = frozenset({'contacts', 'equipment', 'bodySupport', 'supportAlignment'})
POLISH_STAGE_B = frozenset({'playback', 'loopSeam'})
POLISH_STAGE_C = frozenset({
    'jerk', 'jointShake', 'relativeJointShake', 'settling',
    'rootContinuity', 'rootTravel', 'motionDiscontinuity', 'sourceSupportTrajectory',
    'sourceFootContactArticulation',
})
# Stage-A soft LS otherwise loses to seam/temporal terms on supported cycles.
STAGE_A_CONTACT_POLISH_WEIGHT = 8.
# Stage A used to raise contact weight even for equipment-only failures, which
# made an already-clear plant mask dominate the grip term. Boost grip instead.
STAGE_A_EQUIPMENT_POLISH_WEIGHT = 8.
# Soft grip weight; raised when the working reference already misses rigid_pair.
GRIP_FIT_WEIGHT = 5000.
GRIP_FIT_WEIGHT_WHEN_REFERENCE_FAILS = 40000.


def polish_stage_for_failures(failed_checks):
    """Ordered polish focus: contacts → trajectory/temporal → seam."""
    failed = set(failed_checks or [])
    if failed & POLISH_STAGE_A:
        return 'A'
    if failed & POLISH_STAGE_C:
        return 'C'
    # Interpolated playback without a wrap gap is a between-frame path issue,
    # not a seam. Stage-B wrap projection cannot close it.
    if failed <= {'playback'}:
        return 'C'
    if failed & POLISH_STAGE_B:
        return 'B'
    return 'A'


def polishable_near_miss(failed_checks):
    """Failures that leftover outer time should keep polishing."""
    failed = set(failed_checks or [])
    if failed == {'rootTravel'}:
        # A bounded trajectory polish is attempted in Stage C, but repeating
        # identical root-travel-only solves cannot change the source candidate.
        return False
    return bool(failed) and failed <= (POLISH_STAGE_A | POLISH_STAGE_B | POLISH_STAGE_C)


def prioritize_fit_before_broad_temporal_smoothing(
    failed_checks,
    *,
    playback_passed,
    contact_error_meters,
    playback_path_repair_attempted=False,
):
    """Give the source-constrained Stage-C solve a chance before smoothing.

    Absolute-coordinate smoothing can consume the reserved Stage-C window and
    alter source motion before the fit objective gets another chance to reduce
    jerk. Defer broad smoothing when only jerk remains, or when a measured path
    repair has already run and only jerk plus playback remain with clear pins.
    """
    failed = set(failed_checks or ())
    contact_error = float(contact_error_meters or 0.)
    if ('sourceFootContactArticulation' in failed
            and bool(playback_passed)
            and contact_error < 0.0005):
        return True
    if failed == {'jerk'}:
        return bool(playback_passed) and contact_error < 0.0005
    return (
        failed == {'jerk', 'playback'}
        and bool(playback_path_repair_attempted)
        and contact_error < 0.0005
    )


def stage_fit_refinement_budget(
    remaining_seconds,
    *,
    stage,
    minimum_update_seconds,
    prioritize_fit,
):
    """Return a bounded polish window that can afford one measured fit update."""
    remaining = max(0.0, float(remaining_seconds))
    default_budget = min(remaining - 0.5, max(5.0, remaining * {
        'A': 0.40, 'B': 0.35, 'C': 0.30,
    }.get(stage, 0.35)))
    if minimum_update_seconds <= 0:
        return default_budget

    required_budget = stage_fit_refinement_minimum_remaining_seconds(
        minimum_update_seconds, stage=stage,
        prioritize_fit=prioritize_fit,
    ) - 0.5
    available_budget = max(0.0, remaining - 0.5)
    if required_budget > available_budget:
        return None
    return min(available_budget, max(default_budget, required_budget))


def stage_fit_refinement_minimum_remaining_seconds(
        minimum_update_seconds, *, stage, prioritize_fit):
    """Smallest remaining window the bounded fitter will admit for a measured update."""
    if minimum_update_seconds <= 0:
        return 0.0
    # The stage budget reserves an extra half second outside its returned
    # block budget; include it here so outer scheduling uses the same contract.
    update_allowance = 2.0 if prioritize_fit and stage == 'C' else 1.0
    return update_allowance * float(minimum_update_seconds) + 1.0


def timed_out_stage_c_fit_is_stalled(failed_checks, hard_stage_c_tried):
    """Whether a timed-out Stage-C fit has no remaining solver-owned failure.

    Hard temporal smoothing makes another fit attempt low-value for shake and
    settling checks under protected contacts. It does not make a timed-out fit
    useless when jerk, root continuity, or motion discontinuity still fails:
    those remain explicit terms in the source-constrained solver and may need
    the outer continuation budget.
    """
    if not hard_stage_c_tried:
        return False
    failed = set(failed_checks or ())
    return not bool(failed & {'jerk', 'rootContinuity', 'motionDiscontinuity'})


EVIDENCE_TERMINATIONS = frozenset({
    'objective_stalled', 'acceptance_stalled', 'seam_playback_only',
    'seam_excess_needs_different_cycle', 'hard_trajectory_root_failure',
    'unreachable_conflict', 'polish_stalled', 'hard_polish_exhausted',
})


# A fit this far past the distortion band while failing contacts and anatomy
# cannot simultaneously hold its anchors and reach the source pose (measured:
# reverse lunge 13.1-13.9 deg, bench dips 34.8 deg — polish burned its budget
# and re-weighed the same conflict).
UNREACHABLE_ARTICULATION_DEGREES = 12.0
INCOMPLETE_OPTIMIZER_TERMINATIONS = frozenset({
    'time_budget', 'solve_phase_budget', 'evaluation_limit',
})


def unreachable_without_polish(report):
    """Conflicts that more soft LS will not repair — stop without burning budget."""
    if not isinstance(report, dict):
        return False
    checks = report.get('checks') or {}
    if hard_trajectory_and_root_failure(checks):
        return True
    failed = set(failed_check_names(checks))
    reasons = set(report.get('physicalReasons') or [])
    optimizer_termination = report.get('optimizerTermination')
    has_completed_solver_evidence = (
        optimizer_termination in {'converged', 'objective_stalled'}
        or (
            optimizer_termination not in INCOMPLETE_OPTIMIZER_TERMINATIONS
            and report.get('termination') in EVIDENCE_TERMINATIONS
        )
    )
    if ({'anatomy', 'sourceArticulation'} <= failed
            and 'repair_articulation_distortion' in reasons
            and has_completed_solver_evidence):
        return True
    # The fit satisfied its target articulation and its contacts, but the
    # reaching pose breaks hard body structure: matching the source and
    # keeping the skeleton valid are conflicting objectives. Polish can only
    # re-weigh them (measured: chest-attachment conflict survived the full
    # refinement budget with contacts and sourceArticulation both passing).
    if ('anatomy' in failed and 'contacts' not in failed
            and 'sourceArticulation' not in failed
            and reasons == {'anatomy_chest_attachment'}
            and has_completed_solver_evidence):
        return True
    # Contacts and anatomy failed together while the articulation is already
    # displaced past the distortion band: the anchors and the source pose may
    # conflict. This is only decisive after the solver has actually
    # converged/stalled; a later, unrelated refinement stop is insufficient.
    if {'anatomy', 'contacts'} <= failed and 'sourceArticulation' not in failed and (
            float(report.get('maximumArticulationChangeDegrees') or 0.)
            >= UNREACHABLE_ARTICULATION_DEGREES) and has_completed_solver_evidence:
        return True
    return False


def refinement_improved_acceptance(refinement):
    """True when a refinement block strictly cleared at least one failed check."""
    if not isinstance(refinement, dict):
        return False
    blocks = refinement.get('blocks') or []
    if not blocks:
        return False
    initial = set(refinement.get('initialFailedChecks') or [])
    final = set((blocks[-1] or {}).get('failedChecks') or [])
    return bool(initial) and final < initial


def acceptance_stalled_after_refinement(refinement):
    """Same failing checks across two refinement blocks: further LS is low-EV."""
    if not isinstance(refinement, dict):
        return False
    blocks = refinement.get('blocks') or []
    if len(blocks) < 2:
        return False
    previous = set((blocks[-2] or {}).get('failedChecks') or [])
    current = set((blocks[-1] or {}).get('failedChecks') or [])
    return bool(current) and previous == current


def seam_or_playback_only_failure(report):
    """True when the body fit is otherwise OK and only loop closure failed."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if report.get('reason') not in {
        'loop_requires_cycle_repair',
        'playback_validation_failed',
    }:
        return False
    checks = report.get('checks')
    if not isinstance(checks, dict) or not checks:
        return True
    failed = {name for name, passed in checks.items() if passed is False}
    return bool(failed) and failed <= {'loopSeam', 'playback'}


# Soft Stage-B rarely invents continuity when excess is already near the limit;
# a cold second window is low-EV then. When excess is still ≫2×, another ranked
# cycle is the intended recovery (see reject-failure analysis). Keep equal to
# loop_seam.MAX_RANKED_SOURCE_WRAP_RATIO so ranking and Stage-B agree.
SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE = 2.0


def seam_near_miss_for_cycle_skip(report):
    """True when seam/playback-only and both step/velocity are within ~2× limits."""
    if not seam_or_playback_only_failure(report):
        return False
    playback = report.get('playback') or {}
    ratios = []
    excess = playback.get('seamStepExcessMeters')
    limit = playback.get('seamStepExcessLimitMeters')
    if excess is not None and limit is not None and float(limit) > 0:
        ratios.append(float(excess) / float(limit))
    velocity = playback.get('seamVelocityMismatchMetersPerSecond')
    velocity_limit = playback.get('seamVelocityMismatchLimitMetersPerSecond')
    if velocity is not None and velocity_limit is not None and float(velocity_limit) > 0:
        ratios.append(float(velocity) / float(velocity_limit))
    if not ratios:
        # Missing magnitude: keep prior early-stop (treat as near-miss).
        return True
    return max(ratios) <= SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE


def seam_over_limit_ratios(playback):
    """Return step/velocity over-limit ratios from a playback report dict."""
    if not isinstance(playback, dict):
        return []
    ratios = []
    excess = playback.get('seamStepExcessMeters')
    limit = playback.get('seamStepExcessLimitMeters')
    if excess is not None and limit is not None and float(limit) > 0:
        ratios.append(float(excess) / float(limit))
    velocity = playback.get('seamVelocityMismatchMetersPerSecond')
    velocity_limit = playback.get('seamVelocityMismatchLimitMetersPerSecond')
    if velocity is not None and velocity_limit is not None and float(velocity_limit) > 0:
        ratios.append(float(velocity) / float(velocity_limit))
    return ratios


def controlled_fit_unusable_for_more_preview_work(report):
    """Stop sibling preview loops/variants when more fitting cannot produce a selectable clip."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if controlled_fit_processing_incomplete(report):
        return True
    if report.get('reason') in {
        'fit_validation_failed',
        'no_validated_loop_cycle',
        'source_cycle_preflight_rejected',
        'source_cycle_parent_phase_coverage_unresolved',
        'pre_fit_source_articulation_fidelity_failed',
        # Cycle attempts have already failed, and the full interval was
        # skipped because its retained anatomy is persistently folded. This
        # cannot produce a selectable fit, but the baseline source-contact
        # correction may still repair confirmed support before we stop.
        'retained_interval_skipped_after_persistent_source_spine_fold',
        'loop_requires_cycle_repair',
        'playback_validation_failed',
    }:
        return True
    if seam_or_playback_only_failure(report):
        return True
    return hard_trajectory_and_root_failure(report.get('checks'))


def intentional_open_loop_seam(payload):
    """Fit kept an otherwise-valid body with an honest non-continuous wrap."""
    report = payload.get('controlledMotionFit') or {}
    return bool(
        report.get('applied')
        and (
            report.get('reason') == 'validated_controlled_motion_open_seam'
            or report.get('loopSeamOpen') is True
        )
    )


def loop_disabled_playback_passed(payload):
    """True when interpolator/contact/support checks pass without cyclic wrap."""
    from .rig_playback import validate_rig_playback
    if not payload.get('fixedRig'):
        return False
    loop_off = {**payload, 'loop': {**(payload.get('loop') or {}), 'enabled': False}}
    return bool(validate_rig_playback(loop_off).get('passed'))


def can_reuse_controlled_motion(payload):
    from .support_geometry import validate_support_geometry, validate_supported_shoe_orientation
    from .support_alignment import validate_payload_alignment
    from .contact_constraints import source_support_mapping_unresolved
    if (source_support_mapping_unresolved(payload)
            or source_foot_patch_clock_failure(payload)):
        return False
    report = payload.get('controlledMotionFit') or {}
    checks = report.get('checks') or {}
    open_seam = intentional_open_loop_seam(payload)
    # Open-seam accepts waive only wrap checks; body/contact checks still bind.
    waived = {'loopSeam'} | ({'playback'} if open_seam else set())
    required_ok = all(
        checks.get(key) is True for key in REQUIRED_FIT_CHECKS if key not in waived)
    checks_ok = all(
        value is True for key, value in checks.items() if key not in waived)
    seam_ok = open_seam or (
        not (payload.get('loop') or {}).get('enabled') or checks.get('loopSeam') is True)
    fit_source_evidence_digest = report.get('fitSourceEvidenceDigest')
    source_evidence_ok = (
        fit_source_evidence_digest == controlled_motion_fit_source_evidence_digest(payload)
        if isinstance(fit_source_evidence_digest, str)
        else not controlled_motion_has_source_fit_evidence(payload)
    )
    return bool(payload.get('fixedRig') and report.get('applied')
                and report.get('strategy') == CONTROLLED_MOTION_STRATEGY
                and required_ok and checks_ok and seam_ok
                and source_evidence_ok
                and validate_support_geometry(payload)['passed']
                and validate_payload_alignment(payload)['passed']
                and validate_supported_shoe_orientation(payload)['passed']
                and report.get('outputPoseDigest') == pose_digest(payload))


def source_foot_patch_clock_failure(payload, evidence=None):
    """Reject malformed declared source-patch clocks before they erase support.

    Foot-patch states and timestamps are native source evidence. A selected
    cycle may change the fit-frame subset, but must not leave those arrays at
    different lengths or make every overlapping real source frame unmap.
    """
    source_evidence = evidence if isinstance(evidence, dict) else (
        payload.get('sourceFootSupportEvidence') or {})
    patch = source_evidence.get('footPatchEvidence') or {}
    if patch.get('available') is not True:
        return None
    if patch.get('sourceTimeBasis') != 'absolute_source_video':
        if (patch.get('sourceTimeBasis') is not None
                or patch.get('sourceTimesSec') is not None):
            return {'reason': 'source_foot_patch_clock_invalid',
                    'detail': 'unsupported_source_time_basis'}
        return None
    native_times = patch.get('sourceTimesSec')
    feet = patch.get('feet') or {}
    if not isinstance(native_times, list) or not native_times:
        return {'reason': 'source_foot_patch_clock_invalid',
                'detail': 'absolute_source_times_missing'}
    state_counts = {
        side: len(record.get('states'))
        for side, record in feet.items()
        if isinstance(record, dict) and isinstance(record.get('states'), list)
    }
    if (not state_counts or any(count != len(native_times)
                                for count in state_counts.values())):
        return {'reason': 'source_foot_patch_clock_invalid',
                'detail': 'state_timestamp_count_mismatch',
                'sourceTimestampCount': len(native_times),
                'stateCountsBySide': state_counts}
    frames = [frame for frame in (payload.get('frames') or [])
              if isinstance(frame, dict)]
    frame_times = [None if frame.get('syntheticLoopBridge')
                   else frame.get('sourceTimeSec') for frame in frames]
    real_times = []
    for value in frame_times:
        try:
            time_value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(time_value):
            real_times.append(time_value)
    if not real_times:
        return None
    try:
        native_clock = np.asarray(native_times, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return {'reason': 'source_foot_patch_clock_invalid',
                'detail': 'invalid_absolute_source_times'}
    if (not np.isfinite(native_clock).all()
            or np.any(np.diff(native_clock) <= 0.)):
        return {'reason': 'source_foot_patch_clock_invalid',
                'detail': 'nonmonotonic_or_nonfinite_absolute_source_times'}
    from .contact_constraints import mapped_foot_patch_state_indices
    mapped = mapped_foot_patch_state_indices(source_evidence, frame_times, len(frames))
    if real_times and not np.any(mapped >= 0):
        return {'reason': 'source_foot_patch_clock_unmapped',
                'detail': 'real_source_frames_all_unmapped',
                'realSourceFrameCount': len(real_times),
                'sourceTimestampCount': len(native_times),
                'stateCountsBySide': state_counts}
    return None


def controlled_motion_fit_source_evidence(payload):
    """Return source and support inputs that can change fit constraints or acceptance."""
    frames = payload.get('frames') or []
    source_support_evidence = payload.get('sourceFootSupportEvidence')
    motion_space_evidence = None
    if isinstance(source_support_evidence, dict):
        from .body_support_observation import materialize_stationary_sole_support
        from .contact_constraints import _without_fit_local_timing_metadata
        # Bind the same derived rig-side constraints consumed by fitting while
        # preserving canonical source labels and its mapping digest. The fit
        # clock view is deterministic from frame provenance and is ephemeral.
        motion_space_evidence = _without_fit_local_timing_metadata(
            materialize_stationary_sole_support(payload)
        )
    selected_interval = _fit_source_interval_selection(payload)
    if (
        not selected_interval.get('available')
        and not _fit_payload_declares_source_interval(payload)
    ):
        selected_interval = _materialized_fit_source_interval(payload)
    selected_interval_evidence = _canonical_fit_source_interval_evidence(
        selected_interval,
        fps=payload.get('fps'),
    )
    source_frame_provenance = [
        {
            key: frame[key]
            for key in ('sourceFrameIndex', 'sourceTimeSec', 'cycleSourceFrameIndex',
                        'cycleSourceTimeSec', 'syntheticLoopBridge')
            if key in frame
        }
        for frame in frames
        if isinstance(frame, dict)
    ]
    source_articulation_references = [
        {
            key: frame[key]
            for key in ('sourceJoints', 'controlledArticulationReferenceJoints')
            if key in frame
        }
        if isinstance(frame, dict)
        else None
        for frame in frames
    ]
    evidence = {
        'sourcePoseCameraReference': payload.get('sourcePoseCameraReference'),
        'sourcePoseReference': payload.get('sourcePoseReference'),
        # The selected interval can be stored in legacy loopCycleSelection
        # while fitting and then moved into artifactState lineage after the fit.
        # Bind its meaning and bounds, not that storage representation.
        'selectedSourceInterval': selected_interval_evidence,
        'observedCycleProposals': payload.get('observedCycleProposals'),
        'sourceCyclePreflight': payload.get('sourceCyclePreflight'),
        'sourceFrameProvenance': source_frame_provenance,
    }
    if any(source_articulation_references):
        evidence['sourceArticulationReferences'] = source_articulation_references
    fit_context = {
        'sourceFootSupportEvidence': source_support_evidence,
        'motionSpaceSupportEvidence': motion_space_evidence,
        'groundContactMode': payload.get('groundContactMode'),
        'renderFloorY': payload.get('renderFloorY'),
        'elevatedSupportSurfaces': payload.get('elevatedSupportSurfaces'),
        'equipmentConstraints': payload.get('equipmentConstraints'),
        'footRestPitchRadians': payload.get('footRestPitchRadians'),
        'postBakeForefootContactConstraint': payload.get('postBakeForefootContactConstraint'),
    }
    fit_context = {
        key: value
        for key, value in fit_context.items()
        if value is not None and value != {} and value != []
    }
    if fit_context:
        evidence['fitContext'] = fit_context
    return evidence


def _fit_payload_declares_source_interval(payload):
    if isinstance(payload.get('loopCycleSelection'), dict):
        return True
    state = payload.get('artifactState')
    evidence = state.get('selectionEvidence') if isinstance(state, dict) else None
    return isinstance(evidence, dict) and any(
        isinstance(evidence.get(key), dict)
        for key in ('cycleSelection', 'boundedMovementSelection')
    )


def _materialized_fit_source_interval(payload):
    """Bind the frame range the fit actually saw when no selection is declared."""
    frames = payload.get('frames')
    if not isinstance(frames, list):
        return {'available': False, 'reason': 'fit_source_frames_unavailable'}
    source_frames = [
        frame for frame in frames
        if isinstance(frame, dict) and not bool(frame.get('syntheticLoopBridge'))
    ]
    if not source_frames:
        return {'available': False, 'reason': 'fit_source_frame_provenance_unavailable'}

    source_indices = [frame.get('sourceFrameIndex') for frame in source_frames]
    source_times = [frame.get('sourceTimeSec') for frame in source_frames]
    if (
        any(type(index) is not int for index in source_indices)
        or any(
            isinstance(value, bool)
            or _optional_fit_evidence_float(value) is None
            for value in source_times
        )
        or any(
            right != left + 1
            for left, right in zip(source_indices, source_indices[1:])
        )
    ):
        return {'available': False, 'reason': 'fit_source_interval_provenance_not_contiguous'}

    normalized_times = [_optional_fit_evidence_float(value) for value in source_times]
    if any(right <= left for left, right in zip(normalized_times, normalized_times[1:])):
        return {'available': False, 'reason': 'fit_source_interval_time_provenance_invalid'}

    loop = payload.get('loop')
    kind = 'cycle' if isinstance(loop, dict) and loop.get('enabled') is True else 'materialized'
    return {
        'available': True,
        'kind': kind,
        'source': 'materialized_frame_provenance',
        'interval': {
            'startFrame': source_indices[0],
            'endFrame': source_indices[-1],
            'startTimeSec': normalized_times[0],
            'endTimeSec': normalized_times[-1],
        },
    }


def _canonical_fit_source_interval_evidence(selection, *, fps):
    """Normalize legacy and artifact-lineage interval records for fit identity."""
    if not isinstance(selection, dict) or selection.get('available') is not True:
        return {
            'available': False,
            'reason': (
                selection.get('reason')
                if isinstance(selection, dict)
                else 'selected_source_interval_unavailable'
            ),
        }

    interval = selection.get('interval')
    if not isinstance(interval, dict):
        return {'available': False, 'reason': 'selected_source_interval_bounds_missing'}

    start_frame = interval.get('startFrame')
    end_frame = interval.get('endFrame')
    if end_frame is None:
        stop_frame_exclusive = interval.get('stopFrameExclusive')
        if type(stop_frame_exclusive) is int:
            end_frame = stop_frame_exclusive - 1

    start_time = interval.get('startTimeSec', interval.get('sourceStartTimeSec'))
    end_time = interval.get('endTimeSec')
    if end_time is None:
        stop_time_exclusive = _optional_fit_evidence_float(
            interval.get('sourceStopTimeSec')
        )
        resolved_fps = _optional_fit_evidence_float(fps)
        if stop_time_exclusive is not None and resolved_fps is not None and resolved_fps > 0.0:
            end_time = stop_time_exclusive - 1.0 / resolved_fps

    return {
        'available': True,
        'kind': selection.get('kind'),
        'startFrame': start_frame,
        'endFrame': end_frame,
        # Lineage rematerialization can introduce floating-point subtraction
        # noise. Nanosecond identity precision is finer than the microsecond
        # provenance checks and must not invalidate an unchanged interval.
        'startTimeSec': round(float(start_time), 9),
        'endTimeSec': round(float(end_time), 9),
    }


def _optional_fit_evidence_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def controlled_motion_fit_source_evidence_digest(payload):
    evidence = controlled_motion_fit_source_evidence(payload)
    encoded = json.dumps(evidence, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def controlled_motion_has_source_fit_evidence(payload):
    evidence = controlled_motion_fit_source_evidence(payload)
    has_direct_source_evidence = any(
        value is not None
        for key, value in evidence.items()
        if key != 'sourceFrameProvenance'
    )
    return has_direct_source_evidence


def controlled_motion_fit_raw_fallback(payload):
    """Allow a failed, no-op fit to reach independent artifact validation.

    The fallback is limited to a complete fit rejection on the exact unchanged
    pose, with a passing raw-RECONSTRUCTION gate recorded for this candidate. All later
    source, physical, support, playback, render, and review gates still apply.
    """
    report = payload.get('controlledMotionFit') or {}
    evidence = payload.get('rawMotionFallbackEvidence') or {}
    if report.get('applied') is not False or report.get('reason') not in {
        'fit_validation_failed',
        'retained_interval_skipped_after_unreachable_core_cycle_failure',
    } or controlled_fit_processing_incomplete(report):
        return None
    fit_failures = [report] if report.get('reason') == 'fit_validation_failed' else [
        attempt.get('fitReport')
        for attempt in report.get('cycleSelectionAttempts') or []
        if isinstance(attempt, dict)
        and isinstance(attempt.get('fitReport'), dict)
        and attempt['fitReport'].get('reason') == 'fit_validation_failed'
    ]
    complete_failure = next((
        fit_report for fit_report in fit_failures
        if fit_report.get('applied') is False
        and isinstance(fit_report.get('checks'), dict)
        and all(type(fit_report['checks'].get(name)) is bool for name in REQUIRED_FIT_CHECKS)
        and not controlled_fit_processing_incomplete(fit_report)
    ), None)
    if complete_failure is None:
        return None
    checks = complete_failure['checks']
    if evidence.get('schemaVersion') != 1 or evidence.get('rawReconstructionMotionGatePassed') is not True:
        return None
    gate_fingerprint = evidence.get('rawReconstructionMotionGateFingerprint')
    if (not isinstance(gate_fingerprint, str) or len(gate_fingerprint) != 64
            or any(character not in '0123456789abcdef' for character in gate_fingerprint.lower())):
        return None
    fit_input_digest = report.get('fitInputPoseDigest')
    if not isinstance(fit_input_digest, str) or fit_input_digest != pose_digest(payload):
        return None
    source_evidence_digest = report.get('fitSourceEvidenceDigest')
    if isinstance(source_evidence_digest, str):
        if source_evidence_digest != controlled_motion_fit_source_evidence_digest(payload):
            return None
    elif controlled_motion_has_source_fit_evidence(payload):
        return None
    return {
        'used': True,
        'reason': 'unmodified_raw_reconstruction_after_terminal_fit_rejection',
        'fitFailureReason': complete_failure.get('reason'),
        'fitSelectionReason': report.get('reason'),
        'failedChecks': sorted(name for name, passed in checks.items() if passed is False),
        'rawReconstructionMotionGateFingerprint': gate_fingerprint,
        'fitInputPoseDigest': fit_input_digest,
    }


def align_vectors(first, last):
    first, last = unit(first), unit(last)
    cross = np.cross(first, last)
    sine = np.linalg.norm(cross, axis=-1)
    cosine = np.clip(np.sum(first*last, axis=-1), -1., 1.)
    axis = cross / np.maximum(sine[:, None], 1e-12)
    opposite = (sine < 1e-8) & (cosine < 0.)
    if opposite.any():
        basis = np.eye(3)[np.argmin(abs(first[opposite]), axis=-1)]
        axis[opposite] = unit(np.cross(first[opposite], basis))
    return axis*np.arctan2(sine, cosine)[:, None]


def transported_bone_rotations(directions):
    """Infer a continuous minimum-twist frame for position-only observations.

    Independently aligning body-up on every frame is singular for downward
    bones: minute changes can invent half-turns of unobserved axial rotation.
    Transport the previous frame by the observed change in direction instead.
    """
    directions = unit(directions)
    matrices = np.empty((len(directions), 3, 3))
    matrices[0] = Rotation.from_rotvec(align_vectors(np.array([[0., 1., 0.]]), directions[:1])).as_matrix()[0]
    changes = Rotation.from_rotvec(align_vectors(directions[:-1], directions[1:])).as_matrix()
    for frame in range(1, len(directions)):
        matrices[frame] = changes[frame-1]@matrices[frame-1]
    return Rotation.from_matrix(matrices)


class FixedRig:
    """One set of offsets; root travel and local rotations are the only variables.

    Hip and collar sockets inherit the pelvis/chest transform. Their offsets
    cannot float independently. Axial twist is not inferred from joint positions.
    """
    def __init__(self, points, names):
        self.names = names
        self.parents = [names.index(SMPL_JOINT_NAMES[SMPL_JOINT_PARENTS[SMPL_JOINT_NAMES.index(n)]] )
                        if n != 'pelvis' else -1 for n in names]
        self.order = [names.index(n) for n in SMPL_JOINT_NAMES]
        self.root = names.index('pelvis')
        self.fixed = {names.index(n) for n in ('left_hip', 'right_hip', 'left_collar', 'right_collar')}
        self.active = [j for j in self.order if j not in self.fixed]
        self.slots = {j: 3+3*i for i,j in enumerate(self.active)}
        self.width = 3+3*len(self.active)
        self.offsets = np.zeros((len(names), 3))
        self.initial = np.zeros((len(points), self.width))
        self.initial[:, :3] = points[:, self.root]
        matrices = {}
        axes = body_orientation_axes(points, names)
        matrices[self.root] = frame_basis(axes[:, 1], axes[:, 0])
        self.initial[:, self.slots[self.root]:self.slots[self.root]+3] = Rotation.from_matrix(matrices[self.root]).as_rotvec()
        for j in self.order[1:]:
            parent = self.parents[j]
            local = np.einsum('fji,fj->fi', matrices[parent], points[:, j]-points[:, parent])
            length = float(np.median(np.linalg.norm(local, axis=1)))
            if j in self.fixed:
                self.offsets[j] = unit(np.median(local, axis=0))*length
                matrices[j] = matrices[parent]
            else:
                self.offsets[j] = [0., length, 0.]
                rotation = transported_bone_rotations(local)
                self.initial[:, self.slots[j]:self.slots[j]+3] = rotation.as_rotvec()
                matrices[j] = matrices[parent]@rotation.as_matrix()
        # Calibrate anatomy, not pose symmetry. Each limb keeps its own local
        # rotations while matching bones share one length for the entire clip.
        for name in names:
            other = name.replace('left_', 'right_', 1)
            if not name.startswith('left_') or other not in names:
                continue
            left, right = names.index(name), names.index(other)
            length = (np.linalg.norm(self.offsets[left])+np.linalg.norm(self.offsets[right]))*.5
            if left in self.fixed:
                lateral = unit(self.offsets[right]-self.offsets[left])
                center = (self.offsets[left]+self.offsets[right])*.5
                center -= lateral*np.dot(center, lateral)
                half_span = np.linalg.norm(self.offsets[right]-self.offsets[left])*.5
                self.offsets[left] = center-lateral*half_span
                self.offsets[right] = center+lateral*half_span
            self.offsets[left] = unit(self.offsets[left])*length
            self.offsets[right] = unit(self.offsets[right])*length
        # Center the neck attachment in the calibrated chest socket plane.
        # Preserve the head's world direction while rebasing its parent frame.
        self.project_neck_attachment(maximum_lateral_ratio=0.)
        self.dependencies = np.zeros((len(names)*3, self.width))
        for j in self.order:
            columns = [0, 1, 2]
            ancestor = j
            while ancestor >= 0:
                if ancestor in self.slots:
                    columns.extend(range(self.slots[ancestor], self.slots[ancestor]+3))
                ancestor = self.parents[ancestor]
            self.dependencies[j*3:j*3+3, columns] = 1.

    def project_neck_attachment(self, *, maximum_lateral_ratio):
        """Clamp socket offset analytically, retaining length and head direction."""
        self.initial[:] = project_neck_attachment_values(
            self.initial, self.offsets, self.names, self.active, maximum_lateral_ratio)

    def decode(self, values, *, project_socket=True):
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        # Same analytic socket clamp as sample_rig / export projection so residual,
        # keyframe acceptance, and interpolated playback share one neck attachment.
        values = np.asarray(values, dtype=float)
        if project_socket:
            values = project_neck_attachment_values(
                values, self.offsets, self.names, self.active,
                SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
        points = np.empty((len(values), len(self.names), 3))
        points[:, self.root] = values[:, :3]
        matrices = {}
        rotations = Rotation.from_rotvec(values[:, 3:].reshape(-1,3)).as_matrix().reshape(len(values),len(self.active),3,3)
        identity = np.tile(np.eye(3), (len(values),1,1))
        for j in self.order:
            local = rotations[:, (self.slots[j]-3)//3] if j in self.slots else identity
            parent = self.parents[j]
            matrices[j] = local if parent < 0 else matrices[parent]@local
            if parent >= 0:
                points[:, j] = points[:, parent]+np.einsum('fij,j->fi', matrices[j], self.offsets[j])
        return points

    def fk_jacobian(self, values, *, project_socket=True):
        """Exact ∂decoded points/∂rig coordinates as a frame-block-diagonal
        sparse matrix.

        The chain recursion is the decode itself differentiated: a rotation
        vector ω_j moves every point in joint j's subtree by
        M_parent @ (∂R_j/∂ω_j) @ c where c is the point's offset in joint j's
        frame. ∂R_j/∂ω_j uses central differences on the 3x3 rotation matrices
        (three cheap batched conversions per joint - exact to ~1e-9 and
        decoupled from rotvec convention pitfalls). The neck socket clamp is
        piecewise; frames where it engages differentiate the clamp itself.
        """
        from scipy.sparse import coo_matrix
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        values = np.asarray(values, dtype=float)
        count = len(values)
        clamp_limit = SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN
        clamped = values
        if project_socket:
            clamped = project_neck_attachment_values(
                values, self.offsets, self.names, self.active, clamp_limit)
        clamp_active = np.any(clamped != values, axis=1) if project_socket else np.zeros(count, dtype=bool)
        step = 1e-6
        rotations = Rotation.from_rotvec(clamped[:, 3:].reshape(-1, 3)).as_matrix().reshape(count, len(self.active), 3, 3)
        rotvecs = clamped[:, 3:].reshape(count, len(self.active), 3)
        d_rotations = np.zeros((count, len(self.active), 3, 3, 3))
        for k in range(3):
            plus = rotvecs.copy()
            minus = rotvecs.copy()
            plus[:, :, k] += step
            minus[:, :, k] -= step
            d_plus = Rotation.from_rotvec(plus.reshape(-1, 3)).as_matrix().reshape(count, len(self.active), 3, 3)
            d_minus = Rotation.from_rotvec(minus.reshape(-1, 3)).as_matrix().reshape(count, len(self.active), 3, 3)
            d_rotations[:, :, :, :, k] = (d_plus - d_minus) / (2. * step)
        descendants = {j: [] for j in self.order}
        for j in self.order:
            ancestor = j
            while ancestor >= 0:
                if ancestor in self.slots:
                    descendants[ancestor].append(j)
                ancestor = self.parents[ancestor]
        row_indices, column_indices, entries = [], [], []
        joints_count = len(self.names)
        # Vectorized over frames: one einsum chain per (active joint,
        # descendant) pair, with index grids assembled as numpy arrays.
        identity = np.eye(3)
        matrices = {}
        points_all = np.empty((count, joints_count, 3))
        points_all[:, self.root] = clamped[:, :3]
        for j in self.order:
            parent = self.parents[j]
            local = (rotations[:, (self.slots[j] - 3) // 3]
                     if j in self.slots else identity[None, :, :])
            matrices[j] = local if parent < 0 else matrices[parent] @ local
            if parent >= 0:
                points_all[:, j] = (points_all[:, parent]
                                    + np.einsum('fij,j->fi', matrices[j], self.offsets[j]))
        frame_base_rows = np.arange(count)[:, None] * joints_count * 3
        frame_base_cols = np.arange(count)[:, None] * self.width
        axis_grid = np.arange(3)
        for j in self.active:
            parent = self.parents[j]
            matrix_parent = (identity if parent < 0 else matrices[parent])
            if matrix_parent.shape[0] != count:
                matrix_parent = np.broadcast_to(matrix_parent, (count, 3, 3))
            d_rot = d_rotations[:, (self.slots[j] - 3) // 3]
            slot = self.slots[j]
            moved = [i for i in descendants[j] if not (i == j and parent < 0)]
            if not moved:
                continue
            moved_index = np.asarray(moved)
            # chain[f, i] = o_j + M_j^T (p_i - p_j) for descendants; exactly
            # o_j for i == j (the joint's own point rides on its bone).
            delta = (points_all[:, moved_index] - points_all[:, j][:, None, :])
            local_chain = np.einsum('fmi,fdm->fdi', matrices[j], delta)
            local_chain += self.offsets[j]
            # derivative[f, i, axis, comp] = Mp @ dR[..., comp] @ chain
            derivative = np.einsum(
                'fij,fjmc,fdm->fdic', matrix_parent, d_rot, local_chain)
            rows = (frame_base_rows[:, :, None] + moved_index[None, :, None] * 3 + axis_grid[None, None, :])
            cols = (frame_base_cols.reshape(count, 1, 1) + slot + axis_grid.reshape(1, 1, 3))
            rows = rows[:, :, :, None]
            cols = cols[:, :, None, :]
            row_indices.append(np.broadcast_to(rows, (count, len(moved), 3, 3)).ravel())
            column_indices.append(np.broadcast_to(cols, (count, len(moved), 3, 3)).ravel())
            entries.append(derivative.ravel())
        joint_index = np.asarray(self.order)
        rows = (frame_base_rows[:, :, None] + (joint_index[None, :, None] * 3 + axis_grid[None, None, :]))
        cols = (frame_base_cols.reshape(count, 1, 1) + axis_grid.reshape(1, 1, 3))
        eye = (axis_grid[None, None, :] == axis_grid[None, :, None]).astype(float)
        rows = rows[:, :, :, None]
        cols = cols[:, :, None, :]
        row_indices.append(np.broadcast_to(rows, (count, len(joint_index), 3, 3)).ravel())
        column_indices.append(np.broadcast_to(cols, (count, len(joint_index), 3, 3)).ravel())
        entries.append(np.broadcast_to(eye, (count, len(joint_index), 3, 3)).ravel())
        shape = (count * joints_count * 3, count * self.width)
        jacobian = coo_matrix(
            (np.concatenate(entries),
             (np.concatenate(row_indices), np.concatenate(column_indices))),
            shape=shape).tocsr()
        if not np.any(clamp_active) or not project_socket:
            return jacobian
        # Frames with an engaged neck clamp differentiate the clamp itself:
        # jacobian(original) = jacobian(clamped path) @ clamp_jacobian, where
        # clamp_jacobian is the identity with the active frames' neck/head
        # entries replaced by the clamp's own derivative (it only reads and
        # writes the neck/head rotation vectors).
        neck_slot = self.slots[self.names.index('neck')]
        head_slot = self.slots[self.names.index('head')]
        clamp_columns = list(range(neck_slot, neck_slot + 3)) + list(range(head_slot, head_slot + 3))
        clamped_frames = np.flatnonzero(clamp_active)
        clamp_outputs = np.asarray(clamp_columns, dtype=int)
        base = clamped[clamped_frames][:, clamp_outputs]
        clamp_derivatives = np.empty(
            (len(clamped_frames), len(clamp_outputs), len(clamp_columns)), dtype=float)
        # The socket projection changes only neck/head rotation coordinates.
        # Probe all clamped frames together instead of making six tiny calls per
        # frame and building a dense frame-by-frame identity map.
        for input_index, column in enumerate(clamp_columns):
            probes = values[clamped_frames].copy()
            probes[:, column] += step
            moved = project_neck_attachment_values(
                probes, self.offsets, self.names, self.active, clamp_limit)
            clamp_derivatives[:, :, input_index] = (
                moved[:, clamp_outputs] - base) / step

        # Compose only the changed neck/head columns. The full clamp Jacobian
        # is identity outside these small per-frame blocks, so multiplying by a
        # dense identity-like sparse matrix needlessly scales as frames × rig².
        clamp_derivatives[:, np.arange(len(clamp_outputs)), np.arange(len(clamp_columns))] -= 1.0
        correction_rows = np.broadcast_to(
            np.arange(len(clamped_frames))[:, None, None] * len(clamp_outputs)
            + np.arange(len(clamp_outputs))[None, :, None],
            clamp_derivatives.shape,
        )
        correction_columns = np.broadcast_to(
            clamped_frames[:, None, None] * self.width
            + np.asarray(clamp_columns)[None, None, :],
            clamp_derivatives.shape,
        )
        nonzero = clamp_derivatives != 0.0
        correction = coo_matrix(
            (clamp_derivatives[nonzero],
             (correction_rows[nonzero], correction_columns[nonzero])),
            shape=(len(clamped_frames) * len(clamp_outputs), shape[1]),
        ).tocsr()
        output_columns = (
            clamped_frames[:, None] * self.width + clamp_outputs[None, :]
        ).ravel()
        return jacobian + jacobian[:, output_columns] @ correction


def project_neck_attachment_values(coordinates, offsets, names, active, maximum_lateral_ratio):
    """Clamp neck lateral socket on rig coordinates; keep bone lengths and head direction."""
    values = np.array(coordinates, dtype=float, copy=True)
    required = ('neck', 'head', 'left_collar', 'right_collar')
    if any(name not in names for name in required):
        return values
    slots = {j: 3 + 3 * i for i, j in enumerate(active)}
    neck, head = names.index('neck'), names.index('head')
    if neck not in slots or head not in slots:
        return values
    left, right = offsets[names.index('left_collar')], offsets[names.index('right_collar')]
    span = right - left
    width = np.linalg.norm(span)
    if width < 1e-12:
        return values
    lateral = unit(span)
    center = np.dot((left + right) * .5, lateral)
    neck_slot, head_slot = slots[neck], slots[head]
    old_neck = Rotation.from_rotvec(values[:, neck_slot:neck_slot + 3])
    vectors = old_neck.apply(np.tile(offsets[neck], (len(values), 1)))
    component = vectors @ lateral
    limit = maximum_lateral_ratio * width
    length = np.linalg.norm(offsets[neck])
    corrected = np.clip(center + np.clip(component - center, -limit, limit), -length, length)
    orthogonal = vectors - component[:, None] * lateral
    magnitude = np.linalg.norm(orthogonal, axis=1, keepdims=True)
    fallback = unit(np.cross(lateral, np.eye(3)[np.argmin(abs(lateral))]))
    direction = np.where(magnitude > 1e-12, orthogonal / np.maximum(magnitude, 1e-12), fallback)
    target = direction * np.sqrt(np.maximum(length ** 2 - corrected ** 2, 0.))[:, None] + corrected[:, None] * lateral
    new_neck = Rotation.from_rotvec(align_vectors(vectors, target)) * old_neck
    old_head = Rotation.from_rotvec(values[:, head_slot:head_slot + 3])
    values[:, neck_slot:neck_slot + 3] = new_neck.as_rotvec()
    values[:, head_slot:head_slot + 3] = (new_neck.inv() * old_neck * old_head).as_rotvec()
    return values


def anatomical_structure_dependencies(rig, points, names):
    """Keep the structure residual Jacobian local to the affected chains."""
    rows = []
    for label in anatomical_structure_residuals(points, names, pose_only=True)[1]:
        reason, joint = label.split(':', 1)
        if reason == 'anatomy_degenerate_bone':
            affected = [joint, names[rig.parents[names.index(joint)]]]
        elif reason == 'anatomy_bilateral_proportions':
            affected = [joint, joint.replace('left_', 'right_', 1)]
            affected += [names[rig.parents[names.index(n)]] for n in affected.copy()]
        elif reason == 'anatomy_socket_alignment':
            suffix = 'hip' if joint == 'pelvis' else 'collar'
            affected = [joint, 'left_'+suffix, 'right_'+suffix]
        elif reason == 'anatomy_hinge_collapse':
            side, hinge = joint.split('_')
            affected = [side+'_'+n for n in (('hip','knee','ankle') if hinge == 'knee' else ('shoulder','elbow','wrist'))]
        elif reason == 'anatomy_spine_deviation':
            affected = ['pelvis', 'neck', joint]
        elif reason == 'anatomy_spine_fold':
            affected = ['pelvis', 'neck', joint, names[rig.parents[names.index(joint)]]]
        elif reason == 'anatomy_neck_fold':
            affected = ['spine3', 'neck', 'head']
        elif reason == 'anatomy_torso_bend':
            affected = ['left_hip', 'right_hip', 'spine1']
            affected += ['left_shoulder', 'right_shoulder'] if joint == 'shoulders' else ['neck']
        elif reason == 'anatomy_chest_attachment':
            affected = ['spine3', 'neck']
            affected += ['left_shoulder', 'right_shoulder'] if joint == 'shoulders' else ['left_collar', 'right_collar']
        else:
            raise ValueError('Missing anatomy residual dependencies: '+reason)
        dependency = joint_dependencies(rig, affected)
        dependency[:3] = 0.
        dependency[rig.slots[rig.root]:rig.slots[rig.root]+3] = 0.
        rows.append(dependency)
    return np.stack(rows)


def body_relative_points(points, names):
    axes = body_orientation_axes(points,names)
    basis = frame_basis(axes[:,1],axes[:,0])
    relative = points-points[:,names.index('pelvis'):names.index('pelvis')+1]
    return np.einsum('fji,fkj->fki',basis,relative)


def weighted_settling_speed(points, names, fps, weights):
    relative = body_relative_points(points, names)
    return float(np.sqrt(np.sum((np.diff(relative, axis=0)*fps*weights)**2)
                         / max(np.sum(weights)*3, 1.)))


def settling_hold_basis(temporal_reference, working_reference, body_support):
    """Choose the motion whose quiet holds define settling for this fit.

    Preview variants keep the immutable source articulation baseline. When
    observed support intentionally rewrites geometry, that supported reference
    is the trajectory the optimizer starts from—and the only reachable quiet
    hold baseline for acceptance.
    """
    if isinstance(body_support, dict) and body_support.get('required'):
        return working_reference
    return temporal_reference


def support_joint_range_preserved(articulation_ratios):
    """Under body support, jointRange is articulation excursion only.

    World-space spans also encode torso placement/orientation that observed
    support is allowed to correct, so they must not AND with articulation.
    """
    return (all(ratio >= .85 for ratio in articulation_ratios.values())
            if articulation_ratios else True)


def contact_heel_repair_eligible(checks, joint_range_ratios):
    """Admit coupled foot repair when its only range failure is at the foot."""
    if not isinstance(checks, dict):
        return False
    failed = set(failed_check_names(checks))
    if failed == {'sourceFootContactArticulation'}:
        return True
    if failed != {'sourceFootContactArticulation', 'jointRange'}:
        return False
    if not isinstance(joint_range_ratios, dict) or not joint_range_ratios:
        return False
    try:
        ratios = [(str(name), float(ratio))
                  for name, ratio in joint_range_ratios.items()]
    except (TypeError, ValueError, OverflowError):
        return False
    if not ratios or any(not np.isfinite(ratio) for _, ratio in ratios):
        return False
    below_limit = [(name, ratio) for name, ratio in ratios if ratio < .85]
    # The heel repair owns foot pitch and the coupled ankle excursion. It must
    # not be used to admit unrelated range failures elsewhere in the body.
    return bool(below_limit) and all(
        np.isfinite(ratio) and name in {
            'left_ankle', 'right_ankle', 'left_foot', 'right_foot'}
        for name, ratio in below_limit
    )


def supported_ankle_episode_range_ratios(reference, candidate, names, masks, evidence_masks):
    """Measure ankle excursion separately on full-sole and raw-evidence spans."""
    source = np.asarray(reference, dtype=float)
    result = np.asarray(candidate, dtype=float)
    ratios, episodes = {}, {}
    for side, mask in (masks or {}).items():
        ankle, foot = f'{side}_ankle', f'{side}_foot'
        knee = f'{side}_knee'
        if not {knee, ankle, foot}.issubset(names):
            continue
        mask = np.asarray(mask, dtype=bool)
        observed = np.asarray((evidence_masks or {}).get(side, np.zeros(len(source), dtype=bool)),
                              dtype=bool)
        if mask.shape != (len(source),) or observed.shape != (len(source),):
            continue
        joints = [names.index(knee), names.index(ankle), names.index(foot)]
        source_angles = angles(*(source[:, joint] for joint in joints))
        result_angles = angles(*(result[:, joint] for joint in joints))
        side_ratios, side_episodes = [], []
        for authority, interval_mask in (
                ('full_sole', mask & observed), ('raw_contact_state', ~mask & observed)):
            edges = np.diff(np.r_[False, interval_mask, False].astype(np.int8))
            for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                source_range = float(np.ptp(source_angles[start:stop]))
                if source_range <= np.deg2rad(20.):
                    continue
                ratio = float(np.ptp(result_angles[start:stop]) / source_range)
                side_ratios.append(ratio)
                side_episodes.append({
                    'authority': authority, 'startFrame': int(start),
                    'endFrame': int(stop - 1), 'preservedRatio': ratio,
                })
        if side_ratios:
            label = f'{side}_ankle'
            ratios[label] = min(side_ratios)
            episodes[label] = side_episodes
    return ratios, episodes


def smooth_extremity_coordinates(coordinates, rig, names, *, cyclic, sigma=1.5,
                                 pinned=None, include_knees=False):
    """Temporally smooth extremity local rotations (discontinuity owners).

    Only fully stationary extremity slots are skipped. Alternating plant/swing
    feet must remain smoothable; planted-at-event spikes are repaired via plant
    continuity after free distal-chain passes.
    """
    smoothed = np.asarray(coordinates, dtype=float).copy()
    mode = 'wrap' if cyclic else 'nearest'
    always_planted = np.zeros(len(names), dtype=bool)
    if pinned is not None:
        always_planted = np.all(np.asarray(pinned, dtype=bool), axis=0)
    suffixes = ('ankle', 'foot', 'wrist', 'hand', 'elbow') + (('knee',) if include_knees else ())
    for joint, name in enumerate(names):
        if always_planted[joint]:
            continue
        if not name.endswith(suffixes):
            continue
        slot = rig.slots.get(joint)
        if slot is None:
            continue
        smoothed[:, slot:slot + 3] = gaussian_filter1d(
            smoothed[:, slot:slot + 3], sigma, axis=0, mode=mode)
    return smoothed


def repair_motion_discontinuity_coordinates(coordinates, rig, names, *, cyclic, fps,
                                            pinned=None, scale=None, contact_targets=None):
    """Clear fit-introduced extremity velocity discontinuities.

    Free distal chains escalate temporal smooth (including knees). Spikes on
    joints planted at the event are contact/root continuity: temporally filter
    those plant targets and re-project without dragging always-planted anchors
    via extremity gaussian.
    """
    from .temporal_quality import track_discontinuity_metrics

    repaired = np.asarray(coordinates, dtype=float).copy()
    root = names[rig.root]
    body_height = None if scale is None else float(scale)
    pin = None if pinned is None else np.asarray(pinned, dtype=bool)

    def metrics(coords):
        points = rig.decode(coords)
        height = body_height
        if height is None:
            height = float(np.median(np.linalg.norm(np.ptp(points, axis=1), axis=-1)))
        return track_discontinuity_metrics(
            {name: points[:, j].tolist() for j, name in enumerate(names)},
            root_joint=root, fps=fps, body_height=height)

    report = metrics(repaired)
    if not report.get('severe'):
        return repaired
    for sigma, knees in ((1.5, False), (2.5, True), (4.0, True)):
        repaired = smooth_extremity_coordinates(
            repaired, rig, names, cyclic=cyclic, sigma=sigma, pinned=pin,
            include_knees=knees)
        report = metrics(repaired)
        if not report.get('severe'):
            return repaired
    # Remaining events on currently planted contacts: smooth plant targets.
    if pin is None or contact_targets is None or not np.any(pin):
        return repaired
    targets = np.asarray(contact_targets, dtype=float).copy()
    if targets.shape != rig.decode(repaired).shape:
        return repaired
    event_joints = {
        names.index(event['joint'])
        for event in (report.get('events') or [])
        if isinstance(event, dict) and event.get('joint') in names
    }
    planted_event_joints = [
        joint for joint in event_joints
        if pin[:, joint].any() and not np.all(pin[:, joint])
    ]
    if not planted_event_joints:
        # Fully stationary plant spike: still regularize that plant trajectory.
        planted_event_joints = [
            joint for joint in event_joints if np.all(pin[:, joint])
        ]
    if not planted_event_joints:
        return repaired
    mode = 'wrap' if cyclic else 'nearest'
    for joint in planted_event_joints:
        active = pin[:, joint]
        if not np.any(active):
            continue
        filtered = gaussian_filter1d(targets[:, joint], 2.0, axis=0, mode=mode)
        targets[active, joint] = filtered[active]
    repaired = project_contact_plant_coordinates(
        repaired, rig, pin, targets, max_nfev=30, freeze_root=True)
    return repaired


def temporal_coordinate_smooth(coordinates, *, cyclic, sigma=1.0):
    """Mild temporal smooth on local rotations to cut excess post-fit jerk."""
    smoothed = np.array(coordinates, dtype=float, copy=True)
    mode = 'wrap' if cyclic else 'nearest'
    smoothed[:, 3:] = gaussian_filter1d(smoothed[:, 3:], sigma, axis=0, mode=mode)
    return smoothed


def temporal_free_coordinate_smooth(coordinates, rig, pinned, *, cyclic, sigma=1.0):
    """Smooth a rotation only at frames where its descendants are unplanted.

    Preserve held keyframes while allowing swing and approach motion to smooth.
    The caller still checks/restores interpolated contacts: neighboring free
    samples can change the tangent entering a held interval.
    """
    smoothed = np.asarray(coordinates, dtype=float).copy()
    if smoothed.ndim != 2 or smoothed.shape[1] < 6:
        return smoothed
    mode = 'wrap' if cyclic else 'nearest'
    filtered = gaussian_filter1d(smoothed, float(sigma), axis=0, mode=mode)
    locked = np.zeros((len(smoothed), len(rig.names)), dtype=bool)
    if pinned is not None:
        # A swinging limb is free even if it plants later in the clip. Global
        # plant membership prevented smoothing the approach to every touchdown.
        for joint in range(pinned.shape[1]):
            active = pinned[:, joint]
            ancestor = joint
            while ancestor >= 0:
                locked[:, ancestor] |= active
                ancestor = rig.parents[ancestor]
    for joint, start in rig.slots.items():
        free = ~locked[:, joint]
        smoothed[free, start:start + 3] = filtered[free, start:start + 3]
    return smoothed


def polish_free_temporal_preserving_anatomy(
        coordinates, rig, pinned, contact_targets, *, cyclic, sigma,
        deadline=None, floor=None, fps=30., spike_reference=None, reference=None):
    """Free-DOF temporal smooth, then restore physical anatomy if it opened.

    Mild/strong free-chain smooth clears Stage-C jerk on path-repaired clips, but
    spine smoothing can trip anatomy_torso_bend. A bounded anatomical repair brings
    physical back while keeping the lower third-difference roughness.
    """
    trial = temporal_free_coordinate_smooth(
        coordinates, rig, pinned, cyclic=cyclic, sigma=sigma)
    if np.allclose(trial, coordinates):
        return np.asarray(coordinates, dtype=float).copy()
    previous_initial = rig.initial.copy()
    previous_offsets = rig.offsets.copy()
    rig.initial[:] = trial
    try:
        from .anatomical_repair import repair_rig_anatomy
        anatomy_deadline = (
            deadline if deadline is not None else monotonic() + 12.)
        _, polish = repair_rig_anatomy(
            rig, rig.decode(rig.initial), deadline=anatomy_deadline,
            reference=reference)
        if not polish.get('passed'):
            rig.initial[:] = previous_initial
            rig.offsets[:] = previous_offsets
            return np.asarray(coordinates, dtype=float).copy()
        trial = np.asarray(rig.initial, dtype=float).copy()
        if pinned is not None and np.any(pinned) and contact_targets is not None:
            play_before = _playback_contact_sample_error(
                coordinates, rig, pinned, contact_targets, cyclic=cyclic)
            play_after = _playback_contact_sample_error(
                trial, rig, pinned, contact_targets, cyclic=cyclic)
            if (play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or play_after > play_before * 1.05 + 1e-9
                    or _playback_failing_intervals(
                        trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor)):
                plant_deadline = deadline
                trial = project_contact_plant_coordinates(
                    trial, rig, pinned, contact_targets, max_nfev=12,
                    freeze_root=True, deadline=plant_deadline)
                if _playback_failing_intervals(
                        trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                    trial = project_interval_playback_plants(
                        trial, rig, pinned, contact_targets, cyclic=cyclic,
                        floor=floor, max_nfev=10, deadline=plant_deadline,
                        spike_reference=spike_reference)
                trial = repair_playback_velocity_continuity(
                    trial, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.4,
                    deadline=plant_deadline, floor=floor, fps=fps,
                    spike_reference=spike_reference)
                rig.initial[:] = trial
        return trial
    except Exception:
        rig.initial[:] = previous_initial
        rig.offsets[:] = previous_offsets
        return np.asarray(coordinates, dtype=float).copy()



def polish_worsened_jerk(report, previous_jerk):
    """True when a polish block raised third-difference roughness past prior."""
    if previous_jerk is None:
        return False
    after = report.get('jerkAfter')
    if after is None:
        return False
    return float(after) > float(previous_jerk) * 1.05 + 1e-12


def stage_c_temporal_smoothing_rejection_reasons(
        *, contact_after, playback_contact_after, failed_checks, previous_failed_checks,
        previous_jerk, report, previous_nested, nested_after):
    """Reject temporal smoothing only when it breaks an acceptance constraint."""
    reasons = []
    if contact_after >= KEYFRAME_CONTACT_LIMIT_METERS:
        reasons.append('keyframe_contact_limit_exceeded')
    if playback_contact_after >= PLAYBACK_CONTACT_LIMIT_METERS:
        reasons.append('playback_contact_limit_exceeded')
    if 'jerk' in set(failed_checks):
        reasons.append('jerk_not_cleared')
    introduced = ({'anatomy', 'sourceArticulation', 'contacts'}
                  & set(failed_checks)) - set(previous_failed_checks)
    if introduced:
        reasons.extend(f'new_{check}_failure' for check in sorted(introduced))
    if polish_worsened_jerk(report, previous_jerk):
        reasons.append('jerk_worsened')
    if 'velocity' not in previous_nested and 'velocity' in nested_after:
        reasons.append('playback_velocity_regressed')
    return reasons


def polish_reserve_seconds(timeout_seconds, *, cyclic):
    """Wall-clock reserved at the end of the outer budget for Stage-B/C polish."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return 0.
    base = min(POLISH_RESERVE_MAX_SECONDS, max(POLISH_RESERVE_MIN_SECONDS,
                                              POLISH_RESERVE_FRACTION * float(timeout_seconds)))
    reserve = float(base if cyclic else min(base, 15.))
    # Short diagnose budgets: keep polish, but leave anatomy/support enough room.
    if float(timeout_seconds) < 180.:
        reserve = min(reserve, 0.12 * float(timeout_seconds), 15.)
    return min(reserve, max(0., 0.4 * float(timeout_seconds)))


def fit_validation_reserve_seconds(frame_count, timeout_seconds):
    """Reserve time for full-payload checks before allowing soft LS to finish.

    Playback validation cost grows with the number of frames. A bounded estimate
    keeps long fits from spending the validation window on optimization while
    avoiding a fixed surcharge on short diagnostic fits.
    """
    timeout = max(0., float(timeout_seconds or 0.))
    frames = max(0, int(frame_count or 0))
    return min(25., 0.20 * frames, 0.25 * timeout)


def joint_plant_initialization_deadline(
        fit_started, timeout_seconds, *, polish_reserve_seconds,
        validation_reserve_seconds):
    """Give plant initialization the available fit time while protecting later stages."""
    return (float(fit_started) + max(0., float(timeout_seconds))
            - max(0., float(polish_reserve_seconds))
            - max(0., float(validation_reserve_seconds))
            - MIN_USEFUL_FIT_SECONDS)


def fit_soft_solve_deadline(
        *, fit_started, timeout_seconds, now, nominal_solve_seconds,
        validation_reserve_seconds, post_validation_polish_seconds):
    """Cap soft LS so validation and a strict post-fit repair window can run."""
    fit_deadline = float(fit_started) + max(0., float(timeout_seconds))
    protected = max(0., float(validation_reserve_seconds)) + max(
        0., float(post_validation_polish_seconds))
    remaining = max(0., fit_deadline - float(now))
    solve_budget = min(max(0., float(nominal_solve_seconds)), max(0., remaining - protected))
    solve_deadline = min(fit_deadline - protected, float(now) + solve_budget)
    return solve_deadline, solve_budget


def supported_geometry_ready_for_skip_soft_solve(
        *, anchored, playback_anchored, floor_clear, points, names, equipment, payload,
        support_strategy=None, playback_support_geometry_passed=True,
        source_support_trajectory_passed=True):
    """Skip supported geometry only when any required loop seam also passes.

    Long plant-only clips were burning ~150s of soft LS after plants were under
    gate; that raised jerk and consumed the Stage-C polish window. Rigid-pair
    grip leftovers belong to Stage-A hard projection, not soft LS.
    """
    del playback_anchored, equipment
    if not (anchored and floor_clear and playback_support_geometry_passed
            and source_support_trajectory_passed):
        return False
    if support_strategy == 'plant_projection':
        if (payload.get('loop') or {}).get('enabled'):
            # Plants alone do not make a cyclic trajectory ready. The main
            # optimizer owns joint contact/temporal/seam correction; skipping it
            # here strands an open seam in contact-only hard refinement.
            from .loop_seam import seam_quality_metrics
            fps = float(payload.get('fps') or 0.)
            if fps <= 0 or not seam_quality_metrics(
                    points, fps=fps, scale=body_scale(points, names))['seamContinuous']:
                return False
        return True
    return False


def seam_boundary_coordinate_nudge(coordinates, rig, pinned, *, strength=0.55):
    """Cheap first/last free-DOF blend to shrink loop restart hitch before Stage-B LS.

    When any contact is planted, skip root translation — moving the pelvis would
    drag anchored feet. Close the seam on free rotation DOFs, including a
    world-tip pull so free hands/head actually move toward continuity.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3 or strength <= 0:
        return coords
    planted = bool(np.any(pinned))
    if not planted:
        delta_t = coords[0, :3] - coords[-1, :3]
        coords[0, :3] -= 0.5 * strength * delta_t
        coords[-1, :3] += 0.5 * strength * delta_t
    planted_chain = set(_plant_chain_slots(rig, pinned))
    free_joints = [j for j in range(pinned.shape[1]) if j not in planted_chain]
    free_cols = []
    for joint in free_joints:
        slot = rig.slots.get(joint)
        if slot is None:
            continue
        free_cols.extend(range(slot, slot + 3))
        first = Rotation.from_rotvec(coords[0, slot:slot + 3])
        last = Rotation.from_rotvec(coords[-1, slot:slot + 3])
        delta = (first.inv() * last).as_rotvec()
        coords[0, slot:slot + 3] = (first * Rotation.from_rotvec(0.5 * strength * delta)).as_rotvec()
        coords[-1, slot:slot + 3] = (last * Rotation.from_rotvec(-0.5 * strength * delta)).as_rotvec()
    # World-space tip pull on free joints (planted or not): rotation blends alone
    # leave multi-cm hand/head hitches when the hitch is translational in FK.
    if free_joints:
        from .loop_seam import seam_errors
        rig.initial[:] = coords
        points = rig.decode(coords)
        step, _, _ = seam_errors(points)
        for joint in free_joints:
            slot = rig.slots.get(joint)
            parent = rig.parents[joint]
            if slot is None or parent < 0:
                continue
            for frame, sign in ((0, -1.), (-1, 1.)):
                parent_pos = points[frame, parent]
                current = points[frame, joint]
                target = current + sign * 0.5 * strength * step[joint]
                current_dir = current - parent_pos
                desired_dir = target - parent_pos
                if (np.linalg.norm(current_dir) < 1e-8 or np.linalg.norm(desired_dir) < 1e-8):
                    continue
                delta = align_vectors(current_dir[None], desired_dir[None])[0]
                rot = Rotation.from_rotvec(coords[frame, slot:slot + 3])
                coords[frame, slot:slot + 3] = (
                    Rotation.from_rotvec(strength * delta) * rot).as_rotvec()
        # Refresh for neighbor blend after tip pull.
        rig.initial[:] = coords
    # Neighbor frames: reduce velocity mismatch at the wrap on free DOFs only.
    if len(coords) >= 4 and free_cols:
        cols = np.asarray(free_cols, dtype=int)
        blend = (0.25 if planted else 0.45) * strength
        coords[1, cols] = (1. - blend) * coords[1, cols] + blend * coords[0, cols]
        coords[-2, cols] = (1. - blend) * coords[-2, cols] + blend * coords[-1, cols]
        if not planted and len(coords) >= 6:
            coords[2, cols] = (1. - 0.5 * blend) * coords[2, cols] + 0.5 * blend * coords[1, cols]
            coords[-3, cols] = (1. - 0.5 * blend) * coords[-3, cols] + 0.5 * blend * coords[-2, cols]
    return coords


def seam_velocity_neighbor_nudge(coordinates, rig, pinned, *, strength=0.55):
    """Extrapolate frames 1/-2 so wrap incoming/outgoing match the endpoint step.

    Operates in coordinate space on free DOFs (and root translation when
    unplanted). Scored by close_loop_seam_coordinates so regressions are dropped.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 4 or strength <= 0:
        return coords
    planted = bool(np.any(pinned))
    if planted:
        free_cols = []
        planted_chain = set(_plant_chain_slots(rig, pinned))
        for joint in range(pinned.shape[1]):
            if joint in planted_chain:
                continue
            slot = rig.slots.get(joint)
            if slot is not None:
                free_cols.extend(range(slot, slot + 3))
        if not free_cols:
            return coords
        cols = np.asarray(free_cols, dtype=int)
    else:
        cols = np.arange(coords.shape[1], dtype=int)
    # Continuous wrap: coords[1]-coords[0] ≈ coords[0]-coords[-1]
    # and coords[-1]-coords[-2] ≈ coords[0]-coords[-1].
    target_1 = 2. * coords[0] - coords[-1]
    target_m2 = 2. * coords[-1] - coords[0]
    coords[1, cols] = (1. - strength) * coords[1, cols] + strength * target_1[cols]
    coords[-2, cols] = (1. - strength) * coords[-2, cols] + strength * target_m2[cols]
    return coords


def seam_playback_over_limit_score(points, *, scale, fps):
    """Max of step/velocity over-limit ratios used by playback acceptance."""
    from .loop_seam import (
        seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO)
    _, excess, increments = seam_errors(points)
    step_limit = MAX_STEP_EXCESS_BODY_RATIO * float(scale)
    vel_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * float(scale)
    step_ratio = float(np.max(excess, initial=0.)) / step_limit if step_limit > 0 else 0.
    velocity = float(np.max(np.linalg.norm(increments, axis=-1), initial=0.)) * float(fps)
    vel_ratio = velocity / vel_limit if vel_limit > 0 else 0.
    return max(step_ratio, vel_ratio)


def project_contact_root_translation(coordinates, rig, pinned, contact_targets, passes=3,
                                     *, smooth_fps=None):
    """Per-frame root translation that aligns planted contacts to their targets.

    Soft LS under support often stalls a few tenths of a millimeter over the
    contact gate while burning polish. A rigid root shift clears that residual
    without inventing free-limb articulation. A few passes absorb decode
    nonlinearities from dependent rotations. Optional smooth_fps temporally
    filters the per-frame shifts so contact snap does not reintroduce root spikes.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if coords.ndim != 2 or not np.any(pinned):
        return coords
    targets = np.asarray(contact_targets, dtype=float)
    for _ in range(max(1, int(passes))):
        points = rig.decode(coords)
        shifts = np.zeros((len(coords), 3), dtype=float)
        max_shift = 0.
        for frame in range(len(coords)):
            mask = pinned[frame]
            if not np.any(mask):
                continue
            delta = np.mean(targets[frame, mask] - points[frame, mask], axis=0)
            if np.isfinite(delta).all():
                shifts[frame] = delta
                max_shift = max(max_shift, float(np.linalg.norm(delta)))
        if smooth_fps is not None and max_shift > 0.:
            sigma = max(.5, float(smooth_fps) * .08)
            shifts = gaussian_filter1d(shifts, sigma, axis=0, mode='nearest')
        coords[:, :3] += shifts
        if max_shift < 1e-7:
            break
    return coords


def _sampling_payload(rig, coordinates):
    return {
        'jointNames': list(rig.names),
        'parents': rig.parents,
        'order': rig.order,
        'offsets': rig.offsets,
        'rotationJointNames': [rig.names[j] for j in rig.active],
        'interpolation': INTERPOLATION,
        'coordinates': np.asarray(coordinates, dtype=float),
    }


def _plant_chain_slots(rig, pinned):
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    chain = set()
    for joint in plant_joints:
        ancestor = joint
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    return sorted(chain)


def _playback_contact_sample_error(coordinates, rig, pinned, contact_targets, *, cyclic=False):
    """Peak planted-contact error on the same quarter-frame samples playback uses."""
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned):
        return 0.
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    first = np.floor(cursors).astype(int)
    last = (first + 1) % count if cyclic else np.minimum(first + 1, count - 1)
    active = pinned[first] & pinned[last]
    if not np.any(active):
        return 0.
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    return float(np.max(np.linalg.norm((sampled - targets[first])[active], axis=-1), initial=0.))


def playback_contact_repair_needed(coordinates, rig, pinned, contact_targets, *, cyclic=False):
    """Avoid perturbing planted geometry when an unrelated repair leaves it valid."""
    pinned = np.asarray(pinned, dtype=bool)
    if not np.any(pinned):
        return False
    points = rig.decode(np.asarray(coordinates, dtype=float))
    targets = np.asarray(contact_targets, dtype=float)
    keyframe_error = float(np.max(
        np.linalg.norm((points - targets)[pinned], axis=-1), initial=0.))
    if keyframe_error >= SUPPORT_REFERENCE_CONTACT_LIMIT_METERS:
        return True
    return _playback_contact_sample_error(
        coordinates, rig, pinned, targets, cyclic=cyclic,
    ) >= PLAYBACK_CONTACT_LIMIT_METERS


def _playback_vertical_contact_sample_error(
        coordinates, rig, vertical_mask, vertical_targets, *, cyclic=False,
        contact_foot_tracks=None):
    """Peak height-only contact error at the production playback subframes."""
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(vertical_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(vertical_mask):
        return 0.
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    first = np.floor(cursors).astype(int)
    last = (first + 1) % count if cyclic else np.minimum(first + 1, count - 1)
    active = vertical_mask[first] & vertical_mask[last]
    if not np.any(active):
        return 0.
    sampling_payload = _sampling_payload(rig, coords)
    if contact_foot_tracks is not None:
        sampling_payload['contactFootTracks'] = contact_foot_tracks
    sampled = sample_rig(sampling_payload, cursors, wrap=cyclic)
    return float(np.max(np.abs(sampled[:, :, 1][active] - targets[first, :, 1][active]), initial=0.))


def _playback_support_geometry_passed(coordinates, rig, payload, *, cyclic=False):
    """Check stationary support across interpolated frames before skipping fit."""
    from .support_geometry import support_evidence, validate_support_geometry

    if not support_evidence(payload).get('required'):
        return True
    count = len(coordinates)
    if count < 2:
        return False
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coordinates), cursors, wrap=cyclic)
    return bool(validate_support_geometry(payload, sampled, rig.names)['passed'])


def _playback_floor_penetration(coordinates, rig, *, cyclic=False, floor=None):
    if floor is None or len(coordinates) < 2:
        return 0.
    from .rig_playback import sample_rig
    count = len(coordinates)
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coordinates), cursors, wrap=cyclic)
    return max(0., float(floor) - float(sampled[:, :, 1].min()))


def _playback_interval_for_sample(sample_index, cursors, frame_count):
    cursor = float(cursors[int(sample_index)])
    first = min(int(np.floor(cursor)), frame_count - 1)
    return cursor, first, (first + 1) % frame_count


def _playback_failing_intervals(coordinates, rig, pinned, contact_targets, *,
                                cyclic=False, floor=None):
    """One clip-wide quarter-frame sample; return planted intervals over the gate."""
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned):
        return []
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    first = np.floor(cursors).astype(int)
    last = (first + 1) % count if cyclic else np.minimum(first + 1, count - 1)
    active = pinned[first] & pinned[last]
    if not np.any(active):
        return []
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    keyframe = rig.decode(coords)
    failing = []
    for start in range(interval_count):
        rows = slice(start * 3, start * 3 + 3)
        mask = active[rows]
        if not np.any(mask):
            continue
        frames = (start, (start + 1) % count)
        pair_pin = pinned[list(frames)]
        play_err = float(np.max(np.linalg.norm(
            (sampled[rows] - targets[start])[mask], axis=-1), initial=0.))
        key_err = float(np.max(np.linalg.norm(
            (keyframe[list(frames)] - targets[list(frames)])[pair_pin], axis=-1), initial=0.))
        floor_err = 0. if floor is None else max(
            0., float(floor) - float(sampled[rows, :, 1].min()))
        if (play_err >= PLAYBACK_CONTACT_LIMIT_METERS
                or key_err >= KEYFRAME_CONTACT_LIMIT_METERS
                or floor_err > PLAYBACK_FLOOR_LIMIT_METERS):
            failing.append(int(start))
    return failing


def project_reliable_knee_hinge_planes(coordinates, rig, source_references, *,
                                       playback_reference=None, fps=30., cyclic=False,
                                       deadline=None, max_passes=3):
    """Restore failed reliable knee planes by rotating the exact 2-bone pole.

    Root, hip sockets, ankles, feet, both segment lengths, and knee flexion stay
    fixed by construction. Keyframes use each supplied independent source
    reference; playback samples use the same more-flexed endpoint reference as
    ``validate_rig_playback``. Existing hinge tolerances remain authoritative,
    with a half-degree interior margin for numerical/interpolation stability.
    """
    from .foot_kinematics import _source_knee_poles, _transport_knee_poles
    from .structural_refinement import _source_branch_is_temporally_supported
    from .rig_playback import sample_rig

    coords = np.asarray(coordinates, dtype=float).copy()
    original_coords = coords.copy()
    points = rig.decode(coords)
    names = rig.names
    name_index = {name: i for i, name in enumerate(names)}
    refs = []
    for reference in source_references:
        if reference is None:
            continue
        candidate = np.asarray(reference, dtype=float)
        if candidate.shape == points.shape and np.isfinite(candidate).all():
            if not any(np.array_equal(candidate, existing) for existing in refs):
                refs.append(candidate)
    if not refs or not np.isfinite(points).all():
        return original_coords, {'attempted': False, 'reason': 'no_compatible_source_reference'}
    if playback_reference is None:
        playback_reference = refs[0]
    playback_reference = np.asarray(playback_reference, dtype=float)
    if playback_reference.shape != points.shape or not np.isfinite(playback_reference).all():
        playback_reference = refs[0]
    if deadline is not None and monotonic() >= deadline:
        return original_coords, {'attempted': False, 'reason': 'deadline_expired'}

    knee_specs = [(label, a, h, b, tolerance)
                  for label, a, h, b, tolerance in ARTICULATIONS
                  if label.endswith('_knee') and all(n in name_index for n in (
                      a, h, b, f"{label.split('_', 1)[0]}_foot"))]
    knee_sides = tuple(dict.fromkeys(spec[0].split('_', 1)[0] for spec in knee_specs))
    if not knee_specs:
        return original_coords, {'attempted': False, 'reason': 'no_supported_knee_chain'}
    hinge_specs = [spec for spec in ARTICULATIONS
                   if spec[0].endswith(('_knee', '_elbow'))]
    hinge_column = {spec[0]: i for i, spec in enumerate(hinge_specs)}
    def make_source_info(reference, sample_fps):
        parent, bend, strength = hinge_coordinates(reference, names)
        reliability = {}
        poles = {}
        for label, *_parts, _tolerance in knee_specs:
            column = hinge_column[label]
            track = list(zip(parent[:, column], bend[:, column]))
            branch = np.asarray([
                _source_branch_is_temporally_supported(
                    track, frame, max(1, round(float(sample_fps)*.1)))
                for frame in range(len(reference))], dtype=bool)
            reliability[label] = branch & (strength[:, column] > np.sin(np.deg2rad(15.)))
        for side in knee_sides:
            hip_i, knee_i, ankle_i = (name_index[f'{side}_{part}']
                                       for part in ('hip', 'knee', 'ankle'))
            poles[side] = _source_knee_poles(
                reference[:, hip_i], reference[:, knee_i], reference[:, ankle_i])
        return {'source': reference, 'parent': parent, 'bend': bend, 'strength': strength,
                'reliability': reliability, 'poles': poles}

    reference_info = [make_source_info(ref, fps) for ref in refs]

    def events_from_info(current, infos, *, reference_ids=None):
        current_parent, current_bend, current_strength = hinge_coordinates(current, names)
        events = []
        for ref_id, info in enumerate(infos):
            if reference_ids is not None:
                ref_id = reference_ids[ref_id]
            for label, *_parts, tolerance in knee_specs:
                column = hinge_column[label]
                active = info['reliability'][label] & (
                    current_strength[:, column] > np.sin(np.deg2rad(15.)))
                if not np.any(active):
                    continue
                dots = transported_hinge_dots(
                    info['parent'], info['bend'], current_parent, current_bend)[:, column]
                for frame in np.flatnonzero(active & (dots < np.cos(np.deg2rad(tolerance)))):
                    events.append({'reason': 'repair_hinge_direction_distortion',
                                   'joint': label, 'frameIndex': int(frame),
                                   'changeDegrees': float(np.rad2deg(np.arccos(
                                       np.clip(dots[frame], -1., 1.)))),
                                   'toleranceDegrees': float(tolerance),
                                   '_referenceIndex': int(ref_id)})
        return events

    def key_events(current):
        return events_from_info(current, reference_info)

    def source_reliable(ref_id, label, frame):
        return bool(reference_info[int(ref_id)]['reliability'][label][frame])

    def world_matrices(frame, values):
        local = Rotation.from_rotvec(values[frame, 3:].reshape(-1, 3)).as_matrix()
        matrices = {}
        for joint in rig.order:
            slot = rig.slots.get(joint)
            rotation = local[(slot - 3)//3] if slot is not None else np.eye(3)
            parent = rig.parents[joint]
            matrices[joint] = rotation if parent < 0 else matrices[parent] @ rotation
        return matrices

    def alignment_rotation(source, target):
        return Rotation.from_rotvec(align_vectors(
            np.asarray(source, dtype=float)[None, :],
            np.asarray(target, dtype=float)[None, :])[0])

    def knee_from_pole(frame, side, theta, current):
        hip_i, knee_i, ankle_i = (name_index[f'{side}_{part}']
                                   for part in ('hip', 'knee', 'ankle'))
        hip, knee, ankle = current[frame, hip_i], current[frame, knee_i], current[frame, ankle_i]
        leg = ankle - hip
        distance = float(np.linalg.norm(leg))
        if distance < 1e-10:
            return None
        axis = leg / distance
        thigh = knee - hip
        lower = ankle - knee
        upper_length, lower_length = float(np.linalg.norm(thigh)), float(np.linalg.norm(lower))
        along = (upper_length**2 - lower_length**2 + distance**2)/(2.*distance)
        radius_sq = upper_length**2 - along**2
        if radius_sq < -1e-10:
            return None
        pole = thigh - axis*np.dot(thigh, axis)
        pole_length = float(np.linalg.norm(pole))
        if pole_length < 1e-10:
            return None
        pole /= pole_length
        pole = Rotation.from_rotvec(axis*float(theta)).apply(pole)
        return hip + along*axis + np.sqrt(max(0., radius_sq))*pole

    def source_direction(frame, side, info):
        hip_i, knee_i, ankle_i = (name_index[f'{side}_{part}']
                                   for part in ('hip', 'knee', 'ankle'))
        axis = unit(points[frame:frame+1, ankle_i]-points[frame:frame+1, hip_i])[0]
        thigh = points[frame, knee_i]-points[frame, hip_i]
        pole = unit((thigh-axis*np.dot(thigh, axis))[None, :])[0]
        source_poles = info['poles'][side]
        target = _transport_knee_poles(
            source_poles[frame:frame+1],
            info['source'][frame:frame+1, ankle_i]-info['source'][frame:frame+1, hip_i],
            points[frame:frame+1, ankle_i]-points[frame:frame+1, hip_i],
        )[0]
        target = unit((target-axis*np.dot(target, axis))[None, :])[0]
        signed = float(np.arctan2(np.dot(axis, np.cross(pole, target)), np.dot(pole, target)))
        return float(np.sign(signed)) if abs(signed) > 1e-8 else 1.

    def reencode_leg(frame, side, old_knee, new_knee, values, current):
        hip, knee, ankle, foot = (name_index[f'{side}_{part}']
                                  for part in ('hip', 'knee', 'ankle', 'foot'))
        world = world_matrices(frame, values)
        parent = rig.parents[knee]
        delta_knee = alignment_rotation(old_knee-current[frame, hip], new_knee-current[frame, hip])
        new_world_knee = delta_knee.as_matrix() @ world[knee]
        old_calf = current[frame, ankle]-old_knee
        new_calf = current[frame, ankle]-new_knee
        delta_ankle = alignment_rotation(old_calf, new_calf)
        new_world_ankle = delta_ankle.as_matrix() @ world[ankle]
        new_local_knee = world[parent].T @ new_world_knee
        new_local_ankle = new_world_knee.T @ new_world_ankle
        new_local_foot = new_world_ankle.T @ world[foot]
        for joint, local in ((knee, new_local_knee), (ankle, new_local_ankle),
                             (foot, new_local_foot)):
            slot = rig.slots.get(joint)
            if slot is None:
                return False
            values[frame, slot:slot+3] = Rotation.from_matrix(local).as_rotvec()
        return True

    def event_map(events):
        return {(e['joint'], int(e['frameIndex']), e['_referenceIndex']): float(e['changeDegrees'])
                for e in events}

    def preserves_leg_manifold(current, before, movable_knees):
        allowed = np.zeros(current.shape[:2], dtype=bool)
        for frame, knee_index in movable_knees:
            allowed[frame, knee_index] = True
        if np.max(np.abs(current[~allowed]-before[~allowed]), initial=0.) > 1e-9:
            return False
        for frame, knee in movable_knees:
            side = names[knee].split('_', 1)[0]
            hip, ankle = name_index[f'{side}_hip'], name_index[f'{side}_ankle']
            upper = np.linalg.norm(current[frame, knee]-current[frame, hip])
            lower = np.linalg.norm(current[frame, ankle]-current[frame, knee])
            before_upper = np.linalg.norm(before[frame, knee]-before[frame, hip])
            before_lower = np.linalg.norm(before[frame, ankle]-before[frame, knee])
            before_angle = angles(before[frame:frame+1, hip], before[frame:frame+1, knee], before[frame:frame+1, ankle])
            after_angle = angles(current[frame:frame+1, hip], current[frame:frame+1, knee], current[frame:frame+1, ankle])
            if (abs(upper-before_upper) > 1e-9 or abs(lower-before_lower) > 1e-9
                    or np.max(np.abs(after_angle-before_angle), initial=0.) > 1e-9):
                return False
        return True

    baseline_key = key_events(points)
    key_before = event_map(baseline_key)
    margin_by_joint = {label: max(0., min(tolerance, 10.)-.5)
                       for label, *_parts, tolerance in knee_specs}
    key_corrections = []

    # Correct only keyframes that have a reliable source branch and a final
    # hinge-plane failure. Each update is an exact circle rotation, then all
    # independent source references are rechecked before the next update.
    for event in sorted(baseline_key, key=lambda e: -e['changeDegrees']):
        if deadline is not None and monotonic() >= deadline:
            break
        side = event['joint'].split('_', 1)[0]
        frame = int(event['frameIndex'])
        current_event = next((current for current in key_events(points)
                              if current.get('joint') == event['joint']
                              and int(current.get('frameIndex', -1)) == frame
                              and current.get('_referenceIndex') == event['_referenceIndex']), None)
        if current_event is None:
            continue
        event = current_event
        ref = refs[int(event['_referenceIndex'])]
        if not source_reliable(event['_referenceIndex'], event['joint'], frame):
            continue
        tolerance = float(event['toleranceDegrees'])
        required_dot = np.cos(np.deg2rad(max(0., min(tolerance, 10.)-.5)))
        hip_i, knee_i, ankle_i = (name_index[f'{side}_{part}'] for part in ('hip', 'knee', 'ankle'))
        source_parent, source_bend, _ = hinge_coordinates(ref[frame:frame+1], names)
        baseline_values = coords.copy()

        def key_margin(theta):
            knee = knee_from_pole(frame, side, theta, points)
            if knee is None:
                return -np.inf
            trial = points[frame:frame+1].copy()
            trial[0, knee_i] = knee
            cp, cb, _ = hinge_coordinates(trial, names)
            dots = transported_hinge_dots(source_parent, source_bend, cp, cb)[0, hinge_column[event['joint']]]
            return float(dots-required_dot)

        direction = source_direction(frame, side, reference_info[int(event['_referenceIndex'])])
        root = None
        for sign in (direction, -direction):
            previous, previous_value = 0., key_margin(0.)
            for magnitude in np.deg2rad(np.arange(.25, 180.01, .25)):
                value = key_margin(sign*float(magnitude))
                if previous_value < 0. <= value:
                    root = sign * float(brentq(
                        lambda theta: key_margin(sign*theta), previous, float(magnitude),
                        xtol=1e-11, rtol=1e-11))
                    break
                previous, previous_value = float(magnitude), value
            if root is not None:
                break
        if root is None or abs(root) < 1e-12:
            continue
        old_knee = points[frame, knee_i].copy()
        new_knee = knee_from_pole(frame, side, root, points)
        trial_coords = coords.copy()
        if not reencode_leg(frame, side, old_knee, new_knee, trial_coords, points):
            continue
        trial_points = rig.decode(trial_coords)
        if not preserves_leg_manifold(trial_points, points, [(frame, knee_i)]):
            continue
        current_events = key_events(trial_points)
        current_map = event_map(current_events)
        # No new failures or worsened independent references are allowed.
        if any(signature not in key_before or value > key_before[signature]+1e-6
               for signature, value in current_map.items()):
            continue
        coords, points = trial_coords, trial_points
        key_corrections.append({'frameIndex': frame, 'joint': event['joint'],
                                'poleRotationDegrees': float(np.rad2deg(root)),
                                'hingeDegreesBefore': float(event['changeDegrees']),
                                'hingeDegreesAfter': float(current_map.get(
                                    (event['joint'], frame, int(event['_referenceIndex'])), 0.))})

    def playback_reference_samples():
        count = len(points)
        interval_count = count if cyclic else count-1
        cursors = (np.arange(interval_count)[:, None]+np.array([.25, .5, .75])).ravel()
        first = np.floor(cursors).astype(int)
        last = (first+1) % count
        source = playback_reference[first].copy()
        if all(n in name_index for n in ('left_hip', 'right_hip', 'spine1', 'neck')):
            def torso_angles(track):
                hips = .5*(track[:, name_index['left_hip']]+track[:, name_index['right_hip']])
                return angles(hips, track[:, name_index['spine1']], track[:, name_index['neck']])
            choose_last = torso_angles(playback_reference[last]) < torso_angles(playback_reference[first])
            source = np.where(choose_last[:, None, None], playback_reference[last], source)
        return cursors, source

    playback_cursors, playback_refs = playback_reference_samples()
    from .rig_playback import sample_rig
    playback_info = make_source_info(playback_refs, float(fps)*4)

    def playback_events(values):
        sampled = sample_rig(_sampling_payload(rig, values), playback_cursors, wrap=cyclic)
        return events_from_info(sampled, [playback_info])

    playback_before = playback_events(original_coords)
    if not baseline_key and not playback_before:
        return original_coords, {'attempted': False, 'reason': 'no_knee_hinge_failures'}
    quarter_corrections = []
    for pass_index in range(max(0, min(3, int(max_passes)))):
        handled = set()
        while True:
            if deadline is not None and monotonic() >= deadline:
                break
            events = playback_events(coords)
            event_interval = lambda e: _playback_interval_for_sample(
                e['frameIndex'], playback_cursors, len(points))[1:]
            event = next((e for e in events if event_interval(e) not in handled), None)
            if event is None:
                break
            sample_index = int(event['frameIndex'])
            cursor, lo, hi = _playback_interval_for_sample(
                sample_index, playback_cursors, len(points))
            interval = (lo, hi)
            if not cyclic and hi >= len(points):
                break
            handled.add(interval)
            side = event['joint'].split('_', 1)[0]
            reference_sample = playback_refs[sample_index]
            target_dot = np.cos(np.deg2rad(max(0., min(float(event['toleranceDegrees']), 10.)-.5)))
            directions = (source_direction(lo, side, reference_info[0]),
                          source_direction(hi, side, reference_info[0]))

            def propose_pair(degrees, signs):
                proposed = coords.copy()
                for frame, sign in zip((lo, hi), signs):
                    old_knee = points[frame, name_index[f'{side}_knee']].copy()
                    new_knee = knee_from_pole(frame, side, np.deg2rad(degrees)*sign, points)
                    if new_knee is None or not reencode_leg(
                            frame, side, old_knee, new_knee, proposed, points):
                        return None
                return proposed

            def quarter_margin(proposed):
                sampled = sample_rig(_sampling_payload(rig, proposed), np.asarray([cursor]), wrap=cyclic)
                source_parent, source_bend, _ = hinge_coordinates(reference_sample[None, ...], names)
                current_parent, current_bend, _ = hinge_coordinates(sampled, names)
                return float(transported_hinge_dots(
                    source_parent, source_bend, current_parent, current_bend
                )[0, hinge_column[event['joint']]]-target_dot)

            choices = (directions, (directions[0], -directions[1]),
                       (-directions[0], directions[1]), (-directions[0], -directions[1]))
            solution = None
            for signs in choices:
                previous, previous_value = 0., quarter_margin(coords)
                for degrees in np.arange(.1, 6.001, .1):
                    proposed = propose_pair(float(degrees), signs)
                    value = -np.inf if proposed is None else quarter_margin(proposed)
                    if previous_value < 0. <= value:
                        root = float(brentq(
                            lambda amount: quarter_margin(propose_pair(float(amount), signs)),
                            previous, float(degrees), xtol=1e-7, rtol=1e-9))
                        solution = (root, signs)
                        break
                    previous, previous_value = float(degrees), value
                if solution is not None:
                    break
            if solution is None:
                continue
            degrees, signs = solution
            trial_coords = propose_pair(degrees, signs)
            if trial_coords is None:
                continue
            trial_points = rig.decode(trial_coords)
            knee_index = name_index[f'{side}_knee']
            if not preserves_leg_manifold(trial_points, points,
                                          [(lo, knee_index), (hi, knee_index)]):
                continue
            trial_key = key_events(trial_points)
            trial_key_map = event_map(trial_key)
            if any(signature not in key_before or value > key_before[signature]+1e-6
                   for signature, value in trial_key_map.items()):
                continue
            coords, points = trial_coords, trial_points
            quarter_corrections.append({'sampleIndex': sample_index,
                                        'sampleCursor': cursor,
                                        'keyFrames': [lo, hi],
                                        'poleRotationDegrees': [degrees*sign for sign in signs]})

    key_after = key_events(points)
    playback_after = playback_events(coords)
    before_key_excess = sum(max(0., value-10.) for value in key_before.values())
    after_key_excess = sum(max(0., value-10.) for value in event_map(key_after).values())
    before_play_excess = sum(max(0., float(e['changeDegrees'])-10.) for e in playback_before)
    after_play_excess = sum(max(0., float(e['changeDegrees'])-10.) for e in playback_after)
    improved = (after_key_excess + after_play_excess < before_key_excess + before_play_excess-1e-7)
    if not improved:
        coords = original_coords
        key_after = baseline_key
        playback_after = playback_before
    diag = {
        'attempted': True, 'applied': bool(improved),
        'strategy': 'reliable_2bone_knee_pole_projection_v2_cursor_mapping',
        'keyframeFailuresBefore': len(baseline_key), 'keyframeFailuresAfter': len(key_after),
        'quarterFrameFailuresBefore': len(playback_before), 'quarterFrameFailuresAfter': len(playback_after),
        'keyframeExcessDegreesBefore': float(before_key_excess),
        'keyframeExcessDegreesAfter': float(after_key_excess),
        'quarterFrameExcessDegreesBefore': float(before_play_excess),
        'quarterFrameExcessDegreesAfter': float(after_play_excess),
        'keyframeCorrections': key_corrections,
        'quarterFrameCorrections': quarter_corrections,
        'stopReason': 'complete' if not key_after and not playback_after else 'bounded_best_improvement',
    }
    return coords, diag


def _root_shift_failing_playback_intervals(coordinates, rig, pinned, contact_targets, *,
                                           cyclic=False, floor=None, failing, passes=6,
                                           strength=1.25):
    """Rigid endpoint root shifts for failing planted intervals — no dense Jacobian."""
    del floor  # floor failures are handled by apply_supported_floor_clearance
    coords = np.asarray(coordinates, dtype=float).copy()
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if not failing:
        return coords
    from .rig_playback import sample_rig
    sample_cursors = np.array([.25, .5, .75])
    gain = float(strength)
    for _ in range(max(1, int(passes))):
        shifts = np.zeros((count, 3), dtype=float)
        weights = np.zeros(count, dtype=float)
        for start in failing:
            frames = (start, (start + 1) % count)
            pair = coords[list(frames)]
            pair_pin = pinned[list(frames)]
            active = pair_pin[0] & pair_pin[1]
            if not np.any(active):
                continue
            sampled = sample_rig(_sampling_payload(rig, pair), sample_cursors, wrap=False)
            delta = targets[start] - sampled
            mean = np.mean(delta[:, active], axis=(0, 1))
            if not np.isfinite(mean).all():
                continue
            shifts[frames[0]] += mean
            shifts[frames[1]] += mean
            weights[frames[0]] += 1.
            weights[frames[1]] += 1.
        if not np.any(weights):
            break
        max_shift = float(np.max(np.linalg.norm(
            shifts / np.maximum(weights, 1.)[:, None], axis=-1)))
        coords[:, :3] += gain * shifts / np.maximum(weights, 1.)[:, None]
        if max_shift < 1e-5:
            break
    return coords


def _distal_plant_chain_slots(rig, pinned, *, depth=2):
    """Plant joints plus movable ancestors; fixed sockets do not consume a DOF."""
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    chain = set()
    for joint in plant_joints:
        cursor = joint
        remaining = int(depth) + 1
        while cursor >= 0 and remaining:
            if cursor in rig.slots:
                chain.add(cursor)
                remaining -= 1
            cursor = rig.parents[cursor]
    return sorted(chain)


def _contiguous_interval_runs(failing):
    """Group sorted failing interval indices into contiguous inclusive runs."""
    ordered = sorted({int(f) for f in failing})
    if not ordered:
        return []
    runs = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        runs.append((start, prev))
        start = prev = value
    runs.append((start, prev))
    return runs


def _hermite_stencil_frames(intervals, count, *, cyclic):
    """Keyframe indices whose DOFs affect hermite samples on the given intervals.

    limited_tangents(frame) uses neighbors frame-1 and frame+1, so mid-samples on
    [i, i+1] depend on frames {i-1, i, i+1, i+2}. Endpoint-only TRF cannot cancel
    tangent-driven plant bows.
    """
    frames = set()
    for start in intervals:
        for frame in (int(start), (int(start) + 1) % count):
            for delta in (-1, 0, 1):
                neighbor = frame + delta
                if cyclic:
                    frames.add(neighbor % count)
                elif 0 <= neighbor < count:
                    frames.add(neighbor)
    return sorted(frames)


def _trf_playback_run_coupled(
        coordinates, intervals, rig, pinned, contact_targets, chain, *,
        cyclic=False, floor=None, max_nfev=40, deadline=None, spike_reference=None):
    """Jointly refine failing planted intervals in one full-clip hermite TRF.

    Free the hermite stencil around every failing interval (not just endpoints).
    Mid samples are batched into one sample_rig call so sparse multi-seam polish
    stays deadline-friendly.
    """
    from .rig_playback import sample_rig
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    intervals = sorted({int(start) for start in intervals})
    if not intervals:
        return coords
    frames = _hermite_stencil_frames(intervals, count, cyclic=cyclic)
    scored = [(start, 40000.) for start in intervals]
    # Soft-hold immediate neighbors so tangent edits do not spill into cleared gaps.
    interval_count = count if cyclic else count - 1
    failing_set = set(intervals)
    for start in intervals:
        for neighbor in (start - 1, start + 1):
            if cyclic:
                neighbor %= interval_count
            elif not 0 <= neighbor < interval_count:
                continue
            if neighbor not in failing_set:
                scored.append((neighbor, 5000.))
    # De-dupe while preferring the higher failing weight.
    merged = {}
    for start, weight in scored:
        merged[start] = max(merged.get(start, 0.), weight)
    scored = sorted(merged.items())
    parts = []
    for frame in frames:
        parts.append((frame, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, begin:end] for frame, begin, end in parts])
    original = x0.copy()
    frame_index = np.asarray(frames, dtype=int)
    spike_rows = np.empty(0, dtype=int)
    if spike_reference is not None:
        from .temporal_quality import SPIKE_JOINT_NAMES, introduced_joint_spike_limit
        spike_joints = [rig.names.index(name) for name in SPIKE_JOINT_NAMES]
        spike_rows = np.asarray([i for i in range(1, count - 1)
                                 if any(frame in frames for frame in (i - 1, i, i + 1))])
        source_relative = np.asarray(spike_reference) - np.asarray(spike_reference)[:, rig.root:rig.root + 1]
        before_size = .5 * np.linalg.norm(np.diff(source_relative[:, spike_joints], n=2, axis=0), axis=-1)
        initial_points = rig.decode(coords)
        spike_scale = float(np.median(np.linalg.norm(np.ptp(initial_points, axis=1), axis=-1)))
        spike_limits = introduced_joint_spike_limit(before_size[spike_rows - 1], spike_scale)
    before_play = _playback_contact_sample_error(
        coords, rig, pinned, targets, cyclic=cyclic)
    # Near the gate, prefer mid-sample closure over keyframe tightness (still
    # rejected if key leaves the 0.5 mm stored-frame contact limit).
    key_weight = 5000. if before_play < 0.001 else 10000.
    mid_cursors = []
    mid_meta = []  # (start, weight)
    for start, weight in scored:
        boost = 1.5 if before_play < 0.001 and weight >= 40000. else 1.
        for frac in (0.25, 0.5, 0.75):
            mid_cursors.append(start + frac)
            mid_meta.append((start, weight * boost))
    mid_cursors = np.asarray(mid_cursors, dtype=float)

    # A sample only depends on its Hermite stencil, not every free frame.
    # Dense finite differences previously decoded the whole clip once per
    # coordinate and often exhausted the polish deadline before one update.
    frame_columns = defaultdict(list)
    column = 0
    for frame, begin, end in parts:
        frame_columns[frame].extend(range(column, column + end - begin))
        column += end - begin
    blocks = [(3 * int(pinned[frame].sum()), [frame]) for frame in frames]
    for start, _weight in mid_meta:
        active = pinned[start] & pinned[(start + 1) % count]
        stencil = _hermite_stencil_frames([start], count, cyclic=cyclic)
        if np.any(active):
            blocks.append((3 * int(active.sum()), stencil))
        if floor is not None:
            blocks.append((len(rig.names), stencil))
    for frame in spike_rows:
        blocks.append((len(spike_joints), [frame - 1, frame, frame + 1]))
    row_count = sum(size for size, _ in blocks)
    pattern = lil_matrix((row_count, len(x0)), dtype=np.int8)
    row = 0
    for size, dependencies in blocks:
        columns = [col for frame in dependencies for col in frame_columns[frame]]
        if size and columns:
            pattern[row:row + size, columns] = 1
        row += size
    pattern = vstack([pattern.tocsr(), eye(len(x0), format='csr')], format='csr')
    best_values, best_cost = x0.copy(), float('inf')
    best_contact_values, best_contact_cost = None, float('inf')
    # Only free frames and temporal neighbors can change during this local
    # solve. Keep global contact screening without decoding the full clip for
    # every finite-difference probe.
    decoded_frames = sorted(set(frames) | {
        frame + offset for frame in spike_rows for offset in (-1, 0, 1)})
    decoded_index = np.asarray(decoded_frames, dtype=int)
    local_indices = {frame: index for index, frame in enumerate(decoded_frames)}
    key_indices = np.asarray([local_indices[frame] for frame in frames], dtype=int)
    spike_indices = np.asarray([
        [local_indices[frame + offset] for offset in (-1, 0, 1)]
        for frame in spike_rows], dtype=int)
    fixed_frames = np.ones(count, dtype=bool)
    fixed_frames[decoded_index] = False
    fixed_points = rig.decode(coords[fixed_frames]) if np.any(fixed_frames) else None
    fixed_key_error = (float(np.max(np.linalg.norm(
        (fixed_points - targets[fixed_frames])[pinned[fixed_frames]], axis=-1), initial=0.))
        if fixed_points is not None else 0.)

    class PlaybackConstraintsSatisfied(Exception):
        pass

    def unpack(values):
        trial = coords.copy()
        offset = 0
        for frame, begin, end in parts:
            width = end - begin
            trial[frame, begin:end] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        nonlocal best_values, best_cost, best_contact_values, best_contact_cost
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = unpack(values)
        points = rig.decode(trial[decoded_index])
        chunks = [
            key_weight * (points[key_indices] - targets[frame_index])[pinned[frame_index]].ravel(),
        ]
        mid_error, floor_error = 0., 0.
        if mid_cursors.size:
            mid = sample_rig(_sampling_payload(rig, trial), mid_cursors, wrap=cyclic)
            for row, (start, weight) in enumerate(mid_meta):
                active = pinned[start] & pinned[(start + 1) % count]
                if np.any(active):
                    delta = (mid[row] - targets[start])[active]
                    chunks.append(float(weight) * delta.ravel())
                    mid_error = max(mid_error, float(np.max(np.linalg.norm(delta, axis=-1))))
                if floor is not None:
                    chunks.append(2000. * np.minimum(mid[row, :, 1] - float(floor), 0.).ravel())
                    floor_error = max(floor_error, float(floor) - float(mid[row, :, 1].min()))
        spikes_clear = True
        if spike_rows.size:
            relative = points - points[:, rig.root:rig.root + 1]
            stencil = relative[spike_indices][:, :, spike_joints]
            sizes = .5 * np.linalg.norm(np.diff(stencil, n=2, axis=1)[:, 0], axis=-1)
            chunks.append((20000. * np.maximum(sizes - .95 * spike_limits, 0.)).ravel())
            spikes_clear = bool(np.all(sizes <= spike_limits))
        chunks.append(0.001 * (values - original))
        errors = np.concatenate(chunks)
        cost = float(errors @ errors)
        if cost < best_cost:
            best_values, best_cost = values.copy(), cost
        key_error = max(fixed_key_error, float(np.max(np.linalg.norm(
            (points - targets[decoded_index])[pinned[decoded_index]], axis=-1), initial=0.)))
        if key_error < KEYFRAME_CONTACT_LIMIT_METERS and cost < best_contact_cost:
            best_contact_values, best_contact_cost = values.copy(), cost
        if (contact_iterate_is_feasible(key_error, mid_error, floor_error)
                and spikes_clear):
            # This run has met its playback constraints. Continuing to minimize
            # tiny residuals starves later failing runs of the shared deadline.
            best_values = values.copy()
            raise PlaybackConstraintsSatisfied()
        return errors

    try:
        solved = least_squares(
            residual, x0, method='trf', jac_sparsity=pattern,
            max_nfev=int(max_nfev), ftol=1e-10, xtol=1e-10)
    except (TimeoutError, PlaybackConstraintsSatisfied):
        # Preserve useful work, subject to the same contact gates below.
        # Hitting the deadline must not discard a completed feasible iterate.
        solved = SimpleNamespace(x=best_values)
    except (np.linalg.LinAlgError, ValueError):
        return coords
    projected = unpack(solved.x)
    after_key = float(np.max(np.linalg.norm(
        (rig.decode(projected) - targets)[pinned], axis=-1), initial=0.))
    if after_key >= KEYFRAME_CONTACT_LIMIT_METERS and best_contact_values is not None:
        projected = unpack(best_contact_values)
        after_key = float(np.max(np.linalg.norm(
            (rig.decode(projected) - targets)[pinned], axis=-1), initial=0.))
    after_play = _playback_contact_sample_error(
        projected, rig, pinned, targets, cyclic=cyclic)
    # Key may rise within the gate to cancel hermite mid bows; only reject when
    # key leaves the gate or mid-sample error gets worse while still failing.
    if after_key >= KEYFRAME_CONTACT_LIMIT_METERS:
        return coords
    if (after_play > before_play * 1.01 + 1e-9
            and after_play >= PLAYBACK_CONTACT_LIMIT_METERS):
        return coords
    return projected


def project_introduced_spikes_coordinates(coordinates, rig, pinned, contact_targets,
                                         reference, *, fps, cyclic=False, floor=None,
                                         deadline=None):
    """Repair local processing spikes jointly with their contact transitions."""
    coords = np.asarray(coordinates, dtype=float).copy()
    deadline = monotonic() + 16. if deadline is None else deadline
    if monotonic() >= deadline:
        return coords
    points = rig.decode(coords)
    if monotonic() >= deadline:
        return coords
    events = relative_motion_quality(
        points, points, rig.names, fps, spike_reference=reference)['introducedSpikes']['events']
    if not events or monotonic() >= deadline:
        return coords
    intervals = sorted({i for event in events
                        for i in range(max(0, event['frameIndex'] - 2),
                                       min(len(coords) - 1, event['frameIndex'] + 2))})
    chain = set(_plant_chain_slots(rig, pinned))
    for event in events:
        ancestor = rig.names.index(event['joint'])
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    for start, stop in _contiguous_interval_runs(intervals):
        if monotonic() >= deadline:
            break
        coords = _trf_playback_run_coupled(
            coords, range(start, stop + 1), rig, pinned, contact_targets, sorted(chain),
            cyclic=cyclic, floor=floor, max_nfev=40, deadline=deadline,
            spike_reference=reference)
    return coords


def _trf_playback_interval(pair, rig, pair_pin, pair_targets, active, chain, *,
                           floor=None, max_nfev=5, deadline=None):
    """Two-frame plant-chain TRF for one failing planted interval.

    Only valid as a coarse pass when keyframes are still off gate. Mid-sample
    scoring on an isolated pair uses degenerate hermite tangents; once endpoints
    hold, use `_trf_playback_interval_in_clip` instead.
    """
    from .rig_playback import sample_rig
    sample_cursors = np.array([.25, .5, .75])
    parts = []
    for local_i in range(2):
        if not pair_pin[local_i].any():
            continue
        parts.append((local_i, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((local_i, slot, slot + 3))
    if not parts:
        return pair
    x0 = np.concatenate([pair[local_i, begin:end] for local_i, begin, end in parts])
    original = x0.copy()

    def unpack(values):
        trial = pair.copy()
        offset = 0
        for local_i, begin, end in parts:
            width = end - begin
            trial[local_i, begin:end] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = unpack(values)
        points = rig.decode(trial)
        err = (points - pair_targets)[pair_pin].ravel()
        mid = sample_rig(_sampling_payload(rig, trial), sample_cursors, wrap=False)
        err = np.r_[err, (mid - pair_targets[0])[:, active].ravel()]
        if floor is not None:
            err = np.r_[err, np.minimum(mid[:, :, 1] - float(floor), 0.).ravel()]
        return np.r_[2000. * err, 0.05 * (values - original)]

    def peak(trial):
        points = rig.decode(trial)
        key = float(np.max(np.linalg.norm((points - pair_targets)[pair_pin], axis=-1), initial=0.))
        mid = sample_rig(_sampling_payload(rig, trial), sample_cursors, wrap=False)
        play = float(np.max(np.linalg.norm((mid - pair_targets[0])[:, active], axis=-1), initial=0.))
        pen = 0. if floor is None else max(0., float(floor) - float(mid[:, :, 1].min()))
        return max(key, play, max(0., pen - PLAYBACK_FLOOR_LIMIT_METERS))

    before = peak(pair)
    try:
        solved = least_squares(
            residual, x0, method='trf', max_nfev=int(max_nfev), ftol=1e-8, xtol=1e-8)
    except (TimeoutError, np.linalg.LinAlgError, ValueError):
        return pair
    projected = unpack(solved.x)
    return projected if peak(projected) <= before * 1.01 else pair


def _trf_playback_interval_in_clip(
        coordinates, start, rig, pinned, contact_targets, chain, *,
        cyclic=False, floor=None, max_nfev=16, deadline=None):
    """Refine one planted interval against full-clip hermite samples.

    Playback hermite tangents depend on neighboring keyframes. Scoring mids on an
    isolated two-frame pair therefore optimizes a different path than acceptance.
    """
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    frames = (int(start), (int(start) + 1) % count)
    pair_pin = pinned[list(frames)]
    active = pair_pin[0] & pair_pin[1]
    if not np.any(active):
        return coords
    return _trf_playback_run_coupled(
        coords, [int(start)], rig, pinned, contact_targets, chain,
        cyclic=cyclic, floor=floor, max_nfev=max_nfev, deadline=deadline)


def project_interval_playback_plants(coordinates, rig, pinned, contact_targets, *,
                                     cyclic=False, floor=None, max_nfev=5, deadline=None,
                                     spike_reference=None):
    """Hold planted contacts on interpolated samples.

    Large keyframe misses get a root shift then coarse two-frame TRF. When
    endpoints already hold, failing intervals are refined together in full-clip
    hermite context so neighbor tangents and sparse seams stop fighting each other.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    original_coordinates = coords.copy()
    original_points = rig.decode(coords)
    reference_points = original_points if spike_reference is None else np.asarray(spike_reference)
    from .physical_validation import hinge_direction_events

    def jerk(points):
        return float(np.sqrt(np.mean(np.diff(points, n=3, axis=0)**2))) if len(points) > 3 else 0.

    jerk_bound = max(jerk(original_points), jerk(reference_points) * 1.05 + 1e-7)
    previous_knee_errors = {
        (event['joint'], event['frameIndex']): event['changeDegrees']
        for event in hinge_direction_events(original_points, rig.names, reference_points)
        if event['reason'] == 'repair_hinge_direction_distortion'
    }

    def retain_safe_projection(proposed):
        result = rig.decode(proposed)
        if not np.isfinite(result).all() or jerk(result) > jerk_bound + 1e-12:
            return original_coordinates.copy()
        for event in hinge_direction_events(result, rig.names, reference_points):
            if event['reason'] == 'repair_hinge_direction_distortion' and event['changeDegrees'] > max(
                    event['toleranceDegrees'], previous_knee_errors.get(
                        (event['joint'], event['frameIndex']), 0.)) + 1e-7:
                return original_coordinates.copy()
        return proposed

    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned) or (deadline is not None and monotonic() >= deadline):
        return retain_safe_projection(coords)
    failing = _playback_failing_intervals(
        coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
    if not failing or (deadline is not None and monotonic() >= deadline):
        return retain_safe_projection(coords)
    key_peak = float(np.max(np.linalg.norm(
        (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
    endpoints_hold = key_peak < KEYFRAME_CONTACT_LIMIT_METERS
    if not endpoints_hold:
        coords = _root_shift_failing_playback_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor, failing=failing,
            passes=8)
        failing = _playback_failing_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        if not failing:
            return retain_safe_projection(coords)
        leftover_frames = sorted({f for start in failing for f in (start, (start + 1) % count)})
        frame_mask = np.zeros(count, dtype=bool)
        frame_mask[leftover_frames] = True
        endpoint_pin = pinned & frame_mask[:, None]
        if np.any(endpoint_pin):
            coords = project_contact_plant_coordinates(
                coords, rig, endpoint_pin, targets, max_nfev=20, deadline=deadline)
            coords = _root_shift_failing_playback_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor, failing=failing,
                passes=6)
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            if not failing:
                return retain_safe_projection(coords)
            key_peak = float(np.max(np.linalg.norm(
                (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
            endpoints_hold = key_peak < KEYFRAME_CONTACT_LIMIT_METERS
        chain = _plant_chain_slots(rig, pinned)
        for start in failing:
            if deadline is not None and monotonic() >= deadline:
                break
            frames = (start, (start + 1) % count)
            pair_pin = pinned[list(frames)]
            active = pair_pin[0] & pair_pin[1]
            if not np.any(active):
                continue
            projected = _trf_playback_interval(
                coords[list(frames)].copy(), rig, pair_pin, targets[list(frames)],
                active, chain, floor=floor, max_nfev=max_nfev, deadline=deadline)
            coords[list(frames)] = projected
        failing = _playback_failing_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        if not failing:
            return retain_safe_projection(coords)
        key_peak = float(np.max(np.linalg.norm(
            (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
        endpoints_hold = key_peak < KEYFRAME_CONTACT_LIMIT_METERS
    if not failing:
        return retain_safe_projection(coords)
    # Preserve the source temporal evidence across every local contact solve.
    # Otherwise root corrections can close plants by introducing pelvis/limb
    # acceleration spikes, including during velocity-continuity repair.
    from functools import partial
    project_run = partial(_trf_playback_run_coupled,
                          spike_reference=spike_reference)
    # Endpoints hold: hermite-stencil TRF on contiguous failing runs. Sparse seams
    # must be iterated — a joint residual over all gaps often stalls, while
    # per-run distal solves accumulate to the playback gate.
    play_peak = _playback_contact_sample_error(
        coords, rig, pinned, targets, cyclic=cyclic)
    near_miss_mid = endpoints_hold and play_peak < 0.003
    # Hip sockets have no independent rotation in the fixed rig. Include their
    # movable parent so a planted-foot trajectory can adjust its proximal frame.
    # Final articulation/anatomy gates still reject destructive pose changes.
    chain = _distal_plant_chain_slots(rig, pinned, depth=3)
    nfev = max(int(max_nfev), 8 if near_miss_mid else 24)
    if near_miss_mid:
        # Cheap root pass — only when the bow is tiny (translation-dominated).
        if play_peak < 0.001 and (deadline is None or monotonic() < deadline):
            coords = project_run(
                coords, failing, rig, pinned, targets, [],
                cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                deadline=deadline)
            if (_playback_contact_sample_error(
                    coords, rig, pinned, targets, cyclic=cyclic)
                    < PLAYBACK_CONTACT_LIMIT_METERS):
                return retain_safe_projection(coords)
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        for _ in range(8):
            if not failing:
                return retain_safe_projection(coords)
            if deadline is not None and monotonic() >= deadline:
                break
            before = _playback_contact_sample_error(
                coords, rig, pinned, targets, cyclic=cyclic)
            for run_start, run_end in _contiguous_interval_runs(failing):
                if deadline is not None:
                    remaining = deadline - monotonic()
                    if remaining < 1.5:
                        break
                    run_nfev = min(nfev, max(4, int(remaining * 2)))
                else:
                    run_nfev = nfev
                coords = project_run(
                    coords, list(range(run_start, run_end + 1)), rig, pinned, targets,
                    chain, cyclic=cyclic, floor=floor, max_nfev=run_nfev,
                    deadline=deadline)
                if (_playback_contact_sample_error(
                        coords, rig, pinned, targets, cyclic=cyclic)
                        < PLAYBACK_CONTACT_LIMIT_METERS):
                    return retain_safe_projection(coords)
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            after = _playback_contact_sample_error(
                coords, rig, pinned, targets, cyclic=cyclic)
            if after < PLAYBACK_CONTACT_LIMIT_METERS:
                return retain_safe_projection(coords)
            if after >= before * 0.995 and after >= PLAYBACK_CONTACT_LIMIT_METERS:
                # Distal TRF often stalls ~0.05 mm over the gate; a cheap
                # root-only coupled pass on the leftover gaps closes that gap
                # without a second outer call.
                if after < 0.001 and failing and (
                        deadline is None or monotonic() < deadline):
                    coords = project_run(
                        coords, failing, rig, pinned, targets, [],
                        cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                        deadline=deadline)
                    if (_playback_contact_sample_error(
                            coords, rig, pinned, targets, cyclic=cyclic)
                            < PLAYBACK_CONTACT_LIMIT_METERS):
                        return retain_safe_projection(coords)
                    failing = _playback_failing_intervals(
                        coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
                if deadline is not None and deadline - monotonic() < 2.0:
                    break
                # Stall: one joint distal solve on remaining gaps.
                coords = project_run(
                    coords, failing, rig, pinned, targets, chain,
                    cyclic=cyclic, floor=floor, max_nfev=max(nfev, 16), deadline=deadline)
                if (_playback_contact_sample_error(
                        coords, rig, pinned, targets, cyclic=cyclic)
                        < PLAYBACK_CONTACT_LIMIT_METERS):
                    return retain_safe_projection(coords)
                break
        # Final near-gate root pass if distal iterations left a sub-mm miss.
        after = _playback_contact_sample_error(
            coords, rig, pinned, targets, cyclic=cyclic)
        if (PLAYBACK_CONTACT_LIMIT_METERS <= after < 0.001
                and (deadline is None or monotonic() < deadline)):
            leftover = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            if leftover:
                coords = project_run(
                    coords, leftover, rig, pinned, targets, [],
                    cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                    deadline=deadline)
        return retain_safe_projection(coords)
    window = 6
    for run_start, run_end in _contiguous_interval_runs(failing):
        if deadline is not None and monotonic() >= deadline:
            break
        cursor = run_start
        while cursor <= run_end:
            if deadline is not None and monotonic() >= deadline:
                break
            chunk_end = min(run_end, cursor + window - 1)
            coords = project_run(
                coords, list(range(cursor, chunk_end + 1)), rig, pinned, targets, chain,
                cyclic=cyclic, floor=floor, max_nfev=nfev, deadline=deadline)
            if (_playback_contact_sample_error(
                    coords, rig, pinned, targets, cyclic=cyclic)
                    < PLAYBACK_CONTACT_LIMIT_METERS):
                return retain_safe_projection(coords)
            if chunk_end >= run_end:
                break
            cursor = chunk_end
    return retain_safe_projection(coords)


def apply_supported_floor_clearance(coordinates, rig, pinned, contact_targets, floor, *,
                                    cyclic=False):
    """Lift unsupported interpolated geometry, keeping the result only if plants still hold."""
    coords = np.asarray(coordinates, dtype=float).copy()
    from .rig_playback import unanchored_floor_clearance_lift, free_joint_floor_clearance_lift
    payload = _sampling_payload(rig, coords)
    if not np.any(pinned):
        lift = unanchored_floor_clearance_lift(payload, floor, pinned, cyclic=cyclic)
        if lift > 0:
            coords[:, 1] += lift
        return coords, float(lift)
    lift = free_joint_floor_clearance_lift(payload, floor, pinned, cyclic=cyclic)
    if lift <= 0:
        return coords, 0.0

    def plants_hold(values):
        key = float(np.max(np.linalg.norm((rig.decode(values) - contact_targets)[pinned], axis=-1), initial=0.))
        play = _playback_contact_sample_error(values, rig, pinned, contact_targets, cyclic=cyclic)
        return key < KEYFRAME_CONTACT_LIMIT_METERS and play < PLAYBACK_CONTACT_LIMIT_METERS

    for freeze_root in (True, False):
        trial = coords.copy()
        trial[:, 1] += lift
        trial = project_contact_plant_coordinates(
            trial, rig, pinned, contact_targets, max_nfev=40, freeze_root=freeze_root)
        if plants_hold(trial):
            return trial, float(lift)
    return coords, 0.0


def _batched_projection_jacobian(rig, coordinates, columns, residuals, weight, prior_weight):
    """Differentiate independent pose residuals with one batched FK traversal."""
    step = 1e-6
    trials = np.repeat(coordinates[None, :], len(columns) + 1, axis=0)
    trials[np.arange(1, len(columns) + 1), columns] += step
    errors = np.asarray(residuals(rig.decode(trials))).reshape(len(trials), -1)
    return np.vstack([weight * (errors[1:] - errors[0]).T / step,
                      prior_weight * np.eye(len(columns))])


def _plant_projection_continuity_seed(coords, observed, frame, rig, chain, pinned, targets, *, freeze_root):
    """Carry corrections across the same observed stationary contact episode."""
    seed = coords[frame].copy()
    if (frame == 0 or not np.array_equal(pinned[frame], pinned[frame - 1])
            or not np.allclose(targets[frame][pinned[frame]],
                               targets[frame - 1][pinned[frame]], rtol=0., atol=1e-8)):
        return seed
    from .anatomical_repair import _transport_repair_rotation
    if not freeze_root:
        seed[:3] = observed[frame, :3] + coords[frame - 1, :3] - observed[frame - 1, :3]
    for joint in chain:
        slot = rig.slots[joint]
        seed[slot:slot + 3] = _transport_repair_rotation(
            observed[frame - 1, slot:slot + 3], coords[frame - 1, slot:slot + 3],
            observed[frame, slot:slot + 3])
    return seed


def project_contact_plant_coordinates(coordinates, rig, pinned, contact_targets, *, max_nfev=40,
                                      freeze_root=False, preserve_root_posture=False, deadline=None):
    """Hard-project root + planted-chain DOFs onto contact targets.

    Root translation alone cannot clear relative plant error between two feet.
    A small TRF on the planted limb slots targets the 0.5 mm contact gate.
    When freeze_root is set, only limb slots move — used after root-continuity
    projection so contact recovery cannot reintroduce pelvis spikes.

    Long clips use per-frame TRF so each solve stays tiny and a deadline can
    stop between frames. Clip-wide TRF previously burned minutes past the
    soft watchdog on ~150-frame plant-only fits.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if coords.ndim != 2 or not np.any(pinned):
        return coords
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    observed = coords.copy()
    chain = set()
    for joint in plant_joints:
        ancestor = joint
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    if preserve_root_posture:
        # Contacts own plant placement, not a new global body orientation.
        chain = {joint for joint in chain if rig.parents[joint] >= 0}
    chain = sorted(chain)

    def _project_frame(frame_coords, frame_pin, frame_targets, frame_max_nfev):
        if not np.any(frame_pin):
            return frame_coords
        parts = []
        if not freeze_root:
            parts.append((1, 2) if preserve_root_posture else (0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((slot, slot + 3))
        if not parts:
            return frame_coords
        x0 = np.concatenate([frame_coords[start:stop] for start, stop in parts])
        original = x0.copy()
        columns = np.array([column for start, stop in parts for column in range(start, stop)])
        best_values, best_error = x0.copy(), float('inf')

        class ContactReached(Exception):
            pass

        def unpack(values):
            trial = frame_coords.copy()
            offset = 0
            for start, stop in parts:
                width = stop - start
                trial[start:stop] = values[offset:offset + width]
                offset += width
            return trial

        def residual(values):
            nonlocal best_values, best_error
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError
            points = rig.decode(unpack(values)[None, :])[0]
            err = (points - frame_targets)[frame_pin].ravel()
            error = float(np.max(np.linalg.norm(err.reshape(-1, 3), axis=-1), initial=0.))
            if error < best_error:
                best_values, best_error = values.copy(), error
            if error < .05 * PLAYBACK_CONTACT_LIMIT_METERS:
                raise ContactReached
            return np.r_[2000. * err, 0.05 * (values - original)]

        def jacobian(values):
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError
            return _batched_projection_jacobian(
                rig, unpack(values), columns,
                lambda points: (points - frame_targets)[:, frame_pin], 2000., .05)

        before = float(np.max(np.linalg.norm(
            (rig.decode(frame_coords[None, :])[0] - frame_targets)[frame_pin], axis=-1), initial=0.))
        try:
            solved = least_squares(
                residual, x0, jac=jacobian, method='trf', max_nfev=int(frame_max_nfev),
                ftol=1e-10, xtol=1e-10)
            projected = unpack(solved.x)
        except (ContactReached, TimeoutError):
            projected = unpack(best_values)
        except (np.linalg.LinAlgError, ValueError):
            return frame_coords
        after = float(np.max(np.linalg.norm(
            (rig.decode(projected[None, :])[0] - frame_targets)[frame_pin], axis=-1), initial=0.))
        return projected if after <= before * 1.01 else frame_coords

    # Prefer per-frame whenever a deadline is set or the clip is long enough that
    # a joint TRF would dominate the budget. Multiple passes over still-failing
    # frames converge relative foot error that a single low-nfev pass leaves.
    use_per_frame = deadline is not None or count > 24
    if use_per_frame:
        frame_nfev = min(max(int(max_nfev), 25), 40)
        gate = KEYFRAME_CONTACT_LIMIT_METERS
        for _pass in range(3):
            if deadline is not None and monotonic() >= deadline:
                break
            progressed = False
            for frame in range(count):
                if deadline is not None and monotonic() >= deadline:
                    break
                if not pinned[frame].any():
                    continue
                before = float(np.max(np.linalg.norm(
                    (rig.decode(coords[frame:frame + 1])[0] - targets[frame])[pinned[frame]],
                    axis=-1), initial=0.))
                if before < gate:
                    continue
                seed = _plant_projection_continuity_seed(
                    coords, observed, frame, rig, chain, pinned, targets, freeze_root=freeze_root)
                if preserve_root_posture:
                    seed[[0, 2]] = observed[frame, [0, 2]]
                projected = _project_frame(seed, pinned[frame], targets[frame], frame_nfev)
                after = float(np.max(np.linalg.norm(
                    (rig.decode(projected[None, :])[0] - targets[frame])[pinned[frame]],
                    axis=-1), initial=0.))
                if after <= before * 1.01:
                    coords[frame] = projected
                if after < before * 0.98:
                    progressed = True
            if not progressed:
                break
            peak = float(np.max(np.linalg.norm(
                (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
            if peak < gate:
                break
        return coords

    parts = []
    for frame in range(count):
        if not pinned[frame].any():
            continue
        if not freeze_root:
            parts.append((frame, 1, 2) if preserve_root_posture else (frame, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, start:stop] for frame, start, stop in parts])
    original = x0.copy()

    def unpack(values):
        trial = coords.copy()
        offset = 0
        for frame, start, stop in parts:
            width = stop - start
            trial[frame, start:stop] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        points = rig.decode(unpack(values))
        err = (points - targets)[pinned].ravel()
        return np.r_[2000. * err, 0.05 * (values - original)]

    before = float(np.max(np.linalg.norm((rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
    try:
        solved = least_squares(
            residual, x0, method='trf', max_nfev=int(max_nfev), ftol=1e-10, xtol=1e-10)
    except (TimeoutError, np.linalg.LinAlgError, ValueError):
        return coords
    projected = unpack(solved.x)
    after = float(np.max(np.linalg.norm((rig.decode(projected) - targets)[pinned], axis=-1), initial=0.))
    return projected if after <= before * 1.01 else coords


def _rigid_pair_arm_slots(rig, names, equipment, pinned=None):
    """Distal arm DOFs for rigid_pair projection — never plant or torso slots."""
    pair = equipment.get('endpointPair') or []
    if len(pair) != 2 or any(name not in names for name in pair):
        return []
    endpoints = [names.index(name) for name in pair]
    plant_joints = set()
    if pinned is not None and np.any(pinned):
        for joint in range(pinned.shape[1]):
            if pinned[:, joint].any():
                ancestor = joint
                while ancestor >= 0:
                    plant_joints.add(ancestor)
                    ancestor = rig.parents[ancestor]
    torso = {
        names.index(n) for n in (
            'pelvis', 'spine', 'spine1', 'spine2', 'spine3', 'neck', 'head',
            'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder',
            'left_knee', 'right_knee',
            'left_ankle', 'right_ankle', 'left_foot', 'right_foot',
        ) if n in names
    }
    arm_joints = set()
    for joint in endpoints:
        ancestor = joint
        while ancestor >= 0:
            if (ancestor in rig.slots and ancestor not in plant_joints
                    and ancestor not in torso):
                arm_joints.add(ancestor)
            ancestor = rig.parents[ancestor]
    return sorted(rig.slots[j] for j in arm_joints)


def project_rigid_pair_grip_coordinates(coordinates, rig, names, equipment, *,
                                        pinned=None, max_nfev=15, deadline=None):
    """Hard-project arm-chain DOFs onto a rigid hand/wrist spacing.

    Soft grip weights lose to contact/anatomy on reconstruction noise with
    tens of centimeters of spacing variance. Per-frame arm TRF enforces the
    calibrated distance without touching planted limb slots.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if (coords.ndim != 2
            or equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return coords
    arm_slots = _rigid_pair_arm_slots(rig, names, equipment, pinned=pinned)
    if not arm_slots:
        return coords
    from .equipment_constraints import grip_residual

    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    for _pass in range(3):
        if deadline is not None and monotonic() >= deadline:
            break
        progressed = False
        for frame in range(len(coords)):
            if deadline is not None and monotonic() >= deadline:
                break
            frame_coords = coords[frame].copy()
            before = float(abs(grip_residual(
                rig.decode(frame_coords[None, :]), names, equipment)).max(initial=0.))
            if before <= tolerance:
                continue
            x0 = np.concatenate([frame_coords[slot:slot + 3] for slot in arm_slots])
            original = x0.copy()
            columns = np.array([slot + axis for slot in arm_slots for axis in range(3)])
            best_values, best_error = x0.copy(), before

            class GripReached(Exception):
                pass

            def unpack(values, base=frame_coords):
                trial = base.copy()
                offset = 0
                for slot in arm_slots:
                    trial[slot:slot + 3] = values[offset:offset + 3]
                    offset += 3
                return trial

            def residual(values, prior=original):
                nonlocal best_values, best_error
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                points = rig.decode(unpack(values)[None, :])
                grip = grip_residual(points, names, equipment).ravel()
                error = float(np.max(abs(grip), initial=0.))
                if error < best_error:
                    best_values, best_error = values.copy(), error
                if error <= .05 * tolerance:
                    raise GripReached
                return np.r_[8000. * grip, 0.02 * (values - prior)]

            def jacobian(values):
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                return _batched_projection_jacobian(
                    rig, unpack(values), columns,
                    lambda points: grip_residual(points, names, equipment), 8000., .02)

            try:
                solved = least_squares(
                    residual, x0, jac=jacobian, method='trf', max_nfev=max(1, int(max_nfev)),
                    ftol=1e-10, xtol=1e-10)
                projected = unpack(solved.x)
            except (GripReached, TimeoutError):
                projected = unpack(best_values)
            except (np.linalg.LinAlgError, ValueError):
                continue
            after = float(abs(grip_residual(
                rig.decode(projected[None, :]), names, equipment)).max(initial=0.))
            if after <= before * 1.01:
                coords[frame] = projected
                if after < before * 0.98:
                    progressed = True
        peak = float(abs(grip_residual(
            rig.decode(coords), names, equipment)).max(initial=0.))
        if peak <= tolerance or not progressed:
            break
    return coords


def _playback_grip_failing_intervals(coordinates, rig, names, equipment, *,
                                     cyclic=False):
    """Intervals whose hermite mid-samples miss the rigid_pair spacing gate."""
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    if (equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return []
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    if count < 2:
        return []
    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    failing = []
    for start in range(interval_count):
        rows = slice(start * 3, start * 3 + 3)
        err = float(abs(grip_residual(sampled[rows], names, equipment)).max(initial=0.))
        if err > tolerance:
            failing.append(int(start))
    return failing


def _playback_grip_sample_error(coordinates, rig, names, equipment, *, cyclic=False):
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    if (equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return 0.
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    if count < 2:
        return 0.
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    return float(abs(grip_residual(sampled, names, equipment)).max(initial=0.))


def project_playback_rigid_pair_grip(coordinates, rig, names, equipment, *,
                                     pinned=None, cyclic=False, max_nfev=16,
                                     deadline=None, shake_limits=None):
    """Hold rigid_pair spacing on hermite mid-samples, not only keyframes.

    Keyframe grip can pass while interpolated hand spacing bows past tolerance —
    the same hermite-neighbor issue as planted contacts.
    """
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    coords = np.asarray(coordinates, dtype=float).copy()
    if (coords.ndim != 2
            or equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return coords
    arm_slots = _rigid_pair_arm_slots(rig, names, equipment, pinned=pinned)
    if not arm_slots:
        return coords
    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    failing = _playback_grip_failing_intervals(
        coords, rig, names, equipment, cyclic=cyclic)
    if not failing:
        return coords
    count = len(coords)
    nfev = max(8, int(max_nfev))
    for _ in range(4):
        if not failing:
            break
        if deadline is not None and monotonic() >= deadline:
            break
        before = _playback_grip_sample_error(
            coords, rig, names, equipment, cyclic=cyclic)
        for run_start, run_end in _contiguous_interval_runs(failing):
            if deadline is not None and deadline - monotonic() < 1.0:
                break
            intervals = list(range(run_start, run_end + 1))
            frames = _hermite_stencil_frames(intervals, count, cyclic=cyclic)
            parts = [(frame, slot, slot + 3)
                     for frame in frames for slot in arm_slots]
            if not parts:
                continue
            x0 = np.concatenate([coords[frame, begin:end] for frame, begin, end in parts])
            original = x0.copy()
            arm_joints = np.asarray([
                joint for joint, slot in rig.slots.items() if slot in arm_slots
            ], dtype=int)
            base_arm_points = rig.decode(coords)[:, arm_joints]
            correction_scale = max(body_scale(rig.decode(coords), names), 1e-9)

            def unpack(values, _parts=parts):
                trial = coords.copy()
                offset = 0
                for frame, begin, end in _parts:
                    width = end - begin
                    trial[frame, begin:end] = values[offset:offset + width]
                    offset += width
                return trial

            mid_cursors = np.asarray(
                [start + frac for start in intervals for frac in (.25, .5, .75)],
                dtype=float)
            key_frames = np.asarray(frames, dtype=int)

            def residual(values):
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                trial = unpack(values)
                points = rig.decode(trial)
                key_grip = grip_residual(points[key_frames], names, equipment).ravel()
                mid = sample_rig(_sampling_payload(rig, trial), mid_cursors, wrap=cyclic)
                mid_grip = grip_residual(mid, names, equipment).ravel()
                arm_correction = points[:, arm_joints] - base_arm_points
                smooth_correction = np.diff(arm_correction, n=2, axis=0).ravel()
                residual_parts = [
                    8000. * key_grip,
                    20000. * mid_grip,
                    0.02 * (values - original),
                    10000. * smooth_correction / correction_scale,
                ]
                if shake_limits is not None and len(points) >= 3:
                    limits = np.asarray(shake_limits, dtype=float)
                    arm_limits = limits[arm_joints]
                    acceleration = np.sqrt(np.mean(
                        np.diff(points[:, arm_joints], n=2, axis=0) ** 2,
                        axis=(0, 2),
                    ))
                    # Match the acceptance metric exactly: a per-joint RMS of
                    # absolute second differences. This lets the bounded grip
                    # projection trade a tiny endpoint adjustment for clearing
                    # a shake regression it would otherwise introduce. Target
                    # a 0.1% cushion so numerical noise does not leave a tiny
                    # over-limit endpoint after the combined projection.
                    residual_parts.append(18000. * np.maximum(
                        acceleration / np.maximum(arm_limits, 1e-12) - 0.999, 0.))
                return np.concatenate(residual_parts)

            try:
                solved = least_squares(
                    residual, x0, method='trf', max_nfev=nfev, ftol=1e-10, xtol=1e-10)
            except (TimeoutError, np.linalg.LinAlgError, ValueError):
                continue
            projected = unpack(solved.x)
            after = _playback_grip_sample_error(
                projected, rig, names, equipment, cyclic=cyclic)
            if after <= before * 1.01 + 1e-12:
                coords = projected
                if after <= tolerance:
                    return coords
        failing = _playback_grip_failing_intervals(
            coords, rig, names, equipment, cyclic=cyclic)
        after = _playback_grip_sample_error(
            coords, rig, names, equipment, cyclic=cyclic)
        if after >= before * 0.995:
            break
    return coords


def project_playback_neck_clearance(coordinates, rig, *, cyclic=False, deadline=None):
    """Keep the interpolated neck inside its socket before the playback guard.

    Clipping stored poses exactly onto the guard leaves Hermite overshoot to be
    clipped during playback, introducing velocity corners. Reserve the measured
    overshoot inside the stored-pose limit, changing only neck/head coordinates.
    Unresolved proposals are discarded; the caller still validates the motion.
    """
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    from .rig_playback import sample_rig_coordinates
    original = np.asarray(coordinates, dtype=float)
    required = ('neck', 'head', 'left_collar', 'right_collar')
    if len(original) < 3 or any(name not in rig.names for name in required):
        return original.copy()
    neck, head = (rig.names.index(name) for name in required[:2])
    if neck not in rig.slots or head not in rig.slots:
        return original.copy()
    left, right = (rig.offsets[rig.names.index(name)] for name in required[2:])
    width = float(np.linalg.norm(right - left))
    if width < 1e-12:
        return original.copy()
    lateral = (right - left) / width
    center = float(np.dot((left + right) * .5, lateral))
    guard = SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN
    # Inspect the whole interpolated path, not only knot derivatives. Moving a
    # clipping corner between knots would hide the symptom from that check.
    intervals = len(original) if cyclic else len(original) - 1
    cursors = np.arange(intervals * 16 + (not cyclic), dtype=float) / 16.
    candidate = original.copy()
    inset = 0.
    maximum_attempts = 8
    for attempt in range(maximum_attempts):
        if deadline is not None and monotonic() >= deadline:
            break
        sampled = sample_rig_coordinates(_sampling_payload(rig, candidate), cursors, wrap=cyclic)
        slot = rig.slots[neck]
        vectors = Rotation.from_rotvec(sampled[:, slot:slot + 3]).apply(rig.offsets[neck])
        maximum = float(np.max(np.abs((vectors @ lateral - center) / width)))
        if maximum <= guard - ANATOMY_FIT_MARGIN:
            return candidate
        inset += max(ANATOMY_FIT_MARGIN, maximum - guard + ANATOMY_FIT_MARGIN)
        if inset >= guard or attempt == maximum_attempts - 1:
            break
        candidate = project_neck_attachment_values(
            original, rig.offsets, rig.names, rig.active, guard - inset)
    return original.copy()


def repair_playback_velocity_continuity(coordinates, rig, pinned, contact_targets, *,
                                        cyclic=False, sigma=1.0, names=None,
                                        equipment=None, deadline=None, floor=None,
                                        spike_reference=None, fps=30.):
    """Cut hermite knot velocity jumps without abandoning held plants/grip.

    Full mild rotation smooth clears C1 knot jumps from plant/grip TRF. Skip that
    smooth when the jump already clears so held mid-sample plants are not lifted.
    After a required smooth, mid-plant (with near-gate root close) restores the
    0.5 mm playback plant gate. Grip is re-held afterward.
    """
    from .rig_interpolation import frame_boundary_velocity_jump
    from .rig_playback import sample_rig
    from .physical_validation import body_scale

    coords = np.asarray(coordinates, dtype=float)
    if len(coords) < 3 or (deadline is not None and monotonic() >= deadline):
        return coords.copy()

    def _jump(values):
        count = len(values)
        knots = np.arange(count) if cyclic else np.arange(1, count - 1)
        if not len(knots):
            return 0.
        payload = _sampling_payload(rig, values)
        return frame_boundary_velocity_jump(
            lambda cursors: sample_rig(payload, cursors, wrap=cyclic), knots, fps)

    def _limit(values):
        return 0.001 * body_scale(rig.decode(values), rig.names)

    def _replant(values, *, max_nfev=24, budget=None):
        trial = values
        if pinned is None or not np.any(pinned) or contact_targets is None:
            return trial
        if deadline is not None and monotonic() >= deadline:
            return trial
        trial = project_contact_plant_coordinates(
            trial, rig, pinned, contact_targets, max_nfev=max_nfev,
            freeze_root=True, deadline=deadline)
        for _ in range(2):
            if not _playback_failing_intervals(
                    trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                break
            if deadline is not None and monotonic() >= deadline:
                break
            before_jump = _jump(trial)
            # No artificial per-call cap when the outer deadline is open — a
            # short budget aborts the near-gate root close ~0.2 mm over limit.
            if budget is not None:
                plant_deadline = monotonic() + budget
                if deadline is not None:
                    plant_deadline = min(plant_deadline, deadline)
            else:
                plant_deadline = deadline
            candidate = project_interval_playback_plants(
                trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor,
                max_nfev=max_nfev, deadline=plant_deadline, spike_reference=spike_reference)
            if _jump(candidate) <= max(_limit(candidate) * 1.25, before_jump * 1.05):
                trial = candidate
            else:
                break
        return trial

    if _jump(coords) <= _limit(coords):
        smoothed = coords.copy()
    else:
        socket_clear = project_playback_neck_clearance(
            coords, rig, cyclic=cyclic, deadline=deadline)
        from .equipment_constraints import validate_grip
        if (not np.array_equal(socket_clear, coords)
                and _jump(socket_clear) <= _limit(socket_clear)
                and validate_grip(rig.decode(socket_clear), rig.names, equipment or {})['passed']):
            # No root/limb smoothing or replanting is needed for a neck-only
            # guard corner. Existing held contacts and grip remain identical.
            return socket_clear
        smoothed = temporal_coordinate_smooth(
            coords, cyclic=cyclic, sigma=min(float(sigma), 0.85))
        plant_budget = (
            None if deadline is None
            else max(4., deadline - monotonic()))
        smoothed = _replant(smoothed, max_nfev=24, budget=plant_budget)
        # Playback-plant TRF can recreate knot jumps — damp once more, then replant.
        if (deadline is None or monotonic() < deadline) and _jump(smoothed) > _limit(smoothed):
            smoothed = temporal_coordinate_smooth(smoothed, cyclic=cyclic, sigma=0.45)
            smoothed = _replant(smoothed, max_nfev=16)

    if (names is not None and equipment is not None
            and equipment.get('handRelationship') == 'rigid_pair'
            and equipment.get('available')
            and (deadline is None or monotonic() < deadline)):
        from .equipment_constraints import validate_grip
        # Retain the constraint even if it passed before smoothing. Avoid TRF
        # only when the new stored AND interpolated poses still hold the grip.
        cursors = np.arange(0., len(smoothed) if cyclic else len(smoothed) - 1 + .125, .25)
        samples = sample_rig(_sampling_payload(rig, smoothed), cursors, wrap=cyclic)
        if validate_grip(samples, names, equipment)['passed']:
            return smoothed
        smoothed = project_rigid_pair_grip_coordinates(
            smoothed, rig, names, equipment, pinned=pinned, max_nfev=20,
            deadline=deadline)
        if deadline is None or monotonic() < deadline:
            smoothed = project_playback_rigid_pair_grip(
                smoothed, rig, names, equipment, pinned=pinned, cyclic=cyclic,
                max_nfev=12, deadline=deadline)
        smoothed = _replant(smoothed, max_nfev=16)
        if (deadline is None or monotonic() < deadline) and _jump(smoothed) > _limit(smoothed):
            smoothed = temporal_coordinate_smooth(smoothed, cyclic=cyclic, sigma=0.4)
            smoothed = _replant(smoothed, max_nfev=12)
    return smoothed


def _playback_nested_failures(playback):
    """Map nested validate_rig_playback failures onto polish actions."""
    if not playback or playback.get('passed'):
        return set()
    fails = set()
    contact = float(playback.get('maximumContactErrorMeters') or 0.)
    if contact >= PLAYBACK_CONTACT_LIMIT_METERS:
        fails.add('contact')
    equipment = playback.get('equipment') or {}
    if equipment.get('required') and not equipment.get('passed', True):
        fails.add('equipment')
    if playback.get('velocityContinuous') is False:
        fails.add('velocity')
    if playback.get('physicalReasons'):
        fails.add('physical')
    return fails


def playback_path_repair_eligible(report, *, skip_hard_only):
    """Allow bounded path repair for a normal fit's isolated C1 miss.

    Soft-solve skips retain the broader repair path for nested equipment,
    velocity, and physical playback failures. A completed soft solve may enter
    it only when velocity continuity is the sole nested playback failure and
    every fit failure is already in the temporal/playback polish stages.
    """
    if not isinstance(report, dict) or report.get('applied'):
        return False
    failed = set(failed_check_names(report.get('checks')))
    if ('playback' not in failed
            or (report.get('maximumContactErrorMeters') or 0.) >= 0.0005):
        return False
    nested = _playback_nested_failures(report.get('playback'))
    if skip_hard_only:
        return bool(nested & {'equipment', 'velocity', 'physical'})
    return (
        nested == {'velocity'}
        and failed <= (POLISH_STAGE_C | {'playback'})
    )


def project_root_continuity_coordinates(coordinates, fps, scale, passes=40):
    """Clamp root second differences to the rootContinuity acceptance limit.

    Gaussian smoothing alone often stalls ~1.5× over the limit on source spikes.
    This iteratively damps excess acceleration at the offending samples.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3 or scale <= 0 or fps <= 0:
        return coords
    limit = 0.05 * float(scale) * 0.95
    rate = (float(fps) / 30.) ** 2
    root = coords[:, :3]
    for _ in range(max(1, int(passes))):
        acceleration = np.diff(root, n=2, axis=0) * rate
        norms = np.linalg.norm(acceleration, axis=-1)
        bad = norms > limit
        if not bad.any():
            break
        for index in np.flatnonzero(bad):
            mid = int(index) + 1
            # Blend toward the neighbor mean — pure acceleration damping is too
            # weak on single-frame source spikes (~3× over the limit).
            neighbor_mean = 0.5 * (root[mid - 1] + root[mid + 1])
            blend = min(1., 1. - (limit / max(float(norms[index]), 1e-12)) * 0.5)
            root[mid] = (1. - blend) * root[mid] + blend * neighbor_mean
    coords[:, :3] = root
    return coords


def smooth_root_translation_coordinates(coordinates, fps, *, scale=None, max_passes=6):
    """Gaussian-smooth root translation DOFs to clear rootContinuity spikes."""
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3:
        return coords
    # Source-derived roots can be ~3× over the continuity limit; grow sigma
    # until the acceptance screen passes or the pass budget is exhausted.
    sigma = max(1., float(fps) * .12)
    for step in range(max(1, int(max_passes))):
        coords[:, :3] = gaussian_filter1d(
            coords[:, :3], sigma * (1. + 0.5 * step), axis=0, mode='nearest')
        if scale is not None and root_motion_quality(coords[:, :3], fps, scale)['passed']:
            break
    if scale is not None and not root_motion_quality(coords[:, :3], fps, scale)['passed']:
        coords = project_root_continuity_coordinates(coords, fps, scale)
    return coords


def close_loop_seam_coordinates(coordinates, rig, pinned, *, scale, fps=30., passes=5):
    """Iterate boundary + velocity nudges until playback seam ratios are ≤1."""
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3:
        return coords
    planted = bool(np.any(pinned))
    strengths = ([0.45, 0.65, 0.8] if planted
                 else list(np.linspace(0.4, 0.9, max(1, int(passes)))))
    best = coords
    rig.initial[:] = best
    best_score = seam_playback_over_limit_score(rig.decode(best), scale=scale, fps=fps)

    def consider(candidate):
        nonlocal best, best_score
        rig.initial[:] = candidate
        score = seam_playback_over_limit_score(rig.decode(candidate), scale=scale, fps=fps)
        if score < best_score:
            best, best_score = np.asarray(candidate, dtype=float).copy(), score

    for strength in strengths:
        boundary = seam_boundary_coordinate_nudge(best, rig, pinned, strength=float(strength))
        consider(boundary)
        consider(seam_velocity_neighbor_nudge(
            boundary, rig, pinned, strength=min(0.7, float(strength))))
        if best_score <= 1.:
            return best
    consider(seam_velocity_neighbor_nudge(best, rig, pinned, strength=0.65))
    return best


def _source_fit_points_with_boundary_update(source_template, boundary, boundary_points):
    """Apply a local repair in the original source-fit frame-index domain."""
    source_points = np.asarray(source_template, dtype=float).copy()
    indexes = np.asarray(boundary, dtype=int)
    points = np.asarray(boundary_points, dtype=float)
    if (source_points.ndim != 3 or points.shape != (len(indexes), *source_points.shape[1:])
            or np.any(indexes < 0) or np.any(indexes >= len(source_points))):
        raise ValueError('boundary source update does not match the original fit-frame domain')
    source_points[indexes] = points
    return source_points


def project_loop_seam_coordinates(coordinates, rig, pinned, *, scale, fps, max_nfev=50,
                                  deadline=None, settling_weights=None, settling_limit=None,
                                  span_targets=None, equipment=None, source_projection_constraint=None):
    """Hard-project free boundary DOFs so wrap step+velocity fall under playback limits.

    Planted positions are constrained in world space, while local rotations stay
    available to articulate around those contacts. This small TRF solve targets
    the acceptance residuals directly.
    Anatomy is constrained alongside the seam. The caller still independently
    validates the complete interpolated motion, contacts and source fidelity.
    """
    from .loop_seam import (
        seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO)
    from .physical_validation import span_rigidity_fit_residuals
    from .equipment_constraints import grip_residual, validate_grip
    equipment = equipment or {}
    coords = np.asarray(coordinates, dtype=float).copy()
    count = len(coords)
    if count < 4:
        return coords
    planted = bool(np.any(pinned))
    boundary = (0, 1, count - 2, count - 1)
    deadline = monotonic() + 10. if deadline is None else deadline
    original_points = rig.decode(coords[list(boundary)])
    step_limit = MAX_STEP_EXCESS_BODY_RATIO * float(scale)
    vel_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * float(scale)
    _, initial_excess, initial_increments = seam_errors(original_points)
    root_needs_repair = (
        initial_excess[rig.root] >= step_limit
        or np.max(np.linalg.norm(initial_increments[:, rig.root], axis=-1)) * fps >= vel_limit)
    free_frames = boundary
    smooth_boundary = root_needs_repair and count >= 12
    if smooth_boundary:
        # Closing supported root drift in only two samples creates an inward
        # snap next to the repaired wrap. Give that correction a short approach
        # on either side, with fixed inner samples to constrain its derivatives.
        width = min(max(2, round(.15 * fps)), count // 2 - 2)
        free_frames = tuple(range(width)) + tuple(range(count - width, count))
        boundary = tuple(range(width + 2)) + tuple(range(count - width - 2, count))
        original_points = rig.decode(coords[list(boundary)])
    elif settling_weights is not None and count >= 6:
        boundary = (0, 1, 2, count - 3, count - 2, count - 1)
        original_points = rig.decode(coords[list(boundary)])
    settling_segments = []
    if settling_weights is not None and settling_limit is not None:
        baseline_relative = body_relative_points(rig.decode(coords), rig.names)
        weighted_speed = np.diff(baseline_relative, axis=0) * fps * settling_weights
        settling_outside = float(np.sum(weighted_speed ** 2))
        settling_denominator = max(float(np.sum(settling_weights)) * 3., 1.)
        middle = len(boundary) // 2
        for segment in (slice(None, middle), slice(middle, None)):
            indices = np.asarray(boundary[segment][:-1], dtype=int)
            settling_outside -= float(np.sum(weighted_speed[indices] ** 2))
            settling_segments.append((segment, settling_weights[indices]))
    parts = []
    for frame in free_frames:
        # Planted contacts constrain world-space joints, not the root itself.
        # Free translation with the contact residual; otherwise a supported
        # loop with root drift has no variables capable of closing its seam.
        if not planted or root_needs_repair:
            parts.append((frame, 0, 3))
        for joint in range(pinned.shape[1]):
            # A positional plant does not lock this local rotation. Free it
            # while holding the world point, as in the contact projector.
            slot = rig.slots.get(joint)
            if slot is not None:
                parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, start:stop] for frame, start, stop in parts])
    original = x0.copy()

    boundary_template = coords[list(boundary)]
    boundary_indices = {frame: index for index, frame in enumerate(boundary)}
    boundary_source = source_projection_constraint or {}
    if boundary_source.get('available'):
        # Keep every source observation, event and renderer-geometry record in
        # the original fit-frame domain. Only boundary rows change per residual;
        # compacting selected rows would require rebasing every nested family.
        source_template = rig.decode(coords)

    def unpack(values, *, boundary_only=False):
        trial = boundary_template.copy() if boundary_only else coords.copy()
        offset = 0
        for frame, start, stop in parts:
            width = stop - start
            target_frame = boundary_indices[frame] if boundary_only else frame
            trial[target_frame, start:stop] = values[offset:offset + width]
            offset += width
        return trial

    boundary_acceleration_limits = []
    if smooth_boundary:
        middle = len(boundary) // 2
        for segment in (slice(None, middle), slice(middle, None)):
            before = np.linalg.norm(np.diff(original_points[segment], n=2, axis=0), axis=-1)
            boundary_acceleration_limits.append(np.maximum(
                1.1 * before, np.sqrt(3.) * .003 * (30. / fps) ** 2))

    best_values, best_cost = x0.copy(), float('inf')

    def residual_from_points(values, points, unconstrained_points):
        _, excess, increments = seam_errors(points)
        # Continuity applies to every joint, including joints that are planted
        # elsewhere in the repetition but moving at this boundary.
        step_err = np.maximum(excess - 0.95 * step_limit, 0.) / max(float(scale), 1e-6)
        vel_raw = np.linalg.norm(increments, axis=-1) * float(fps)
        vel_err = np.maximum(vel_raw - 0.95 * vel_limit, 0.) / max(float(scale), 1e-6)
        contact_err = np.zeros(0)
        if planted:
            deltas = []
            for local_frame, frame in enumerate(boundary):
                active = pinned[frame]
                if active.any():
                    deltas.append((points[local_frame, active] - original_points[local_frame, active]).ravel())
            if deltas:
                contact_err = np.concatenate(deltas) / max(float(scale), 1e-6)
        span_errors, _ = span_rigidity_fit_residuals(
            unconstrained_points, rig.names, span_targets, body_scale_m=scale)
        result = np.r_[
            # Step and velocity limits are both hard playback requirements.
            # A 50x step term was dwarfed by the fps-scaled velocity residual,
            # leaving a visible displacement hitch after velocity improved.
            2000. * step_err.ravel(),
            80. * vel_err.ravel(),
            20000. * contact_err,
            ANATOMY_FIT_WEIGHT * anatomical_structure_residuals(
                unconstrained_points, rig.names, pose_only=True,
                margin=ANATOMY_FIT_MARGIN, reference=original_points)[0].ravel(),
            ANATOMY_FIT_WEIGHT * span_errors.ravel(),
            (GRIP_FIT_WEIGHT * grip_residual(points, rig.names, equipment)
             / max(float(scale), 1e-6)).ravel(),
            0.02 * (values - original),
        ]
        if boundary_source.get('available'):
            source_points = _source_fit_points_with_boundary_update(
                source_template, boundary, points)
            result = np.r_[result,
                _source_projection_fit_rows(source_points, boundary_source),
                _source_endpoint_posture_fit_rows(source_points, boundary_source)]
        if smooth_boundary:
            middle = len(boundary) // 2
            for segment, limit in zip(
                    (slice(None, middle), slice(middle, None)), boundary_acceleration_limits):
                after = np.linalg.norm(np.diff(points[segment], n=2, axis=0), axis=-1)
                # Bound added acceleration, not changes in acceleration: removing
                # a source endpoint spike must not be penalized as a new defect.
                # The temporal gate's 3 mm per-axis floor is in meters, not
                # body-scale units. Convert it to a vector norm at this fps.
                result = np.r_[result, (1000. * np.maximum(after - limit, 0.) / scale).ravel()]
        if settling_segments:
            squared_speed = max(0., settling_outside)
            for segment, weights in settling_segments:
                relative = body_relative_points(points[segment], rig.names)
                squared_speed += float(np.sum((np.diff(relative, axis=0) * fps * weights) ** 2))
            settling_speed = np.sqrt(squared_speed / settling_denominator)
            result = np.r_[result, 150. * max(
                settling_speed / max(settling_limit, 1e-12) - .95, 0.)]
        return result

    def check_projection_budget():
        if monotonic() >= deadline:
            raise TimeoutError('seam_projection_budget_exhausted')

    def residual(values):
        nonlocal best_values, best_cost
        check_projection_budget()
        boundary_coordinates = unpack(values, boundary_only=True)
        points = rig.decode(boundary_coordinates)
        unconstrained_points = rig.decode(boundary_coordinates, project_socket=False)
        result = residual_from_points(values, points, unconstrained_points)
        cost = float(result @ result)
        if cost < best_cost:
            best_values, best_cost = values.copy(), cost
        return result

    def jacobian(values):
        check_projection_budget()
        # Decode all finite-difference probes together. Per-coordinate FK calls
        # otherwise spend most of this bounded solve traversing the same rig.
        steps = np.sqrt(np.finfo(float).eps) * np.maximum(1., np.abs(values))
        probes = np.tile(values, (len(values) + 1, 1))
        probes[np.arange(len(values)), np.arange(len(values))] += steps
        trials = np.asarray([unpack(probe, boundary_only=True) for probe in probes])
        check_projection_budget()
        points = rig.decode(trials.reshape(-1, coords.shape[1])).reshape(
            len(probes), len(boundary), len(rig.names), 3)
        check_projection_budget()
        unconstrained_points = rig.decode(
            trials.reshape(-1, coords.shape[1]), project_socket=False).reshape(points.shape)
        check_projection_budget()

        def probe_residual(probe, pose, raw_pose):
            check_projection_budget()
            return residual_from_points(probe, pose, raw_pose)

        residuals = np.asarray([probe_residual(probe, pose, raw_pose)
                                for probe, pose, raw_pose in zip(probes, points, unconstrained_points)])
        check_projection_budget()
        return ((residuals[:-1] - residuals[-1]) / steps[:, None]).T

    try:
        solved = least_squares(
            residual, x0, jac=jacobian, method='trf', tr_solver='lsmr', max_nfev=int(max_nfev),
            ftol=1e-10, xtol=1e-10)
        best_values = solved.x
    except TimeoutError:
        pass
    projected = unpack(best_values)
    # Keep only if the playback score improved.
    before_points, after_points = rig.decode(coords), rig.decode(projected)
    if (validate_grip(before_points, rig.names, equipment)['passed']
            and not validate_grip(after_points, rig.names, equipment)['passed']):
        return coords
    before = seam_playback_over_limit_score(before_points, scale=scale, fps=fps)
    after = seam_playback_over_limit_score(after_points, scale=scale, fps=fps)
    return projected if after <= before else coords


def root_relative_acceleration(points, names):
    root = names.index('pelvis')
    relative = points-points[:, root:root+1]
    return np.sqrt(np.mean(np.diff(relative, n=2, axis=0)**2, axis=(0, 2)))


def relative_motion_quality(points, reference, names, fps, *, spike_reference=None):
    """Global translation noise must not hide newly introduced limb jitter."""
    before = root_relative_acceleration(reference, names)
    after = root_relative_acceleration(points, names)
    limits = np.maximum(before*1.2, .003*(30./fps)**2)
    spike_reference = reference if spike_reference is None else spike_reference
    payload = {'fps': fps, 'frames': [
        {'timeSec': i/fps, 'joints': dict(zip(names, current.tolist())),
         'sourceJoints': dict(zip(names, source.tolist()))}
        for i, (current, source) in enumerate(zip(points, spike_reference))]}
    spikes = introduced_joint_spikes(payload)
    rotation = body_orientation_noise(points, names, reference, fps)
    return {'relativeJointShake': bool(np.all(after <= limits) and not spikes['severe']),
            'bodyRotation': not rotation['severe'],
            'jointAccelerationBefore': dict(zip(names, before.tolist())),
            'jointAccelerationAfter': dict(zip(names, after.tolist())),
            'introducedSpikes': spikes, 'rotation': rotation}


def temporal_fit_scales(reference, names, fps):
    """Normalize temporal residuals by the independent acceptance budgets."""
    acceleration = root_relative_acceleration(reference, names)
    acceleration_limit = np.maximum(acceleration*1.2, .003*(30./fps)**2)
    rotation = body_orientation_noise(reference, names, reference, fps)
    rotation_limit = np.deg2rad(rotation['limitDegreesAt30Hz'])*(30./fps)**2
    count = len(reference)-2
    return (TEMPORAL_FIT_TARGET_RATIO*acceleration_limit*np.sqrt(count*3),
            TEMPORAL_FIT_TARGET_RATIO*rotation_limit*np.sqrt(count*2))


def project_track_to_reference_bone_lengths(track, index, bones, reference_lengths):
    """Re-impose reference bone lengths on a joint track, parents first.

    Smoothing and deviation attenuation bend bones: the fit target must stay
    anatomically possible for the fixed rig, so each child is re-projected
    onto its bone's reference length along its current direction from the
    (already projected) parent. ``bones`` must be in topological
    (parent-before-child) order. Returns the projected track copy.
    """
    projected = np.array(track, dtype=float, copy=True)
    for child, parent in bones:
        ci, pi = index[child], index[parent]
        target_length = reference_lengths.get(f'{child}<-{parent}')
        if target_length is None:
            continue
        delta = projected[:, ci] - projected[:, pi]
        norm = np.linalg.norm(delta, axis=-1, keepdims=True)
        usable = norm > 1e-9
        projected[:, ci] = np.where(
            usable,
            projected[:, pi] + delta / np.maximum(norm, 1e-12) * target_length,
            projected[:, ci],
        )
    return projected


def controlled_target(points, names, fps):
    """Preserve native timing while attenuating subordinate local jitter.

    Local PCA acts on the original native-clock tracks after removing linear
    travel, in a fixed body basis. Dominant travel components are left intact;
    only small subordinate deviations are attenuated. This never locks a
    world axis, mirrors limbs, or uses an exercise label.
    """
    scale = body_scale(points, names)
    root = names.index('pelvis')
    basis = body_orientation_axes(points, names)
    rotation = frame_basis(basis[:1, 1], basis[:1, 0])[0]
    local = (points-points[:, root:root+1])@rotation
    tracks = np.concatenate([points[:, root:root+1]@rotation, local], axis=1)
    smooth = tracks
    radius = max(3, round(fps*.6))
    target = smooth.copy()
    corrections = []
    for frame in range(len(points)):
        start, end = max(0, frame-radius), min(len(points), frame+radius+1)
        time = np.arange(start, end, dtype=float)-frame
        design = np.column_stack([np.ones(len(time)), time])
        for joint in range(tracks.shape[1]):
            values = smooth[start:end, joint]
            linear = design@np.linalg.lstsq(design, values, rcond=None)[0]
            residual = values-linear
            _, singular, axes = np.linalg.svd(residual, full_matrices=False)
            if singular[0] < 1e-9:
                continue
            amplitudes = singular/np.sqrt(len(time))
            # Only small components subordinate to a clear main trajectory.
            weights = np.clip(1.-amplitudes/(.015*scale), 0., .8)
            weights[singular > singular[0]*.25] = 0.
            correction = ((residual[frame-start]@axes.T)*weights)@axes
            target[frame, joint] -= correction
            corrections.append(np.linalg.norm(correction))
    target = target[:, 1:]+target[:, :1]
    target = target@rotation.T
    # Quiet intervals encourage settling, without pinning contacts inferred
    # from low speed. Their velocity is a soft objective in the unified fit.
    relative = body_relative_points(points,names)
    hold_radius = max(2, round(fps*.2))
    holds = np.zeros(points.shape[:2])
    for frame in range(len(points)):
        values = relative[max(0,frame-hold_radius):min(len(points),frame+hold_radius+1)]
        span = np.linalg.norm(np.ptp(values, axis=0), axis=-1)
        path = np.sum(np.linalg.norm(np.diff(values,axis=0),axis=-1),axis=0)
        progress = np.linalg.norm(values[-1]-values[0],axis=-1)/np.maximum(path,1e-12)
        # Even very small monotonic motion is movement, not a quiet hold.
        holds[frame] = np.clip(1.-span/(.02*scale),0.,1.)*(1.-np.clip((progress-.4)/.4,0.,1.))
    holds[:, root] = 0.
    return target, holds, {'maximumMinorDeviationCorrectionMeters': float(max(corrections, default=0.)),
                            'smoothingSeconds': 0., 'localWindowSeconds': 1.2,
                            'denoisingPolicy': 'native_clock_subordinate_deviation_only'}


def excursion_constraints(target, root, scale):
    """Preserve substantial observed excursions while allowing quiet settling.

    Directions follow each joint's actual trajectory, not world axes. Only its
    outer excursion receives a lower bound; small motions remain unconstrained.
    """
    relative = target-target[:, root:root+1]
    center = relative.mean(axis=0)
    centered = relative-center
    radius = np.linalg.norm(centered, axis=-1)
    moving = np.linalg.norm(np.ptp(relative, axis=0), axis=-1) > .1*scale
    active = moving[None, :] & (radius >= .8*radius.max(axis=0))
    return center, np.where(active[:,:,None],unit(centered),0.), .9*radius, active


def hinge_coordinates(points, names):
    """Vectorized version of the final validator's body-local hinge frame."""
    right = unit(points[:,names.index('right_shoulder')]-points[:,names.index('left_shoulder')])
    forward = unit(np.cross(points[:,names.index('neck')]-points[:,names.index('pelvis')],right))
    up = unit(np.cross(right,forward))
    basis = np.stack([right,up,forward],axis=1)
    specs = [spec for spec in ARTICULATIONS if spec[0].endswith(('_knee','_elbow'))]
    parent = np.stack([unit(points[:,names.index(a)]-points[:,names.index(h)]) for _,a,h,_,_ in specs],axis=1)
    child = np.stack([unit(points[:,names.index(b)]-points[:,names.index(h)]) for _,_,h,b,_ in specs],axis=1)
    perpendicular = child-parent*np.sum(child*parent,axis=-1,keepdims=True)
    bend = unit(perpendicular)
    return (np.einsum('fai,fhi->fha',basis,parent),
            np.einsum('fai,fhi->fha',basis,bend),np.linalg.norm(perpendicular,axis=-1))


def transported_hinge_dots(source_parent, source_bend, current_parent, current_bend):
    shape = source_parent.shape
    rotation = Rotation.from_rotvec(align_vectors(source_parent.reshape(-1,3),current_parent.reshape(-1,3)))
    transported = rotation.apply(source_bend.reshape(-1,3)).reshape(shape)
    opposite = np.sum(source_parent*current_parent,axis=-1) < -1.+1e-9
    transported[opposite] = source_bend[opposite]
    return np.sum(transported*current_bend,axis=-1)


def fit_time_budget(payload, timeout_seconds=None):
    """Safety-cap wall clock only. Accept/stall/conflict should finish earlier."""
    if timeout_seconds is not None:
        return float(timeout_seconds)
    frames = len(payload.get('frames') or [])
    # One bounded bump so multi-cycle observed fits can finish without per-exercise overrides.
    return max(180., min(360., 2.5 * frames))


def _stage_deadline(fit_started, timeout_seconds, *, fraction, minimum_seconds, reserved_seconds=0.):
    """Bound a pre-solve stage. Polish is reserved from the solve phase, not here."""
    del reserved_seconds  # reserved only for soft-LS / Stage-B carve-out
    stage_budget = max(float(minimum_seconds), float(fraction) * float(timeout_seconds))
    fit_deadline = float(fit_started) + float(timeout_seconds)
    return min(fit_deadline, monotonic() + stage_budget)


def _support_cache_key(evidence, points, names):
    stationary = tuple(evidence.get('stationaryJoints') or [])
    if not stationary:
        return None
    indices = [names.index(name) for name in stationary if name in names]
    if not indices:
        return None
    median = np.median(points[:, indices], axis=0)
    digest = np.round(median, 3).tobytes()
    groups = tuple(
        (tuple(group.get('joints') or []), tuple(np.round(group.get('normal') or [0., 1., 0.], 4)))
        for group in (evidence.get('coplanarGroups') or [])
    )
    return (stationary, groups, digest)


def support_range_episode_tracks(reference, names, full_sole_masks, evidence_masks):
    """Return the final ankle-excursion gate's per-episode fit targets."""
    from .physical_validation import ARTICULATIONS

    reference = np.asarray(reference, dtype=float)
    tracks = []
    for side, full_sole in (full_sole_masks or {}).items():
        label = f'{side}_ankle'
        articulation = next((entry for entry in ARTICULATIONS if entry[0] == label), None)
        if articulation is None or not set(articulation[1:4]).issubset(names):
            continue
        _, a, b, c, _ = articulation
        joints = [names.index(joint) for joint in (a, b, c)]
        full_sole = np.asarray(full_sole, dtype=bool)
        observed = np.asarray((evidence_masks or {}).get(side, np.zeros(len(reference), dtype=bool)),
                              dtype=bool)
        if full_sole.shape != (len(reference),) or observed.shape != (len(reference),):
            continue
        source_angles = angles(*(reference[:, joint] for joint in joints))
        for mask in (full_sole & observed, ~full_sole & observed):
            edges = np.diff(np.r_[False, mask, False].astype(np.int8))
            for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                source = source_angles[start:stop]
                if np.ptp(source) > np.deg2rad(20.):
                    tracks.append((label, joints, source.copy(), np.arange(start, stop)))
    return tuple(tracks)


def support_range_residuals(candidate, tracks):
    """Fit existing 0.92 range margin on whole tracks and owned episodes."""
    errors = []
    for _, joints, source, *frame_range in tracks:
        frames = frame_range[0] if frame_range else np.arange(len(candidate))
        fitted = angles(*(candidate[frames, joint] for joint in joints))
        errors.append(12000. * max(0., .92 * float(np.ptp(source)) - float(np.ptp(fitted))))
    return np.asarray(errors, dtype=float)


def support_range_sparsity(rig, frame_count, tracks):
    rows = []
    for _, joints, _, *frame_range in tracks:
        frames = frame_range[0] if frame_range else np.arange(frame_count)
        dependencies = np.max(rig.dependencies[
            np.ravel([[joint * 3 + axis for axis in range(3)] for joint in joints])
        ], axis=0)
        row = np.zeros((frame_count, rig.width), dtype=np.int8)
        row[frames] = dependencies
        rows.append(row.reshape(-1))
    if not rows:
        return csr_matrix((0, frame_count * rig.width), dtype=np.int8)
    return csr_matrix(np.asarray(rows, dtype=np.int8).reshape(len(rows), frame_count * rig.width))


def support_range_jacobian(values, rig, tracks):
    """Differentiate range floors at their extrema without recoloring the clip.

    Each angular range depends locally on two frames. At tied extrema, choosing
    one extremum supplies a subgradient of the unchanged min/max objective.
    """
    coordinates = np.asarray(values).reshape(-1, rig.width)
    points = rig.decode(coordinates)
    rows, columns, derivatives = [], [], []
    step = np.sqrt(np.finfo(float).eps)
    for row, track_spec in enumerate(tracks):
        _, joints, source, *frame_range = track_spec
        frames = (np.asarray(frame_range[0], dtype=int) if frame_range
                  else np.arange(len(points)))
        track = angles(*(points[frames, joint] for joint in joints))
        if np.ptp(track) >= .92 * float(np.ptp(source)):
            continue
        dependencies = np.flatnonzero(np.max(
            rig.dependencies[[joint * 3 + axis for joint in joints for axis in range(3)]],
            axis=0))
        for local_frame, sign in ((int(np.argmin(track)), 1.), (int(np.argmax(track)), -1.)):
            frame = int(frames[local_frame])
            probes = np.repeat(coordinates[frame:frame + 1], len(dependencies), axis=0)
            probes[np.arange(len(dependencies)), dependencies] += step
            moved = rig.decode(probes)
            derivative = sign * 12000. * (
                angles(*(moved[:, joint] for joint in joints)) - track[local_frame]) / step
            rows.extend([row] * len(dependencies))
            columns.extend(frame * rig.width + dependencies)
            derivatives.extend(derivative)
    return csr_matrix((derivatives, (rows, columns)), shape=(len(tracks), len(values)))


def timed_foot_articulation_residuals(
    current_angles, specs, tracks, weight, source_foot_coverage=None,
    source_foot_phase_coverage=None, *, fps=30., cyclic=False,
):
    """Track leg-motion phase while timed foot contacts are owned.

    Knee rows compare source-relative angular increments, allowing a constant
    pose correction within the unchanged physical gates. Other articulation
    tracks retain their existing absolute-angle objective.
    """
    columns = {label: index for index, (label, _, _) in enumerate(specs)}
    current_angles = np.asarray(current_angles, dtype=float)
    frame_count = len(current_angles)
    phase_scale = np.sqrt(max(float(fps), 1e-9) / 30.)

    def residual_for_track(label, source):
        source = np.asarray(source, dtype=float)
        weights = np.full(len(current_angles), weight, dtype=float)
        if source_foot_coverage and label.endswith('_ankle'):
            coverage = np.asarray(source_foot_coverage.get(label, 0.))
            weights = np.where(
                coverage > 0., min(weight, SOURCE_PROJECTION_FIT_WEIGHT), weights,
            )
        phase_coverage = (source_foot_phase_coverage or {}).get(label)
        if phase_coverage is not None and label.endswith('_ankle'):
            weights = np.where(
                np.asarray(phase_coverage) > 0.,
                min(weight, SOURCE_PROJECTION_FIT_WEIGHT), weights,
            )
        angle_error = current_angles[:, columns[label]] - source
        if label.endswith('_knee'):
            previous = (np.roll(angle_error, 1) if cyclic
                        else np.r_[angle_error[:1], angle_error[:-1]])
            increment_error = angle_error - previous
            if not cyclic and frame_count:
                increment_error[0] = 0.
            return weights * phase_scale * increment_error
        return weights * angle_error

    return np.stack([
        residual_for_track(label, source)
        for label, _, source in tracks if label in columns
    ], axis=1) if tracks else np.empty((len(current_angles), 0))


def solve_trajectory(residual, initial, pattern, max_evaluations, *,
                     local_jacobian=None, tail_jacobian=None,
                     initial_jacobian=None):
    # Use an absolute perturbation throughout the solve. Relative steps shrink
    # toward cancellation at tiny rotations, especially under stiff penalties.
    # Reuse the coloring; one-sided grouped differences avoid doubling all FK
    # and interpolated-frame evaluations as central differences would.
    tail_rows = 0 if tail_jacobian is None else tail_jacobian(initial).shape[0]
    local_pattern = pattern[:-tail_rows] if tail_rows else pattern
    groups = group_columns(local_pattern) if local_jacobian is None else None
    initial_values = np.asarray(initial, dtype=float).reshape(-1)
    seeded_jacobian = initial_jacobian
    if (seeded_jacobian is not None
            and getattr(seeded_jacobian, 'shape', None) != pattern.shape):
        seeded_jacobian = None

    def local_residual(values):
        errors = residual(values)
        return errors[:-tail_rows] if tail_rows else errors
    def jacobian(values):
        nonlocal seeded_jacobian
        if seeded_jacobian is not None:
            if np.array_equal(np.asarray(values, dtype=float), initial_values):
                result = seeded_jacobian
                seeded_jacobian = None
                return result
            seeded_jacobian = None
        if local_jacobian is not None:
            local = local_jacobian(values)
            return vstack([local, tail_jacobian(values)], format='csr') if tail_rows else local
        local = approx_derivative(local_residual, values, method='2-point',
            abs_step=np.sqrt(np.finfo(float).eps), sparsity=(local_pattern, groups))
        return vstack([local, tail_jacobian(values)], format='csr') if tail_rows else local
    return least_squares(residual,initial,jac=jacobian,
                         max_nfev=max_evaluations,ftol=1e-6,xtol=None,gtol=1e-6,
                         x_scale='jac',tr_options={'maxiter':600})


def root_travel_preservation_residual(root_track, target_root_track, *, body_scale):
    target_span = float(np.linalg.norm(np.ptp(target_root_track, axis=0)))
    if target_span < ROOT_TRAVEL_SMALL_MOTION_BODY_RATIO * body_scale:
        return 0.
    fitted_span = float(np.linalg.norm(np.ptp(root_track, axis=0)))
    return ROOT_TRAVEL_FIT_WEIGHT * max(
        0., ROOT_TRAVEL_MINIMUM_PRESERVED_RATIO * target_span - fitted_span,
    ) / body_scale


def root_travel_preservation_jacobian(
        root_track, target_root_track, *, body_scale, coordinate_width=3):
    """Differentiate the active one-sided root-span residual at its extrema."""
    root_track = np.asarray(root_track, dtype=float)
    target_spans = np.ptp(np.asarray(target_root_track, dtype=float), axis=0)
    target_span = float(np.linalg.norm(target_spans))
    fitted_spans = np.ptp(root_track, axis=0)
    fitted_span = float(np.linalg.norm(fitted_spans))
    shape = (1, len(root_track) * int(coordinate_width))
    if (target_span < ROOT_TRAVEL_SMALL_MOTION_BODY_RATIO * body_scale
            or fitted_span >= ROOT_TRAVEL_MINIMUM_PRESERVED_RATIO * target_span):
        return csr_matrix(shape)

    direction = fitted_spans / fitted_span if fitted_span > 1e-12 else target_spans / target_span
    columns, values = [], []
    for axis, component in enumerate(direction):
        if abs(component) <= 1e-15:
            continue
        minimum = int(np.argmin(root_track[:, axis]))
        maximum = int(np.argmax(root_track[:, axis]))
        if minimum == maximum:
            minimum, maximum = 0, len(root_track) - 1
        columns.extend((minimum * coordinate_width + axis, maximum * coordinate_width + axis))
        values.extend((
            ROOT_TRAVEL_FIT_WEIGHT * component / body_scale,
            -ROOT_TRAVEL_FIT_WEIGHT * component / body_scale,
        ))
    return csr_matrix((values, ([0] * len(columns), columns)), shape=shape)


def world_jerk_fit_target(jerk_before, jerk_limit):
    """Use native jerk as the target, with only existing gate headroom as margin."""
    jerk_limit = float(jerk_limit)
    jerk_before = float(jerk_before)
    if (jerk_limit <= 0. or not np.isfinite(jerk_limit)
            or not np.isfinite(jerk_before)):
        return jerk_limit
    return min(jerk_limit, max(jerk_before, TEMPORAL_FIT_TARGET_RATIO * jerk_limit))


def world_jerk_feasibility_residual(points, world_d3, fit_target):
    """Penalize only candidates above the source-relative interior fit target."""
    fit_target = float(fit_target)
    point_jerk = np.asarray(world_d3 @ np.asarray(points).reshape(len(points), -1), dtype=float)
    if (fit_target <= 0. or point_jerk.size == 0
            or not np.isfinite(fit_target) or not np.isfinite(point_jerk).all()):
        return float(ANATOMY_FIT_WEIGHT)
    rms_jerk = float(np.sqrt(np.mean(point_jerk ** 2)))
    return ANATOMY_FIT_WEIGHT * max(0., rms_jerk / fit_target - 1.)


def world_jerk_profile_rows(points, reference, world_d3, jerk_limit):
    """Track changes from the observed jerk profile, not a slower zero-jerk pose."""
    points = np.asarray(points, dtype=float)
    reference = np.asarray(reference, dtype=float)
    delta_jerk = world_d3 @ (points - reference).reshape(len(points), -1)
    return (10. * np.asarray(delta_jerk).ravel() /
            (TEMPORAL_FIT_TARGET_RATIO * float(jerk_limit) * np.sqrt(delta_jerk.size)))


def world_jerk_feasibility_jacobian(coordinates, rig, world_d3, fit_target):
    """Analytic one-row RMS-jerk hinge derivative, chained through the rig FK."""
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    points = rig.decode(coordinates)
    point_jerk = np.asarray(world_d3 @ points.reshape(len(points), -1), dtype=float)
    rms_jerk = (float(np.sqrt(np.mean(point_jerk ** 2)))
                if point_jerk.size and np.isfinite(point_jerk).all() else 0.)
    fit_target = float(fit_target)
    if (fit_target <= 0. or not np.isfinite(fit_target)
            or not np.isfinite(rms_jerk) or rms_jerk <= fit_target or rms_jerk <= 1e-15):
        return csr_matrix((1, coordinates.size))
    point_gradient = (
        ANATOMY_FIT_WEIGHT * (world_d3.T @ point_jerk).reshape(-1)
        / (point_jerk.size * rms_jerk * fit_target)
    )
    return csr_matrix(point_gradient.reshape(1, -1)) @ rig.fk_jacobian(coordinates)


def _stationary_source_anchor_groups(payload, names, count):
    """Map source-confirmed planted feet/ankles to shared stance identities."""
    from .contact_constraints import (
        contact_frame_bounds,
        is_stationary_contact,
        motion_space_support_evidence,
        motion_support_contacts,
    )

    groups = np.full((count, len(names)), None, dtype=object)
    confidences = np.full((count, len(names)), np.nan, dtype=float)
    evidence = motion_space_support_evidence(payload)
    airborne_epochs = {}
    for contact_index, contact in enumerate(motion_support_contacts(evidence)):
        if (not is_stationary_contact(contact)
                or contact.get('contactState') == 'heel_only'):
            continue
        name = str(contact.get('jointName') or '')
        if name not in names or not name.endswith(('_foot', '_ankle')):
            continue
        start, end = contact_frame_bounds(contact, count)
        side = name.split('_', 1)[0]
        full_sole = contact.get('contactState') == 'full_sole'
        supplied_anchor = contact.get('anchorGroupId')
        row_identity = str(supplied_anchor) if supplied_anchor is not None else f'contact:{contact_index}'
        if full_sole:
            if name.endswith('_foot'):
                anchor_by_joint = {
                    f'{side}_foot': row_identity,
                    f'{side}_ankle': str(contact.get('ankleAnchorGroupId') or row_identity),
                }
            else:
                anchor_by_joint = {
                    f'{side}_ankle': row_identity,
                    f'{side}_foot': str(contact.get('ankleAnchorGroupId') or row_identity),
                }
            joint_names = (f'{side}_foot', f'{side}_ankle')
        else:
            anchor_by_joint = {name: row_identity}
            joint_names = (name,)
        confidence = contact.get('confidence')
        try:
            confidence = float(confidence)
        except (TypeError, ValueError, OverflowError):
            confidence = .1
        if not np.isfinite(confidence):
            confidence = .1
        confidence = float(np.clip(confidence, 0., 1.))
        if side not in airborne_epochs:
            airborne_epochs[side] = _airborne_epoch_track(
                evidence, f'{side}_ankle', count,
            )
        epochs = airborne_epochs[side]
        for frame_index in range(start, end + 1):
            scoped_anchors = {
                joint_name: _airborne_scoped_anchor_id(
                    anchor_id,
                    None if epochs is None else epochs[frame_index],
                )
                for joint_name, anchor_id in anchor_by_joint.items()
            }
            if full_sole:
                group_key = (
                    'sole', side, scoped_anchors[f'{side}_foot'],
                    scoped_anchors[f'{side}_ankle'],
                )
            else:
                group_key = (
                    'joint', side, name.rsplit('_', 1)[-1],
                    scoped_anchors[name],
                )
            for joint_name in joint_names:
                if joint_name not in names:
                    continue
                joint = names.index(joint_name)
                groups[frame_index, joint] = group_key
                confidences[frame_index, joint] = confidence
    return groups, confidences


def _fit_source_interval_selection(payload):
    """Resolve the selected source interval whose endpoints the fit must retain.

    Internal cycle fitting predates artifact-state metadata and still uses
    ``loopCycleSelection``. Preview baking records its interval in artifact
    lineage instead. Prefer the legacy marker when both exist: it describes
    the exact sub-cycle currently being fitted, while artifact lineage can
    describe its parent selection.
    """
    frames = payload.get('frames') or []
    loop = payload.get('loop') or {}
    legacy = payload.get('loopCycleSelection')
    selection = None
    if isinstance(legacy, dict):
        start = legacy.get('startFrame')
        stop = legacy.get('stopFrameExclusive')
        if (type(start) is int and type(stop) is int and start >= 0 and stop > start
                and len(frames) == stop - start):
            input_count = legacy.get('inputFrameCount')
            if (input_count is None or (type(input_count) is int and stop <= input_count)):
                if not all(isinstance(frame, dict) for frame in frames):
                    return {
                        'available': False,
                        'reason': 'selected_source_interval_legacy_frame_provenance_missing',
                    }
                expected_frame_indices = range(start, stop)
                actual_frame_indices = [frame.get('cycleSourceFrameIndex') for frame in frames]
                if any(type(actual) is not int for actual in actual_frame_indices) or list(
                    expected_frame_indices
                ) != actual_frame_indices:
                    return {
                        'available': False,
                        'reason': 'selected_source_interval_legacy_frame_bounds_mismatch',
                    }
                try:
                    source_times = [float(frame['cycleSourceTimeSec']) for frame in frames]
                    source_start = float(legacy['sourceStartTimeSec'])
                    source_stop = float(legacy['sourceStopTimeSec'])
                    fps = float(payload['fps'])
                except (KeyError, TypeError, ValueError, OverflowError):
                    return {
                        'available': False,
                        'reason': 'selected_source_interval_legacy_time_provenance_missing',
                    }
                if (not np.isfinite(source_times).all()
                        or not np.isfinite([source_start, source_stop, fps]).all()
                        or fps <= 0.
                        or any(right <= left for left, right in zip(source_times, source_times[1:]))):
                    return {
                        'available': False,
                        'reason': 'selected_source_interval_legacy_time_provenance_invalid',
                    }
                if (abs(source_start - source_times[0]) > 1e-6
                        or abs(source_stop - (source_times[-1] + 1. / fps)) > 1e-6
                        or any(time < source_start - 1e-6 or time >= source_stop for time in source_times)):
                    return {
                        'available': False,
                        'reason': 'selected_source_interval_legacy_time_bounds_mismatch',
                    }
                selection = {'kind': 'cycle', 'source': 'loopCycleSelection', 'interval': legacy}
    if selection is None:
        state = payload.get('artifactState')
        evidence = state.get('selectionEvidence') if isinstance(state, dict) else None
        if isinstance(evidence, dict):
            cycle = evidence.get('cycleSelection')
            bounded = evidence.get('boundedMovementSelection')
            if isinstance(cycle, dict) and isinstance(cycle.get('interval'), dict):
                selection = {
                    'kind': 'cycle', 'source': 'artifactState.cycleSelection',
                    'interval': cycle['interval'],
                }
            elif isinstance(bounded, dict) and isinstance(bounded.get('interval'), dict):
                selection = {
                    'kind': 'bounded_movement', 'source': 'artifactState.boundedMovementSelection',
                    'interval': bounded['interval'],
                }
    if selection is None:
        return {'available': False, 'reason': 'selected_source_interval_unavailable'}

    interval = selection['interval']
    first = next((frame for frame in frames if isinstance(frame, dict)), {})
    last = next((frame for frame in reversed(frames) if isinstance(frame, dict)), {})

    def same_frame_bound(expected, actual):
        return type(expected) is int and type(actual) is int and expected == actual

    def same_time_bound(expected, actual):
        try:
            return (not isinstance(expected, bool) and not isinstance(actual, bool)
                    and np.isfinite(float(expected)) and np.isfinite(float(actual))
                    and abs(float(expected) - float(actual)) <= 1e-6)
        except (TypeError, ValueError, OverflowError):
            return False

    if selection['source'].startswith('artifactState.'):
        # Artifact lineage and the exported source bounds must name the same
        # inclusive frame/time interval. Falling back to actual frame provenance
        # supports older payloads whose loop object omitted these fields.
        checks = (
            ('startFrame', 'sourceStartFrame', first.get('sourceFrameIndex'), same_frame_bound),
            ('endFrame', 'sourceEndFrame', last.get('sourceFrameIndex'), same_frame_bound),
            ('startTimeSec', 'sourceStartTimeSec', first.get('sourceTimeSec'), same_time_bound),
            ('endTimeSec', 'sourceEndTimeSec', last.get('sourceTimeSec'), same_time_bound),
        )
        for interval_key, loop_key, frame_value, matcher in checks:
            expected = interval.get(interval_key)
            loop_value = loop.get(loop_key) if isinstance(loop, dict) else None
            if loop_value is not None and not matcher(expected, loop_value):
                return {'available': False, 'reason': 'selected_source_interval_loop_bounds_mismatch'}
            if frame_value is not None and not matcher(expected, frame_value):
                return {'available': False, 'reason': 'selected_source_interval_frame_bounds_mismatch'}
    else:
        # A legacy selection uses parent-frame indices. Verify its crop size
        # above, and when source bounds are present ensure they still describe
        # the actual exported endpoints.
        for loop_key, frame_key in (
            ('sourceStartFrame', 'sourceFrameIndex'),
            ('sourceEndFrame', 'sourceFrameIndex'),
        ):
            loop_value = loop.get(loop_key) if isinstance(loop, dict) else None
            frame_value = first.get(frame_key) if loop_key == 'sourceStartFrame' else last.get(frame_key)
            if loop_value is not None and not same_frame_bound(loop_value, frame_value):
                return {'available': False, 'reason': 'selected_source_interval_loop_bounds_mismatch'}
        for loop_key, frame in (
            ('sourceStartTimeSec', first),
            ('sourceEndTimeSec', last),
        ):
            loop_value = loop.get(loop_key) if isinstance(loop, dict) else None
            frame_value = frame.get('sourceTimeSec')
            if loop_value is not None and not same_time_bound(loop_value, frame_value):
                return {'available': False, 'reason': 'selected_source_interval_loop_bounds_mismatch'}

    return {
        'available': True,
        'kind': selection['kind'],
        'source': selection['source'],
        'interval': interval,
    }


def _selected_interval_source_fit_coverage_gaps(payload, constraint):
    """Require source-camera evidence at both endpoints of a selected movement."""
    selection = _fit_source_interval_selection(payload)
    if not selection.get('available'):
        state = payload.get('artifactState')
        evidence = state.get('selectionEvidence') if isinstance(state, dict) else None
        declares_interval = (
            isinstance(payload.get('loopCycleSelection'), dict)
            or isinstance(evidence, dict)
            and any(isinstance(evidence.get(key), dict) for key in (
                'cycleSelection', 'boundedMovementSelection'))
        )
        if not declares_interval:
            return []
        reason = selection.get('reason') or 'selected_source_interval_unavailable'
        return [f'selected_source_interval_invalid:{reason}']

    if not constraint.get('available'):
        reason = constraint.get('reason') or 'source_projection_constraint_unavailable'
        return [f'source_projection_constraint_unavailable:{reason}']

    gaps = []
    endpoint_coverage = constraint.get('endpointPostureCoverage') or {}
    for role in ('start', 'end'):
        if not (endpoint_coverage.get(role) or {}).get('available'):
            gaps.append(f'source_endpoint_posture_{role}_unavailable')

    if selection.get('kind') == 'cycle':
        boundary_coverage = constraint.get('cycleBoundaryCoverage') or {}
        boundary_observation_count = constraint.get('cycleBoundaryObservationCount') or {}
        for role in ('start', 'end'):
            coverage = boundary_coverage.get(role) or {}
            effective_count = boundary_observation_count.get(role, 0)
            effective_available = (
                type(effective_count) is int
                and effective_count >= SOURCE_CYCLE_BOUNDARY_MIN_EFFECTIVE_OBSERVATIONS
            )
            if not coverage.get('available') or not effective_available:
                gaps.append(f'source_cycle_boundary_{role}_unavailable')
    return gaps


def _authoritative_support_projection_joints(body_support, names):
    """Return stationary joints whose observed 3D support plane outranks image lift."""
    if (not isinstance(body_support, dict)
            or body_support.get('required') is not True
            or body_support.get('status') != 'confirmed'):
        return set()
    stationary = set(body_support.get('stationaryJoints') or []) & set(names)
    if not stationary:
        return set()
    from .support_geometry import evidence_is_complete
    if not evidence_is_complete(body_support, names):
        return set()
    plane_constrained_joints = {
        joint_name
        for group in body_support.get('coplanarGroups') or []
        if group.get('planeOffsetMeters') is not None
        for joint_name in group.get('joints') or []
    }
    return stationary & plane_constrained_joints


def _source_projection_constraint_report(constraint):
    diagnostics = {
        key: constraint.get(key)
        for key in (
            'available', 'reason', 'sourceFrameCount', 'observationCount',
            'distinctFitTimeCount', 'cameraAuthority', 'weight',
            'cycleBoundaryCoverage', 'cycleBoundaryObservationCount',
            'cycleBoundaryFitMultiplier',
            'supportAnchorObservationCount', 'supportAnchorProjectionOmittedCount',
            'sourceFootRayObservationCount', 'sourceFootRaySideMapping',
            'sourceFootHeelPhaseObservationCount',
            'sourceFootHeelImageObservationCount',
            'sourceFootHeelTrajectoryObservationCount',
            'sourceFootHeelUnresolvedToeOnlyObservationCount',
            'sourceFootHeelCalibrationBySide',
            'sourceFootPointObservationCount', 'sourceFootPointOffsetBySide',
            'endpointPostureObservationCount', 'endpointPostureCoverage',
            'endpointPostureWindowHalfWidthSeconds', 'endpointPostureFitMultiplier',
            'selectedIntervalKind', 'selectedIntervalEvidenceSource', 'selectedIntervalReason',
        )
    }
    diagnostics.update({
        'sourceFootRayObservationCount': len(
            constraint.get('sourceFootRayObservations') or []),
        'sourceFootHeelPhaseObservationCount': len(
            _source_foot_phase_observations(constraint)),
        'sourceFootHeelImageObservationCount': len(
            constraint.get('sourceFootHeelImageObservations') or []),
        'sourceFootHeelTrajectoryObservationCount': len(
            constraint.get('sourceFootHeelTrajectoryObservations') or []),
        'sourceFootHeelTrajectoryEventCount': len(
            constraint.get('sourceFootHeelTrajectoryEvents') or []),
        'sourceFootHeelUnresolvedToeOnlyObservationCount': int(
            constraint.get('sourceFootHeelUnresolvedToeOnlyObservationCount', 0)),
        'sourceFootHeelCalibrationBySide': constraint.get(
            'sourceFootHeelTrajectoryCalibrationBySide') or {},
        'sourceFootRaySideMapping': constraint.get('sourceFootRaySideMapping') or {},
        'sourceFootPointObservationCount': len(
            constraint.get('sourceFootPointObservations') or []),
        'sourceFootPointOffsetBySide': constraint.get('sourceFootPointOffsetBySide') or {},
        'supportRelativeObservationCount': len(
            constraint.get('supportRelativeObservations') or []
        ),
        'supportRelativeJointNames': constraint.get(
            'supportRelativeJointNames', []),
        'supportRelativeWeight': constraint.get('supportRelativeWeight'),
    })
    diagnostics['sharedAnchorAdjustment'] = {
        'adjustedGroupCount': 0,
        'maximumShiftMeters': 0.,
    }
    return diagnostics


def _prepare_source_projection_fit_constraints(payload, frames, names, points, pinned, scale):
    """Project retained source observations into the fit using its fixed camera."""
    retained = payload.get('sourcePoseCameraReference')
    unavailable = {'available': False, 'observations': [], 'reason': 'source_camera_reference_missing'}
    if not isinstance(retained, dict):
        return unavailable
    source_pose = retained.get('sourcePose')
    camera = retained.get('camera')
    if not isinstance(source_pose, dict) or not isinstance(camera, dict):
        return {**unavailable, 'reason': 'source_camera_reference_incomplete'}
    if not frames or not all(
        isinstance(frame, dict) and ('sourceTimeSec' in frame or 'cycleSourceTimeSec' in frame)
        for frame in frames
    ):
        return {**unavailable, 'reason': 'source_timestamps_unavailable'}
    try:
        rotation = np.asarray(camera.get('cameraRotation'), dtype=float)
        image_transform = tuple(float(value) for value in camera.get('cameraImageTransform', []))
    except (TypeError, ValueError, OverflowError):
        return {**unavailable, 'reason': 'invalid_source_camera_registration'}
    if (
        rotation.shape != (3, 3)
        or not np.isfinite(rotation).all()
        or len(image_transform) != 6
        or not np.isfinite(image_transform).all()
    ):
        return {**unavailable, 'reason': 'invalid_source_camera_registration'}

    from .pose_fidelity import (
        _bilateral_name,
        _pose_frames,
        _recenter_constant_image_offset,
        source_pose_reference_for_motion,
    )
    from .pose_fidelity import materialized_camera_placement_transform
    placement = materialized_camera_placement_transform(source_pose, payload)
    if not placement.get('available'):
        return {**unavailable, 'reason': placement.get('reason', 'source_camera_placement_unavailable')}
    # Transport the retained camera into the placed skeleton's coordinate frame.
    rotation = rotation @ placement['orientation'] / placement['scale']
    source_window = source_pose_reference_for_motion(
        source_pose,
        payload,
        include_adjacent_boundary_evidence=True,
    )
    source_frames = _pose_frames(source_window, source=True)
    if len(source_frames) < 3:
        return {**unavailable, 'reason': 'insufficient_timestamped_source_observations'}

    try:
        times = np.asarray([float(frame['timeSec']) for frame in frames], dtype=float)
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**unavailable, 'reason': 'fit_timestamps_unavailable'}
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        return {**unavailable, 'reason': 'invalid_fit_timestamps'}
    selected_source_frames = [
        frame for frame in source_frames
        if times[0] - 1e-9 <= float(frame['time']) <= times[-1] + 1e-9
    ]
    if len(selected_source_frames) < 3:
        return {**unavailable, 'reason': 'insufficient_in_interval_source_observations'}
    projection_source_time_tolerance = max(
        0.5 / float(payload.get('fps') or 30.), 1e-6,
    )
    selected_interval = _fit_source_interval_selection(payload)
    selected_interval_kind = selected_interval.get('kind') if selected_interval.get('available') else None
    selected_cycle = selected_interval_kind == 'cycle'
    selected_movement = selected_interval_kind in {'cycle', 'bounded_movement'}
    cycle_boundary_roles = defaultdict(set)
    cycle_boundary_coverage = {
        'selectedCycle': selected_cycle,
        'selectedMovement': selected_movement,
        'start': {'available': False},
        'end': {'available': False},
    }
    endpoint_posture_observations = []
    endpoint_posture_coverage = {
        'selectedCycle': selected_cycle,
        'selectedMovement': selected_movement,
        'start': {'available': False},
        'end': {'available': False},
    }
    swap = camera.get('bilateralAssignment') == 'swapped'

    def source_confidence(frame, joint_names):
        values = frame.get('jointConfidence') or {}
        confidences = []
        for joint_name in joint_names:
            try:
                value = float(values.get(joint_name, .1))
            except (TypeError, ValueError, OverflowError):
                value = .1
            if not np.isfinite(value):
                value = .1
            confidences.append(float(np.clip(value, 0., 1.)))
        return min(confidences, default=.1)

    if selected_movement:
        source_times = np.asarray([float(frame['time']) for frame in source_frames], dtype=float)
        positive_source_deltas = np.diff(source_times)
        positive_source_deltas = positive_source_deltas[positive_source_deltas > 0.]
        source_step = (
            float(np.median(positive_source_deltas))
            if positive_source_deltas.size
            else 0.
        )
        fit_step = float(np.median(np.diff(times))) if len(times) > 1 else 0.
        coverage_tolerance = max(.5 * source_step, .5 * fit_step, 1e-6)
        projection_source_time_tolerance = coverage_tolerance
        if selected_cycle:
            for role, target_time in (('start', float(times[0])), ('end', float(times[-1]))):
                nearest_index = int(np.argmin(np.abs(source_times - target_time)))
                delta = abs(float(source_times[nearest_index] - target_time))
                source_joint_count = sum(
                    _bilateral_name(name, swap=swap) in names
                    for name in source_frames[nearest_index]['joints']
                )
                covered = delta <= coverage_tolerance + 1e-9 and source_joint_count >= 3
                cycle_boundary_coverage[role] = {
                    'available': covered,
                    'sourceObservationIndex': nearest_index if covered else None,
                    'offsetSeconds': delta if covered else None,
                    'toleranceSeconds': coverage_tolerance,
                    'jointObservationCount': source_joint_count,
                }
                if covered:
                    cycle_boundary_roles[nearest_index].add(role)
        requested_posture_window_half_width = min(
            SOURCE_ENDPOINT_POSTURE_MAX_WINDOW_SECONDS,
            max(SOURCE_ENDPOINT_POSTURE_MIN_WINDOW_SECONDS, 1.5 * source_step, 2. * fit_step),
        )
        cycle_duration = max(0., float(times[-1] - times[0]))
        posture_window_half_width = min(
            requested_posture_window_half_width,
            cycle_duration / 4.,
        )
        fit_joint_index = {name: index for index, name in enumerate(names)}
        can_use_pelvis_center = 'pelvis' in fit_joint_index
        can_use_hip_center = {'left_hip', 'right_hip'} <= set(fit_joint_index)
        if can_use_pelvis_center or can_use_hip_center:
            def source_center(frame):
                joints = frame['joints']
                pelvis_confidence = (
                    source_confidence(frame, ('pelvis',))
                    if 'pelvis' in joints else 0.
                )
                if (can_use_pelvis_center and 'pelvis' in joints
                        and pelvis_confidence >= .35):
                    center = np.asarray(joints['pelvis'], dtype=float)
                    confidence_names = ('pelvis',)
                    center_joint_indices = (fit_joint_index['pelvis'],)
                elif (can_use_hip_center and {'left_hip', 'right_hip'} <= joints.keys()
                      and source_confidence(frame, ('left_hip', 'right_hip')) >= .35):
                    center = (np.asarray(joints['left_hip'], dtype=float)
                              + np.asarray(joints['right_hip'], dtype=float)) * .5
                    confidence_names = ('left_hip', 'right_hip')
                    center_joint_indices = (
                        fit_joint_index['left_hip'], fit_joint_index['right_hip'],
                    )
                elif can_use_pelvis_center and 'pelvis' in joints:
                    center = np.asarray(joints['pelvis'], dtype=float)
                    confidence_names = ('pelvis',)
                    center_joint_indices = (fit_joint_index['pelvis'],)
                elif (can_use_hip_center and {'left_hip', 'right_hip'} <= joints.keys()):
                    center = (np.asarray(joints['left_hip'], dtype=float)
                              + np.asarray(joints['right_hip'], dtype=float)) * .5
                    confidence_names = ('left_hip', 'right_hip')
                    center_joint_indices = (
                        fit_joint_index['left_hip'], fit_joint_index['right_hip'],
                    )
                else:
                    return None, .1, ()
                return center, source_confidence(frame, confidence_names), center_joint_indices

            for role, target_time in (('start', float(times[0])), ('end', float(times[-1]))):
                window_frames = [
                    (frame_index, frame)
                    for frame_index, frame in enumerate(source_frames)
                    if abs(float(frame['time']) - target_time) <= posture_window_half_width + 1e-9
                ]
                samples_by_joint = defaultdict(dict)
                center_sample_times = []
                role_observations = []
                for source_frame_index, source_frame in window_frames:
                    source_time = float(source_frame['time'])
                    center, center_confidence, center_joint_indices = source_center(source_frame)
                    if center is None:
                        continue
                    source_time_key = next((known_time for known_time in center_sample_times
                                            if abs(known_time - source_time) <= 1e-6), None)
                    if source_time_key is None:
                        source_time_key = source_time
                        center_sample_times.append(source_time_key)
                    right = int(np.searchsorted(times, source_time, side='left'))
                    if right <= 0:
                        left, right, alpha = 0, 0, 0.
                    elif right >= len(times):
                        left, right, alpha = len(times) - 1, len(times) - 1, 0.
                    else:
                        left = right - 1
                        span = float(times[right] - times[left])
                        alpha = 0. if span <= 1e-12 else float((source_time - times[left]) / span)
                    for source_name, source_point in source_frame['joints'].items():
                        motion_name = _bilateral_name(source_name, swap=swap)
                        joint_index = fit_joint_index.get(motion_name)
                        if joint_index is None or joint_index in center_joint_indices:
                            continue
                        point_confidence_names = (source_name,)
                        if (source_name == 'pelvis'
                                and source_confidence(source_frame, ('pelvis',)) < .35
                                and {'left_hip', 'right_hip'} <= source_frame['joints'].keys()
                                and source_confidence(
                                    source_frame, ('left_hip', 'right_hip')) >= .35):
                            source_point = (
                                np.asarray(source_frame['joints']['left_hip'], dtype=float)
                                + np.asarray(source_frame['joints']['right_hip'], dtype=float)
                            ) * .5
                            point_confidence_names = ('left_hip', 'right_hip')
                        confidence = min(
                            source_confidence(source_frame, point_confidence_names),
                            center_confidence,
                        )
                        if confidence <= 0.:
                            continue
                        sample = {
                            'sourceDelta': np.asarray(source_point, dtype=float) - center,
                            'confidence': confidence,
                            'centerJointIndices': center_joint_indices,
                            'leftFrame': left,
                            'rightFrame': right,
                            'alpha': alpha,
                            'sourceFrameIndex': source_frame_index,
                            'sourceTime': source_time,
                        }
                        previous = samples_by_joint[joint_index].get(source_time_key)
                        if previous is None or confidence > previous['confidence']:
                            samples_by_joint[joint_index][source_time_key] = sample
                covered_joints = 0
                for joint_index, samples_by_time in samples_by_joint.items():
                    samples = list(samples_by_time.values())
                    # A posture window needs multiple source times; a single
                    # landmark would duplicate the pointwise boundary row.
                    if len(samples) < 2:
                        continue
                    sample_weights = np.asarray([sample['confidence'] for sample in samples], dtype=float)
                    weight_sum = float(sample_weights.sum())
                    if not np.isfinite(weight_sum) or weight_sum <= 1e-9:
                        continue
                    confidence_weight = float(np.sqrt(np.mean(sample_weights)))
                    for sample, sample_weight in zip(samples, sample_weights):
                        role_observations.append({
                            'role': role,
                            'jointIndex': joint_index,
                            'centerJointIndices': sample['centerJointIndices'],
                            'sourceDelta': sample['sourceDelta'],
                            'fitLinks': [{
                                'leftFrame': sample['leftFrame'],
                                'rightFrame': sample['rightFrame'],
                                'alpha': sample['alpha'],
                                'weight': 1.,
                            }],
                            'confidenceWeight': confidence_weight,
                            'sampleWeight': float(np.sqrt(sample_weight / weight_sum)),
                            'sourceSampleCount': len(samples),
                        })
                    covered_joints += 1
                role_available = len(center_sample_times) >= 2 and covered_joints >= 3
                if role_available:
                    endpoint_posture_observations.extend(role_observations)
                endpoint_posture_coverage[role] = {
                    'available': role_available,
                    'sourceSampleCount': len(center_sample_times),
                    'constrainedJointCount': covered_joints if role_available else 0,
                    'meanConfidenceWeight': float(np.mean([
                        observation['confidenceWeight'] for observation in role_observations
                    ])) if role_available else 0.,
                    'windowHalfWidthSeconds': float(posture_window_half_width),
                    'sourceTimeStartSec': float(min((frame['time'] for _, frame in window_frames), default=target_time)),
                    'sourceTimeEndSec': float(max((frame['time'] for _, frame in window_frames), default=target_time)),
                }
        else:
            posture_window_half_width = 0.
            for role in ('start', 'end'):
                endpoint_posture_coverage[role]['reason'] = 'fit_pelvis_unavailable'
    else:
        posture_window_half_width = 0.
        for role in ('start', 'end'):
            endpoint_posture_coverage[role]['reason'] = 'selected_source_interval_unavailable'
    axis_flip = np.asarray([1., -1., -1.])
    transformed_input = []
    for index, frame in enumerate(frames):
        transformed = (rotation @ points[index].T).T * axis_flip
        transformed_input.append({
            'time': float(times[index]),
            'joints': {name: tuple(point) for name, point in zip(names, transformed)},
        })
    transform = _recenter_constant_image_offset(
        selected_source_frames,
        transformed_input,
        swap,
        image_transform,
    )
    a, b, source_x, source_y, target_x, target_y = transform
    projection_scale = float(np.hypot(a, b))
    if not np.isfinite(projection_scale) or projection_scale <= 1e-9:
        return {**unavailable, 'reason': 'source_camera_scale_unavailable'}
    projection = np.asarray([
        a * rotation[0] - b * rotation[1],
        b * rotation[0] + a * rotation[1],
    ])
    offset = np.asarray([
        -a * source_x + b * source_y + target_x,
        -b * source_x - a * source_y + target_y,
    ])

    observations = []
    source_foot_ray_observations = []
    source_foot_point_observations = []
    source_foot_point_offset_by_side = {}
    source_foot_ray_side_mapping = {}
    source_foot_heel_trajectory_observations = []
    source_foot_heel_trajectory_events = []
    source_foot_heel_image_observations = []
    source_foot_heel_calibration_by_side = {}
    source_foot_heel_calibration_observations = []
    source_foot_heel_unresolved_toe_only_count = 0
    fit_joint_index = {name: index for index, name in enumerate(names)}
    from .contact_constraints import motion_space_support_evidence
    body_support = motion_space_support_evidence(payload).get('bodySupport') or {}
    support_plane_authoritative_joints = _authoritative_support_projection_joints(
        body_support, names,
    )
    confirmed_body_support_joints = (
        set(body_support.get('stationaryJoints') or [])
        if body_support.get('required') is True and body_support.get('status') == 'confirmed'
        else set()
    )
    anchor_groups, anchor_confidences = _stationary_source_anchor_groups(
        payload, names, len(frames))
    cycle_boundary_observation_count = {'start': 0, 'end': 0}
    support_anchor_observation_count = 0
    support_anchor_projection_omitted_count = 0
    for source_frame_index, source_frame in enumerate(source_frames):
        source_time = float(source_frame['time'])
        if (source_time < times[0] - projection_source_time_tolerance
                or source_time > times[-1] + projection_source_time_tolerance):
            continue
        right = int(np.searchsorted(times, source_time, side='left'))
        if right <= 0:
            left, right, alpha = 0, 0, 0.
        elif right >= len(times):
            left, right, alpha = len(times) - 1, len(times) - 1, 0.
        else:
            left = right - 1
            span = float(times[right] - times[left])
            alpha = 0. if span <= 1e-12 else float((source_time - times[left]) / span)
        confidence = source_frame.get('jointConfidence') or {}
        for source_name, source_point in source_frame['joints'].items():
            motion_name = _bilateral_name(source_name, swap=swap)
            joint_index = fit_joint_index.get(motion_name)
            if joint_index is None:
                continue
            if motion_name in support_plane_authoritative_joints:
                # The retained source-camera lift is noisy along image vertical.
                # A confirmed, explicit 3D support plane already fixes these
                # anchors; allowing the image lift to move them breaks contact
                # geometry. Keep source-camera rows for every other joint.
                support_anchor_projection_omitted_count += 1
                continue
            anchor_group = None
            if pinned[left, joint_index] and pinned[right, joint_index]:
                if not motion_name.endswith(('_foot', '_ankle')):
                    # Confirmed body-support anchors are already constrained by
                    # the support geometry in 3D. Keep that geometry authoritative
                    # for depth, while also giving the fit the exact source-camera
                    # observation for each pinned joint. Unconfirmed or unrelated
                    # pinned joints remain excluded from this additional prior.
                    if motion_name not in confirmed_body_support_joints:
                        continue
                else:
                    left_group = anchor_groups[left, joint_index]
                    right_group = anchor_groups[right, joint_index]
                    if left_group is not None and left_group == right_group:
                        anchor_group = left_group
                    elif motion_name not in confirmed_body_support_joints:
                        # Contact-derived anchor identities are required for
                        # unconfirmed distal pins. A confirmed body-support
                        # joint is already fixed by its 3D support geometry,
                        # so its source-camera observation can still constrain
                        # the visible placement when no foot-patch group exists.
                        continue
                if motion_name in confirmed_body_support_joints:
                    support_anchor_observation_count += 1
            # An absent confidence value is unknown; keep the observation at
            # low trust instead of silently promoting it to full authority.
            confidence_value = confidence.get(source_name)
            if (source_name == 'pelvis'
                    and (confidence_value is None or confidence_value < .35)
                    and {'left_hip', 'right_hip'} <= source_frame['joints'].keys()):
                hip_confidence = source_confidence(
                    source_frame, ('left_hip', 'right_hip'))
                if hip_confidence >= .35:
                    # Some pose extractors synthesize pelvis from the hips but
                    # omit its confidence. Treat that derived center as no more
                    # uncertain than its observed bilateral inputs.
                    source_point = (
                        np.asarray(source_frame['joints']['left_hip'], dtype=float)
                        + np.asarray(source_frame['joints']['right_hip'], dtype=float)
                    ) * .5
                    confidence_value = hip_confidence
            try:
                confidence_value = float(confidence_value)
            except (TypeError, ValueError, OverflowError):
                confidence_value = .1
            if not np.isfinite(confidence_value):
                confidence_value = .1
            confidence_value = float(np.clip(confidence_value, 0., 1.))
            if anchor_group is not None:
                contact_confidence = np.nanmean([
                    anchor_confidences[left, joint_index],
                    anchor_confidences[right, joint_index],
                ])
                if not np.isfinite(contact_confidence):
                    contact_confidence = .1
                confidence_value = min(confidence_value, float(contact_confidence))
            confidence_weight = float(np.sqrt(confidence_value))
            boundary_roles = sorted(cycle_boundary_roles.get(source_frame_index, ()))
            fit_confidence_weight = confidence_weight * (
                SOURCE_CYCLE_BOUNDARY_FIT_MULTIPLIER if boundary_roles else 1.0
            )
            for role in boundary_roles:
                cycle_boundary_observation_count[role] += 1
            observations.append({
                'leftFrame': left,
                'rightFrame': right,
                'alpha': alpha,
                'jointIndex': joint_index,
                'sourcePoint': np.asarray(source_point, dtype=float),
                'confidenceWeight': confidence_weight,
                'fitConfidenceWeight': fit_confidence_weight,
                'cycleBoundaryRoles': boundary_roles,
                'sharedAnchorGroup': anchor_group,
                'sourceTime': source_time,
                'outsideSelectedInterval': bool(
                    source_time < times[0] - 1e-9 or source_time > times[-1] + 1e-9
                ),
            })
    patch_feet = (((payload.get('sourceFootSupportEvidence') or {}).get(
        'footPatchEvidence') or {}).get('feet') or {})
    for source_side in ('left', 'right'):
        motion_ankle_name = _bilateral_name(f'{source_side}_ankle', swap=swap)
        motion_side = motion_ankle_name[:-6]
        motion_foot_name = f'{motion_side}_foot'
        ankle_index = fit_joint_index.get(motion_ankle_name)
        foot_index = fit_joint_index.get(motion_foot_name)
        source_foot_ray_side_mapping[source_side] = motion_side
        if ankle_index is None or foot_index is None:
            continue
        foot_data = patch_feet.get(source_side) or {}
        side_rays = []
        for ray in foot_data.get('rayObservations') or []:
            try:
                source_time = float(ray['sourceTimeSec'])
                source_ray = np.asarray(ray['ankleToToeImageRay'], dtype=float)
                confidence_value = float(ray['confidence'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            try:
                toe_image_point = np.asarray(ray.get('toeImagePoint'), dtype=float)
            except (TypeError, ValueError, OverflowError):
                toe_image_point = np.empty(0, dtype=float)
            if toe_image_point.shape != (2,) or not np.isfinite(toe_image_point).all():
                toe_image_point = None
            if (not np.isfinite(source_time) or source_ray.shape != (2,)
                    or not np.isfinite(source_ray).all() or np.linalg.norm(source_ray) < 1e-8
                    or not np.isfinite(confidence_value) or confidence_value < .8
                    or source_time < times[0] - projection_source_time_tolerance
                    or source_time > times[-1] + projection_source_time_tolerance):
                continue
            right = int(np.searchsorted(times, source_time, side='left'))
            if right <= 0:
                left, right, alpha = 0, 0, 0.
            elif right >= len(times):
                left, right, alpha = len(times) - 1, len(times) - 1, 0.
            else:
                left = right - 1
                span = float(times[right] - times[left])
                alpha = 0. if span <= 1e-12 else float((source_time - times[left]) / span)
            source_ray = source_ray / np.linalg.norm(source_ray)
            source_angle = float(np.arctan2(source_ray[1], source_ray[0]))
            side_rays.append({
                'leftFrame': left, 'rightFrame': right, 'alpha': alpha,
                'ankleJointIndex': ankle_index, 'footJointIndex': foot_index,
                'sourceRay': source_ray, 'sourceAngle': source_angle,
                'toeImagePoint': toe_image_point,
                'confidenceWeight': float(np.sqrt(np.clip(confidence_value, 0., 1.))),
                'sourceTime': source_time,
                'state': str(ray.get('state', 'unknown')),
                'stationaryAnchorGroupId': ray.get('stationaryAnchorGroupId'),
                'sourceSide': source_side, 'motionSide': motion_side,
            })
        if len(side_rays) < 3:
            continue
        full_sole_angles = [ray['sourceAngle'] for ray in side_rays
                            if ray['state'] == 'full_sole']
        stance_source_angle = None
        stance_angle_noise = None
        if len(full_sole_angles) >= 3:
            stance_center = float(np.arctan2(
                np.mean(np.sin(full_sole_angles)), np.mean(np.cos(full_sole_angles)),
            ))
            stance_offsets_from_native = np.asarray([
                np.arctan2(np.sin(angle - stance_center), np.cos(angle - stance_center))
                for angle in full_sole_angles
            ])
            stance_source_angle = float(stance_center + np.median(stance_offsets_from_native))
            stance_residuals = np.asarray([
                np.arctan2(np.sin(angle - stance_source_angle),
                           np.cos(angle - stance_source_angle))
                for angle in full_sole_angles
            ])
            stance_angle_noise = float(max(
                np.deg2rad(8),
                3 * 1.4826 * np.median(np.abs(stance_residuals)),
            ))
        # Remove only a robust constant rest-heading bias, calibrated from
        # independently observed full-sole frames when available. This leaves
        # each frame's source angular change intact and adds no contact pins.
        stance_offsets = []
        stance_toe_offsets = []
        stationary_toe_points_by_anchor = {}
        for ray in side_rays:
            anchor_group = ray.get('stationaryAnchorGroupId')
            if anchor_group is not None and ray['toeImagePoint'] is not None:
                stationary_toe_points_by_anchor.setdefault(anchor_group, []).append(
                    ray['toeImagePoint'])
            if ray['state'] != 'full_sole' or ray['toeImagePoint'] is None:
                continue
            left, right, alpha = ray['leftFrame'], ray['rightFrame'], ray['alpha']
            source_ankle = (points[left, ankle_index] * (1. - alpha)
                            + points[right, ankle_index] * alpha)
            source_foot = (points[left, foot_index] * (1. - alpha)
                           + points[right, foot_index] * alpha)
            fitted_ray = projection @ (source_foot - source_ankle)
            if np.linalg.norm(fitted_ray) < 1e-8:
                continue
            fitted_angle = float(np.arctan2(fitted_ray[1], fitted_ray[0]))
            stance_offsets.append(float(np.arctan2(
                np.sin(fitted_angle - ray['sourceAngle']),
                np.cos(fitted_angle - ray['sourceAngle']),
            )))
            projected_foot = projection @ source_foot + offset
            stance_toe_offsets.append(projected_foot - ray['toeImagePoint'])
        heading_offset = 0.
        if stance_offsets:
            circular_center = float(np.arctan2(
                np.mean(np.sin(stance_offsets)), np.mean(np.cos(stance_offsets)),
            ))
            unwrapped_offsets = [circular_center + float(np.arctan2(
                np.sin(value - circular_center), np.cos(value - circular_center),
            )) for value in stance_offsets]
            heading_offset = float(np.median(unwrapped_offsets))
        cosine, sine = np.cos(heading_offset), np.sin(heading_offset)
        heading_rotation = np.asarray([[cosine, -sine], [sine, cosine]])
        for ray in side_rays:
            ray['targetRay'] = heading_rotation @ ray['sourceRay']
            ray['headingOffsetRadians'] = heading_offset
            if stance_source_angle is not None and ray['state'] == 'toe_only':
                native_phase = float(np.arctan2(
                    np.sin(ray['sourceAngle'] - stance_source_angle),
                    np.cos(ray['sourceAngle'] - stance_source_angle),
                ))
                if abs(native_phase) > stance_angle_noise:
                    ray['heelPhasePreservation'] = {
                        'nativePhaseRadians': native_phase,
                        'stanceTargetAngleRadians': stance_source_angle + heading_offset,
                        'noiseThresholdRadians': stance_angle_noise,
                        'fitMinimumRatio': .92,
                        'acceptanceMinimumRatio': .85,
                    }
            source_foot_ray_observations.append(ray)
        if len(stance_toe_offsets) >= 3:
            toe_offset = np.median(np.asarray(stance_toe_offsets), axis=0)
            source_foot_point_offset_by_side[source_side] = toe_offset.tolist()
            stationary_toe_targets = {
                anchor_group: np.median(np.asarray(points, dtype=float), axis=0)
                for anchor_group, points in stationary_toe_points_by_anchor.items()
            }
            for ray in side_rays:
                if ray['toeImagePoint'] is None:
                    continue
                anchor_group = ray.get('stationaryAnchorGroupId')
                source_toe_point = stationary_toe_targets.get(
                    anchor_group, ray['toeImagePoint'])
                source_foot_point_observations.append({
                    'leftFrame': ray['leftFrame'],
                    'rightFrame': ray['rightFrame'],
                    'alpha': ray['alpha'],
                    'jointIndex': foot_index,
                    'sourcePoint': source_toe_point + toe_offset,
                    'confidenceWeight': ray['confidenceWeight'],
                    'fitConfidenceWeight': ray['confidenceWeight'],
                    'sourceTime': ray['sourceTime'],
                    'sourceSide': source_side,
                    'motionSide': motion_side,
                    'sourceEvidence': 'native_foot_landmark_toe',
                    'stationaryAnchorGroupId': anchor_group,
                    'sourcePointAggregation': (
                        'stationary_anchor_median' if anchor_group is not None
                        else 'per_frame_native'),
                })
        # Calibrate the rendered material heel-to-toe image vector once from
        # reliable full-sole samples. Toe-only samples preserve the observed
        # heel trajectory without inferring a 3D height or adding contact pins.
        from .foot_geometry import sample_material_foot_points
        native_heel_rows = []
        for heel_row in foot_data.get('heelImageObservations') or []:
            try:
                source_time = float(heel_row['sourceTimeSec'])
                heel_image = np.asarray(heel_row['heelImagePoint'], dtype=float)
                toe_image = np.asarray(heel_row['toeImagePoint'], dtype=float)
                heel_confidence = float(heel_row['heelConfidence'])
                toe_confidence = float(heel_row['toeConfidence'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            confidence = min(heel_confidence, toe_confidence)
            if (not np.isfinite(source_time) or heel_image.shape != (2,)
                    or toe_image.shape != (2,) or not np.isfinite(heel_image).all()
                    or not np.isfinite(toe_image).all() or confidence < .8
                    or source_time < times[0] - projection_source_time_tolerance
                    or source_time > times[-1] + projection_source_time_tolerance):
                continue
            right = int(np.searchsorted(times, source_time, side='left'))
            if right <= 0:
                left, right, alpha = 0, 0, 0.
            elif right >= len(times):
                left, right, alpha = len(times) - 1, len(times) - 1, 0.
            else:
                left = right - 1
                span = float(times[right] - times[left])
                alpha = 0. if span <= 1e-12 else float((source_time - times[left]) / span)
            native_heel_rows.append({
                'leftFrame': left, 'rightFrame': right, 'alpha': alpha,
                'ankleJointIndex': ankle_index, 'footJointIndex': foot_index,
                'sourceHeelToToeVector': heel_image - toe_image,
                'confidenceWeight': float(np.sqrt(np.clip(confidence, 0., 1.))),
                'sourceTime': source_time,
                'state': str(heel_row.get('state', 'unknown')),
                'stationaryAnchorGroupId': heel_row.get('stationaryAnchorGroupId'),
                'sourceSide': source_side, 'motionSide': motion_side,
            })
        fullsole_rows = [row for row in native_heel_rows
                         if row['state'] == 'full_sole'
                         and row.get('stationaryAnchorGroupId') is not None]
        if len(fullsole_rows) >= 3:
            lift_direction = projection @ np.asarray([0., 1., 0.])
            lift_direction /= max(float(np.linalg.norm(lift_direction)), 1e-12)
            cursors = [row['leftFrame'] + row['alpha'] for row in fullsole_rows]
            material = sample_material_foot_points(payload, cursors, points=points)[motion_side]
            predicted = np.asarray([
                projection @ (heel - toe)
                for heel, toe in zip(material['heel'], material['toe'])
            ])
            observed = np.asarray([row['sourceHeelToToeVector'] for row in fullsole_rows])
            image_offset = np.median(predicted - observed, axis=0)
            grouped_baselines = {}
            for group_id in {row['stationaryAnchorGroupId'] for row in fullsole_rows}:
                group_indices = [index for index, row in enumerate(fullsole_rows)
                                 if row['stationaryAnchorGroupId'] == group_id]
                if len(group_indices) < 3:
                    continue
                source_vector = observed[group_indices]
                source_lift_samples = source_vector @ lift_direction
                grouped_baselines[group_id] = {
                    'sourceVector': np.median(source_vector, axis=0),
                    'fitVector': np.median(predicted[group_indices], axis=0),
                    'sourceNoiseImageUnits': float(max(
                        1. / max(float(source_pose.get('imageHeight') or 1000), 1.),
                        3 * 1.4826 * np.median(np.abs(
                            source_lift_samples - np.median(source_lift_samples))),
                    )),
                    'observationCount': len(group_indices),
                }
            source_foot_heel_calibration_by_side[source_side] = {
                'imageOffset': image_offset.tolist(),
                'observationCount': len(fullsole_rows),
                'groupBaselineCount': len(grouped_baselines),
                'toeOnlyWithoutEpisodeBaselineCount': sum(
                    row['state'] == 'toe_only'
                    and row.get('stationaryAnchorGroupId') not in grouped_baselines
                    for row in native_heel_rows),
                'unknownStateObservationCount': sum(
                    row['state'] == 'unknown' for row in native_heel_rows),
                'medianAbsoluteCalibrationResidualPixels': float(np.median(np.linalg.norm(
                    predicted - observed - image_offset, axis=1)
                    * max(float(source_pose.get('imageHeight') or 1.), 1.))),
            }
            source_foot_heel_calibration_observations.extend(fullsole_rows)
            source_foot_heel_unresolved_toe_only_count += sum(
                row['state'] == 'toe_only'
                and row.get('stationaryAnchorGroupId') not in grouped_baselines
                for row in native_heel_rows)
            side_noise = float(np.median([
                baseline['sourceNoiseImageUnits']
                for baseline in grouped_baselines.values()
            ])) if grouped_baselines else 1. / max(
                float(source_pose.get('imageHeight') or 1000), 1.)
            row_baselines = {}
            for row in native_heel_rows:
                baseline = grouped_baselines.get(row.get('stationaryAnchorGroupId'))
                row_baselines[id(row)] = baseline
                image_row = {
                    **row,
                    'imageOffset': image_offset,
                    'sourceNoiseImageUnits': (
                        baseline['sourceNoiseImageUnits'] if baseline else side_noise),
                }
                source_foot_heel_image_observations.append(image_row)

            # Episodes follow the classifier's toe-only state and anchor identity.
            # A state change or missing native sample closes an episode; timestamps
            # are retained as-is, so the fit never shifts or warps the source curve.
            native_intervals = np.diff(sorted(row['sourceTime'] for row in native_heel_rows))
            native_intervals = native_intervals[native_intervals > 1e-6]
            max_episode_gap = (2.5 * float(np.median(native_intervals))
                               if native_intervals.size else 0.)
            toe_episodes = []
            active_episode = []
            previous = None
            for row in native_heel_rows:
                baseline = row_baselines[id(row)]
                contiguous = (
                    previous is not None
                    and row['state'] == 'toe_only'
                    and previous['state'] == 'toe_only'
                    and row.get('stationaryAnchorGroupId')
                    == previous.get('stationaryAnchorGroupId')
                    and row['sourceTime'] - previous['sourceTime'] <= max_episode_gap
                    and baseline is not None
                )
                if not contiguous and active_episode:
                    toe_episodes.append(active_episode)
                    active_episode = []
                if row['state'] == 'toe_only' and baseline is not None:
                    active_episode.append(row)
                previous = row
            if active_episode:
                toe_episodes.append(active_episode)
            image_row_by_time = {
                (row['sourceSide'], round(float(row['sourceTime']), 8)): row
                for row in source_foot_heel_image_observations
            }
            for episode_index, episode in enumerate(toe_episodes):
                baseline = row_baselines[id(episode[0])]
                source_curve = np.asarray([
                    float((row['sourceHeelToToeVector'] - baseline['sourceVector'])
                          @ lift_direction)
                    for row in episode
                ])
                source_amplitude = float(max(0., np.quantile(source_curve, .9)))
                if source_amplitude <= baseline['sourceNoiseImageUnits']:
                    continue
                event_id = (source_side, episode[0].get('stationaryAnchorGroupId'),
                            episode_index)
                event_observations = []
                for row in episode:
                    image_row = image_row_by_time[
                        (row['sourceSide'], round(float(row['sourceTime']), 8))]
                    trajectory_row = {
                        **image_row,
                        'baselineSourceVector': baseline['sourceVector'],
                        'baselineFitVector': baseline['fitVector'],
                        'sourceNoiseImageUnits': baseline['sourceNoiseImageUnits'],
                        'liftDirection': lift_direction,
                        'episodeId': event_id,
                    }
                    source_foot_heel_trajectory_observations.append(trajectory_row)
                    event_observations.append(trajectory_row)
                source_foot_heel_trajectory_events.append({
                    'episodeId': event_id,
                    'sourceSide': source_side,
                    'motionSide': motion_side,
                    'stationaryAnchorGroupId': episode[0].get('stationaryAnchorGroupId'),
                    'observationTimes': [row['sourceTime'] for row in event_observations],
                    'sourceExcursionImageUnits': source_amplitude,
                    'sourceNoiseImageUnits': baseline['sourceNoiseImageUnits'],
                    'fitMinimumRatio': .92,
                    'acceptanceMinimumRatio': .85,
                })
        else:
            source_foot_heel_unresolved_toe_only_count += sum(
                row['state'] == 'toe_only' for row in native_heel_rows)
    support_relative_observations = []
    support_relative_joint_names = []
    if (body_support.get('required') is True
            and body_support.get('status') == 'confirmed'):
        support_plane_joints = {
            joint_name
            for group in body_support.get('coplanarGroups') or []
            if group.get('planeOffsetMeters') is not None
            for joint_name in group.get('joints') or []
        }
        measured_support_joints = set()
        for support_name in sorted(
            set(body_support.get('stationaryJoints') or []) & support_plane_joints
        ):
            source_support_base = _bilateral_name(support_name, swap=swap)
            source_support_names = [source_support_base]
            if source_support_base.endswith('_foot'):
                source_support_names.append(source_support_base[:-5] + '_ankle')
            source_support_name = next((
                name for name in source_support_names
                if any(name in frame['joints'] for frame in selected_source_frames)
            ), None)
            if source_support_name is None:
                continue
            support_motion_name = _bilateral_name(source_support_name, swap=swap)
            support_joint_index = fit_joint_index.get(support_motion_name)
            if support_joint_index is None or support_motion_name in measured_support_joints:
                continue
            measured_support_joints.add(support_motion_name)
            support_evidence = payload.get('sourceFootSupportEvidence') or {}
            pixel_evidence = support_evidence.get('supportRelativePixelTracks') or {}
            pixel_rows = {}
            if (pixel_evidence.get('available') is True
                    and pixel_evidence.get('sourceVideoSha256')
                    and pixel_evidence.get('sourceVideoSha256')
                    == (support_evidence.get('bodySupportObservation') or {}).get('sourceVideoSha256')):
                pixel_rows = {
                    round(float(row['sourceTimeSec']), 6): row['sourceDelta']
                    for row in (pixel_evidence.get('tracks') or {}).get(source_support_name, [])
                }

            source_center_modes = []
            if 'pelvis' in fit_joint_index:
                source_center_modes.append((('pelvis',), (fit_joint_index['pelvis'],)))
            if {'left_hip', 'right_hip'} <= set(fit_joint_index):
                source_center_modes.append((
                    ('left_hip', 'right_hip'),
                    tuple(fit_joint_index[_bilateral_name(name, swap=swap)]
                          for name in ('left_hip', 'right_hip')),
                ))
            if not source_center_modes:
                continue

            def support_source_confidence(source_frame, joint_names):
                confidence_values = source_frame.get('jointConfidence') or {}
                values = []
                for joint_name in joint_names:
                    try:
                        value = float(confidence_values.get(joint_name, .1))
                    except (TypeError, ValueError, OverflowError):
                        value = .1
                    if not np.isfinite(value):
                        value = .1
                    values.append(float(np.clip(value, 0., 1.)))
                return min(values, default=.1)

            seen_times = set()
            for source_frame in selected_source_frames:
                source_time = float(source_frame['time'])
                if source_time in seen_times:
                    continue
                source_joints = source_frame['joints']

                support_point = source_joints.get(source_support_name)
                if (support_point is None
                        or support_source_confidence(source_frame, (source_support_name,))
                        < SOURCE_SUPPORT_RELATIVE_MIN_CONFIDENCE):
                    continue
                center_names = None
                center_indices = None
                center_point = None
                center_confidence = .1
                for source_names, candidate_indices in source_center_modes:
                    if not all(name in source_joints for name in source_names):
                        continue
                    candidate_confidence = support_source_confidence(source_frame, source_names)
                    if candidate_confidence >= SOURCE_SUPPORT_RELATIVE_MIN_CONFIDENCE:
                        center_names = source_names
                        center_indices = candidate_indices
                        center_point = np.mean(
                            [np.asarray(source_joints[name], dtype=float)[:2]
                             for name in source_names], axis=0,
                        )
                        center_confidence = candidate_confidence
                        break
                if center_point is None:
                    continue

                right = int(np.searchsorted(times, source_time, side='left'))
                if right <= 0:
                    left, right, alpha = 0, 0, 0.
                elif right >= len(times):
                    left, right, alpha = len(times) - 1, len(times) - 1, 0.
                else:
                    left = right - 1
                    span = float(times[right] - times[left])
                    alpha = 0. if span <= 1e-12 else float((source_time - times[left]) / span)
                support_point = np.asarray(support_point, dtype=float)[:2]
                source_delta = center_point - support_point
                pixel_delta = pixel_rows.get(round(
                    source_time + float(source_pose.get('sourceTimeOriginSec', 0.)), 6))
                use_pixel_delta = (
                    center_names == ('left_hip', 'right_hip') and pixel_delta is not None
                    and np.asarray(pixel_delta).shape == (2,)
                    and np.isfinite(pixel_delta).all())
                if use_pixel_delta:
                    source_delta = np.asarray(pixel_delta, dtype=float)
                if (not np.isfinite(source_delta).all()
                        or not np.isfinite(support_point).all()):
                    continue
                support_relative_observations.append({
                    'leftFrame': left,
                    'rightFrame': right,
                    'alpha': alpha,
                    'centerJointIndices': tuple(center_indices),
                    'supportJointIndex': support_joint_index,
                    'sourceDelta': source_delta,
                    'confidenceWeight': float(np.sqrt(min(
                        center_confidence,
                        support_source_confidence(source_frame, (source_support_name,)),
                    ))),
                    'sourceTime': source_time,
                    'sourceCenterJoints': tuple(center_names),
                    'sourceSupportJoint': source_support_name,
                    'supportGroup': support_motion_name,
                    'sourceEvidence': 'source_pixel_tracking' if use_pixel_delta else 'source_pose',
                })
                seen_times.add(source_time)
                support_relative_joint_names.append(support_motion_name)

    support_relative_times = {
        round(row['sourceTime'], 6) for row in support_relative_observations
    }
    if len(support_relative_times) < SOURCE_SUPPORT_RELATIVE_MIN_OBSERVATIONS:
        support_relative_observations = []
    support_relative_material_motion = _source_support_relative_has_material_motion(
        support_relative_observations,
    )
    distinct_frames = len({(row['leftFrame'], row['rightFrame']) for row in observations})
    for role in ('start', 'end'):
        cycle_boundary_coverage[role]['effectiveObservationCount'] = (
            cycle_boundary_observation_count[role]
        )
        cycle_boundary_coverage[role]['effectiveAvailable'] = (
            cycle_boundary_observation_count[role]
            >= SOURCE_CYCLE_BOUNDARY_MIN_EFFECTIVE_OBSERVATIONS
        )
    if len(observations) < 6 or distinct_frames < 3:
        return {**unavailable, 'reason': 'insufficient_source_projection_coverage'}
    return {
        'available': True,
        'observations': observations,
        'sourceFootRayObservations': source_foot_ray_observations,
        'sourceFootRaySideMapping': source_foot_ray_side_mapping,
        'sourceFootRayWeight': SOURCE_PROJECTION_FIT_WEIGHT,
        'sourceFootPointObservations': source_foot_point_observations,
        'sourceFootHeelTrajectoryObservations': source_foot_heel_trajectory_observations,
        'sourceFootHeelTrajectoryEvents': source_foot_heel_trajectory_events,
        'sourceFootHeelImageObservations': source_foot_heel_image_observations,
        'sourceFootHeelUnresolvedToeOnlyObservationCount': (
            source_foot_heel_unresolved_toe_only_count),
        'sourceFootHeelTrajectoryCalibrationBySide': source_foot_heel_calibration_by_side,
        'sourceFootHeelCalibrationObservations': source_foot_heel_calibration_observations,
        # Bind heel baselines to the shoe calibration used to measure them.
        'footGeometryPayload': {
            **payload,
            'footRestPitchRadians': dict(payload.get('footRestPitchRadians') or {}),
        },
        'sourceFootPointOffsetBySide': source_foot_point_offset_by_side,
        'supportRelativeObservations': support_relative_observations,
        'supportRelativeMaterialMotion': support_relative_material_motion,
        'supportRelativeJointNames': sorted(set(support_relative_joint_names)),
        'supportRelativeWeight': SOURCE_PROJECTION_FIT_WEIGHT * SOURCE_SUPPORT_RELATIVE_FIT_MULTIPLIER,
        'supportRelativeMaxRmsBodyRatio': SOURCE_SUPPORT_RELATIVE_MAX_RMS_BODY_RATIO,
        'supportRelativeMinTravelRatio': SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_RATIO,
        'supportRelativeMinTravelDistanceRatio': SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_DISTANCE_RATIO,
        'projection': projection,
        'offset': offset,
        'normalization': max(float(scale) * projection_scale, 1e-9),
        'weight': SOURCE_PROJECTION_FIT_WEIGHT,
        'sourceFrameCount': len(selected_source_frames),
        'boundaryEvidenceFrameCount': len(source_frames) - len(selected_source_frames),
        'boundaryEvidenceSourceTimesSec': source_window.get(
            'boundaryEvidenceSourceTimesSec', [],
        ),
        'observationCount': len(observations),
        'distinctFitTimeCount': distinct_frames,
        'cycleBoundaryCoverage': cycle_boundary_coverage,
        'cycleBoundaryObservationCount': cycle_boundary_observation_count,
        'supportAnchorObservationCount': support_anchor_observation_count,
        'supportAnchorProjectionOmittedCount': support_anchor_projection_omitted_count,
        'cycleBoundaryFitMultiplier': SOURCE_CYCLE_BOUNDARY_FIT_MULTIPLIER,
        'endpointPostureObservations': endpoint_posture_observations,
        'endpointPostureObservationCount': len(endpoint_posture_observations),
        'endpointPostureCoverage': endpoint_posture_coverage,
        'endpointPostureWindowHalfWidthSeconds': float(posture_window_half_width),
        'endpointPostureFitMultiplier': SOURCE_ENDPOINT_POSTURE_FIT_MULTIPLIER,
        'cameraAuthority': 'retained_source_correction_camera',
        'selectedIntervalKind': selected_interval_kind,
        'selectedIntervalEvidenceSource': selected_interval.get('source'),
        'selectedIntervalReason': selected_interval.get('reason'),
        'anchorGroups': anchor_groups,
        'reason': None,
    }


def _align_shared_contact_anchors_to_source_projection(
    constraint, pinned, contact_targets, *, ground_contacts=None, rig=None, body_support=None,
):
    """Align non-ground contact groups without splitting linked sole anchors."""
    result = np.asarray(contact_targets, dtype=float).copy()
    if not constraint.get('available'):
        return result, {
            'adjustedGroupCount': 0,
            'maximumShiftMeters': 0.,
            'skippedGroundAnchoredGroupCount': 0,
        }
    groups = constraint.get('anchorGroups')
    if groups is None:
        return result, {
            'adjustedGroupCount': 0,
            'maximumShiftMeters': 0.,
            'skippedGroundAnchoredGroupCount': 0,
        }
    ground_mask = None
    if ground_contacts is not None:
        ground_mask = np.asarray(ground_contacts, dtype=bool)
        if ground_mask.shape != np.asarray(pinned).shape:
            raise ValueError('ground contact mask must match pinned contact shape')
    grouped_observations = defaultdict(list)
    for observation in constraint['observations']:
        group = observation.get('sharedAnchorGroup')
        if group is not None:
            grouped_observations[group].append(observation)
    projection = constraint['projection']
    offset = constraint['offset']
    shifts = []
    skipped_ground_groups = 0
    skipped_support_groups = 0
    skipped_rigid_groups = 0
    stationary_support = set((body_support or {}).get('stationaryJoints') or []) if (
        (body_support or {}).get('status') == 'confirmed') else set()
    for group, observations in grouped_observations.items():
        design_rows = []
        residual_rows = []
        active = np.zeros(pinned.shape, dtype=bool)
        # A full-sole group identifies both its foot and ankle anchors. The
        # source camera may observe only the ankle, but moving that point alone
        # breaks the fixed-rig foot/ankle relationship in contact_targets.
        for joint in range(pinned.shape[1]):
            group_frames = np.fromiter(
                (value == group for value in groups[:, joint]),
                dtype=bool, count=len(groups))
            active[:, joint] = group_frames & np.asarray(pinned[:, joint])
        if ground_mask is not None and np.any(active & ground_mask):
            # A 2D camera projection cannot move a confirmed floor anchor in
            # 3D without risking a floor-normal shift. Keep the physical ground
            # target and let the source-projection residual remain a soft fit
            # constraint instead of relocating the contact anchor.
            skipped_ground_groups += 1
            continue
        if rig is not None and any(
                (name in stationary_support or name.endswith(('_ankle', '_foot')))
                and np.any(active[:, joint])
                for joint, name in enumerate(rig.names)):
            # Stationary foot pins and calibrated supports cannot be relocated by a 2D projection.
            skipped_support_groups += 1
            continue
        for observation in observations:
            joint = observation['jointIndex']
            left, right, alpha = (
                observation['leftFrame'], observation['rightFrame'], observation['alpha'])
            anchor = (result[left, joint] * (1. - alpha) + result[right, joint] * alpha)
            design_rows.append(projection * observation['confidenceWeight'])
            residual_rows.append((observation['sourcePoint'] - projection @ anchor - offset)
                                 * observation['confidenceWeight'])
        design = np.concatenate(design_rows, axis=0)
        residual = np.concatenate(residual_rows, axis=0)
        # The minimum-norm camera-plane correction leaves the projection
        # nullspace (depth) unchanged instead of choosing an arbitrary depth.
        correction, _, _, _ = np.linalg.lstsq(design, residual, rcond=None)
        if not np.isfinite(correction).all() or not np.any(active):
            continue
        proposed = result.copy()
        proposed[active] += correction
        if rig is not None:
            rigid_conflict = False
            for child, parent in enumerate(rig.parents):
                if parent < 0:
                    continue
                linked = pinned[:, child] & pinned[:, parent] & (active[:, child] | active[:, parent])
                lengths = np.linalg.norm(proposed[linked, child]-proposed[linked, parent], axis=-1)
                if np.any(np.abs(lengths-np.linalg.norm(rig.offsets[child]))
                          > 2. * KEYFRAME_CONTACT_LIMIT_METERS):
                    rigid_conflict = True
                    break
            if rigid_conflict:
                # Keep feasible physical anchors; camera matching remains soft.
                skipped_rigid_groups += 1
                continue
        result = proposed
        shifts.append(float(np.linalg.norm(correction)))
    return result, {
        'adjustedGroupCount': len(shifts),
        'maximumShiftMeters': max(shifts, default=0.),
        'skippedGroundAnchoredGroupCount': skipped_ground_groups,
        'skippedObservedSupportGroupCount': skipped_support_groups,
        'skippedRigidContactGroupCount': skipped_rigid_groups,
    }


def _source_projection_fit_rows(candidate, constraint):
    if not constraint.get('available'):
        return np.empty(0, dtype=float)
    projection = constraint['projection']
    offset = constraint['offset']
    normalization = constraint['normalization']
    weight = constraint['weight']
    rows = []
    point_observations = _source_projection_point_observations(constraint)
    for observation in point_observations:
        left = observation['leftFrame']
        right = observation['rightFrame']
        alpha = observation['alpha']
        point = (candidate[left, observation['jointIndex']] * (1. - alpha)
                 + candidate[right, observation['jointIndex']] * alpha)
        error = projection @ point + offset - observation['sourcePoint']
        confidence_weight = observation.get(
            'fitConfidenceWeight', observation['confidenceWeight'])
        rows.extend((weight * confidence_weight * error / normalization).tolist())
    rows.extend(_source_foot_ray_fit_rows(candidate, constraint).tolist())
    rows.extend(_source_foot_material_heel_fit_rows(candidate, constraint).tolist())
    return np.asarray(rows, dtype=float)


def _source_projection_point_observations(constraint):
    return [
        *(constraint.get('observations') or []),
        *(constraint.get('sourceFootPointObservations') or []),
    ]


def _source_foot_ray_fit_rows(candidate, constraint):
    """Preserve observed ankle-to-toe heading changes without adding contact pins."""
    observations = constraint.get('sourceFootRayObservations') or []
    if not observations:
        return np.empty(0, dtype=float)
    projection = constraint['projection']
    weight = constraint.get('sourceFootRayWeight', constraint['weight'])
    rows = []
    for observation in observations:
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle_index = observation['ankleJointIndex']
        foot_index = observation['footJointIndex']
        ankle = (candidate[left, ankle_index] * (1. - alpha)
                 + candidate[right, ankle_index] * alpha)
        foot = (candidate[left, foot_index] * (1. - alpha)
                + candidate[right, foot_index] * alpha)
        fitted_ray = projection @ (foot - ankle)
        length = float(np.linalg.norm(fitted_ray))
        if length <= 1e-9:
            rows.append(0.)
            continue
        target = observation['targetRay']
        cross = float(target[0] * fitted_ray[1] - target[1] * fitted_ray[0])
        rows.append(weight * observation['confidenceWeight'] * cross / length)
    return np.asarray(rows, dtype=float)


def _source_foot_phase_observations(constraint):
    return [
        observation for observation in constraint.get('sourceFootRayObservations') or []
        if observation.get('heelPhasePreservation')
    ]


def _source_foot_phase_frame_coverage(constraint, names, frame_count):
    coverage = {}
    for observation in _source_foot_phase_observations(constraint):
        ankle_name = f"{observation['motionSide']}_ankle"
        if ankle_name not in names:
            continue
        covered = coverage.setdefault(ankle_name, np.zeros(frame_count))
        if observation['alpha'] < 1.:
            covered[observation['leftFrame']] = 1.
        if observation['alpha'] > 0.:
            covered[observation['rightFrame']] = 1.
    return coverage


def _source_foot_phase_fit_rows(candidate, constraint):
    """Keep clear native toe-only heel pivots above their observed phase floor."""
    observations = _source_foot_phase_observations(constraint)
    if not observations:
        return np.empty(0, dtype=float)
    projection = constraint['projection']
    rows = []
    for observation in observations:
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle = (candidate[left, observation['ankleJointIndex']] * (1. - alpha)
                 + candidate[right, observation['ankleJointIndex']] * alpha)
        foot = (candidate[left, observation['footJointIndex']] * (1. - alpha)
                + candidate[right, observation['footJointIndex']] * alpha)
        fitted_ray = projection @ (foot - ankle)
        if np.linalg.norm(fitted_ray) <= 1e-9:
            rows.append(0.)
            continue
        phase = float(np.arctan2(fitted_ray[1], fitted_ray[0])
                      - observation['heelPhasePreservation']['stanceTargetAngleRadians'])
        phase = float(np.arctan2(np.sin(phase), np.cos(phase)))
        native_phase = observation['heelPhasePreservation']['nativePhaseRadians']
        signed_fitted_phase = np.sign(native_phase) * phase
        minimum_fit_phase = .92 * abs(native_phase)
        rows.append(SOURCE_FOOT_PHASE_FIT_WEIGHT
                    * max(0., minimum_fit_phase - signed_fitted_phase))
    return np.asarray(rows, dtype=float)


def _source_foot_material_heel_vectors(candidate, constraint, observations):
    if not observations:
        return np.empty((0, 2), dtype=float)
    from .foot_geometry import sample_material_foot_points
    cursors = [row['leftFrame'] + row['alpha'] for row in observations]
    material_by_side = sample_material_foot_points(
        constraint['footGeometryPayload'], cursors, points=candidate)
    projection = constraint['projection']
    return np.asarray([
        projection @ (material_by_side[row['motionSide']]['heel'][index]
                      - material_by_side[row['motionSide']]['toe'][index])
        for index, row in enumerate(observations)
    ])


def _source_foot_material_heel_fit_rows(candidate, constraint):
    """Fit observed heel-to-toe image motion against renderer material geometry."""
    observations = constraint.get('sourceFootHeelImageObservations') or []
    if not observations:
        return np.empty(0, dtype=float)
    fitted_vectors = _source_foot_material_heel_vectors(
        candidate, constraint, observations)
    vector_rows = []
    for fitted, observation in zip(fitted_vectors, observations):
        confidence = observation['confidenceWeight']
        target = observation['sourceHeelToToeVector']
        offset = observation['imageOffset']
        # imageOffset is calibrated as fitted source-frame vector minus the
        # observed vector, so compare against source + offset.
        error = fitted - offset - target
        uncertainty = float(observation.get('sourceNoiseImageUnits', 0.))
        vector_rows.extend((SOURCE_PROJECTION_FIT_WEIGHT * confidence
                            * np.sign(error) * np.maximum(0., np.abs(error) - uncertainty)).tolist())
    observation_index = {
        (row['sourceSide'], round(float(row['sourceTime']), 8)): index
        for index, row in enumerate(observations)
    }
    trajectory_by_time = {
        (row['sourceSide'], round(float(row['sourceTime']), 8)): row
        for row in constraint.get('sourceFootHeelTrajectoryObservations') or []
    }
    event_rows = []
    for event in constraint.get('sourceFootHeelTrajectoryEvents') or []:
        indices = [observation_index[(event['sourceSide'], round(float(time), 8))]
                   for time in event['observationTimes']
                   if (event['sourceSide'], round(float(time), 8)) in observation_index]
        if not indices:
            event_rows.append(0.)
            continue
        lifts = []
        for index in indices:
            key = (event['sourceSide'], round(float(observations[index]['sourceTime']), 8))
            trajectory = trajectory_by_time[key]
            lifts.append(max(0., float((fitted_vectors[index]
                                        - trajectory['baselineFitVector'])
                                       @ trajectory['liftDirection'])))
        lifts = np.asarray(lifts)
        fitted_amplitude = float(np.quantile(lifts, .9))
        event_rows.append(SOURCE_FOOT_PHASE_FIT_WEIGHT
                          * max(0., event['fitMinimumRatio']
                                * event['sourceExcursionImageUnits'] - fitted_amplitude))
    return np.r_[np.asarray(vector_rows), np.asarray(event_rows)]


def _source_foot_material_heel_fit_evidence(payload, constraint):
    observations = constraint.get('sourceFootHeelTrajectoryObservations') or []
    calibration_rows = constraint.get('sourceFootHeelCalibrationObservations') or []
    unresolved_toe_only = int(constraint.get(
        'sourceFootHeelUnresolvedToeOnlyObservationCount', 0))
    required = bool(observations or unresolved_toe_only)
    if not constraint.get('available') or not observations or not calibration_rows:
        return {
            'available': False, 'passed': not required,
            'reason': 'reliable_native_material_heel_trajectory_unavailable',
            'observationCount': len(observations), 'calibrationObservationCount': len(calibration_rows),
            'unresolvedToeOnlyObservationCount': unresolved_toe_only,
            'minimumPreservedRatio': .85, 'worstPreservedRatio': None,
        }
    from .foot_geometry import sample_material_foot_points
    projection = constraint['projection']
    placement = payload.get('scenePlacement') or {}
    try:
        placement_rotation = Rotation.from_rotvec(np.asarray(
            placement.get('rotationVector', [0., 0., 0.]), dtype=float)).as_matrix()
    except (TypeError, ValueError):
        placement_rotation = np.eye(3)
    if placement_rotation.shape == (3, 3):
        # normalize_scene_placement rotates serialized geometry after the fit.
        # Transport its rendered vectors back into the fit camera basis.
        projection = projection @ placement_rotation.T

    def rendered_vectors(rows):
        cursors = [row['leftFrame'] + row['alpha'] for row in rows]
        geometry = sample_material_foot_points(payload, cursors)
        return {
            id(row): projection @ (
                geometry[row['motionSide']]['heel'][index]
                - geometry[row['motionSide']]['toe'][index])
            for index, row in enumerate(rows)
        }

    calibration_vectors = rendered_vectors(calibration_rows)
    baseline_by_group = {}
    side_for_group = {}
    for row in calibration_rows:
        group_id = row.get('stationaryAnchorGroupId')
        if group_id is None:
            continue
        baseline_by_group.setdefault((row['sourceSide'], group_id), []).append(
            (row['sourceHeelToToeVector'], calibration_vectors[id(row)]))
        side_for_group[(row['sourceSide'], group_id)] = row['motionSide']
    baselines = {}
    for key, values in baseline_by_group.items():
        if len(values) < 3:
            continue
        baselines[key] = {
            'source': np.median(np.asarray([item[0] for item in values]), axis=0),
            'fit': np.median(np.asarray([item[1] for item in values]), axis=0),
            'count': len(values),
        }
    image_row_by_time = {
        (row['sourceSide'], round(float(row['sourceTime']), 8)): row
        for row in observations
    }
    fitted_vectors = rendered_vectors(observations)
    source_pose = ((payload.get('sourcePoseCameraReference') or {}).get('sourcePose') or {})
    height = float(source_pose.get('imageHeight') or 1.)
    events = []
    for event in constraint.get('sourceFootHeelTrajectoryEvents') or []:
        key = (event['sourceSide'], event.get('stationaryAnchorGroupId'))
        baseline = baselines.get(key)
        if baseline is None:
            continue
        rows = [image_row_by_time[(event['sourceSide'], round(float(time), 8))]
                for time in event['observationTimes']
                if (event['sourceSide'], round(float(time), 8)) in image_row_by_time]
        if not rows:
            continue
        source_lifts = np.asarray([
            float((row['sourceHeelToToeVector'] - baseline['source'])
                  @ row['liftDirection'])
            for row in rows
        ])
        rendered_lifts = np.asarray([
            float((fitted_vectors[id(row)] - baseline['fit']) @ row['liftDirection'])
            for row in rows
        ])
        source_amplitude = float(max(0., np.quantile(source_lifts, .9)))
        rendered_amplitude = float(max(0., np.quantile(rendered_lifts, .9)))
        ratio = rendered_amplitude / max(source_amplitude, 1e-9)
        trajectory_errors = rendered_lifts - source_lifts
        noise = float(event['sourceNoiseImageUnits'])
        source_times = np.asarray([row['sourceTime'] for row in rows], dtype=float)
        source_peak_time = float(source_times[int(np.argmax(source_lifts))])
        rendered_peak_time = float(source_times[int(np.argmax(rendered_lifts))])
        rms_error = float(np.sqrt(np.mean(np.square(trajectory_errors))))
        max_error = float(np.max(np.abs(trajectory_errors)))
        events.append({
            'episodeId': list(event['episodeId']),
            'sourceSide': event['sourceSide'],
            'motionSide': event['motionSide'],
            'stationaryAnchorGroupId': event.get('stationaryAnchorGroupId'),
            'observationCount': len(rows),
            'sourceExcursionImageUnits': source_amplitude,
            'renderedExcursionImageUnits': rendered_amplitude,
            'amplitudeRatio': ratio,
            'minimumPreservedRatio': event['acceptanceMinimumRatio'],
            'trajectoryRmsErrorImageUnits': rms_error,
            'trajectoryMaxErrorImageUnits': max_error,
            'sourceNoiseImageUnits': noise,
            'trajectoryRmsErrorPixels': rms_error * height,
            'trajectoryMaxErrorPixels': max_error * height,
            'sourceNoisePixels': noise * height,
            'trajectoryRmsWithinNoise': rms_error <= noise,
            'sourcePeakTimeSec': source_peak_time,
            'renderedPeakTimeSec': rendered_peak_time,
            'peakTimeOffsetSec': rendered_peak_time - source_peak_time,
            'calibrationObservationCount': baseline['count'],
        })
    if not events:
        return {
            'available': False, 'passed': not required,
            'reason': 'native_material_heel_baseline_unavailable',
            'observationCount': len(observations),
            'calibrationObservationCount': len(calibration_rows),
            'calibrationGroupCount': len(baselines),
            'unresolvedToeOnlyObservationCount': unresolved_toe_only,
            'minimumPreservedRatio': .85, 'eventCount': 0,
        }
    unresolved_passed = unresolved_toe_only == 0
    worst = min(events, key=lambda item: item['amplitudeRatio'])
    amplitude_passed = all(
        event['amplitudeRatio'] >= event['minimumPreservedRatio'] for event in events)
    trajectory_passed = all(event['trajectoryRmsWithinNoise'] for event in events)
    return {
        'available': True,
        'passed': bool(amplitude_passed and trajectory_passed and unresolved_passed),
        'reason': ('unresolved_toe_only_heel_baseline' if not unresolved_passed else
                   'material_heel_excursion_not_preserved' if not amplitude_passed else
                   'native_time_heel_trajectory_exceeds_measurement_uncertainty'
                   if not trajectory_passed else None),
        'observationCount': len(observations),
        'eventCount': len(events),
        'events': events,
        'amplitudePreservationPassed': amplitude_passed,
        'nativeTimeTrajectoryPassed': trajectory_passed,
        'calibrationObservationCount': len(calibration_rows),
        'calibrationGroupCount': len(baselines),
        'unresolvedToeOnlyObservationCount': unresolved_toe_only,
        'minimumPreservedRatio': .85,
        'fitMinimumRatio': .92,
        'worstPreservedRatio': float(worst['amplitudeRatio']),
        'worstSourceTimeSec': worst['sourcePeakTimeSec'],
        'worstSourceSide': worst['sourceSide'],
        'worstMotionSide': worst['motionSide'],
        'worstEvent': worst,
        'sourceExcursionPixels': float(worst['sourceExcursionImageUnits'] * height),
        'renderedExcursionPixels': float(worst['renderedExcursionImageUnits'] * height),
        'noisePixels': float(worst['sourceNoiseImageUnits'] * height),
        'minimumPassingRatio': .85,
        'gateApplied': True,
    }


def _source_foot_ray_fit_evidence(candidate, constraint):
    observations = constraint.get('sourceFootRayObservations') or []
    if not constraint.get('available') or not observations:
        return {
            'available': False, 'passed': True,
            'reason': 'independent_source_foot_ray_unavailable',
            'observationCount': 0,
        }
    errors = []
    for observation in observations:
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle = (candidate[left, observation['ankleJointIndex']] * (1. - alpha)
                 + candidate[right, observation['ankleJointIndex']] * alpha)
        foot = (candidate[left, observation['footJointIndex']] * (1. - alpha)
                + candidate[right, observation['footJointIndex']] * alpha)
        fitted = constraint['projection'] @ (foot - ankle)
        if np.linalg.norm(fitted) <= 1e-9:
            continue
        angle = np.arctan2(
            observation['targetRay'][0] * fitted[1] - observation['targetRay'][1] * fitted[0],
            float(np.dot(observation['targetRay'], fitted)),
        )
        errors.append(float(np.degrees(angle)))
    errors = np.asarray(errors, dtype=float)
    return {
        'available': bool(len(errors)),
        'passed': True,
        'reason': None if len(errors) else 'projected_foot_ray_degenerate',
        'observationCount': int(len(errors)),
        'sourceSideMapping': constraint.get('sourceFootRaySideMapping') or {},
        'headingOffsetDegreesBySide': {
            side: float(np.degrees(np.median([
                row['headingOffsetRadians'] for row in observations
                if row['sourceSide'] == side
            ])))
            for side in ('left', 'right')
            if any(row['sourceSide'] == side for row in observations)
        },
        'absoluteAngularResidualRmsDegrees': (
            float(np.sqrt(np.mean(errors ** 2))) if len(errors) else None),
        'absoluteAngularResidualMedianDegrees': (
            float(np.median(np.abs(errors))) if len(errors) else None),
        'gateApplied': False,
    }


def _source_foot_phase_fit_evidence(candidate, constraint):
    observations = _source_foot_phase_observations(constraint)
    if not constraint.get('available') or not observations:
        return {
            'available': False, 'passed': True,
            'reason': 'no_reliable_native_toe_only_heel_phase',
            'observationCount': 0, 'minimumAcceptanceRatio': .85,
            'worstPreservedRatio': None, 'worstSourceTimeSec': None,
        }
    projection = constraint['projection']
    ratios = []
    for observation in observations:
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle = (candidate[left, observation['ankleJointIndex']] * (1. - alpha)
                 + candidate[right, observation['ankleJointIndex']] * alpha)
        foot = (candidate[left, observation['footJointIndex']] * (1. - alpha)
                + candidate[right, observation['footJointIndex']] * alpha)
        fitted_ray = projection @ (foot - ankle)
        if np.linalg.norm(fitted_ray) <= 1e-9:
            ratio = float('-inf')
        else:
            phase_data = observation['heelPhasePreservation']
            phase = float(np.arctan2(fitted_ray[1], fitted_ray[0])
                          - phase_data['stanceTargetAngleRadians'])
            phase = float(np.arctan2(np.sin(phase), np.cos(phase)))
            ratio = float(np.sign(phase_data['nativePhaseRadians']) * phase
                          / abs(phase_data['nativePhaseRadians']))
        ratios.append({
            'ratio': ratio,
            'sourceTimeSec': float(observation['sourceTime']),
            'sourceSide': observation['sourceSide'],
            'motionSide': observation['motionSide'],
        })
    worst = min(ratios, key=lambda item: item['ratio'])
    finite_ratios = [item['ratio'] for item in ratios if np.isfinite(item['ratio'])]
    return {
        'available': True,
        'passed': bool(worst['ratio'] >= .85),
        'reason': None if worst['ratio'] >= .85 else 'observed_heel_phase_not_preserved',
        'observationCount': len(observations),
        'minimumAcceptanceRatio': .85,
        'fitTargetRatio': .92,
        'worstPreservedRatio': (float(worst['ratio'])
                                if np.isfinite(worst['ratio']) else None),
        'worstSourceTimeSec': worst['sourceTimeSec'],
        'worstSourceSide': worst['sourceSide'],
        'worstMotionSide': worst['motionSide'],
        'preservedRatioMedian': (float(np.median(finite_ratios))
                                 if finite_ratios else None),
        'sourceSideMapping': constraint.get('sourceFootRaySideMapping') or {},
    }


def _source_support_relative_fit_rows(candidate, constraint):
    """Match source-projected temporal travel, invariant to one constant offset."""
    pairs = _source_support_relative_fit_pairs(constraint)
    if not constraint.get('available') or not pairs:
        return np.empty(0, dtype=float)
    projection = constraint['projection']
    normalization = constraint['normalization']
    weight = constraint['supportRelativeWeight']
    rows = []
    for reference, observation in pairs:
        fitted_delta = _projected_source_support_delta(candidate, observation, projection)
        reference_delta = _projected_source_support_delta(candidate, reference, projection)
        source_delta = observation['sourceDelta'] - reference['sourceDelta']
        error = (fitted_delta - reference_delta) - source_delta
        confidence_weight = min(
            observation['confidenceWeight'], reference['confidenceWeight'],
        )
        rows.extend((weight * confidence_weight * error / normalization).tolist())
    return np.asarray(rows, dtype=float)


def _source_support_relative_fit_pairs(constraint):
    if not constraint.get('supportRelativeMaterialMotion', False):
        return []
    grouped = defaultdict(list)
    for observation in constraint.get('supportRelativeObservations') or []:
        grouped[observation.get('supportGroup')].append(observation)
    return [
        (observations[0], observation)
        for observations in grouped.values()
        for observation in observations[1:]
    ]


def _source_support_relative_has_material_motion(observations):
    grouped = defaultdict(list)
    for observation in observations or []:
        grouped[observation.get('supportGroup')].append(observation['sourceDelta'])
    for tracks in grouped.values():
        source_tracks = np.asarray(tracks, dtype=float)
        if len(source_tracks) < 2:
            continue
        typical_source_distance = max(
            float(np.median(np.linalg.norm(source_tracks, axis=1))), 1e-9,
        )
        source_span = np.ptp(source_tracks, axis=0) / typical_source_distance
        if np.any(source_span >= SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_DISTANCE_RATIO):
            return True
    return False


def _projected_source_support_delta(candidate, observation, projection):
    left, right, alpha = (
        observation['leftFrame'], observation['rightFrame'], observation['alpha'],
    )
    center_joints = observation['centerJointIndices']
    center = np.mean(candidate[left, center_joints], axis=0) * (1. - alpha)
    center += np.mean(candidate[right, center_joints], axis=0) * alpha
    support_joint = observation['supportJointIndex']
    support = (candidate[left, support_joint] * (1. - alpha)
               + candidate[right, support_joint] * alpha)
    return projection @ (center - support)


def _source_support_relative_fit_jacobian(
    constraint, *, frame_count, joint_count, rig, coordinates, fk_jacobian=None,
):
    pairs = _source_support_relative_fit_pairs(constraint)
    if not constraint.get('available') or not pairs:
        return csr_matrix((0, frame_count * rig.width))
    rows, columns, values = [], [], []
    projection = constraint['projection']
    normalization = constraint['normalization']
    weight = constraint['supportRelativeWeight']
    for observation_index, (reference, observation) in enumerate(pairs):
        confidence_weight = min(
            observation['confidenceWeight'], reference['confidenceWeight'],
        )
        gain = weight * confidence_weight / normalization
        for sample, sample_sign in ((observation, 1.), (reference, -1.)):
            left, right, alpha = (
                sample['leftFrame'], sample['rightFrame'], sample['alpha'],
            )
            endpoints = [(left, 1. - alpha)]
            if right != left:
                endpoints.append((right, alpha))
            center_joints = sample['centerJointIndices']
            support_joint = sample['supportJointIndex']
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight == 0.:
                    continue
                for output_axis in range(2):
                    row = observation_index * 2 + output_axis
                    for coordinate in range(3):
                        component_gain = (sample_sign * gain * interpolation_weight
                                          * projection[output_axis, coordinate])
                        if component_gain == 0.:
                            continue
                        center_gain = component_gain / len(center_joints)
                        for center_joint in center_joints:
                            rows.append(row)
                            columns.append((frame_index * joint_count + center_joint) * 3 + coordinate)
                            values.append(center_gain)
                        rows.append(row)
                        columns.append((frame_index * joint_count + support_joint) * 3 + coordinate)
                        values.append(-component_gain)
    point_jacobian = csr_matrix(
        (values, (rows, columns)),
        shape=(len(pairs) * 2, frame_count * joint_count * 3),
    )
    if fk_jacobian is None:
        fk_jacobian = rig.fk_jacobian(coordinates)
    return point_jacobian @ fk_jacobian


def _source_support_relative_fit_evidence(candidate, constraint):
    observations = constraint.get('supportRelativeObservations') or []
    if not constraint.get('available') or not observations:
        return {'available': False, 'passed': True, 'reason': 'confirmed_source_support_unavailable'}
    projection = constraint['projection']
    normalization = constraint['normalization']
    grouped = defaultdict(list)
    for observation in observations:
        grouped[observation.get('supportGroup')].append(observation)
    path_errors = []
    relevant_travel_ratios = []
    source_travel_by_support = {}
    fitted_travel_by_support = {}
    retention_by_support = {}
    position_offsets = []
    material_motion = False
    for support_group, group_observations in grouped.items():
        source_tracks = np.asarray([row['sourceDelta'] for row in group_observations], dtype=float)
        fitted_tracks = np.asarray([
            _projected_source_support_delta(candidate, row, projection)
            for row in group_observations
        ], dtype=float)
        if len(source_tracks) < 2:
            continue
        raw_error = fitted_tracks - source_tracks
        position_offsets.append(np.mean(raw_error, axis=0) / normalization)
        path_error = (fitted_tracks - fitted_tracks[0]) - (source_tracks - source_tracks[0])
        path_errors.extend(path_error[1:] / normalization)
        typical_source_distance = max(
            float(np.median(np.linalg.norm(source_tracks, axis=1))), 1e-9,
        )
        source_span = np.ptp(source_tracks, axis=0) / typical_source_distance
        fitted_span = np.ptp(fitted_tracks, axis=0) / typical_source_distance
        relevant_axes = source_span >= SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_DISTANCE_RATIO
        ratios = np.divide(
            fitted_span,
            np.maximum(source_span, 1e-12),
            out=np.ones_like(fitted_span),
            where=relevant_axes,
        )
        source_travel_by_support[str(support_group)] = source_span.tolist()
        fitted_travel_by_support[str(support_group)] = fitted_span.tolist()
        retention_by_support[str(support_group)] = [float(value) for value in ratios]
        if np.any(relevant_axes):
            material_motion = True
            relevant_travel_ratios.extend(ratios[relevant_axes].tolist())
    path_errors = np.asarray(path_errors, dtype=float)
    rms_body_ratio = float(np.sqrt(np.mean(np.sum(path_errors ** 2, axis=1)))) if len(path_errors) else 0.
    minimum_travel_ratio = (
        float(np.min(relevant_travel_ratios)) if relevant_travel_ratios else None
    )
    position_offset_body_ratio = (
        float(np.sqrt(np.mean(np.sum(np.asarray(position_offsets) ** 2, axis=1))))
        if position_offsets else 0.
    )
    passed = (
        (not material_motion or rms_body_ratio <= SOURCE_SUPPORT_RELATIVE_MAX_RMS_BODY_RATIO)
        and (minimum_travel_ratio is None
             or minimum_travel_ratio >= SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_RATIO)
    )
    return {
        'available': True,
        'passed': bool(passed),
        'observationCount': len(observations),
        'supportJointNames': constraint.get('supportRelativeJointNames') or [],
        'pixelTrackObservationCount': sum(
            row.get('sourceEvidence') == 'source_pixel_tracking' for row in observations),
        'relativePathRmsBodyRatio': rms_body_ratio,
        'relativePositionOffsetBodyRatio': position_offset_body_ratio,
        'sourceTravelRatiosBySupport': source_travel_by_support,
        'fittedTravelRatiosBySupport': fitted_travel_by_support,
        'travelRetentionRatiosBySupport': retention_by_support,
        'minimumRelevantTravelRetentionRatio': minimum_travel_ratio,
        'materialMotion': material_motion,
        'reason': 'source_path_mismatch' if material_motion and not passed else (
            'not_materially_moving' if not material_motion else None),
        'maximumRmsBodyRatio': SOURCE_SUPPORT_RELATIVE_MAX_RMS_BODY_RATIO,
        'minimumTravelRetentionRatio': SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_RATIO,
        'minimumSourceTravelRelativeDistanceRatio': SOURCE_SUPPORT_RELATIVE_MIN_TRAVEL_DISTANCE_RATIO,
    }


def _source_endpoint_posture_fit_rows(candidate, constraint):
    """Match source-confirmed 2D posture over selected-cycle endpoint windows."""
    observations = constraint.get('endpointPostureObservations') or []
    if not constraint.get('available') or not observations:
        return np.empty(0, dtype=float)
    projection = constraint['projection']
    normalization = constraint['normalization']
    weight = constraint['weight'] * constraint.get(
        'endpointPostureFitMultiplier', SOURCE_ENDPOINT_POSTURE_FIT_MULTIPLIER)
    rows = []
    for observation in observations:
        joint = observation['jointIndex']
        center_joints = observation['centerJointIndices']
        projected_delta = np.zeros(2, dtype=float)
        for link in observation['fitLinks']:
            left, right, alpha = link['leftFrame'], link['rightFrame'], link['alpha']
            point = (candidate[left, joint] * (1. - alpha)
                     + candidate[right, joint] * alpha)
            center = np.mean(candidate[left, center_joints], axis=0) * (1. - alpha)
            center += np.mean(candidate[right, center_joints], axis=0) * alpha
            projected_delta += link['weight'] * (projection @ (point - center))
        error = projected_delta - observation['sourceDelta']
        rows.extend((weight * observation['confidenceWeight']
                     * observation.get('sampleWeight', 1.) * error / normalization).tolist())
    return np.asarray(rows, dtype=float)


def _source_projection_fit_jacobian(
    constraint, *, frame_count, joint_count, rig, coordinates, fk_jacobian=None,
):
    if not constraint.get('available'):
        return csr_matrix((0, frame_count * rig.width))
    rows, columns, values = [], [], []
    projection = constraint['projection']
    normalization = constraint['normalization']
    weight = constraint['weight']
    point_observations = _source_projection_point_observations(constraint)
    for observation_index, observation in enumerate(point_observations):
        joint = observation['jointIndex']
        alpha = observation['alpha']
        confidence_weight = observation.get(
            'fitConfidenceWeight', observation['confidenceWeight'])
        endpoints = [(observation['leftFrame'], 1. - alpha)]
        if observation['rightFrame'] != observation['leftFrame']:
            endpoints.append((observation['rightFrame'], alpha))
        for output_axis in range(2):
            row = observation_index * 2 + output_axis
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight == 0.:
                    continue
                for coordinate in range(3):
                    value = (weight * confidence_weight * interpolation_weight
                             * projection[output_axis, coordinate] / normalization)
                    if value == 0.:
                        continue
                    rows.append(row)
                    columns.append((frame_index * joint_count + joint) * 3 + coordinate)
                    values.append(value)
    point_jacobian = csr_matrix(
        (values, (rows, columns)),
        shape=(len(point_observations) * 2, frame_count * joint_count * 3),
    )
    ray_observations = constraint.get('sourceFootRayObservations') or []
    # The ankle-to-toe proxy remains diagnostic. Its angle can be met by yaw
    # while the rendered heel stays down, so only material-heel rows own lift.
    phase_observations = []
    ray_rows, ray_columns, ray_values = [], [], []
    ray_weight = constraint.get('sourceFootRayWeight', weight)
    ray_points = rig.decode(coordinates) if ray_observations else None
    for observation_index, observation in enumerate(ray_observations):
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle_index = observation['ankleJointIndex']
        foot_index = observation['footJointIndex']
        ankle = (ray_points[left, ankle_index] * (1. - alpha)
                 + ray_points[right, ankle_index] * alpha)
        foot = (ray_points[left, foot_index] * (1. - alpha)
                + ray_points[right, foot_index] * alpha)
        fitted_ray = projection @ (foot - ankle)
        length = float(np.linalg.norm(fitted_ray))
        if length <= 1e-9:
            continue
        target = observation['targetRay']
        cross = float(target[0] * fitted_ray[1] - target[1] * fitted_ray[0])
        gradient = np.asarray([-target[1], target[0]]) / length
        gradient -= cross * fitted_ray / (length ** 3)
        gain = ray_weight * observation['confidenceWeight']
        for frame_index, interpolation_weight in (
            (left, 1. - alpha), (right, alpha),
        ):
            if interpolation_weight == 0.:
                continue
            for coordinate in range(3):
                component = gain * interpolation_weight * float(
                    gradient @ projection[:, coordinate])
                if component == 0.:
                    continue
                row = len(point_observations) * 2 + observation_index
                ray_rows.extend((row, row))
                ray_columns.extend((
                    (frame_index * joint_count + foot_index) * 3 + coordinate,
                    (frame_index * joint_count + ankle_index) * 3 + coordinate,
                ))
                ray_values.extend((component, -component))
    phase_points = rig.decode(coordinates) if phase_observations else None
    phase_rows, phase_columns, phase_values = [], [], []
    phase_row_offset = len(point_observations) * 2 + len(ray_observations)
    for observation_index, observation in enumerate(phase_observations):
        left, right, alpha = (
            observation['leftFrame'], observation['rightFrame'], observation['alpha'],
        )
        ankle_index = observation['ankleJointIndex']
        foot_index = observation['footJointIndex']
        ankle = (phase_points[left, ankle_index] * (1. - alpha)
                 + phase_points[right, ankle_index] * alpha)
        foot = (phase_points[left, foot_index] * (1. - alpha)
                + phase_points[right, foot_index] * alpha)
        fitted_ray = projection @ (foot - ankle)
        squared_length = float(np.dot(fitted_ray, fitted_ray))
        if squared_length <= 1e-18:
            continue
        phase_data = observation['heelPhasePreservation']
        phase = float(np.arctan2(fitted_ray[1], fitted_ray[0])
                      - phase_data['stanceTargetAngleRadians'])
        phase = float(np.arctan2(np.sin(phase), np.cos(phase)))
        native_phase = phase_data['nativePhaseRadians']
        signed_fitted_phase = np.sign(native_phase) * phase
        if signed_fitted_phase >= .92 * abs(native_phase):
            continue
        angle_gradient = np.asarray([-fitted_ray[1], fitted_ray[0]]) / squared_length
        gain = -SOURCE_FOOT_PHASE_FIT_WEIGHT * np.sign(native_phase)
        for frame_index, interpolation_weight in ((left, 1. - alpha), (right, alpha)):
            if interpolation_weight == 0.:
                continue
            for coordinate in range(3):
                component = gain * interpolation_weight * float(
                    angle_gradient @ projection[:, coordinate])
                if component == 0.:
                    continue
                row = phase_row_offset + observation_index
                phase_rows.extend((row, row))
                phase_columns.extend((
                    (frame_index * joint_count + foot_index) * 3 + coordinate,
                    (frame_index * joint_count + ankle_index) * 3 + coordinate,
                ))
                phase_values.extend((component, -component))
    ray_point_jacobian = csr_matrix(
        (ray_values, (ray_rows, ray_columns)),
        shape=(len(point_observations) * 2 + len(ray_observations) + len(phase_observations),
               frame_count * joint_count * 3),
    )
    phase_point_jacobian = csr_matrix(
        (phase_values, (phase_rows, phase_columns)),
        shape=(len(point_observations) * 2 + len(ray_observations) + len(phase_observations),
               frame_count * joint_count * 3),
    )
    heel_observations = constraint.get('sourceFootHeelImageObservations') or []
    heel_events = constraint.get('sourceFootHeelTrajectoryEvents') or []
    heel_rows, heel_columns, heel_values = [], [], []
    if heel_observations:
        from .foot_geometry import sample_material_foot_points
        heel_points = rig.decode(coordinates)
        cursors = np.asarray([
            row['leftFrame'] + row['alpha'] for row in heel_observations
        ], dtype=float)
        rendered_geometry = sample_material_foot_points(
            constraint['footGeometryPayload'], cursors, points=heel_points)
        heel_base_vectors = np.asarray([
            projection @ (rendered_geometry[row['motionSide']]['heel'][index]
                          - rendered_geometry[row['motionSide']]['toe'][index])
            for index, row in enumerate(heel_observations)
        ])
        trajectory_by_time = {
            (row['sourceSide'], round(float(row['sourceTime']), 8)): row
            for row in constraint.get('sourceFootHeelTrajectoryObservations') or []
        }
        observation_indices = {
            (row['sourceSide'], round(float(row['sourceTime']), 8)): index
            for index, row in enumerate(heel_observations)
        }
        event_jacobian_rows = {}
        for event_index, event in enumerate(heel_events):
            keys = [(event['sourceSide'], round(float(time), 8))
                    for time in event['observationTimes']]
            indices = [observation_indices[key] for key in keys if key in observation_indices]
            trajectories = [trajectory_by_time[key] for key in keys if key in trajectory_by_time]
            if not indices:
                continue
            lifts = np.asarray([
                max(0., float((heel_base_vectors[index] - trajectory['baselineFitVector'])
                              @ trajectory['liftDirection']))
                for index, trajectory in zip(indices, trajectories)
            ])
            order = np.argsort(lifts)
            quantile_position = .9 * (len(lifts) - 1)
            lower_order = int(np.floor(quantile_position))
            upper_order = int(np.ceil(quantile_position))
            upper_weight = quantile_position - lower_order
            selected = [(int(order[lower_order]), 1. - upper_weight)]
            if upper_order != lower_order:
                selected.append((int(order[upper_order]), upper_weight))
            fitted_amplitude = float(np.quantile(lifts, .9))
            if fitted_amplitude < event['fitMinimumRatio'] * event['sourceExcursionImageUnits']:
                event_jacobian_rows[event_index] = [
                    (indices[local_index], trajectories[local_index], quantile_weight)
                    for local_index, quantile_weight in selected
                    if quantile_weight > 0. and lifts[local_index] > 0.
                ]
        epsilon = 1e-6
        sides = {row['motionSide'] for row in heel_observations}
        heel_joint_indices = {
            side: (heel_observations[next(
                i for i, row in enumerate(heel_observations)
                if row['motionSide'] == side)]['ankleJointIndex'],
                heel_observations[next(
                    i for i, row in enumerate(heel_observations)
                    if row['motionSide'] == side)]['footJointIndex'])
            for side in sides
        }
        # The rendered lateral axis is transported from each frame's stored
        # bone side. Holding it fixed while perturbing ankle/toe positions
        # drops that transport derivative (material at nonzero rest pitch).
        # Perturb both bilateral tracks together and extract each side's rows;
        # the two shoes are independent, so six sampler calls cover both sides.
        local_vector_derivatives = {}
        for kind in range(2):
            for coordinate in range(3):
                perturbed_points = heel_points.copy()
                for side, joint_indices in heel_joint_indices.items():
                    perturbed_points[:, joint_indices[kind], coordinate] += epsilon
                perturbed_geometry = sample_material_foot_points(
                    constraint['footGeometryPayload'], cursors, points=perturbed_points)
                for side in sides:
                    side_indices = [index for index, row in enumerate(heel_observations)
                                    if row['motionSide'] == side]
                    moved_vectors = np.asarray([
                        projection @ (heel - toe)
                        for heel, toe in zip(
                            perturbed_geometry[side]['heel'][side_indices],
                            perturbed_geometry[side]['toe'][side_indices])
                    ])
                    derivatives = np.zeros((len(heel_observations), 2), dtype=float)
                    derivatives[side_indices] = (
                        moved_vectors - heel_base_vectors[side_indices]) / epsilon
                    local_vector_derivatives[(side, kind, coordinate)] = derivatives
        for observation_index, observation in enumerate(heel_observations):
            side = observation['motionSide']
            ankle_index, foot_index = heel_joint_indices[side]
            endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
            if observation['rightFrame'] != observation['leftFrame']:
                endpoints.append((observation['rightFrame'], observation['alpha']))
            for kind, joint_index in enumerate((ankle_index, foot_index)):
                for coordinate in range(3):
                    derivative = local_vector_derivatives[(
                        side, kind, coordinate)][observation_index]
                    for frame_index, interpolation_weight in endpoints:
                        if interpolation_weight == 0.:
                            continue
                        column = (frame_index * joint_count + joint_index) * 3 + coordinate
                        weighted_derivative = derivative * interpolation_weight
                        for axis in range(2):
                            error = (heel_base_vectors[observation_index, axis]
                                     - observation['imageOffset'][axis]
                                     - observation['sourceHeelToToeVector'][axis])
                            noise = float(observation.get('sourceNoiseImageUnits', 0.))
                            if abs(error) <= noise:
                                continue
                            value = (SOURCE_PROJECTION_FIT_WEIGHT
                                     * observation['confidenceWeight']
                                     * weighted_derivative[axis])
                            if value != 0.:
                                heel_rows.append(observation_index * 2 + axis)
                                heel_columns.append(column)
                                heel_values.append(float(value))
                        for event_index, contributions in event_jacobian_rows.items():
                            for selected_index, trajectory, quantile_weight in contributions:
                                if selected_index != observation_index:
                                    continue
                                value = (SOURCE_FOOT_PHASE_FIT_WEIGHT * quantile_weight
                                         * float(-weighted_derivative
                                                 @ trajectory['liftDirection']))
                                if value != 0.:
                                    heel_rows.append(2 * len(heel_observations) + event_index)
                                    heel_columns.append(column)
                                    heel_values.append(value)
    heel_point_jacobian = csr_matrix(
        (heel_values, (heel_rows, heel_columns)),
        shape=(2 * len(heel_observations) + len(heel_events),
               frame_count * joint_count * 3),
    )
    if fk_jacobian is None:
        fk_jacobian = rig.fk_jacobian(coordinates)
    if ray_observations or phase_observations or heel_observations:
        return vstack([
            point_jacobian,
            ray_point_jacobian[len(point_observations) * 2:, :]
            + phase_point_jacobian[len(point_observations) * 2:, :],
            heel_point_jacobian,
        ], format='csr') @ fk_jacobian
    return point_jacobian @ fk_jacobian


def _source_endpoint_posture_fit_jacobian(
    constraint, *, frame_count, joint_count, rig, coordinates, fk_jacobian=None,
):
    observations = constraint.get('endpointPostureObservations') or []
    if not constraint.get('available') or not observations:
        return csr_matrix((0, frame_count * rig.width))
    rows, columns, values = [], [], []
    projection = constraint['projection']
    normalization = constraint['normalization']
    weight = constraint['weight'] * constraint.get(
        'endpointPostureFitMultiplier', SOURCE_ENDPOINT_POSTURE_FIT_MULTIPLIER)
    for observation_index, observation in enumerate(observations):
        joint = observation['jointIndex']
        center_joints = observation['centerJointIndices']
        confidence_weight = observation['confidenceWeight']
        for link in observation['fitLinks']:
            endpoints = [(link['leftFrame'], 1. - link['alpha'])]
            if link['rightFrame'] != link['leftFrame']:
                endpoints.append((link['rightFrame'], link['alpha']))
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight == 0.:
                    continue
                gain = (weight * confidence_weight * observation.get('sampleWeight', 1.)
                        * link['weight'] * interpolation_weight / normalization)
                for output_axis in range(2):
                    row = observation_index * 2 + output_axis
                    for coordinate in range(3):
                        component_gain = gain * projection[output_axis, coordinate]
                        if component_gain == 0.:
                            continue
                        rows.append(row)
                        columns.append((frame_index * joint_count + joint) * 3 + coordinate)
                        values.append(component_gain)
                        center_gain = -component_gain / len(center_joints)
                        for center_joint in center_joints:
                            rows.append(row)
                            columns.append((frame_index * joint_count + center_joint) * 3 + coordinate)
                            values.append(center_gain)
    point_jacobian = csr_matrix(
        (values, (rows, columns)),
        shape=(len(observations) * 2, frame_count * joint_count * 3),
    )
    if fk_jacobian is None:
        fk_jacobian = rig.fk_jacobian(coordinates)
    return point_jacobian @ fk_jacobian


def joint_dependencies(rig, names):
    return np.max(rig.dependencies[[rig.names.index(name)*3 for name in names]],axis=0)


def _source_foot_direction_fit_evidence(points, target_directions, authority_mask,
                                        joint_names, *, tolerance_degrees=None):
    """Measure source-owned ankle-to-toe direction error without adding pins."""
    points = np.asarray(points, dtype=float)
    targets = np.asarray(target_directions, dtype=float)
    authority = np.asarray(authority_mask, dtype=bool)
    names = list(joint_names)
    if (points.ndim != 3 or targets.shape != (len(points), 2, 3)
            or authority.shape != (len(points), 2)):
        raise ValueError('source foot direction evidence arrays have incompatible shapes')
    if tolerance_degrees is None:
        ankle_limits = [limit for label, _, _, _, limit in ARTICULATIONS
                        if label.endswith('_ankle')]
        tolerance_degrees = min(10., *ankle_limits) if ankle_limits else 10.
    sides = {}
    all_errors = []
    for side_index, side in enumerate(('left', 'right')):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        mask = authority[:, side_index]
        if ankle_name not in names or toe_name not in names:
            sides[side] = {
                'observationCount': 0,
                'invalidObservationCount': int(np.count_nonzero(mask)),
                'maximumErrorDegrees': None,
                'p95ErrorDegrees': None,
                'passed': not bool(np.any(mask)),
            }
            continue
        if not np.any(mask):
            sides[side] = {'observationCount': 0, 'maximumErrorDegrees': None,
                           'p95ErrorDegrees': None, 'passed': True}
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        bone = points[:, toe] - points[:, ankle]
        lengths = np.linalg.norm(bone, axis=1)
        valid = mask & (lengths > 1e-9)
        predicted = bone / np.maximum(lengths[:, None], 1e-12)
        desired = targets[:, side_index].copy()
        target_lengths = np.linalg.norm(desired, axis=1)
        valid &= np.isfinite(points[:, ankle]).all(axis=1)
        valid &= np.isfinite(points[:, toe]).all(axis=1)
        valid &= np.isfinite(desired).all(axis=1) & (target_lengths > 1e-9)
        desired /= np.maximum(np.linalg.norm(desired, axis=1, keepdims=True), 1e-12)
        errors = np.rad2deg(np.arccos(np.clip(np.sum(predicted * desired, axis=1), -1., 1.)))
        errors = errors[valid]
        if not len(errors):
            sides[side] = {'observationCount': 0,
                           'invalidObservationCount': int(np.count_nonzero(mask)),
                           'maximumErrorDegrees': None,
                           'p95ErrorDegrees': None, 'passed': False}
            continue
        maximum = float(np.max(errors))
        p95 = float(np.percentile(errors, 95.))
        all_errors.extend(errors.tolist())
        sides[side] = {
            'observationCount': int(len(errors)),
            'invalidObservationCount': int(np.count_nonzero(mask) - len(errors)),
            'maximumErrorDegrees': maximum,
            'p95ErrorDegrees': p95,
            'passed': (len(errors) == int(np.count_nonzero(mask))
                       and maximum <= float(tolerance_degrees)),
        }
    available = bool(all_errors)
    return {
        'available': available,
        'passed': bool(all(side['passed'] for side in sides.values())),
        'authoritySampleCount': int(sum(side['observationCount'] for side in sides.values())),
        'toleranceDegrees': float(tolerance_degrees),
        'maximumErrorDegrees': float(max(all_errors)) if all_errors else None,
        'p95ErrorDegrees': float(np.percentile(all_errors, 95.)) if all_errors else None,
        'bySide': sides,
    }


def rotation_prior_dependencies(width):
    # SO(3) logarithm components couple the three coordinates of each rotation.
    pattern=np.zeros((width-3,width))
    for start in range(3,width,3):
        pattern[start-3:start,start:start+3]=1.
    return pattern


def fit_controlled_motion(payload, *, max_evaluations=None, timeout_seconds=None):
    """Schedule numerical fitting separately from concurrent browser/review work."""
    patch_clock_failure = source_foot_patch_clock_failure(payload)
    if patch_clock_failure:
        return payload, {
            "applied": False,
            "strategy": CONTROLLED_MOTION_STRATEGY,
            "reason": patch_clock_failure['reason'],
            "failureStage": 'source_support_contact_readiness',
            "sourceFootPatchClock": patch_clock_failure,
        }
    from .contact_constraints import source_support_mapping_unresolved
    if source_support_mapping_unresolved(payload):
        return payload, {
            "applied": False,
            "reason": "source_support_mapping_unresolved",
        }
    from .support_geometry import support_contact_readiness
    support_readiness = support_contact_readiness(payload)
    if not support_readiness['passed']:
        return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                         'reason': support_readiness['rejectionReasons'][0],
                         'failureStage': 'source_support_contact_readiness',
                         'sourceContactReadiness': support_readiness}
    from .fit_runtime import FitSlotTimeout, cpu_fit_slot
    try:
        with cpu_fit_slot(timeout_seconds=timeout_seconds) as waited:
            fit_timeout = (
                None if timeout_seconds is None
                else max(0.0, float(timeout_seconds) - float(waited))
            )
            result, report = _fit_candidate_motion(
                payload, max_evaluations=max_evaluations, timeout_seconds=fit_timeout)
    except FitSlotTimeout as exc:
        return payload, {
            "applied": False,
            "reason": "fit_timeout",
            "failureStage": "cpu_fit_slot_admission",
            "cpuFitQueueWaitSeconds": round(exc.waited_seconds, 3),
            "error": str(exc),
        }
    report['cpuFitQueueWaitSeconds'] = waited
    if report.get('applied') and not isinstance(report.get('fitSourceEvidenceDigest'), str):
        report['fitSourceEvidenceDigest'] = controlled_motion_fit_source_evidence_digest(result)
    return result, report


def _hybrid_jacobian_enabled():
    raw_flag = os.environ.get('EXERCISE_MOTION_HYBRID_JACOBIAN')
    if raw_flag is None:
        return True
    return raw_flag.strip().lower() in ('force', '1', 'true', 'yes', 'on')


def _cyclic_frame_probe_colors(frame_count):
    """Color cyclic three-frame stencils so wrapped rows never collide."""
    if frame_count < 3:
        raise ValueError('cyclic frame probes require at least three frames')
    colors = np.arange(frame_count, dtype=int) % 3
    remainder = frame_count % 3
    if remainder:
        colors[-remainder:] = np.arange(3, 3 + remainder, dtype=int)
    return colors, int(3 + remainder)


def _fit_candidate_motion(payload, *, max_evaluations=None, timeout_seconds=None):
    """Reuse equivalent fits and share one deadline across candidate variants."""
    from .fit_runtime import current_fit_session, fit_input_key
    session = current_fit_session()
    if session is None:
        return _fit_observed_cycles(payload, max_evaluations=max_evaluations, timeout_seconds=timeout_seconds)
    key = fit_input_key({'payload': payload, 'maxEvaluations': max_evaluations,
                         'timeoutSeconds': timeout_seconds})
    if key in session.results:
        session.reused_fits += 1
        result, report = deepcopy(session.results[key])
        report['reusedCandidateFit'] = True
        return result, report
    remaining = session.remaining()
    candidate_fit_budget = {
        'seconds': session.budget_seconds,
        'remainingSeconds': remaining,
        'fitCalls': session.fit_calls,
        'reusedFits': session.reused_fits,
        'reusedAnatomyFrames': session.reused_frames,
    }
    if remaining <= 0:
        return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                         'reason': 'fit_timeout', 'budgetOwner': 'candidate', 'elapsedSeconds': 0.,
                         'candidateFitBudget': candidate_fit_budget}
    if remaining < MIN_USEFUL_FIT_SECONDS and timeout_seconds is None:
        # Later variants inherit session scraps once earlier fits consumed the
        # candidate deadline (measured: a variant started with 1.45s left and
        # burned a guaranteed-failure fit). Skip below the useful floor; explicit
        # caller deadlines stay hard caps and keep full ownership.
        return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                         'reason': 'fit_timeout', 'budgetOwner': 'candidate', 'elapsedSeconds': 0.,
                         'skippedBelowUsefulFloor': True,
                         'remainingSeconds': remaining,
                         'candidateFitBudget': candidate_fit_budget}
    session.fit_calls += 1
    session.started = monotonic()
    try:
        # Cycle attempts share one deadline. When using the frame-scaled default,
        # allow up to 2x that base if the candidate session still has time so a
        # short single-fit floor cannot leave usable budget stranded mid-cycle.
        # Explicit caller deadlines stay hard caps.
        base = fit_time_budget(payload, timeout_seconds)
        if timeout_seconds is None:
            allocated = min(remaining, max(base, min(remaining, 2.0 * base)))
        else:
            allocated = min(remaining, base)
        result, report = _fit_observed_cycles(payload, max_evaluations=max_evaluations,
            timeout_seconds=allocated)
    finally:
        # Browser work and rendering between fits do not consume the fit budget.
        session.previously_spent += max(0., monotonic() - session.started)
        session.started = None
        session.save()
    report['candidateFitBudget'] = {'seconds': session.budget_seconds,
        'remainingSeconds': session.remaining(), 'fitCalls': session.fit_calls,
        'reusedFits': session.reused_fits, 'reusedAnatomyFrames': session.reused_frames}
    session.results[key] = deepcopy((result, report))
    return result, report


def _fit_observed_cycles(payload, *, max_evaluations=None, timeout_seconds=None):
    """Prefer a source-confirmed cycle, retaining the full interval as fallback."""
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    artifact_state = payload.get('artifactState')
    selection_evidence = (
        artifact_state.get('selectionEvidence')
        if isinstance(artifact_state, dict)
        else None
    )
    has_artifact_selected_interval = isinstance(selection_evidence, dict) and any(
        isinstance(selection_evidence.get(key), dict)
        and isinstance(selection_evidence[key].get('interval'), dict)
        for key in ('cycleSelection', 'boundedMovementSelection')
    )
    selected_phase_preflight = payload.get('selectedIntervalSourcePhasePreflight')
    if (not (payload.get('loop') or {}).get('enabled') or payload.get('fixedRig')
            or payload.get('loopCycleSelection') or has_artifact_selected_interval
            or timeout_seconds <= 0):
        source_phase = (
            selected_phase_preflight.get('sourcePhase')
            if isinstance(selected_phase_preflight, dict)
            else None
        )
        if (timeout_seconds > 0
                and (payload.get('loop') or {}).get('enabled')
                and not payload.get('fixedRig')
                and isinstance(source_phase, dict)
                and source_phase.get('required') is True
                and source_phase.get('passed') is False):
            return payload, {
                'applied': False,
                'strategy': CONTROLLED_MOTION_STRATEGY,
                'reason': 'selected_interval_source_phase_rejected',
                'retainedIntervalFit': False,
                'selectedIntervalSourcePhasePreflight': selected_phase_preflight,
                'elapsedSeconds': 0.,
            }
        if (timeout_seconds > 0 and (payload.get('loop') or {}).get('enabled')
                and not payload.get('fixedRig')):
            from .loop_cycles import cycle_boundary_motion_metrics
            boundary = cycle_boundary_motion_metrics(payload)
            if not boundary['passed']:
                return payload, {
                    'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                    'reason': 'source_cycle_preflight_rejected',
                    'retainedIntervalFit': False, 'boundaryMotion': boundary,
                    'cycleSelectionAttempts': [],
                    'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
                    'elapsedSeconds': 0.,
                }
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=timeout_seconds)
    from .loop_cycles import cycle_boundary_motion_metrics, rank_loop_cycles, slice_loop_cycle
    started = monotonic()
    boundary_ranking = {}
    choices = (payload['observedCycleProposals'] if 'observedCycleProposals' in payload
               else rank_loop_cycles(payload, max_candidates=3, diagnostics=boundary_ranking))
    boundary_rejections = []
    admitted_choices = []
    for choice in choices:
        boundary = cycle_boundary_motion_metrics(payload, choice)
        if boundary['passed']:
            admitted_choices.append(choice)
        else:
            boundary_rejections.append({'selection': choice, 'boundaryMotion': boundary})
    choices = admitted_choices
    if not choices:
        boundary = cycle_boundary_motion_metrics(payload)
        if boundary['passed'] and boundary_ranking.get('boundaryMotion'):
            boundary = boundary_ranking['boundaryMotion']
        if not boundary['passed']:
            return payload, {
                'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                'reason': 'source_cycle_preflight_rejected',
                'retainedIntervalFit': False, 'boundaryMotion': boundary,
                'cycleBoundaryRejections': boundary_rejections,
                'cycleSelectionAttempts': [],
                'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
                'elapsedSeconds': monotonic() - started,
            }
    shared_support = {}
    attempts = []
    open_cycle_fallback = None
    cycle_retry_stop_reason = None

    def fit_attempt(candidate_payload, attempt_timeout):
        attempt_started = monotonic()
        fitted_payload, fit_report = _fit_controlled_motion(
            candidate_payload,
            max_evaluations=max_evaluations,
            timeout_seconds=attempt_timeout,
            shared_support=shared_support,
        )
        return fitted_payload, fit_report, monotonic() - attempt_started

    source_preflight = [
        entry for entry in payload.get('sourceCyclePreflight', [])
        if isinstance(entry, dict)
    ]
    required_source_phases = [
        entry.get('sourcePhase')
        for entry in source_preflight
        if isinstance(entry.get('sourcePhase'), dict)
        and entry['sourcePhase'].get('required') is True
    ]
    rejected_source_cycle_preflight = any(
        entry.get('passed') is False
        and entry.get('reason') == 'no_feasible_observed_cycle'
        and isinstance(entry.get('proposalDiagnostics'), dict)
        for entry in source_preflight
    )
    unresolved_parent_phase_coverage = any(
        entry.get('needsReview') is True
        and entry.get('reason') == 'parent_phase_coverage_unresolved'
        for entry in source_preflight
    )
    if not choices and unresolved_parent_phase_coverage:
        return payload, {
            'applied': False,
            'strategy': CONTROLLED_MOTION_STRATEGY,
            'reason': 'source_cycle_parent_phase_coverage_unresolved',
            'reviewRequired': True,
            'retainedIntervalFit': False,
            'cycleSelectionAttempts': attempts,
            'sourceCyclePreflight': source_preflight,
            'elapsedSeconds': monotonic() - started,
        }
    if not choices and (
        rejected_source_cycle_preflight
        or (required_source_phases and all(
            phase.get('passed') is False for phase in required_source_phases
        ))
    ):
        # The cycle optimizer cannot make a source-incomplete repetition
        # source-complete. A populated preflight rejection means every observed
        # cycle failed the source phase/range/wrap constraints. Avoid spending
        # the remaining fit budget on an open-seam interval that cannot satisfy
        # the required loop contract.
        rejected_boundary = next((
            entry['proposalDiagnostics']['boundaryMotion']
            for entry in source_preflight
            if isinstance(entry.get('proposalDiagnostics'), dict)
            and isinstance(entry['proposalDiagnostics'].get('boundaryMotion'), dict)
        ), None)
        return payload, {
            'applied': False,
            'strategy': CONTROLLED_MOTION_STRATEGY,
            'reason': 'source_cycle_preflight_rejected',
            'retainedIntervalFit': False,
            'cycleSelectionAttempts': attempts,
            'sourceCyclePreflight': source_preflight,
            **({'boundaryMotion': rejected_boundary} if rejected_boundary is not None else {}),
            'elapsedSeconds': monotonic() - started,
        }
    source_confirmed_first = bool(choices) and any(
        entry.get('passed') is True and entry.get('selection') == choices[0]
        for entry in source_preflight)
    first_is_full_interval = bool(choices) and (
        int(choices[0].get('startFrame', -1)) == 0
        and int(choices[0].get('stopFrameExclusive', -1)) == len(payload.get('frames') or [])
    )
    retained_interval_minimum_budget = (
        RETAINED_INTERVAL_VALIDATION_RESERVE_SECONDS + MIN_USEFUL_FIT_SECONDS
    )
    preserve_retained_interval = (
        timeout_seconds >= retained_interval_minimum_budget + MIN_USEFUL_FIT_SECONDS
    )
    if (source_confirmed_first and first_is_full_interval
            and timeout_seconds >= SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS):
        # The complete interval is itself the retained source movement. Fund
        # its bounded cyclic fit before optional crops; reserving a second
        # retained-interval attempt here lets minor overhead starve this route.
        choice, choices = choices[0], choices[1:]
        remaining = max(0., timeout_seconds - (monotonic() - started))
        source_confirmed_budget = min(
            120., max(
                SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS,
                .3 * float(timeout_seconds),
            ),
            remaining,
        )
        candidate, report, attempt_elapsed = fit_attempt(
            slice_loop_cycle(payload, choice), source_confirmed_budget)
        attempts.append({'selection': choice, 'reason': report.get('reason'),
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': attempt_elapsed,
                         'reportedFitElapsedSeconds': report.get('elapsedSeconds'),
                         'fitReport': deepcopy(report), 'sourceConfirmedFirst': True,
                         'completeIntervalFirst': True})
        if report.get('applied'):
            if (report.get('loopSeamOpen') or report.get('checks', {}).get('loopSeam') is False
                    or report.get('reason') == 'validated_controlled_motion_open_seam'):
                open_cycle_fallback = candidate, report
            else:
                report['cycleSelectionAttempts'] = attempts
                report['elapsedSeconds'] = monotonic() - started
                report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
                return candidate, report
    elif (source_confirmed_first
            and timeout_seconds >= (
                SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS
                + retained_interval_minimum_budget
            )):
        choice, choices = choices[0], choices[1:]
        remaining = max(0., timeout_seconds - (monotonic() - started))
        source_confirmed_budget = min(
            120., max(
                SOURCE_CONFIRMED_CYCLE_MINIMUM_BUDGET_SECONDS,
                .3 * float(timeout_seconds),
            ),
            max(0., remaining - retained_interval_minimum_budget),
        )
        candidate, report, attempt_elapsed = fit_attempt(
            slice_loop_cycle(payload, choice), source_confirmed_budget)
        attempts.append({'selection': choice, 'reason': report.get('reason'),
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': attempt_elapsed,
                         'reportedFitElapsedSeconds': report.get('elapsedSeconds'),
                         'fitReport': deepcopy(report), 'sourceConfirmedFirst': True})
        if report.get('applied'):
            if (report.get('loopSeamOpen') or report.get('checks', {}).get('loopSeam') is False
                    or report.get('reason') == 'validated_controlled_motion_open_seam'):
                open_cycle_fallback = candidate, report
            else:
                report['cycleSelectionAttempts'] = attempts
                report['elapsedSeconds'] = monotonic() - started
                report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
                return candidate, report
    # Ranked cycles can directly produce the required closed loop. Try them
    # before spending most of the budget on the retained interval, which is
    # deliberately fitted open-seam whenever a cycle proposal is available.
    remaining_before_cycles = max(0., timeout_seconds - (monotonic() - started))
    cycle_slots = max(0, int((remaining_before_cycles + 54.) // 55.))
    choices = choices[:cycle_slots]
    for index, choice in enumerate(choices):
        remaining = timeout_seconds - (monotonic() - started)
        later = len(choices) - index - 1
        if preserve_retained_interval:
            # Keep enough time for a useful retained-interval validation.
            # Without this reserve, overlapping crops can consume the full
            # budget and guarantee that the fallback is skipped.
            attempt_timeout = min(120., remaining - retained_interval_minimum_budget)
        else:
            # A short budget cannot support retained-interval validation. Use
            # the older crop allowance so otherwise useful time is not stranded.
            next_cycle_reserve = min(90., max(45., 0.3 * float(timeout_seconds)))
            attempt_timeout = remaining - next_cycle_reserve if later else remaining
        if remaining < MIN_USEFUL_FIT_SECONDS or attempt_timeout < MIN_USEFUL_FIT_SECONDS:
            break
        candidate, report, attempt_elapsed = fit_attempt(
            slice_loop_cycle(payload, choice), attempt_timeout)
        attempts.append({'selection': choice, 'reason': report['reason'],
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': attempt_elapsed,
                         'reportedFitElapsedSeconds': report.get('elapsedSeconds'),
                         'fitReport': deepcopy(report)})
        if report['applied']:
            if (report.get('loopSeamOpen') or report.get('checks', {}).get('loopSeam') is False
                    or report.get('reason') == 'validated_controlled_motion_open_seam'):
                # Body-valid is not a completed loop. Keep the best-ranked
                # open crop as fallback while trying the remaining budgeted
                # proposals, especially when the fitter requests another cycle.
                if open_cycle_fallback is None:
                    open_cycle_fallback = candidate, report
                continue
            report['cycleSelectionAttempts'] = attempts
            report['elapsedSeconds'] = monotonic() - started
            report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
            return candidate, report
        if hard_trajectory_and_root_failure(report.get('checks')):
            break
        if seam_near_miss_for_cycle_skip(report):
            break
        if repeated_anatomical_cycle_failure(attempts, choices[index + 1:]):
            # Similar cycle crops failing the same physical anatomy invariant
            # are not promising a different repair path. Keep the retained
            # interval validation budget and avoid repeating that fit family.
            cycle_retry_stop_reason = 'repeated_anatomical_cycle_failure'
            break
        if repeated_unreachable_support_conflict(attempts):
            # Another crop fit would repeat the same hard support blockers.
            # Preserve the remaining candidate budget for the retained
            # interval, whose endpoint constraints differ from this crop.
            cycle_retry_stop_reason = 'repeated_unreachable_support_conflict'
            break
        if repeated_unreachable_root_travel(attempts, choices[index + 1:]):
            # The two most recent, highly overlapping cycles both fit their
            # trajectories but failed the independent root-travel check. Do
            # not spend the remaining cycle budget on the same crop family.
            cycle_retry_stop_reason = 'repeated_unreachable_root_travel'
            break
    remaining_before_retained = max(0., timeout_seconds - (monotonic() - started))
    retained_fit_has_validation_budget = (
        remaining_before_retained >= retained_interval_minimum_budget
    )
    retained_attempt_elapsed = 0.
    core_unreachable_checks = {
        'contacts', 'sourceArticulation', 'trajectoryFit', 'equipment', 'bodySupport'
    }
    cycle_attempts = [
        attempt for attempt in attempts
        if isinstance(attempt.get('selection'), dict)
        and attempt['selection'].get('kind') != 'retained_interval'
    ]
    core_unreachable_failures = []
    for attempt in cycle_attempts:
        fit_report = attempt.get('fitReport')
        checks = fit_report.get('checks') if isinstance(fit_report, dict) else None
        if not isinstance(fit_report, dict) or fit_report.get('termination') != 'unreachable_conflict':
            core_unreachable_failures = []
            break
        failed_core_checks = sorted(
            name for name in core_unreachable_checks
            if isinstance(checks, dict) and checks.get(name) is False
        )
        if not failed_core_checks:
            core_unreachable_failures = []
            break
        core_unreachable_failures.append(failed_core_checks)
    shared_core_failures = (
        set(core_unreachable_failures[0]) if core_unreachable_failures else set()
    )
    for failures in core_unreachable_failures[1:]:
        shared_core_failures.intersection_update(failures)
    # A looped candidate and the retained open-seam fit have different endpoint
    # constraints. One stalled cycle cannot establish that the open fit is
    # unreachable; require repeated cycle attempts with the same core blocker.
    skip_retained_after_core_failure = (
        len(cycle_attempts) >= 2
        and len(core_unreachable_failures) == len(cycle_attempts)
        and bool(shared_core_failures)
    )
    failed_anatomy_cycle_attempts = [
        attempt for attempt in cycle_attempts
        if isinstance(attempt.get('checks'), dict)
        and attempt['checks'].get('anatomy') is False
    ]
    skip_retained_after_persistent_source_fold = False
    source_spine_fold_ratio = None
    if (
        cycle_attempts
        and len(failed_anatomy_cycle_attempts) == len(cycle_attempts)
        and remaining_before_retained >= retained_interval_minimum_budget
    ):
        source_spine_fold_ratio = source_spine_fold_frame_ratio(payload)
        source_fold_repaired_by_cycle_fit = False
        for attempt in failed_anatomy_cycle_attempts:
            fit_report = attempt.get('fitReport')
            initialization = (
                fit_report.get('anatomicalInitialization')
                if isinstance(fit_report, dict)
                else None
            )
            if (
                isinstance(initialization, dict)
                and initialization.get('passed') is True
                and initialization.get('remainingViolations') == []
            ):
                source_fold_repaired_by_cycle_fit = True
                break
        skip_retained_after_persistent_source_fold = (
            source_spine_fold_ratio is not None
            and source_spine_fold_ratio >= SOURCE_SPINE_FOLD_RETAINED_FIT_SKIP_FRAME_RATIO
            and not source_fold_repaired_by_cycle_fit
        )
    else:
        skip_retained_after_persistent_source_fold = False
    if skip_retained_after_persistent_source_fold:
        cycle_retry_stop_reason = 'persistent_source_spine_fold_after_cycle_anatomy_failure'
        retained, retained_report = payload, {
            'applied': False,
            'reason': 'retained_interval_skipped_after_persistent_source_spine_fold',
            'skipReason': 'persistent_source_spine_fold_after_cycle_anatomy_failure',
            'sourceSpineFoldFrameRatio': source_spine_fold_ratio,
            'sourceSpineFoldSkipThreshold': SOURCE_SPINE_FOLD_RETAINED_FIT_SKIP_FRAME_RATIO,
            'availableBudgetSeconds': remaining_before_retained,
            'retainedIntervalFit': False,
            'checks': {},
        }
    elif skip_retained_after_core_failure:
        # Recent artifact replay found no retained-interval passes after all
        # cycle proposals ended in unreachable conflicts on these core checks
        # (24 cases); less fundamental failures still keep the fallback because
        # it has recovered valid open-seam movements in retained artifacts.
        retained, retained_report = payload, {
            'applied': False,
            'reason': 'retained_interval_skipped_after_unreachable_core_cycle_failure',
            'skipReason': 'unreachable_core_cycle_failure',
            'coreCycleFailureChecks': sorted(shared_core_failures),
            'coreCycleFailureAttempts': len(cycle_attempts),
            'availableBudgetSeconds': remaining_before_retained,
            'retainedIntervalFit': False,
            'checks': {},
        }
    else:
        if retained_fit_has_validation_budget:
            retained_input = deepcopy(payload)
            retained_input['loop'] = {**(retained_input.get('loop') or {}), 'enabled': False}
            retained, retained_report, retained_attempt_elapsed = fit_attempt(
                retained_input, remaining_before_retained)
        else:
            retained, retained_report = payload, {
                'applied': False,
                'reason': 'retained_interval_skipped_insufficient_validation_budget',
                'availableBudgetSeconds': remaining_before_retained,
                'requiredBudgetSeconds': retained_interval_minimum_budget,
                'checks': {},
            }
    retained_checks = retained_report.get('checks') or {}
    retained_seam_reported_open = (
        retained_report.get('loopSeamOpen') is True
        or retained_checks.get('loopSeam') is False
        or retained_report.get('reason') == 'validated_controlled_motion_open_seam'
    )
    if (retained_report.get('applied') and retained_fit_has_validation_budget
            and retained_seam_reported_open):
        retained = deepcopy(retained)
        retained['loop'] = {
            **(retained.get('loop') or {}),
            'enabled': True,
            'transition': 'requires_cycle_repair',
            'restartFadeMillis': 0,
        }
        retained_report = {
            **retained_report,
            'loopSeamOpen': True,
            'reason': 'validated_controlled_motion_open_seam',
        }
        retained.pop('sequenceStabilization', None)
        retained_report['outputPoseDigest'] = pose_digest(retained)
        retained['controlledMotionFit'] = retained_report
    retained_report = {
        **retained_report,
        'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
    }
    retained_report.setdefault('retainedIntervalFit', True)
    if cycle_retry_stop_reason is not None:
        retained_report['cycleRetryStopReason'] = cycle_retry_stop_reason
    if retained_report.get('applied'):
        retained['controlledMotionFit'] = retained_report
        retained_report['outputPoseDigest'] = pose_digest(retained)
        retained['controlledMotionFit'] = retained_report
    attempts.append({
        'selection': {'kind': 'retained_interval'},
        'reason': retained_report.get('reason'),
        'checks': retained_report.get('checks', {}),
        'elapsedSeconds': retained_attempt_elapsed,
        'reportedFitElapsedSeconds': retained_report.get('elapsedSeconds'),
        'fitReport': deepcopy(retained_report),
    })
    if retained_report.get('applied'):
        retained_report['cycleSelectionAttempts'] = attempts
        retained_report['elapsedSeconds'] = monotonic() - started
        return retained, retained_report
    if open_cycle_fallback is not None:
        candidate, report = open_cycle_fallback
        report['cycleSelectionAttempts'] = attempts
        report['elapsedSeconds'] = monotonic() - started
        report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
        return candidate, report
    # Keep explicit bounded-fallback skip/failure reasons. Replacing them with
    # this generic label hid whether the fallback was intentionally skipped
    # (for example after a persistent source spine fold) or actually attempted.
    reason = retained_report.get('reason') or 'no_validated_loop_cycle'
    return payload, {
        **retained_report,
        'applied': False,
        'reason': reason,
        'cycleSelectionAttempts': attempts,
        'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
        'elapsedSeconds': monotonic() - started,
    }


def _smooth_root_rotation_candidate(rig, coordinates, original, pinned_joints, sigma):
    """Smooth root rotation while encoding pinned-joint compensation in root travel."""
    candidate = coordinates.copy()
    candidate[:, 3:6] = gaussian_filter1d(
        candidate[:, 3:6], sigma, axis=0, mode='nearest')
    trial = rig.decode(candidate)
    delta = np.mean(
        (original - trial)[:, pinned_joints], axis=1, keepdims=True)
    candidate[:, :3] += delta[:, 0, :]
    return candidate, rig.decode(candidate)


def _fit_controlled_motion(payload, *, max_evaluations=None, timeout_seconds=None, shared_support=None):
    """Fit with one local, motion-space view of materialized support evidence."""
    from .body_support_observation import materialize_stationary_sole_support
    from .contact_constraints import fit_motion_space_support_evidence_scope

    fit_support_evidence = materialize_stationary_sole_support(payload)
    with fit_motion_space_support_evidence_scope(payload, fit_support_evidence):
        result, report = _fit_controlled_motion_impl(
            payload,
            max_evaluations=max_evaluations,
            timeout_seconds=timeout_seconds,
            shared_support=shared_support,
            fit_support_evidence=fit_support_evidence,
        )
    # Bind the persisted fit to canonical evidence after the scoped fit-only
    # materialization has been removed. The scope can contain transient support
    # edits made while solving; those are not source authority and must not
    # poison the reusable fit identity.
    if report.get('applied'):
        report['fitSourceEvidenceDigest'] = controlled_motion_fit_source_evidence_digest(result)
    return result, report


def _fit_controlled_motion_impl(payload, *, max_evaluations=None, timeout_seconds=None,
                                shared_support=None, fit_support_evidence=None):
    """Return only a validated fit; otherwise retain the input with a report."""
    allow_refinement = max_evaluations is None
    if max_evaluations is None:
        frames = len(payload.get('frames') or [])
        max_evaluations = max(25, min(40, (frames // 3) or 25))
    started = monotonic()
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    cyclic_preview = bool((payload.get('loop') or {}).get('enabled'))
    reserved_polish = polish_reserve_seconds(timeout_seconds, cyclic=cyclic_preview)
    validation_reserve = fit_validation_reserve_seconds(
        len(payload.get('frames') or []), timeout_seconds)
    report = {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
              'timeBudgetSeconds': timeout_seconds, 'polishReserveSeconds': reserved_polish,
              'validationReserveSeconds': validation_reserve}
    polish_left = reserved_polish
    plant_polish = 0.
    post_validation_polish_reserve = max(float(reserved_polish), 12.)
    optimization_deadline = started + timeout_seconds
    if fit_support_evidence is None:
        from .body_support_observation import materialize_stationary_sole_support
        fit_support_evidence = materialize_stationary_sole_support(payload)
    patch_clock_failure = source_foot_patch_clock_failure(payload, fit_support_evidence)
    if patch_clock_failure:
        return payload, {
            **report,
            'reason': patch_clock_failure['reason'],
            'failureStage': 'source_support_contact_readiness',
            'sourceFootPatchClock': patch_clock_failure,
        }
    if can_reuse_controlled_motion(payload):
        from .scene_placement import normalize_scene_placement
        payload = normalize_scene_placement(payload)
        return payload, {**payload['controlledMotionFit'], 'reused': True}
    frames = payload.get('frames') or []
    names = payload.get('jointNames') or []
    fps = float(payload.get('fps', 0.))
    if len(frames)<7 or len(names)!=len(SMPL_JOINT_NAMES) or set(names)!=set(SMPL_JOINT_NAMES):
        return payload, {**report, 'reason': 'requires_contiguous_smpl_skeleton'}
    times = np.array([f.get('timeSec', np.nan) for f in frames])
    if not np.isfinite(fps) or fps<=0 or not np.isfinite(times).all() or np.max(abs(np.diff(times)-1/fps))>.05/fps:
        return payload, {**report, 'reason': 'irregular_sampling'}
    if any(f.get('syntheticLoopBridge') for f in frames):
        return payload, {**report, 'reason': 'synthetic_bridge_requires_separate_loop_fit'}
    if any(any(n not in f.get('joints',{}) for n in names) for f in frames):
        return payload, {**report, 'reason': 'incomplete_joint_tracks'}
    points = np.array([[f['joints'][n] for n in names] for f in frames], dtype=float)
    if not np.isfinite(points).all():
        return payload, {**report, 'reason': 'nonfinite_input'}
    reference = np.asarray([[f.get('controlledArticulationReferenceJoints',f['joints'])[n] for n in names] for f in frames],dtype=float)
    if not np.isfinite(reference).all():
        return payload, {**report, 'reason': 'nonfinite_articulation_reference'}
    # Keep the original source pose for articulation-preservation targets.
    anatomical_reference = reference.copy()
    # Source articulation and the hard anatomical gate have separate owners.
    # Supported fitting can later replace ``reference`` with a feasible
    # support-corrected pose; the final artifact gate uses that same pose for
    # anatomy checks, while articulation preservation still uses the source.
    fit_anatomy_reference = fit_anatomy_constraint_reference(anatomical_reference)
    # Keep temporal evidence immutable across camera/contact/anatomy variants.
    temporal_reference = reference.copy()
    # Match the final renderer's immutable before-processing spike evidence.
    # Support projection may change the working reference; it must not turn a
    # newly introduced touchdown spike into the accepted temporal baseline.
    spike_reference = np.asarray([
        [(frame.get('sourceJoints') or frame['joints']).get(name, frame['joints'][name])
         for name in names]
        for frame in frames], dtype=float)
    pinned = contact_mask(payload, names, len(frames))
    if pinned is None:
        return payload, {**report, 'reason': 'unrepresented_heel_contact'}
    source_contact_pinned = pinned.copy()
    foot_contact_indices = [names.index(name) for name in
                            ('left_ankle', 'left_foot', 'right_ankle', 'right_foot')
                            if name in names]
    pinned_foot_contact_owned = bool(foot_contact_indices and
                                     np.any(pinned[:, foot_contact_indices]))
    if (payload.get('postBakeForefootContactConstraint') or {}).get('requiresReconstruction'):
        return payload, {**report, 'reason': 'upstream_contacts_unresolved'}
    # Missing observed endpoints cannot be recovered by anatomy or support solves.
    coverage_constraint = _prepare_source_projection_fit_constraints(
        payload, frames, names, points, pinned, body_scale(points, names))
    coverage_gaps = _selected_interval_source_fit_coverage_gaps(payload, coverage_constraint)
    if coverage_gaps:
        return payload, {
            **report, 'reason': 'selected_source_interval_source_evidence_incomplete',
            'sourceProjectionConstraint': _source_projection_constraint_report(coverage_constraint),
            'sourceIntervalFitCoverageGaps': coverage_gaps,
            'elapsedSeconds': monotonic() - started,
        }
    root_index = names.index('pelvis')
    if all('controlledArticulationReferenceJoints' in frame for frame in frames):
        source_axes = body_orientation_axes(reference[:1], names)
        baked_axes = body_orientation_axes(points[:1], names)
        rotation = frame_basis(baked_axes[:, 1], baked_axes[:, 0])[0]@frame_basis(source_axes[:, 1], source_axes[:, 0])[0].T
        root_reference = (reference[:, root_index]-reference[0, root_index])@rotation.T+points[0, root_index]
        placement_reference = 'original_source_root_in_baked_frame'
    else:
        root_reference = points[:, root_index].copy()
        placement_reference = 'continuous_input_root'
    # Continuity screen every derived root — transformed articulation roots
    # previously bypassed smoothing and failed rootContinuity after registration.
    if not root_motion_quality(root_reference, fps, body_scale(points, names))['passed']:
        scale_for_root = body_scale(points, names)
        sigma = max(1., fps * .12)
        for step in range(6):
            root_reference = gaussian_filter1d(
                root_reference, sigma * (1. + 0.5 * step), axis=0, mode='nearest')
            if root_motion_quality(root_reference, fps, scale_for_root)['passed']:
                break
        if not root_motion_quality(root_reference, fps, scale_for_root)['passed']:
            projected = project_root_continuity_coordinates(
                np.concatenate([root_reference, np.zeros((len(root_reference), 3))], axis=1),
                fps, scale_for_root)
            root_reference = projected[:, :3]
        placement_reference = (
            'smoothed_discontinuous_source_root_in_baked_frame'
            if placement_reference == 'original_source_root_in_baked_frame'
            else 'smoothed_discontinuous_input_root'
        )
    from .contact_constraints import observed_ground_contact_mask
    ground_contacts = observed_ground_contact_mask(fit_support_evidence, names, len(frames))
    points, registration = register_contact_placement(points, pinned, root_index, fps, root_reference,
                                                     ground_contacts=ground_contacts, floor=payload.get('renderFloorY'))
    registration['reference'] = placement_reference
    if registration.get('reason') in {
            'placement_registration_did_not_converge', 'placement_registration_temporal_conflict'}:
        return payload, {**report, 'reason': registration['reason'], 'placementRegistration': registration}
    height_shift = 0.
    if not registration.get('observedGroundEpisodes'):
        points, height_shift = align_registered_contacts_above_floor(
            points, pinned, [names.index(n) for n in ('left_foot', 'right_foot')], payload.get('renderFloorY'))
    registration['floorHeightGaugeCorrectionMeters'] = height_shift
    report['placementRegistration'] = registration
    pre_contact_articulation_reference = points.copy()
    # Calibrate the material sole once from immutable, motion-space source
    # evidence before support targets are materialized; every later stage uses
    # this same rig-side pitch rather than recalibrating from edited anchors.
    from .foot_geometry import calibrated_foot_rest_pitches
    payload['footRestPitchRadians'] = calibrated_foot_rest_pitches(
        pre_contact_articulation_reference, names, fit_support_evidence,
        frame_times=[frame.get('sourceTimeSec') for frame in frames])
    fit_support_evidence['materialFootRestPitchRadians'] = deepcopy(
        payload['footRestPitchRadians'])
    rig = FixedRig(points, names)
    from .anatomical_repair import (
        ANATOMICAL_REPAIR_INPUT_REASONS,
        repair_residuals,
        repair_rig_anatomy,
        transport_equivalent_anatomical_repair,
    )
    from .support_geometry import plant_only_body_support
    repaired_reference = None
    initialized_points = None
    anatomy_initialization = {'passed': False, 'reason': 'not_run'}
    # Bilateral plant-only clips do not need a 75s anatomy floor before hard
    # plant projectors. One-sided / incomplete plant masks (e.g. some floor
    # presses) still need the fuller anatomy budget or soft LS returns.
    body_support_preview = (
        fit_support_evidence.get('bodySupport') or {})
    stationary_preview = set(body_support_preview.get('stationaryJoints') or [])
    bilateral_plant_only = (
        plant_only_body_support(body_support_preview)
        and ({'left_ankle', 'left_foot'} & stationary_preview)
        and ({'right_ankle', 'right_foot'} & stationary_preview))
    try:
        anatomy_deadline = _stage_deadline(
            started, timeout_seconds,
            fraction=(0.12 if bilateral_plant_only else ANATOMY_REPAIR_TIME_FRACTION),
            minimum_seconds=(12. if bilateral_plant_only else ANATOMY_REPAIR_MIN_SECONDS),
        )
        initialized_points, anatomy_initialization = repair_rig_anatomy(
            rig, points, deadline=anatomy_deadline, reference=anatomical_reference,
            completion_deadline=(started + timeout_seconds - reserved_polish
                                 - validation_reserve - MIN_USEFUL_FIT_SECONDS))
        report['anatomicalInitialization'] = anatomy_initialization
        if bilateral_plant_only:
            report['anatomicalInitializationPlantOnlyBudget'] = True
        source_violations, _ = repair_residuals(
            anatomical_reference, names, reference=anatomical_reference)
        if np.any(source_violations > 1e-6):
            # When the articulation reference is the working observation, one
            # projection already owns the outcome. A second identical solve only
            # burns the anatomy budget after an incomplete first pass.
            if np.allclose(points, anatomical_reference, atol=1e-10, rtol=0.):
                source_anatomy = {**anatomy_initialization, 'reusedInitialization': True,
                                  'evaluations': 0, 'residualBatchCount': 0, 'residualPointCount': 0,
                                  'warmStartedFrameCount': 0}
                repaired_reference = initialized_points if anatomy_initialization.get('passed') else None
            else:
                repaired_reference = transport_equivalent_anatomical_repair(
                    points, initialized_points, anatomical_reference, names)
                if repaired_reference is not None:
                    # Repositioning the source does not require solving its same
                    # malformed frames twice. Articulation changes cannot reuse it.
                    source_anatomy = {**anatomy_initialization, 'reusedInitialization': True,
                                      'evaluations': 0, 'residualBatchCount': 0, 'residualPointCount': 0,
                                      'warmStartedFrameCount': 0}
                else:
                    reference_rig = FixedRig(anatomical_reference, names)
                    repaired_reference, source_anatomy = repair_rig_anatomy(
                        reference_rig, anatomical_reference, deadline=anatomy_deadline,
                        reference=anatomical_reference)
            report['anatomicalSourceRepair'] = source_anatomy
            if repaired_reference is None or not source_anatomy['passed']:
                return payload, {**report, 'reason': 'anatomical_source_projection_incomplete'}
            reference = repaired_reference
    except TimeoutError:
        report['anatomicalInitializationTimedOut'] = True
        if initialized_points is None:
            initialized_points = rig.decode(rig.initial)
        anatomy_initialization = report.get('anatomicalInitialization') or {
            'passed': False, 'reason': 'time_budget'}
    report['anatomicalInitialization'] = anatomy_initialization
    from .rig_playback import rig_contact_targets
    from .contact_constraints import InfeasibleContactCorrection
    try:
        contact_targets, ankle_anchor_calibration = rig_contact_targets(
            points,names,pinned,rig.offsets,evidence=fit_support_evidence,
            floor=payload.get('renderFloorY'), rest_pitches=payload.get('footRestPitchRadians'))
    except InfeasibleContactCorrection as error:
        return payload, {**report, 'reason': 'incompatible_stationary_contact_anchors',
                         'contactConstraintError': str(error)}
    # The early coverage constraint owns only source-interval completeness. It
    # was prepared before rig-side foot-rest pitch calibration, so its material
    # heel baseline is stale for inversion. Prepare the foot-direction evidence
    # once against the registered rig, calibrated rest pitch, and exact contact
    # targets; reuse it in the fitter while these inputs remain unchanged.
    source_foot_projection_points = points.copy()
    source_foot_projection_rest_pitch = deepcopy(payload.get('footRestPitchRadians'))
    source_foot_projection_constraint = _prepare_source_projection_fit_constraints(
        payload, frames, names, points, pinned, body_scale(points, names))
    from .contact_heel_pitch import propose_source_heel_pitch
    source_heel_deadline = joint_plant_initialization_deadline(
        started, timeout_seconds, polish_reserve_seconds=reserved_polish,
        validation_reserve_seconds=validation_reserve)
    try:
        desired_world_foot_directions, source_heel_initialization = propose_source_heel_pitch(
            rig, rig.initial.copy(), payload, source_foot_projection_constraint, pinned, fps,
            deadline=source_heel_deadline, contact_targets=contact_targets)
    except TimeoutError:
        return payload, {**report, 'reason': 'source_heel_direction_timed_out',
                         'sourceHeelDirectionTimedOut': True,
                         'elapsedSeconds': monotonic() - started}
    pitch_authority_mask_by_side = {
        side: np.asarray(mask, dtype=bool) for side, mask in (
            source_heel_initialization.get('pitchAuthorityMaskBySide') or {}).items()
    }
    pitch_trajectory_mask_by_side = {
        side: np.asarray(mask, dtype=bool) for side, mask in (
            source_heel_initialization.get('pitchTrajectoryMaskBySide') or {}).items()
    }
    report['sourceHeelPitchInitialization'] = {
        key: source_heel_initialization.get(key)
        for key in ('available', 'passed', 'method', 'eventCount',
                    'inversionFailureCount', 'inversionFailures', 'sides')
    }
    report['sourceHeelPitchInitialization'].update(
        pitchAuthorityFrameCountBySide={
            side: int(mask.sum()) for side, mask in pitch_authority_mask_by_side.items()},
        pitchTrajectoryFrameCountBySide={
            side: int(mask.sum()) for side, mask in pitch_trajectory_mask_by_side.items()},
    )
    from .joint_plant_initialization import (
        contact_conditioned_articulation_reference,
        source_conditioned_foot_direction_reference,
    )
    (support_articulation_reference, full_sole_excursion_masks,
     ankle_evidence_masks, conditioning_report) = (
        contact_conditioned_articulation_reference(
            pre_contact_articulation_reference, source_contact_pinned,
            contact_targets, names, fit_support_evidence,
            [frame.get('sourceTimeSec') for frame in frames],
        )
    )
    support_articulation_reference, source_direction_reference_counts = (
        source_conditioned_foot_direction_reference(
            support_articulation_reference, source_contact_pinned, names,
            desired_world_foot_directions, pitch_trajectory_mask_by_side)
    )
    conditioning_report['sourceTimedFootDirectionReferenceFrameCountBySide'] = (
        source_direction_reference_counts)
    report['supportArticulationReference'] = conditioning_report
    unresolved_source_contact_sides = []
    for side, details in (conditioning_report.get('sides') or {}).items():
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        if (details.get('reason') == 'source_patch_clock_unresolved'
                and np.any(source_contact_pinned[:, ankle] & source_contact_pinned[:, toe])):
            unresolved_source_contact_sides.append(side)
    if unresolved_source_contact_sides:
        return payload, {
            **report, 'reason': 'source_support_contact_clock_unresolved',
            'unresolvedSides': unresolved_source_contact_sides,
            'elapsedSeconds': monotonic() - started,
        }
    from .equipment_constraints import calibrated_grip_constraint, grip_residual, validate_grip
    equipment = calibrated_grip_constraint(payload, points, names)
    from .support_geometry import support_evidence, calibrate_support_pose, validate_support_geometry, geometry_errors, geometry_dependencies
    body_support = support_evidence(payload)
    from .support_alignment import (alignment_features, alignment_constraint_errors, alignment_dependencies,
                                    validate_alignment, payload_alignment_reference)
    alignment_source = payload_alignment_reference(payload)
    if alignment_source is None:
        # Preserve valid source structure, not a malformed relationship that
        # the preceding anatomical projection has already had to repair.
        alignment_source = (initialized_points if anatomy_initialization.get('sourceViolations') else points).copy()
    source_alignment = alignment_features(alignment_source, names, body_support)
    support_range_reference = initialized_points.copy()
    plant_only = not body_support.get('required')

    def run_joint_plant_initializer(initialization_coordinates, stage_started):
        strategy = 'bounded_joint_root_and_closed_chain_legs'
        report['supportInitializationStrategy'] = strategy
        plant_deadline = joint_plant_initialization_deadline(
            started, timeout_seconds, polish_reserve_seconds=reserved_polish,
            validation_reserve_seconds=validation_reserve)
        if plant_deadline <= monotonic():
            report['supportInitializationTimedOut'] = True
            report['supportInitializationSeconds'] = monotonic() - stage_started
            return None, 'timed_out'
        from .joint_plant_initialization import initialize_joint_plant_coordinates
        try:
            initialized_coordinates, initialization_report = initialize_joint_plant_coordinates(
                rig, initialization_coordinates, pinned, contact_targets,
                articulation_reference=support_articulation_reference,
                fps=fps, cyclic=bool((payload.get('loop') or {}).get('enabled')),
                deadline=plant_deadline,
                desired_world_foot_directions=desired_world_foot_directions,
                pitch_authority_mask_by_side=pitch_authority_mask_by_side,
                pitch_trajectory_mask_by_side=pitch_trajectory_mask_by_side,
            )
        except TimeoutError:
            report['supportInitializationTimedOut'] = True
            report['supportInitializationSeconds'] = monotonic() - stage_started
            return None, 'timed_out'
        report['supportInitializationSolver'] = initialization_report
        report['supportInitializationSeconds'] = monotonic() - stage_started
        if initialized_coordinates is None:
            return None, 'infeasible'
        return initialized_coordinates, None

    def record_support_articulation_guard(initialized):
        regressions = (
            support_initialization_articulation_regressions(
                support_articulation_reference, initialized, names, fps=fps,
                ankle_excursion_masks=full_sole_excursion_masks,
                ankle_evidence_masks=ankle_evidence_masks)
            if pinned_foot_contact_owned else [])
        report['supportInitializationArticulationGuard'] = {
            'passed': not bool(regressions),
            'reference': 'source_shin_with_observed_full_sole_foot_vector',
            'regressions': regressions,
        }
        return not bool(regressions)

    if not body_support.get('required') and pinned_foot_contact_owned:
        # Timed foot contacts still need root/leg initialization when no torso
        # support plane is required; otherwise they enter the soft fit unplanted.
        support_started = monotonic()
        initialized_coordinates, failure = run_joint_plant_initializer(
            rig.initial.copy(), support_started)
        if failure:
            reason = ('support_initialization_timed_out' if failure == 'timed_out'
                      else 'support_initialization_joint_plant_infeasible')
            return payload, {**report, 'reason': reason,
                             'elapsedSeconds': monotonic() - started}
        rig.initial[:] = initialized_coordinates
        initialized_points = rig.decode(rig.initial)
        report['supportInitializationAdmission'] = 'timed_foot_contacts_without_body_support'
        if not record_support_articulation_guard(initialized_points):
            # Feasible contact seeds may need the main fit's free knee planes;
            # the immutable source reference and final articulation gate still apply.
            report['supportInitializationArticulationGuard']['needsArticulationRefinement'] = True
    if body_support.get('required'):
        support_started = monotonic()
        from .support_geometry import plant_only_body_support
        plant_only = plant_only_body_support(body_support)
        # A static body-pose solve has no objective to preserve foot heading.
        # For plant-only clips, derive support from the registered source
        # contact evidence and let the bounded root/leg initializer solve it.
        # Keep torso/body support on its existing calibrated-pose path.
        support_key = None if plant_only else _support_cache_key(body_support, points, names)
        reused_pose = (
            not plant_only
            and isinstance(shared_support, dict)
            and support_key is not None
            and shared_support.get('supportKey') == support_key
            and shared_support.get('supportPose') is not None
        )
        if plant_only:
            support_pose = points[0].copy()
            support_calibration = {
                'strategy': 'source_contact_anchor_initialization',
                'staticPoseCalibrationSkipped': True,
                'elapsedSeconds': 0.,
            }
        elif reused_pose:
            support_pose = np.asarray(shared_support['supportPose'], dtype=float)
            support_calibration = {
                **deepcopy(shared_support.get('supportCalibration') or {}),
                'reusedAcrossCycles': True,
                'elapsedSeconds': 0.,
            }
        else:
            support_pose, support_calibration = calibrate_support_pose(
                rig, points, body_support, alignment_reference=alignment_source,
                articulation_reference=anatomical_reference)
            support_calibration['elapsedSeconds'] = monotonic()-support_started
        report['supportCalibration'] = support_calibration
        if support_pose is None:
            return payload, {**report, 'reason': 'supported_body_evidence_or_geometry_unresolved'}
        for name in body_support.get('stationaryJoints', []):
            index = names.index(name)
            pinned[:, index] = True
        source_authoritative_foot_joints = set()
        for side in ('left', 'right'):
            ankle, toe = f'{side}_ankle', f'{side}_foot'
            if ankle not in names or toe not in names:
                continue
            ankle_index, toe_index = names.index(ankle), names.index(toe)
            if np.any(source_contact_pinned[:, ankle_index]
                      & source_contact_pinned[:, toe_index]):
                source_authoritative_foot_joints.update((ankle, toe))
        stationary_positions = {
            name: support_pose[names.index(name)]
            for name in body_support.get('stationaryJoints', [])
            if name not in source_authoritative_foot_joints
        }
        support_calibration['sourceContactAnchorJointsPreserved'] = sorted(
            source_authoritative_foot_joints)
        support_calibration['stationaryPositionOverrideJoints'] = (
            [] if plant_only else sorted(stationary_positions))
        pinned_foot_contact_owned = bool(foot_contact_indices and
                                         np.any(pinned[:, foot_contact_indices]))
        # Apply observed anchors before calibrating linked toe/ankle targets.
        # Replacing a toe afterward leaves an overlapping ankle stance pinned
        # to a different, physically incompatible foot segment.
        try:
            contact_targets, ankle_anchor_calibration = rig_contact_targets(
                points, names, pinned, rig.offsets,
                stationary_positions=(None if plant_only else stationary_positions),
                evidence=fit_support_evidence, floor=payload.get('renderFloorY'),
                rest_pitches=payload.get('footRestPitchRadians'))
        except InfeasibleContactCorrection as error:
            return payload, {**report, 'reason': 'incompatible_stationary_contact_anchors',
                             'contactConstraintError': str(error)}
        (support_articulation_reference, full_sole_excursion_masks,
         ankle_evidence_masks, conditioning_report) = (
            contact_conditioned_articulation_reference(
                pre_contact_articulation_reference, source_contact_pinned,
                contact_targets, names, fit_support_evidence,
                [frame.get('sourceTimeSec') for frame in frames],
            )
        )
        report['supportArticulationReference'] = conditioning_report
        from .support_geometry import initialize_supported_motion
        # Reuse compatible static support calibration, never another interval's
        # trajectory. Resizing a full-clip rig to a crop stretches its movement
        # phases and then makes those altered poses the articulation reference.
        if plant_only:
            # Use registered source coordinates as the solver baseline. A
            # framewise shift toward static supportPose is an unbounded second
            # root correction outside the joint solver's contact/temporal
            # constraints; the solver owns the complete XYZ adjustment.
            initialization_coordinates = rig.initial.copy()
            if np.any(pinned):
                initialized_coordinates, failure = run_joint_plant_initializer(
                    initialization_coordinates, support_started)
                if failure:
                    reason = ('support_initialization_timed_out' if failure == 'timed_out'
                              else 'support_initialization_joint_plant_infeasible')
                    return payload, {**report, 'reason': reason,
                                     'elapsedSeconds': monotonic() - started}
                initialization_coordinates = initialized_coordinates
            rig.initial[:] = initialization_coordinates
            initialized_points = rig.decode(rig.initial)
            report['supportInitializationSeconds'] = monotonic() - support_started
            report['supportInitializationStrategy'] = 'bounded_joint_root_and_closed_chain_legs'
            support_calibration['strategy'] = 'bounded_joint_root_and_closed_chain_legs'
        else:
            # Support projection is LS-heavy and scales with frames × evals. A flat
            # 90s ceiling aborted finishable 129-frame cold inits (~146s). Scale the
            # minimum with measured cost, capped only by outer budget minus solve room.
            projection_evals = SUPPORT_INIT_COLD_EVALUATIONS
            support_cost = (SUPPORT_INIT_SECONDS_PER_FRAME_EVAL
                            * float(len(points)) * float(projection_evals))
            solve_reserve = max(
                SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
                SUPPORT_INIT_SOLVE_RESERVE_FRACTION * float(timeout_seconds),
            )
            support_min = max(SUPPORT_INIT_MIN_SECONDS, support_cost)
            support_min = min(
                support_min,
                max(SUPPORT_INIT_MIN_SECONDS, float(timeout_seconds) - solve_reserve),
            )
            support_deadline = _stage_deadline(
                started, timeout_seconds,
                fraction=SUPPORT_INIT_TIME_FRACTION,
                minimum_seconds=support_min,
            )
            try:
                initialized_points = initialize_supported_motion(
                    rig, points, body_support, support_pose, support_calibration,
                    support_deadline, fps=fps, alignment_reference=alignment_source,
                    pinned=pinned, contact_targets=contact_targets, equipment=equipment,
                    max_evaluations=projection_evals, articulation_reference=anatomical_reference)
                report['supportInitializationSeconds'] = monotonic()-support_started
                report['supportInitializationStrategy'] = 'supported_motion_ls'
            except TimeoutError:
                report['supportInitializationSeconds'] = monotonic()-support_started
                report['supportInitializationTimedOut'] = True
                report['supportInitializationStrategy'] = 'supported_motion_ls'
                # Watchdog ends this stage's LS, not the fit. Keep the last
                # placement and let the main solve / plant projection judge it.
                initialized_points = rig.decode(rig.initial)
        if not record_support_articulation_guard(initialized_points):
            return payload, {
                **report,
                'reason': 'support_initialization_articulation_conflict',
                'elapsedSeconds': monotonic() - started,
            }
        if isinstance(shared_support, dict) and support_key is not None:
            shared_support['supportKey'] = support_key
            shared_support['supportPose'] = np.asarray(support_pose, dtype=float).copy()
            shared_support['supportCalibration'] = deepcopy(support_calibration)
        report['supportReferenceGeometry'] = validate_support_geometry(payload, initialized_points, names)
        report['supportReferenceAlignment'] = validate_alignment(initialized_points, alignment_source, names, body_support)
        report['supportReferenceEquipment'] = validate_grip(initialized_points, names, equipment)
        reference_contact_error = float(np.max(
            np.linalg.norm((initialized_points-contact_targets)[pinned], axis=-1), initial=0.))
        report['supportReferenceContacts'] = {
            'passed': support_reference_contacts_pass(reference_contact_error),
            'maximumErrorMeters': reference_contact_error,
            'toleranceMeters': SUPPORT_REFERENCE_CONTACT_LIMIT_METERS,
        }
        reference_errors, reference_labels = repair_residuals(
            initialized_points, names, reference=anatomical_reference)
        failed_reference_features = np.max(reference_errors, axis=0) > 1e-6
        report['supportReferenceAnatomy'] = {
            'passed': not bool(np.any(failed_reference_features)),
            'violations': [reference_labels[j] for j in np.flatnonzero(failed_reference_features)],
            'residualByViolation': {reference_labels[j]: float(np.max(reference_errors[:, j]))
                                    for j in np.flatnonzero(failed_reference_features)}}
        support_gates = (
            'supportReferenceGeometry', 'supportReferenceAlignment', 'supportReferenceAnatomy',
            'supportReferenceEquipment', 'supportReferenceContacts')
        # Geometry/alignment describe whether local support projection is safe.
        # Equipment has a separate grip projector later; it must not prevent
        # anatomy/contact repair and thereby cause root-continuity rejection.
        support_frame_ok = support_reference_can_be_polished(report)
        needs_anatomy = not report['supportReferenceAnatomy']['passed']
        if (support_frame_ok
                and (needs_anatomy or not report['supportReferenceContacts']['passed'])
                and monotonic() < started + timeout_seconds):
            anatomy_budget = max(6., 0.15 * float(timeout_seconds))
            # Plant-only clips already paid for keyframe plants; anatomy polish
            # must not re-burn a soft-LS-sized window before the deferred play pass.
            if report.get('supportInitializationStrategy') == 'plant_projection':
                anatomy_budget = min(8., anatomy_budget)
            anatomy_deadline = min(
                started + timeout_seconds,
                monotonic() + anatomy_budget,
            )
            try:
                if needs_anatomy:
                    initialized_points, support_anatomy_polish = repair_rig_anatomy(
                        rig, initialized_points, deadline=anatomy_deadline,
                        reference=anatomical_reference)
                    report['supportReferenceAnatomyPolish'] = support_anatomy_polish
                    reference_contact_error = float(np.max(
                        np.linalg.norm((initialized_points - contact_targets)[pinned], axis=-1),
                        initial=0.))
                if not support_reference_contacts_pass(reference_contact_error):
                    # Anatomy repair can leave planted joints a few millimeters
                    # off; project only when the post-repair pose still misses
                    # the support-reference contact gate.
                    # Plant-only already deferred plant-chain TRF to the main fit —
                    # another full-clip plant here reintroduces the same stall.
                    if report.get('supportInitializationStrategy') == (
                            'bounded_joint_root_and_closed_chain_legs'):
                        report['supportReferenceContactPolish'] = {
                            'applied': False,
                            'reason': 'preserve_initializer_articulation',
                            'maximumErrorMetersBefore': reference_contact_error,
                        }
                    else:
                        if report.get('supportInitializationStrategy') == 'plant_projection':
                            planted = project_contact_root_translation(
                                rig.initial, rig, pinned, contact_targets,
                                passes=3, smooth_fps=fps)
                        else:
                            planted = project_contact_plant_coordinates(
                                rig.initial, rig, pinned, contact_targets, max_nfev=40)
                        rig.initial[:] = planted
                        initialized_points = rig.decode(planted)
                        report['supportReferenceContactPolish'] = {
                            'applied': True,
                            'maximumErrorMetersBefore': reference_contact_error,
                        }
                    projected_errors, _ = repair_residuals(
                        initialized_points, names, reference=anatomical_reference)
                    if np.any(projected_errors > 1e-6):
                        try:
                            initialized_points, anatomy_repolish = repair_rig_anatomy(
                                rig, initialized_points, deadline=anatomy_deadline,
                                reference=anatomical_reference)
                            report['supportReferenceAnatomyRepolish'] = anatomy_repolish
                        except TimeoutError:
                            report['supportReferenceAnatomyRepolish'] = {
                                'passed': False, 'reason': 'time_budget'}
                reference_errors, reference_labels = repair_residuals(
                    initialized_points, names, reference=anatomical_reference)
                failed_reference_features = np.max(reference_errors, axis=0) > 1e-6
                report['supportReferenceAnatomy'] = {
                    'passed': not bool(np.any(failed_reference_features)),
                    'violations': [reference_labels[j] for j in np.flatnonzero(failed_reference_features)],
                    'residualByViolation': {
                        reference_labels[j]: float(np.max(reference_errors[:, j]))
                        for j in np.flatnonzero(failed_reference_features)},
                }
                report['supportReferenceGeometry'] = validate_support_geometry(
                    payload, initialized_points, names)
                report['supportReferenceAlignment'] = validate_alignment(
                    initialized_points, alignment_source, names, body_support)
                report['supportReferenceEquipment'] = validate_grip(initialized_points, names, equipment)
                reference_contact_error = float(np.max(
                    np.linalg.norm((initialized_points - contact_targets)[pinned], axis=-1), initial=0.))
                report['supportReferenceContacts'] = {
                    'passed': support_reference_contacts_pass(reference_contact_error),
                    'maximumErrorMeters': reference_contact_error,
                    'toleranceMeters': SUPPORT_REFERENCE_CONTACT_LIMIT_METERS,
                }
                if report.get('supportReferenceContactPolish'):
                    report['supportReferenceContactPolish']['maximumErrorMetersAfter'] = (
                        reference_contact_error)
            except TimeoutError:
                report['supportReferenceAnatomyPolish'] = {'passed': False, 'reason': 'time_budget'}
        if (report.get('supportInitializationTimedOut')
                and support_reference_grossly_invalid(report)):
            failed_support_gates = {
                key: bool(report[key].get('passed')) for key in support_gates
            }
            report['supportReferenceEarlyReject'] = {
                'reason': 'gross_failure_after_support_initialization_timeout',
                'toleranceMultiplier': 5.,
            }
            report['checks'] = failed_support_gates
            return payload, {**report, 'applied': False, 'reason': 'fit_validation_failed'}
        if (report.get('supportInitializationStrategy') ==
                'bounded_joint_root_and_closed_chain_legs'
                and not report['supportReferenceContacts']['passed']):
            # The joint initializer promises a feasible contact reference. Do
            # not defer its unresolved pins to the main fit, which would trade
            # source articulation against an unreachable support target.
            return payload, {
                **report,
                'applied': False,
                'reason': 'support_reference_projection_incomplete',
            }
        if not all(report[key]['passed'] for key in support_gates):
            if support_reference_equipment_can_be_deferred(
                    report, report.get('supportInitializationStrategy')):
                report['supportReferenceEquipmentDeferred'] = True
            elif (report.get('supportInitializationTimedOut')
                    or report.get('supportInitializationStrategy') == 'plant_projection'):
                # Light plant init / timed-out torso LS leave near-miss contacts for
                # the main trajectory fit and playback plant projection to finish.
                report['supportReferenceContinuedAfterTimeout'] = True
            else:
                return payload, {**report, 'reason': 'support_reference_projection_incomplete'}
        # Supported reference must itself satisfy rootContinuity. Otherwise the
        # main solve prior and Stage-C repairs fight planted contacts/anatomy.
        support_scale = body_scale(initialized_points, names)
        if not root_motion_quality(initialized_points[:, root_index], fps, support_scale)['passed']:
            continuous = project_root_continuity_coordinates(
                rig.initial.copy(), fps, support_scale)
            if np.any(pinned):
                root_plant_deadline = monotonic() + min(
                    8., max(2., 0.05 * float(timeout_seconds)))
                continuous = project_contact_plant_coordinates(
                    continuous, rig, pinned, contact_targets, max_nfev=20,
                    freeze_root=True, deadline=root_plant_deadline)
            candidate_points = rig.decode(continuous)
            contact_err = float(np.max(
                np.linalg.norm((candidate_points - contact_targets)[pinned], axis=-1), initial=0.))
            anatomy_errors, _ = repair_residuals(
                candidate_points, names, reference=anatomical_reference)
            anatomy_ok = not bool(np.any(anatomy_errors > 1e-6))
            support_ok = validate_support_geometry(payload, candidate_points, names)['passed']
            root_ok = root_motion_quality(
                candidate_points[:, root_index], fps, support_scale)['passed']
            if (support_reference_contacts_pass(contact_err)
                    and anatomy_ok and support_ok and root_ok):
                rig.initial[:] = continuous
                initialized_points = candidate_points
                report['supportReferenceRootContinuity'] = {'applied': True, 'passed': True}
                report['supportReferenceGeometry'] = validate_support_geometry(
                    payload, initialized_points, names)
                report['supportReferenceContacts'] = {
                    'passed': True,
                    'maximumErrorMeters': contact_err,
                    'toleranceMeters': SUPPORT_REFERENCE_CONTACT_LIMIT_METERS,
                }
            else:
                report['supportReferenceRootContinuity'] = {
                    'applied': False, 'passed': False,
                    'contactErrorMeters': contact_err,
                    'anatomyPassed': anatomy_ok, 'supportPassed': support_ok,
                    'rootPassed': root_ok,
                }
                # A supported fit's temporal prior and later polish assume the
                # reference already clears root continuity. Continuing from a
                # failed joint root/contact repair makes those stages optimize
                # against contradictory support geometry (and burns the fit
                # budget without a feasible starting reference).
                return payload, {
                    **report,
                    'applied': False,
                    'reason': 'support_reference_projection_incomplete',
                }
        # Explicit support owns these corrections. Keep the original temporal
        # evidence unchanged, but compare articulation to the feasible supported
        # pose rather than requiring reproduction of the unsupported geometry.
        reference = initialized_points.copy()
        fit_anatomy_reference = fit_anatomy_constraint_reference(
            anatomical_reference, reference)
        # Estimated rigid-pair spacing must follow the supported geometry. A
        # pre-support reconstruction distance becomes an unreachable target once
        # support rewrites hand placement, and the main solve then fails equipment.
        if equipment.get('handRelationship') == 'rigid_pair' and equipment.get('distanceSource') != 'explicit':
            equipment = calibrated_grip_constraint(
                {**payload, 'equipmentConstraints': {
                    **(payload.get('equipmentConstraints') or {}),
                    'handRelationship': 'rigid_pair', 'distanceMeters': None}},
                reference, names)
            report['supportReferenceEquipment'] = validate_grip(reference, names, equipment)
        # Reconstruction often leaves tens of centimeters of rigid-pair variance.
        # Hard-project arm DOFs onto the calibrated spacing before the main solve.
        if (equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
                and not report['supportReferenceEquipment']['passed']
                and monotonic() < started + timeout_seconds):
            grip_budget = min(12., max(2., 0.08 * float(timeout_seconds)))
            grip_deadline = min(started + timeout_seconds - 30., monotonic() + grip_budget)
            before_grip_coordinates = rig.initial.copy()
            gripped = project_rigid_pair_grip_coordinates(
                rig.initial, rig, names, equipment, pinned=pinned, max_nfev=25,
                deadline=grip_deadline)
            if (np.any(pinned)
                    and report.get('supportInitializationStrategy') !=
                    'bounded_joint_root_and_closed_chain_legs'):
                # Distal arm projection should not move plants; re-snap anyway in
                # case collar/shoulder coupling nudged a foot sample.
                gripped = project_contact_root_translation(
                    gripped, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = min(
                    started + timeout_seconds - 30.,
                    monotonic() + min(6., max(2., 0.05 * float(timeout_seconds))))
                if plant_deadline > monotonic():
                    gripped = project_contact_plant_coordinates(
                        gripped, rig, pinned, contact_targets, max_nfev=16,
                        preserve_root_posture=(report.get(
                            'supportInitializationStrategy') == 'plant_projection'),
                        deadline=plant_deadline)
            gripped_reference = rig.decode(gripped)
            grip_projection_metrics = supported_reference_projection_metrics(
                gripped_reference,
                payload=payload,
                names=names,
                alignment_reference=alignment_source,
                anatomy_reference=anatomical_reference,
                body_support=body_support,
                equipment=equipment,
                pinned=pinned,
                contact_targets=contact_targets,
            )
            report['supportReferenceGripProjection'] = {
                'applied': grip_projection_metrics['passed'],
                'passed': grip_projection_metrics['passed'],
                'rejectionReasons': grip_projection_metrics['rejectionReasons'],
                'maximumSpacingErrorMeters': grip_projection_metrics['equipment'].get(
                    'maximumSpacingErrorMeters'),
                **grip_projection_metrics,
            }
            if grip_projection_metrics['passed']:
                rig.initial[:] = gripped
                reference = gripped_reference
                fit_anatomy_reference = fit_anatomy_constraint_reference(
                    anatomical_reference, reference)
                initialized_points = reference
                report['supportReferenceAnatomy'] = grip_projection_metrics['anatomy']
                report['supportReferenceGeometry'] = grip_projection_metrics['geometry']
                report['supportReferenceAlignment'] = grip_projection_metrics['alignment']
                report['supportReferenceEquipment'] = grip_projection_metrics['equipment']
                report['supportReferenceContacts'] = grip_projection_metrics['contacts']
            else:
                rig.initial[:] = before_grip_coordinates
        if (report.get('supportInitializationStrategy') ==
                'bounded_joint_root_and_closed_chain_legs'
                and not report['supportReferenceEquipment'].get('passed')):
            return payload, {
                **report,
                'applied': False,
                'reason': 'support_reference_equipment_projection_incomplete',
            }
        # One playback-plant pass after keyframe plants (+ optional grip). Soft LS
        # cannot close mid-sample bows; do not pay for this twice around grip.
        if (report.get('supportInitializationStrategy') == 'plant_projection'
                and np.any(pinned)
                and monotonic() < started + timeout_seconds):
            play_budget = min(14., max(5., 0.08 * float(timeout_seconds)))
            play_deadline = min(
                started + timeout_seconds - 25.,
                monotonic() + play_budget)
            if play_deadline > monotonic() and _playback_failing_intervals(
                    rig.initial, rig, pinned, contact_targets, cyclic=cyclic_preview,
                    floor=payload.get('renderFloorY')):
                before_playback_coordinates = rig.initial.copy()
                projected_coordinates = project_interval_playback_plants(
                    rig.initial, rig, pinned, contact_targets,
                    cyclic=cyclic_preview, floor=payload.get('renderFloorY'),
                    max_nfev=16, deadline=play_deadline, spike_reference=spike_reference)
                projected_reference = rig.decode(projected_coordinates)
                playback_projection_metrics = supported_reference_projection_metrics(
                    projected_reference,
                    payload=payload,
                    names=names,
                    alignment_reference=alignment_source,
                    anatomy_reference=anatomical_reference,
                    body_support=body_support,
                    equipment=equipment,
                    pinned=pinned,
                    contact_targets=contact_targets,
                )
                report['supportPlaybackPlantProjection'] = {
                    'applied': playback_projection_metrics['passed'],
                    **playback_projection_metrics,
                }
                if playback_projection_metrics['passed']:
                    rig.initial[:] = projected_coordinates
                    reference = projected_reference
                    initialized_points = reference
                    report['supportReferenceAnatomy'] = playback_projection_metrics['anatomy']
                    report['supportReferenceGeometry'] = playback_projection_metrics['geometry']
                    report['supportReferenceAlignment'] = playback_projection_metrics['alignment']
                    report['supportReferenceEquipment'] = playback_projection_metrics['equipment']
                    report['supportReferenceContacts'] = playback_projection_metrics['contacts']
                    report['supportPlaybackPlantsApplied'] = True
                else:
                    rig.initial[:] = before_playback_coordinates
                    report['supportPlaybackPlantsApplied'] = False
            else:
                report['supportPlaybackPlantsApplied'] = False
        if pinned_foot_contact_owned:
            post_polish_regressions = support_initialization_articulation_regressions(
                support_articulation_reference, initialized_points, names, fps=fps,
                ankle_excursion_masks=full_sole_excursion_masks,
                ankle_evidence_masks=ankle_evidence_masks)
            report['supportInitializationArticulationGuard'] = {
                'passed': not bool(post_polish_regressions),
                'reference': 'source_shin_with_observed_full_sole_foot_vector',
                'checkpoint': 'after_support_reference_polish',
                'regressions': post_polish_regressions,
            }
            if post_polish_regressions:
                return payload, {
                    **report,
                    'reason': 'support_initialization_articulation_conflict',
                    'elapsedSeconds': monotonic() - started,
                }
        report['supportReferenceCorrection'] = {'source': body_support.get('source'),
            'maximumCorrectionMeters': float(np.max(np.linalg.norm(reference-points, axis=-1)))}
    # Under support, jointRange accepts articulation excursion (not world-space
    # spans that also encode placement). Fit the same metric so soft targets
    # cannot quietly shrink free-chain ROM below the acceptance floor.
    support_articulation_tracks_by_label = {}
    timed_foot_articulation_tracks = ()
    if body_support.get('required') or pinned_foot_contact_owned:
        from .support_geometry import moving_support_articulations
    if body_support.get('required'):
        for track in moving_support_articulations(
            support_range_reference, names, body_support, support_corrected_points=reference,
            constraint_endpoints=[names[j] for j in np.flatnonzero(np.any(pinned, axis=0))]):
            support_articulation_tracks_by_label[track[0]] = track
    if pinned_foot_contact_owned:
        # Timed foot pins still move the leg chain even when no torso-level
        # bodySupport model is present. On observed full-sole rows, use the
        # contact-conditioned foot vector with the immutable source shin; raw
        # angles remain authoritative outside those timed rows.
        timed_foot_articulation_tracks = tuple(
            track for track in moving_support_articulations(
                support_articulation_reference, names, {})
            if track[0].endswith(('_knee', '_ankle'))
        )
        for track in timed_foot_articulation_tracks:
            support_articulation_tracks_by_label[track[0]] = track
    support_articulation_tracks = tuple(support_articulation_tracks_by_label.values())
    support_ankle_episode_tracks = support_range_episode_tracks(
        support_articulation_reference, names,
        full_sole_excursion_masks, ankle_evidence_masks,
    ) if pinned_foot_contact_owned else ()
    support_range_fit_tracks = support_articulation_tracks + support_ankle_episode_tracks
    height_only_mask = vertical_only_contact_mask(
        fit_support_evidence, names, len(frames),
    ) & ~pinned
    height_only_targets_mask, height_only_targets = vertical_only_contact_targets(
        reference, fit_support_evidence, names, floor=payload.get('renderFloorY'),
    )
    height_only_mask &= height_only_targets_mask
    report['heightOnlyContactConstraint'] = {
        'available': bool(np.any(height_only_mask)),
        'frameJointCount': int(np.count_nonzero(height_only_mask)),
        'axis': 'floor_normal_y',
    }
    # Initializers evaluate guarded geometry and can leave rotations far beyond
    # the socket boundary behind that guard. Commit the identical decoded pose
    # to coordinates before raw-geometry fitting, interpolation, and the rotation
    # prior are initialized; otherwise the main solve must undo hidden damage.
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    rig.project_neck_attachment(
        maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
    registered_root = rig.decode(rig.initial)[:, rig.root].copy()
    target, _, evidence = controlled_target(rig.decode(rig.initial), names, fps)
    settling_basis = settling_hold_basis(temporal_reference, reference, body_support)
    _, holds, _ = controlled_target(settling_basis, names, fps)
    # Shared basis and limits keep fit validation and playback-grip repair on
    # the same shake authority. Previously the playback repair could fix the
    # interpolated rigid grip while nudging wrist/hand acceleration just past
    # the validator's limit.
    shake_basis = settling_basis if body_support.get('required') else temporal_reference
    acceleration_before = np.sqrt(np.mean(
        np.diff(shake_basis, n=2, axis=0) ** 2, axis=(0, 2)))
    shake_limits = np.maximum(acceleration_before * 1.2, .003 * (30. / fps) ** 2)
    # Same authority as settling: when support rewrites geometry, its temporal
    # content — not the unsupported source — defines the reachable jerk floor.
    jerk_basis = settling_basis if body_support.get('required') else temporal_reference
    jerk_before = float(np.sqrt(np.mean(np.diff(jerk_basis, n=3, axis=0)**2)))
    jerk_limit = jerk_before * 1.05 + 1e-7
    jerk_fit_target = world_jerk_fit_target(jerk_before, jerk_limit)
    hold_weights = np.minimum(holds[1:], holds[:-1])[:, :, None]
    settling_before = weighted_settling_speed(settling_basis, names, fps, hold_weights)
    settling_limit = max(settling_before * 1.1, .003)
    report['temporalReference'] = 'source_articulation_before_repairs'
    report['settlingReference'] = (
        'supported_reference' if body_support.get('required') else 'source_articulation_before_repairs')
    report['settlingLimit'] = settling_limit
    target, _, placement_report = contact_consistent_target(
        target, pinned, contact_targets, root_index=rig.root,
        root_reference=registered_root)
    evidence['placement'] = placement_report
    evidence['placementRegistration'] = registration
    # Distinguish the three ways a fit can become unsatisfiable: a bent input
    # skeleton, a target that is anatomically impossible for the rig, or
    # anchors that conflict with the pose. Without these numbers a failed fit
    # cannot be root-caused from its report alone.
    initial_points = rig.decode(rig.initial)
    from .smpl_joint_names import SMPL_JOINT_NAMES as _SMPL_NAMES, SMPL_JOINT_PARENTS as _SMPL_PARENTS
    _index = {name: position for position, name in enumerate(names)}
    _bones = [
        (child, _SMPL_NAMES[parent])
        for child, parent in zip(_SMPL_NAMES, _SMPL_PARENTS)
        if 0 <= parent < len(_SMPL_NAMES) and child in names and _SMPL_NAMES[parent] in names
    ]

    def _bone_medians(track):
        return {
            f'{child}<-{parent}': float(
                np.median(np.linalg.norm(
                    track[:, _index[child]] - track[:, _index[parent]], axis=-1)))
            for child, parent in _bones
        }

    initial_bones = _bone_medians(initial_points)
    target_bones = _bone_medians(target)
    input_bone_variation = max(
        (float(np.ptp(np.linalg.norm(
            initial_points[:, names.index(child)] - initial_points[:, names.index(parent)],
            axis=-1)))
         for child, parent in _bones),
        default=0.0)
    target_mismatch = max(
        (abs(target_bones[bone] - initial_bones[bone])
         for bone in target_bones if bone in initial_bones),
        default=0.0)
    worst_bone = (
        max(target_bones, key=lambda bone: abs(target_bones[bone] - initial_bones.get(bone, 0.0)))
        if target_bones else None)
    evidence['fitInputEvidence'] = {
        'maximumInputBoneVariationMeters': round(float(input_bone_variation), 6),
        'maximumTargetBoneMismatchMeters': round(float(target_mismatch), 6),
        'worstTargetBone': worst_bone,
    }
    if target_mismatch > FIT_INPUT_MAX_TARGET_BONE_MISMATCH_METERS:
        # Feasibility by construction: smoothing and deviation attenuation
        # bend the target's bones, and the rig cannot honor bone lengths it
        # does not have — an infeasible target makes the whole solve
        # unreachable no matter how long it runs. Re-impose the rig's median
        # bone lengths on the target (parents first) and re-seat the contact
        # anchors, so the solve starts from a provably feasible target.
        reference_lengths = {
            bone: length for bone, length in initial_bones.items()
        }
        target = project_track_to_reference_bone_lengths(
            target, _index, _bones, reference_lengths
        )
        target, _, placement_report = contact_consistent_target(
            target, pinned, contact_targets, root_index=rig.root,
            root_reference=registered_root
        )
        evidence['placement'] = placement_report
        projected_bones = _bone_medians(target)
        projected_mismatch = max(
            (
                abs(projected_bones[bone] - initial_bones[bone])
                for bone in projected_bones
                if bone in initial_bones
            ),
            default=0.0,
        )
        evidence['fitInputEvidence'].update(
            projectedToRigBones=True,
            mismatchAfterProjectionMeters=round(float(projected_mismatch), 6),
        )
    # Registration owns root placement; a second contact-average translation
    # would introduce jumps whenever the active contact set changes.
    scale = body_scale(points, names)
    count, joints, _ = points.shape
    cyclic = bool((payload.get("loop") or {}).get("enabled"))
    source_projection_inputs_unchanged = (
        np.array_equal(points, source_foot_projection_points)
        and payload.get('footRestPitchRadians') == source_foot_projection_rest_pitch
    )
    if source_projection_inputs_unchanged:
        source_projection_constraint = source_foot_projection_constraint
        report['sourceFootProjectionConstraintReused'] = True
    else:
        source_projection_constraint = _prepare_source_projection_fit_constraints(
            payload, frames, names, points, pinned, scale,
        )
        report['sourceFootProjectionConstraintReused'] = False
    # Independently observed foot phase supersedes its reconstructed ankle
    # phase locally. Missing observations retain the reconstruction prior.
    source_foot_coverage = {}
    for observation in source_projection_constraint.get('sourceFootRayObservations', []):
        label = names[observation['ankleJointIndex']]
        covered = source_foot_coverage.setdefault(label, np.zeros(count))
        if observation['alpha'] < 1.:
            covered[observation['leftFrame']] = 1.
        if observation['alpha'] > 0.:
            covered[observation['rightFrame']] = 1.
    source_foot_phase_coverage = _source_foot_phase_frame_coverage(
        source_projection_constraint, names, count,
    )
    source_foot_direction_authority = {
        side: np.asarray(pitch_authority_mask_by_side.get(side, np.zeros(count)), dtype=bool)
        for side in ('left', 'right')
    }
    source_foot_direction_targets = np.asarray(
        desired_world_foot_directions, dtype=float).copy()
    if source_foot_direction_targets.shape != (count, 2, 3):
        raise ValueError('source heel pitch directions must match the fitted frame count')
    source_foot_direction_targets /= np.maximum(
        np.linalg.norm(source_foot_direction_targets, axis=2, keepdims=True), 1e-12)
    source_foot_direction_targets[~np.isfinite(source_foot_direction_targets)] = 0.
    source_foot_direction_masks = np.column_stack([
        source_foot_direction_authority[side] for side in ('left', 'right')
    ])
    source_foot_direction_trajectory_masks = np.column_stack([
        np.asarray(pitch_trajectory_mask_by_side.get(side, np.zeros(count)), dtype=bool)
        for side in ('left', 'right')
    ])

    def source_foot_direction_targets_at(first, last, alpha, *, authority_masks=True):
        alpha = np.asarray(alpha, dtype=float).reshape(-1)
        first = np.asarray(first, dtype=int).reshape(-1)
        last = np.asarray(last, dtype=int).reshape(-1)
        targets = (source_foot_direction_targets[first] * (1. - alpha[:, None, None])
                   + source_foot_direction_targets[last] * alpha[:, None, None])
        targets /= np.maximum(np.linalg.norm(targets, axis=2, keepdims=True), 1e-12)
        fit_masks = (source_foot_direction_masks if authority_masks
                     else source_foot_direction_trajectory_masks)
        masks = fit_masks[first] & fit_masks[last]
        return targets, masks

    def source_foot_direction_residuals(candidate, targets, masks):
        residuals = np.zeros((len(candidate), 6), dtype=float)
        for side_index, side in enumerate(('left', 'right')):
            if f'{side}_ankle' not in names or f'{side}_foot' not in names:
                continue
            ankle_index, toe_index = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
            bone = candidate[:, toe_index] - candidate[:, ankle_index]
            lengths = np.linalg.norm(bone, axis=1)
            valid = np.asarray(masks[:, side_index], dtype=bool) & (lengths > 1e-9)
            unit = bone / np.maximum(lengths[:, None], 1e-12)
            residuals[valid, side_index * 3:(side_index + 1) * 3] = (
                SOURCE_FOOT_PHASE_FIT_WEIGHT * (unit[valid] - targets[valid, side_index]))
        return residuals

    # Reuse the exact initializer reference, including bounded same-anchor
    # geometric interpolation through unknown gaps. Only measured authority
    # contributes to acceptance; bounded interpolation remains a fit prior.
    source_conditioned_articulation_reference = support_articulation_reference
    report['independentFootPhaseFrames'] = {
        label: int(np.count_nonzero(covered)) for label, covered in source_foot_coverage.items()}
    report['independentHeelPhaseFramesByAnkle'] = {
        label: int(np.count_nonzero(covered))
        for label, covered in source_foot_phase_coverage.items()}
    report['sourceProjectionConstraint'] = _source_projection_constraint_report(source_projection_constraint)
    source_interval_coverage_gaps = _selected_interval_source_fit_coverage_gaps(
        payload, source_projection_constraint,
    )
    if source_interval_coverage_gaps:
        return payload, {
            **report,
            'reason': 'selected_source_interval_source_evidence_incomplete',
            'sourceIntervalFitCoverageGaps': source_interval_coverage_gaps,
            'elapsedSeconds': monotonic() - started,
        }
    contact_targets, source_anchor_adjustment = _align_shared_contact_anchors_to_source_projection(
        source_projection_constraint, pinned, contact_targets,
        ground_contacts=ground_contacts,
        rig=rig,
        body_support=body_support,
    )
    if source_anchor_adjustment['adjustedGroupCount']:
        target, _, placement_report = contact_consistent_target(
            target, pinned, contact_targets, root_index=rig.root,
            root_reference=registered_root,
        )
        evidence['placement'] = placement_report
        source_projection_constraint['anchorAdjustment'] = source_anchor_adjustment
    excursion_center, excursion_direction, excursion_minimum, excursion_active = excursion_constraints(target, rig.root, scale)
    report['sourceProjectionConstraint']['sharedAnchorAdjustment'] = source_anchor_adjustment
    specs = [(label, [names.index(n) for n in (a,b,c)], tolerance)
             for label,a,b,c,tolerance in ARTICULATIONS]
    reference_angles = np.stack([angles(*(source_conditioned_articulation_reference[:,i]
                                          for i in cols)) for _,cols,_ in specs], axis=1)
    acceleration_fit_scale, rotation_fit_scale = temporal_fit_scales(
        settling_basis if body_support.get('required') else temporal_reference, names, fps)
    source_parent, source_bend, source_hinge_sine = hinge_coordinates(reference,names)
    from .structural_refinement import _source_branch_is_temporally_supported
    branch_supported = np.ones(source_hinge_sine.shape,dtype=bool)
    for hinge in range(source_parent.shape[1]):
        track = list(zip(source_parent[:,hinge],source_bend[:,hinge]))
        branch_supported[:,hinge] = [_source_branch_is_temporally_supported(track,frame,max(1,round(fps*.1)))
                                    for frame in range(count)]
    branch_supported &= source_hinge_sine > np.sin(np.deg2rad(15.))
    tolerance = np.deg2rad([min(t, 10.)-.5 for _,_,t in specs])
    low, high = reference_angles-tolerance, reference_angles+tolerance
    for column,(label,_,_) in enumerate(specs):
        if label.endswith('_ankle'):
            low[:,column] = np.maximum(low[:,column], np.deg2rad(35.1))
            high[:,column] = np.minimum(high[:,column], np.deg2rad(164.9))
    # Every residual frame depends only on that frame's rig; temporal blocks
    # share those dependencies across adjacent frames, not the full sequence.
    from .foot_geometry import foot_scale_from_pose, material_floor_heights
    foot_rest_pitches = payload['footRestPitchRadians']
    material_foot_scale = foot_scale_from_pose(points[0], names)
    floor_pattern = rig.dependencies[1::3].copy()
    for side in foot_rest_pitches:
        floor_pattern[names.index(f'{side}_ankle')] = joint_dependencies(
            rig, (f'{side}_ankle', f'{side}_foot'))
    angle_pattern = np.stack([np.max(rig.dependencies[np.ravel([[j*3+k for k in range(3)] for j in cols])],axis=0)
                              for _,cols,_ in specs])
    timed_foot_articulation_pattern = np.stack([
        np.max(rig.dependencies[np.ravel([[j*3+k for k in range(3)] for j in cols])], axis=0)
        for _, cols, _ in timed_foot_articulation_tracks
    ]) if timed_foot_articulation_tracks else np.empty((0, rig.width))
    source_foot_direction_pattern = np.vstack([
        (np.tile(joint_dependencies(rig, (f'{side}_ankle', f'{side}_foot')),
                 (3, 1))
         if f'{side}_ankle' in names and f'{side}_foot' in names
         else np.zeros((3, rig.width)))
        for side in ('left', 'right')
    ])
    collision_pattern = np.stack([np.max(rig.dependencies[np.ravel([[names.index(n)*3+k for k in range(3)] for n in (*a,*b)])],axis=0)
                                  for _,a,b,_,_ in collision_specs(names)])
    body_dependencies = joint_dependencies(rig,('pelvis','left_hip','right_hip','neck'))
    from .physical_validation import (
        SPAN_FIT_ACTIVATION_FRACTION,
        SPAN_JOINT_PAIRS,
        SPAN_TOLERANCE_METERS,
        SPAN_TOLERANCE_RATIO,
        span_rigidity_fit_residuals,
        span_rigidity_violations,
    )
    source_span_measurements = span_rigidity_violations(reference, names)
    span_targets = {label: float(target)
                    for label, (_, target) in source_span_measurements.items()}
    span_pairs = {label: (left, right)
                  for label, left, right in SPAN_JOINT_PAIRS
                  if label in span_targets}
    if span_targets:
        report['spanStabilityConstraint'] = {
            'targetSource': 'repaired_fit_reference_median',
            'activationFractionOfValidationTolerance': SPAN_FIT_ACTIVATION_FRACTION,
            'targets': {
                label: {
                    'targetMeters': target,
                    'validationToleranceMeters': max(
                        SPAN_TOLERANCE_METERS, target * SPAN_TOLERANCE_RATIO),
                }
                for label, target in span_targets.items()
            },
        }
    span_dependencies = np.stack([
        joint_dependencies(rig, pair) for pair in span_pairs.values()
    ]) if span_pairs else np.empty((0, rig.width))
    if len(span_dependencies):
        span_dependencies[:, :3] = 0.
    head_pattern = joint_dependencies(rig,('pelvis','left_hip','right_hip','neck','head'))[None,:]
    branch_basis = joint_dependencies(rig,('pelvis','neck','left_shoulder','right_shoulder'))
    branch_pattern = np.stack([np.maximum(branch_basis,joint_dependencies(rig,(a,h,b)))
                               for label,a,h,b,_ in ARTICULATIONS if label.endswith(('_knee','_elbow'))])
    settling_pattern = np.maximum(rig.dependencies,body_dependencies[None,:])
    frame_pattern = np.vstack([rig.dependencies,rig.dependencies,rig.dependencies[1::3],
                               angle_pattern,timed_foot_articulation_pattern,
                               source_foot_direction_pattern,
                               floor_pattern,head_pattern,rotation_prior_dependencies(rig.width),collision_pattern,
                               rig.dependencies[::3],branch_pattern])
    structure_pattern = np.vstack([
        anatomical_structure_dependencies(rig, points, names), span_dependencies,
    ])
    frame_pattern = np.vstack([frame_pattern, structure_pattern])
    equipment_pattern = (joint_dependencies(rig, equipment['endpointPair'])[None, :]
                         if equipment.get('available') else np.empty((0, rig.width)))
    frame_pattern = np.vstack([frame_pattern, equipment_pattern])
    support_pattern = np.vstack([geometry_dependencies(rig, body_support), alignment_dependencies(rig, body_support)])
    frame_pattern = np.vstack([frame_pattern, support_pattern])
    from .heel_contacts import heel_contact_tracks
    heel_contacts = heel_contact_tracks(points, names, fit_support_evidence,
                                       floor=payload.get('renderFloorY'), fps=fps,
                                       rest_pitches=payload['footRestPitchRadians'])
    heel_pattern = np.vstack([
        np.tile(joint_dependencies(rig, (names[ankle], names[toe])), (3, 1))
        for ankle, toe in heel_contacts.pairs
    ]) if heel_contacts.pairs else np.empty((0, rig.width))
    frame_pattern = np.vstack([frame_pattern, heel_pattern])
    temporal_pattern = csr_matrix(rig.dependencies)
    root_pattern = csr_matrix(rig.dependencies[rig.root*3:rig.root*3+3])
    d2 = csr_matrix(np.diff(np.eye(count), n=2, axis=0))
    d3 = csr_matrix(np.diff(np.eye(count), n=3, axis=0))
    # Acceptance measures world-space differences over the observed interval.
    # Cyclic seam constraints remain separate and are checked in playback.
    world_d3 = d3.copy()
    d1 = csr_matrix(np.diff(np.eye(count), axis=0))
    if cyclic:
        cyclic_first = csr_matrix(np.roll(np.eye(count),-1,axis=0)-np.eye(count))
        d2 = cyclic_first@cyclic_first
        d3 = d2@cyclic_first
    keyframe_pattern = kron(eye(count), csr_matrix(frame_pattern)).tolil()
    # Knee phase rows are first differences, so each row also depends on the
    # previous frame's knee chain. Add those exact temporal neighbors to the
    # per-frame sparsity pattern used by the hybrid Jacobian.
    if timed_foot_articulation_tracks:
        phase_row_offset = 7 * joints + len(specs)
        previous_frames = (np.roll(np.arange(count), 1) if cyclic
                           else np.r_[-1, np.arange(max(count - 1, 0))])
        for track_index, (label, _, _) in enumerate(timed_foot_articulation_tracks):
            if not label.endswith('_knee'):
                continue
            dependencies = np.flatnonzero(timed_foot_articulation_pattern[track_index])
            if not dependencies.size:
                continue
            for frame_index, previous_frame in enumerate(previous_frames):
                if previous_frame < 0:
                    continue
                row = frame_index * frame_pattern.shape[0] + phase_row_offset + track_index
                columns = previous_frame * rig.width + dependencies
                keyframe_pattern[row, columns] = 1
    pattern = vstack([keyframe_pattern.tocsr(),
                     kron(abs(d2),temporal_pattern), kron(abs(d3),temporal_pattern),
                     kron(abs(d1),csr_matrix(settling_pattern)),
                     kron(abs(d2),root_pattern),
                     kron(abs(d3),root_pattern),
                     kron(abs(d2),csr_matrix(np.tile(body_dependencies, (6, 1))))], format='csr')
    from .rig_playback import sample_rig_coordinates
    playback_rig = {'jointNames':names,'parents':rig.parents,'order':rig.order,'offsets':rig.offsets,
                    'rotationJointNames':[names[j] for j in rig.active],
                    'interpolation': INTERPOLATION}
    # Constrain the same quarter-frame locations used by independent playback
    # validation. A subframe alone can miss the maximum of a nonlinear FK arc.
    interval_count = count if cyclic else count-1
    subframe_cursors = (np.arange(interval_count)[:,None]+np.array([.25,.5,.75])).ravel()
    subframe_count = len(subframe_cursors)
    subframe_first = np.floor(subframe_cursors).astype(int)
    subframe_last = (subframe_first+1)%count
    subframe_pinned = pinned[subframe_first]&pinned[subframe_last]
    subframe_targets = contact_targets[subframe_first]
    subframe_height_pinned = height_only_mask[subframe_first] & height_only_mask[subframe_last]
    subframe_height_targets = height_only_targets[subframe_first, :, 1]
    subframe_alpha = (subframe_cursors-subframe_first)[:, None, None]
    # Keep knee/elbow articulation phase aligned with playback's linear
    # reference. Structural anatomy alone uses the enclosing torso reference.
    playback_articulation_reference = source_conditioned_articulation_reference
    subframe_articulation_reference, _ = playback_reference_samples(
        playback_articulation_reference, subframe_first, subframe_last,
        subframe_alpha[:, 0, 0], names)
    _, subframe_anatomy_reference = playback_reference_samples(
        fit_anatomy_reference, subframe_first, subframe_last,
        subframe_alpha[:, 0, 0], names)
    subframe_reference_angles = np.stack([
        angles(*(subframe_articulation_reference[:, joint] for joint in columns))
        for _, columns, _ in specs
    ], axis=1)
    subframe_angle_tolerance = np.deg2rad([min(tolerance, 10.) - .5
                                          for _, _, tolerance in specs])
    subframe_direction_targets, subframe_direction_masks = source_foot_direction_targets_at(
        subframe_first, subframe_last, subframe_alpha[:, 0, 0], authority_masks=False)
    subframe_reference_parent, subframe_reference_bend, subframe_reference_sine = hinge_coordinates(
        subframe_articulation_reference, names)
    from .structural_refinement import _source_branch_is_temporally_supported
    subframe_hinge_specs = [spec for spec in ARTICULATIONS
                            if spec[0].endswith(('_knee', '_elbow'))]
    knee_hinge_indices = [i for i, spec in enumerate(subframe_hinge_specs)
                          if spec[0].endswith('_knee')]
    subframe_branch_supported = np.zeros(
        (subframe_count, len(subframe_hinge_specs)), dtype=bool)
    branch_support_radius = max(1, round(fps * 4 * .1))
    for hinge in range(len(subframe_hinge_specs)):
        source_track = list(zip(subframe_reference_parent[:, hinge],
                                subframe_reference_bend[:, hinge]))
        subframe_branch_supported[:, hinge] = [
            _source_branch_is_temporally_supported(source_track, sample, branch_support_radius)
            for sample in range(subframe_count)
        ]
    subframe_branch_supported &= subframe_reference_sine > np.sin(np.deg2rad(15.))
    subframe_alignment = alignment_features(
        alignment_source[subframe_first]*(1.-subframe_alpha)+alignment_source[subframe_last]*subframe_alpha,
        names, body_support)
    subframe_knee_branch_pattern = np.stack([
        np.maximum(branch_basis, joint_dependencies(rig, (a, h, b)))
        for label, a, h, b, _ in subframe_hinge_specs if label.endswith('_knee')
    ])
    subframe_pattern = np.vstack([rig.dependencies,rig.dependencies[1::3],
                                  floor_pattern,angle_pattern,
                                  subframe_knee_branch_pattern,
                                  source_foot_direction_pattern,collision_pattern])
    subframe_pattern = np.vstack([subframe_pattern, equipment_pattern])
    subframe_pattern = np.vstack([subframe_pattern, support_pattern])
    subframe_pattern = np.vstack([subframe_pattern, heel_pattern])
    # point_rows appends anatomy after all point-space sections. Sparsity must
    # follow that same order for grouped finite differences and point probes.
    subframe_pattern = np.vstack([subframe_pattern, structure_pattern])
    neighbors = np.column_stack([subframe_first-1, subframe_first, subframe_last, subframe_last+1])
    neighbors = neighbors % count if cyclic else np.clip(neighbors, 0, count-1)
    # Cyclic stencils can contain distinct frames in the same modulo-4
    # probe class when count is not divisible by four (for example
    # [199, 200, 0, 1] at a 201-frame seam). A class probe then perturbs
    # both frames and the response cannot be assigned to either column.
    # Route only those cursor rows through exact single-frame probes.
    hermite_collision_cursors = (
        _hermite_probe_collision_cursors(neighbors) if cyclic
        else np.zeros(subframe_count, dtype=bool)
    )
    pair_pattern = csr_matrix((np.ones(4*subframe_count),
                               (np.repeat(np.arange(subframe_count),4), neighbors.ravel())),
                              shape=(subframe_count,count))
    pattern = vstack([pattern,kron(pair_pattern,csr_matrix(subframe_pattern))],format='csr')
    if cyclic:
        seam_pattern = np.zeros((2,count));seam_pattern[0,[0,-1,-2]]=1.;seam_pattern[1,[0,1,-1]]=1.
        pattern = vstack([pattern,kron(csr_matrix(seam_pattern),csr_matrix(rig.dependencies))],format='csr')
        excess_pattern = np.zeros((1, count)); excess_pattern[0, [0, 1, -2, -1]] = 1.
        excess_dependencies = rig.dependencies.reshape(joints, 3, rig.width).max(axis=1)
        pattern = vstack([pattern, kron(csr_matrix(excess_pattern), csr_matrix(excess_dependencies))], format='csr')
        pattern = vstack([pattern, kron(csr_matrix(seam_pattern), csr_matrix(excess_dependencies))], format='csr')
    pattern = vstack([pattern, kron(abs(world_d3), temporal_pattern)], format='csr')
    if source_projection_constraint.get('available'):
        source_observations = _source_projection_point_observations(
            source_projection_constraint)
        source_pattern = lil_matrix(
            (len(source_observations) * 2, count * rig.width), dtype=np.int8,
        )
        for observation_index, observation in enumerate(source_observations):
            joint = observation['jointIndex']
            joint_dependencies_mask = np.max(
                rig.dependencies[joint * 3:joint * 3 + 3], axis=0,
            ) > 0
            active_columns = np.flatnonzero(joint_dependencies_mask)
            endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
            if observation['rightFrame'] != observation['leftFrame']:
                endpoints.append((observation['rightFrame'], observation['alpha']))
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight <= 0.:
                    continue
                columns = frame_index * rig.width + active_columns
                source_pattern[observation_index * 2, columns] = 1
                source_pattern[observation_index * 2 + 1, columns] = 1
        source_ray_observations = (
            source_projection_constraint.get('sourceFootRayObservations') or [])
        source_ray_pattern = lil_matrix(
            (len(source_ray_observations), count * rig.width), dtype=np.int8,
        )
        for observation_index, observation in enumerate(source_ray_observations):
            joint_indices = (observation['ankleJointIndex'], observation['footJointIndex'])
            active_columns = np.unique(np.concatenate([
                np.flatnonzero(np.max(
                    rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                for joint in joint_indices
            ]))
            endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
            if observation['rightFrame'] != observation['leftFrame']:
                endpoints.append((observation['rightFrame'], observation['alpha']))
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight <= 0.:
                    continue
                columns = frame_index * rig.width + active_columns
                source_ray_pattern[observation_index, columns] = 1
        # Native ankle-to-toe angle remains report-only; rendered material
        # heel rows below own observed lift preservation.
        source_phase_observations = []
        source_phase_pattern = lil_matrix(
            (len(source_phase_observations), count * rig.width), dtype=np.int8,
        )
        for observation_index, observation in enumerate(source_phase_observations):
            joint_indices = (observation['ankleJointIndex'], observation['footJointIndex'])
            active_columns = np.unique(np.concatenate([
                np.flatnonzero(np.max(
                    rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                for joint in joint_indices
            ]))
            endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
            if observation['rightFrame'] != observation['leftFrame']:
                endpoints.append((observation['rightFrame'], observation['alpha']))
            for frame_index, interpolation_weight in endpoints:
                if interpolation_weight <= 0.:
                    continue
                source_phase_pattern[observation_index,
                                     frame_index * rig.width + active_columns] = 1
        pattern = vstack([
            pattern, source_pattern.tocsr(), source_ray_pattern.tocsr(),
            source_phase_pattern.tocsr(),
        ], format='csr')
        source_heel_observations = (
            source_projection_constraint.get('sourceFootHeelImageObservations') or [])
        source_heel_events = (
            source_projection_constraint.get('sourceFootHeelTrajectoryEvents') or [])
        if source_heel_observations:
            source_heel_pattern = lil_matrix(
                (2 * len(source_heel_observations) + len(source_heel_events),
                 count * rig.width), dtype=np.int8,
            )
            heel_index_by_key = {
                (row['sourceSide'], round(float(row['sourceTime']), 8)): index
                for index, row in enumerate(source_heel_observations)
            }
            for observation_index, observation in enumerate(source_heel_observations):
                joint_indices = (observation['ankleJointIndex'], observation['footJointIndex'])
                active_columns = np.unique(np.concatenate([
                    np.flatnonzero(np.max(
                        rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                    for joint in joint_indices
                ]))
                endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
                if observation['rightFrame'] != observation['leftFrame']:
                    endpoints.append((observation['rightFrame'], observation['alpha']))
                for frame_index, interpolation_weight in endpoints:
                    if interpolation_weight <= 0.:
                        continue
                    columns = frame_index * rig.width + active_columns
                    source_heel_pattern[observation_index * 2, columns] = 1
                    source_heel_pattern[observation_index * 2 + 1, columns] = 1
            for event_index, event in enumerate(source_heel_events):
                for source_time in event['observationTimes']:
                    observation_index = heel_index_by_key.get((
                        event['sourceSide'], round(float(source_time), 8)))
                    if observation_index is None:
                        continue
                    observation = source_heel_observations[observation_index]
                    joint_indices = (observation['ankleJointIndex'],
                                     observation['footJointIndex'])
                    active_columns = np.unique(np.concatenate([
                        np.flatnonzero(np.max(
                            rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                        for joint in joint_indices
                    ]))
                    endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
                    if observation['rightFrame'] != observation['leftFrame']:
                        endpoints.append((observation['rightFrame'], observation['alpha']))
                    row = 2 * len(source_heel_observations) + event_index
                    for frame_index, interpolation_weight in endpoints:
                        if interpolation_weight > 0.:
                            columns = frame_index * rig.width + active_columns
                            source_heel_pattern[row, columns] = 1
            pattern = vstack([pattern, source_heel_pattern.tocsr()], format='csr')
        support_relative_pairs = _source_support_relative_fit_pairs(source_projection_constraint)
        if support_relative_pairs:
            support_relative_pattern = lil_matrix(
                (len(support_relative_pairs) * 2, count * rig.width), dtype=np.int8,
            )
            for observation_index, pair in enumerate(support_relative_pairs):
                for observation in pair:
                    joint_indices = (
                        *observation['centerJointIndices'], observation['supportJointIndex'])
                    active_columns = np.unique(np.concatenate([
                        np.flatnonzero(np.max(
                            rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                        for joint in joint_indices
                    ]))
                    endpoints = [(observation['leftFrame'], 1. - observation['alpha'])]
                    if observation['rightFrame'] != observation['leftFrame']:
                        endpoints.append((observation['rightFrame'], observation['alpha']))
                    for frame_index, interpolation_weight in endpoints:
                        if interpolation_weight <= 0.:
                            continue
                        columns = frame_index * rig.width + active_columns
                        support_relative_pattern[observation_index * 2, columns] = 1
                        support_relative_pattern[observation_index * 2 + 1, columns] = 1
            pattern = vstack([pattern, support_relative_pattern.tocsr()], format='csr')
        endpoint_observations = source_projection_constraint.get('endpointPostureObservations') or []
        if endpoint_observations:
            endpoint_pattern = lil_matrix(
                (len(endpoint_observations) * 2, count * rig.width), dtype=np.int8,
            )
            for observation_index, observation in enumerate(endpoint_observations):
                joint_indices = (observation['jointIndex'], *observation['centerJointIndices'])
                active_columns = np.unique(np.concatenate([
                    np.flatnonzero(np.max(rig.dependencies[joint * 3:joint * 3 + 3], axis=0) > 0)
                    for joint in joint_indices
                ]))
                for link in observation['fitLinks']:
                    endpoints = [(link['leftFrame'], 1. - link['alpha'])]
                    if link['rightFrame'] != link['leftFrame']:
                        endpoints.append((link['rightFrame'], link['alpha']))
                    for frame_index, interpolation_weight in endpoints:
                        if interpolation_weight <= 0.:
                            continue
                        columns = frame_index * rig.width + active_columns
                        endpoint_pattern[observation_index * 2, columns] = 1
                        endpoint_pattern[observation_index * 2 + 1, columns] = 1
            pattern = vstack([pattern, endpoint_pattern.tocsr()], format='csr')
    if support_range_fit_tracks:
        pattern = vstack([
            pattern, support_range_sparsity(rig, count, support_range_fit_tracks),
        ], format='csr')
    root_travel_columns = (
        np.arange(count)[:, None] * rig.width + np.arange(3)
    ).reshape(-1)
    root_travel_pattern = csr_matrix((
        np.ones(len(root_travel_columns), dtype=np.int8),
        (np.zeros(len(root_travel_columns), dtype=int), root_travel_columns),
    ), shape=(1, count * rig.width))
    pattern = vstack([pattern, root_travel_pattern], format='csr')
    jerk_feasibility_pattern = csr_matrix((
        np.ones(count * rig.width, dtype=np.int8),
        (np.zeros(count * rig.width, dtype=int), np.arange(count * rig.width)),
    ), shape=(1, count * rig.width))
    pattern = vstack([pattern, jerk_feasibility_pattern], format='csr')
    initial_rotations = Rotation.from_rotvec(rig.initial[:,3:].reshape(-1,3))
    floor = payload.get('renderFloorY')
    source_head = body_local_head_direction(reference,names)
    from .fit_runtime import current_fit_session, fit_input_key, fit_should_yield_for_priority
    fit_session = current_fit_session()
    trajectory_key = fit_input_key(payload) if fit_session is not None else None
    best_coordinates = None
    best_cost = float('inf')
    best_feasible_coordinates = None
    best_feasible_cost = float('inf')
    source_heel_evidence_required = bool(
        source_projection_constraint.get('sourceFootHeelTrajectoryObservations')
        or source_projection_constraint.get('sourceFootHeelUnresolvedToeOnlyObservationCount'))
    best_feasible_heel_passed = not source_heel_evidence_required
    seam_polish_weight = 1.
    contact_polish_weight = 1.
    equipment_polish_weight = 1.
    grip_fit_weight = GRIP_FIT_WEIGHT
    if (equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
            and not validate_grip(rig.decode(rig.initial), names, equipment)['passed']):
        # Source/reconstruction often has large rigid-pair variance; give grip
        # room to compete with pose/contact before Stage-A polish.
        grip_fit_weight = GRIP_FIT_WEIGHT_WHEN_REFERENCE_FAILS
        report['gripFitWeight'] = float(grip_fit_weight)
    support_root_track = reference[:, rig.root]
    if body_support.get('required') and not root_motion_quality(support_root_track, fps, scale)['passed']:
        support_root_track = gaussian_filter1d(
            support_root_track, max(.5, fps * .08), axis=0, mode='nearest')

    def keyframe_pre_rows(candidate, contact_weight):
        current_angles = np.stack([angles(*(candidate[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
        artic_weight = (SUPPORT_ARTICULATION_FIT_WEIGHT if body_support.get('required') else 500.)
        articulation = artic_weight*(np.minimum(current_angles-low,0.)+np.maximum(current_angles-high,0.))
        if timed_foot_articulation_tracks:
            articulation = np.concatenate([
                articulation,
                timed_foot_articulation_residuals(
                    current_angles, specs, timed_foot_articulation_tracks, artic_weight,
                    source_foot_coverage=source_foot_coverage,
                    source_foot_phase_coverage=source_foot_phase_coverage,
                    fps=fps, cyclic=cyclic,
                ),
            ], axis=1)
        source_direction = source_foot_direction_residuals(
            candidate, source_foot_direction_targets, source_foot_direction_trajectory_masks)
        floor_error = np.zeros((count,joints)) if floor is None else FLOOR_FIT_WEIGHT*np.minimum(
            material_floor_heights(candidate, names, foot_rest_pitches, material_foot_scale)-float(floor),0.)
        current_head = body_local_head_direction(candidate,names)
        head_angle = np.arccos(np.clip(np.sum(source_head*current_head,axis=1),-1.,1.))
        head_weight = (SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT if body_support.get('required')
                       else HEAD_ARTICULATION_FIT_WEIGHT)
        head_penalty = head_weight*np.maximum(head_angle-np.deg2rad(14.),0.)[:,None]
        pose_error = 2. * (candidate - target) / scale
        if body_support.get('required'):
            pose_error[:, rig.root] = 8. * (candidate[:, rig.root] - support_root_track) / scale
        return np.concatenate([pose_error.reshape(count,-1),
                               (contact_weight*(candidate-contact_targets)*pinned[:,:,None]).reshape(count,-1),
                               (contact_weight*(candidate[:,:,1]-height_only_targets[:,:,1])
                                * height_only_mask).reshape(count,-1),
                               articulation, source_direction, floor_error,
                               head_penalty],axis=1)

    def keyframe_mid_rows(candidate):
        excursion_projection = np.sum((candidate-candidate[:,rig.root:rig.root+1]-excursion_center)*excursion_direction,axis=-1)
        excursion_penalty = 20.*np.minimum(excursion_projection-excursion_minimum,0.)*excursion_active/scale
        current_parent, current_bend, current_sine = hinge_coordinates(candidate,names)
        branch_dot = transported_hinge_dots(source_parent,source_bend,current_parent,current_bend)
        branch_penalty = 20.*np.minimum(branch_dot-.2,0.)*branch_supported*np.clip(current_sine/np.sin(np.deg2rad(15.)),0.,1.)
        for column, (label, _, _, _, tolerance) in enumerate(
                spec for spec in ARTICULATIONS if spec[0].endswith(('_knee', '_elbow'))):
            if label.endswith('_knee'):
                reliable = branch_supported[:, column] * np.clip(
                    current_sine[:, column] / np.sin(np.deg2rad(15.)), 0., 1.)
                deviation = np.arccos(np.clip(branch_dot[:, column], -1., 1.))
                branch_penalty[:, column] = 500. * np.maximum(
                    deviation - np.deg2rad(tolerance - .5), 0.) * reliable
        return np.concatenate([
            100.*np.minimum(collision_clearances(candidate,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
            excursion_penalty,branch_penalty],axis=1)

    def anatomy_rows(unconstrained_candidate):
        structure = fit_anatomy_structure_residuals(
            unconstrained_candidate, names, fit_anatomy_reference)
        spans, _ = span_rigidity_fit_residuals(
            unconstrained_candidate, names, span_targets, body_scale_m=scale)
        return np.concatenate([ANATOMY_FIT_WEIGHT * structure,
                               ANATOMY_FIT_WEIGHT * spans], axis=1)

    def keyframe_post_rows(candidate, grip_weight, contact_weight):
        return np.concatenate([
            grip_weight*grip_residual(candidate,names,equipment)/scale,
            2000.*geometry_errors(candidate,names,body_support)/scale,
            10.*alignment_constraint_errors(candidate,source_alignment,names,body_support)/scale,
            (contact_weight * heel_contacts.residual(candidate)).reshape(count, -1)],axis=1)

    def acceleration_jerk_rows(candidate):
        root_relative = (candidate-candidate[:,rig.root:rig.root+1])/scale
        acceleration = (d2@(candidate-candidate[:,rig.root:rig.root+1]).reshape(count,-1)).reshape(-1,joints,3)
        acceleration = (10.*acceleration/acceleration_fit_scale[None,:,None]).reshape(-1,joints*3)
        jerk = (d3@root_relative.reshape(count,-1))*(fps*.10)**3
        return np.r_[acceleration.ravel(),jerk.ravel()]

    def settling_rows(candidate):
        relative = body_relative_points(candidate,names)
        settling_weight = 150. if body_support.get('required') else 50.
        settling = (settling_weight*np.diff(relative,axis=0)*hold_weights*fps
                    / (settling_limit*np.sqrt(max(np.sum(hold_weights)*3, 1.))))
        return settling.ravel()

    def root_temporal_rows(candidate):
        root_acceleration = (d2@(candidate[:,rig.root]/scale))*(fps*.10)**2*np.sqrt(joints)
        root_jerk = (d3@(candidate[:,rig.root]/scale))*(fps*.07)**3*np.sqrt(joints)
        if body_support.get('required'):
            root_acceleration = 4. * root_acceleration
            root_jerk = 4. * root_jerk
        return np.r_[root_acceleration.ravel(),root_jerk.ravel()]

    def orientation_rows(candidate):
        return (10.*(d2@body_orientation_axes(candidate,names).reshape(count,-1))/rotation_fit_scale).ravel()

    def temporal_rows(candidate):
        return np.r_[acceleration_jerk_rows(candidate),settling_rows(candidate),
                     root_temporal_rows(candidate),orientation_rows(candidate)]

    def world_jerk_rows(candidate):
        return world_jerk_profile_rows(candidate, jerk_basis, world_d3, jerk_limit)

    def subframe_articulation_sections(subframe):
        current_angles = np.stack([
            angles(*(subframe[:, joint] for joint in columns))
            for _, columns, _ in specs
        ], axis=1)
        articulation_weight = (SUPPORT_ARTICULATION_FIT_WEIGHT
                               if body_support.get('required') else 500.)
        angle_residual = articulation_weight * (
            np.minimum(current_angles - subframe_reference_angles + subframe_angle_tolerance, 0.)
            + np.maximum(current_angles - subframe_reference_angles - subframe_angle_tolerance, 0.)
        )
        current_parent, current_bend, current_sine = hinge_coordinates(subframe, names)
        transported_dot = transported_hinge_dots(
            subframe_reference_parent, subframe_reference_bend,
            current_parent, current_bend,
        )[:, knee_hinge_indices]
        source_reliable = subframe_branch_supported[:, knee_hinge_indices]
        candidate_reliable = current_sine[:, knee_hinge_indices] > np.sin(np.deg2rad(15.))
        reliable = source_reliable & candidate_reliable
        hinge_tolerances = np.deg2rad([
            tolerance - .5 for label, _, _, _, tolerance in subframe_hinge_specs
            if label.endswith('_knee')
        ])
        branch_deviation = np.arccos(np.clip(transported_dot, -1., 1.))
        branch_residual = 500. * np.maximum(
            branch_deviation - hinge_tolerances[None, :], 0.
        ) * reliable
        return angle_residual, branch_residual

    def subframe_point_sections(subframe, contact_weight, grip_weight):
        subframe_contacts = contact_weight*(subframe-subframe_targets)*subframe_pinned[:,:,None]
        subframe_height = (contact_weight * (subframe[:, :, 1] - subframe_height_targets)
                           * subframe_height_pinned)
        subframe_floor = np.zeros((subframe_count,joints)) if floor is None else FLOOR_FIT_WEIGHT*np.minimum(
            material_floor_heights(subframe, names, foot_rest_pitches, material_foot_scale)-float(floor),0.)
        subframe_angles, subframe_knee_branches = subframe_articulation_sections(subframe)
        subframe_directions = source_foot_direction_residuals(
            subframe, subframe_direction_targets, subframe_direction_masks)
        return [subframe_contacts.reshape(subframe_count,-1),subframe_height,subframe_floor,
                subframe_angles,subframe_knee_branches,subframe_directions,
                100.*np.minimum(collision_clearances(subframe,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                grip_weight*grip_residual(subframe,names,equipment)/scale,
                2000.*geometry_errors(subframe,names,body_support)/scale,
                10.*alignment_constraint_errors(subframe,subframe_alignment,names,body_support)/scale,
                (contact_weight * heel_contacts.residual(
                    subframe, subframe_first, subframe_last)).reshape(subframe_count, -1)]

    def subframe_point_rows(subframe, contact_weight, grip_weight):
        return np.concatenate(subframe_point_sections(subframe, contact_weight, grip_weight), axis=1)

    def subframe_anatomy_rows(unconstrained_subframe):
        structure = fit_anatomy_structure_residuals(
            unconstrained_subframe, names, subframe_anatomy_reference)
        spans, _ = span_rigidity_fit_residuals(
            unconstrained_subframe, names, span_targets, body_scale_m=scale)
        return np.concatenate([ANATOMY_FIT_WEIGHT * structure,
                               ANATOMY_FIT_WEIGHT * spans], axis=1)

    def seam_rows(candidate):
        from .loop_seam import seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO
        _, excess, increments = seam_errors(candidate)
        # Optimize the actual playback step bound as well as velocity
        # matching. A small least-squares velocity error can still leave
        # a visibly oversized restart step, especially in slow movement.
        limit = MAX_STEP_EXCESS_BODY_RATIO * scale
        # Use body-normalized meters, as for contact/grip residuals.
        # Dividing by the millimeter acceptance limit makes this term
        # dominate anatomy and contact fitting by orders of magnitude.
        # Stage-B polish raises seam_polish_weight so soft LS prioritizes
        # restart continuity once body/contact terms are already good.
        seam_excess = (2000. * seam_polish_weight) * np.maximum(
            excess - .8 * limit, 0.) / scale
        velocity_step_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * scale / fps
        # Stage-B near-misses are often velocity-limited after step is close;
        # weight wrap increments above step excess so LS closes the hitch.
        velocity_weight = 3500. * seam_polish_weight if seam_polish_weight > 1. else 2000. * seam_polish_weight
        seam_velocity_excess = velocity_weight * np.maximum(
            np.linalg.norm(increments, axis=-1) - .8 * velocity_step_limit, 0.) / scale
        closure = (150. * seam_polish_weight) * increments / scale
        return closure, seam_excess, seam_velocity_excess

    def point_rows(candidate, unconstrained_candidate, subframe, unconstrained_subframe,
                   contact_weight, grip_weight):
        """Every residual row that is a function of decoded points.

        ``candidate``/``unconstrained_candidate`` are the keyframe point
        arrays; the subframe pair likewise. ``rotation_prior`` and the seam
        rows depend on raw coordinates and stay in ``residual``. Splitting
        these out lets the Jacobian probe points directly and chain through
        the analytic FK Jacobian instead of grouped coordinate differences.
        """
        keyframe_pre = keyframe_pre_rows(candidate, contact_weight)
        keyframe_mid = keyframe_mid_rows(candidate)
        anatomy = anatomy_rows(unconstrained_candidate)
        keyframe_post = keyframe_post_rows(candidate, grip_weight, contact_weight)
        temporal = temporal_rows(candidate)
        subframe_sections = subframe_point_sections(subframe, contact_weight, grip_weight)
        subframe_anatomy = subframe_anatomy_rows(unconstrained_subframe)
        subframe_rows = np.concatenate([*subframe_sections, subframe_anatomy], axis=1)
        return {'keyframe_pre': keyframe_pre, 'keyframe_mid': keyframe_mid,
                'anatomy': anatomy, 'keyframe_post': keyframe_post,
                'temporal': temporal, 'subframe': subframe_rows,
                'subframeSectionWidths': tuple(section.shape[1] for section in subframe_sections),
                'subframeAnatomy': subframe_anatomy}

    last_residual_state = None

    def check_optimizer_budget():
        """Stop residual and Jacobian work at the same solve-phase fence."""
        if fit_should_yield_for_priority() or monotonic() >= optimization_deadline:
            raise TimeoutError

    def candidate_heel_evidence(values):
        geometry_payload = deepcopy(
            source_projection_constraint.get('footGeometryPayload') or payload)
        geometry_payload.pop('scenePlacement', None)
        geometry_payload['fixedRig'] = {
            'version': 1, 'jointNames': names, 'parents': rig.parents,
            'order': rig.order, 'offsets': rig.offsets.tolist(),
            'interpolation': INTERPOLATION,
            'rotationJointNames': [names[joint] for joint in rig.active],
            'coordinates': np.asarray(values, dtype=float).reshape(count, rig.width).tolist(),
        }
        candidate_points = rig.decode(np.asarray(values, dtype=float).reshape(count, rig.width))
        for frame, frame_points in zip(geometry_payload['frames'], candidate_points):
            frame['joints'] = dict(zip(names, frame_points.tolist()))
        transport_corrected_bone_sides(frames, geometry_payload)
        return _source_foot_material_heel_fit_evidence(
            geometry_payload, source_projection_constraint)

    def residual(values):
        nonlocal last_residual_state
        nonlocal best_coordinates, best_cost, best_feasible_coordinates, best_feasible_cost
        nonlocal best_feasible_heel_passed
        check_optimizer_budget()
        coordinates = values.reshape(count,rig.width)
        candidate = rig.decode(coordinates)
        # A clipped socket hides its violation from the optimizer and creates
        # velocity corners where the interpolated path enters the clamp. Score
        # the underlying geometry so fitting can remove the need for clipping.
        unconstrained_candidate = rig.decode(coordinates, project_socket=False)
        rotation_prior = .01*(initial_rotations.inv()*Rotation.from_rotvec(coordinates[:,3:].reshape(-1,3))).as_rotvec().reshape(count,-1)
        contact_weight = CONTACT_FIT_WEIGHT * contact_polish_weight
        grip_weight = grip_fit_weight * equipment_polish_weight
        subframe_coordinates = sample_rig_coordinates(
            {**playback_rig,'coordinates':coordinates},subframe_cursors,wrap=cyclic)
        subframe = rig.decode(subframe_coordinates)
        unconstrained_subframe = rig.decode(subframe_coordinates, project_socket=False)
        rows = point_rows(candidate, unconstrained_candidate, subframe, unconstrained_subframe,
                          contact_weight, grip_weight)
        # least_squares evaluates fun(x) immediately before jac(x). Retain its
        # baseline arrays and point-space sections so the hybrid Jacobian can
        # probe from this exact state without decoding and evaluating the
        # unperturbed residual a second time.
        last_residual_state = {
            'values': np.asarray(values, dtype=float).copy(),
            'coordinates': coordinates,
            'candidate': candidate,
            'unconstrainedCandidate': unconstrained_candidate,
            'subframeCoordinates': subframe_coordinates,
            'subframe': subframe,
            'unconstrainedSubframe': unconstrained_subframe,
            'contactWeight': contact_weight,
            'gripWeight': grip_weight,
            'rows': rows,
        }
        per_frame = np.concatenate([rows['keyframe_pre'], rotation_prior,
                                    rows['keyframe_mid'], rows['anatomy'],
                                    rows['keyframe_post']],axis=1)
        # The final sample precedes the first by one frame. Equal endpoint
        # positions would impose a stop; match the incoming/outgoing increments.
        closure, seam_excess, seam_velocity_excess = np.empty(0), np.empty(0), np.empty(0)
        if cyclic:
            # The final sample precedes the first by one frame. Equal endpoint
            # positions would impose a stop; match the incoming/outgoing increments.
            closure, seam_excess, seam_velocity_excess = seam_rows(candidate)
        errors = np.r_[per_frame.ravel(),rows['temporal'],
                     rows['subframe'].ravel(),closure.ravel(),seam_excess.ravel(),seam_velocity_excess.ravel()]
        errors = np.r_[errors, world_jerk_rows(candidate)]
        errors = np.r_[errors, _source_projection_fit_rows(candidate, source_projection_constraint)]
        errors = np.r_[errors, _source_support_relative_fit_rows(candidate, source_projection_constraint)]
        errors = np.r_[errors, _source_endpoint_posture_fit_rows(candidate, source_projection_constraint)]
        ratios = {}
        if support_range_fit_tracks:
            # Soft floor slightly above the 0.85 acceptance ratio so the solver
            # has margin instead of landing on the hard fail boundary. Weight
            # must compete with contact/seam terms; 5k left retained fits at
            # ~0.80 hip/shoulder ratios that still failed jointRange.
            errors = np.r_[errors, support_range_residuals(candidate, support_range_fit_tracks)]
        errors = np.r_[errors, root_travel_preservation_residual(
            candidate[:, rig.root], target[:, rig.root], body_scale=scale)]
        errors = np.r_[errors, world_jerk_feasibility_residual(
            candidate, world_d3, jerk_fit_target)]
        cost = float(errors@errors)
        if np.isfinite(cost) and cost < best_cost:
            best_cost, best_coordinates = cost, values.copy()
        # Longer solves can improve soft cost while leaving the contact-feasible
        # region. Keep the best iterate that still clears planted contacts so
        # acceptance is not hostage to an over-fit soft minimum.
        if np.isfinite(cost) and (np.any(pinned) or np.any(heel_contacts.active)):
            contact_err = float(np.max(
                np.linalg.norm((candidate - contact_targets)[pinned], axis=-1), initial=0.))
            play_err = float(np.max(
                np.linalg.norm((subframe - subframe_targets)[subframe_pinned], axis=-1), initial=0.))
            contact_err = max(contact_err, float(np.max(
                np.linalg.norm(heel_contacts.residual(candidate), axis=-1), initial=0.)))
            play_err = max(play_err, float(np.max(np.linalg.norm(
                heel_contacts.residual(subframe, subframe_first, subframe_last), axis=-1), initial=0.)))
            floor_pen = 0. if floor is None else max(
                0., float(floor) - float(min(
                    material_floor_heights(candidate, names, foot_rest_pitches,
                                           material_foot_scale).min(),
                    material_floor_heights(subframe, names, foot_rest_pitches,
                                           material_foot_scale).min())))
            if (contact_iterate_is_feasible(contact_err, play_err, floor_pen)
                    and contact_iterate_can_challenge_best(
                        cost, best_feasible_cost,
                        has_best=best_feasible_coordinates is not None,
                        heel_evidence_required=source_heel_evidence_required,
                        best_heel_passed=best_feasible_heel_passed)):
                # Contact-only selection can replace a valid supported spine
                # with a cheaper iterate just beyond the final anatomy gate.
                anatomy_max = max(
                    float(np.max(anatomical_structure_residuals(
                        candidate, names, reference=fit_anatomy_reference)[0], initial=0.)),
                    float(np.max(anatomical_structure_residuals(
                        subframe, names,
                        reference=subframe_anatomy_reference
                    )[0], initial=0.)),
                )
                if contact_iterate_is_feasible(
                        contact_err, play_err, floor_pen,
                        maximum_anatomy_residual=anatomy_max):
                    heel_passed = not source_heel_evidence_required
                    if source_heel_evidence_required:
                        heel_passed = bool(candidate_heel_evidence(values).get('passed'))
                    if (best_feasible_coordinates is None
                            or contact_iterate_is_preferred(
                                cost, heel_passed, best_feasible_cost,
                                best_feasible_heel_passed)):
                        best_feasible_cost = cost
                        best_feasible_coordinates = values.copy()
                        best_feasible_heel_passed = heel_passed
        return errors
    hybrid_jacobian_enabled = _hybrid_jacobian_enabled()

    pattern_support_cache = {}

    def hybrid_jacobian(values):
        """Point-space Jacobian: each residual section is finite-differenced
        over decoded points and chained with the exact analytic FK Jacobian
        (and, for subframe rows, the coordinate interpolator), instead of
        probing the whole residual through grouped coordinate differences.
        Row order mirrors ``residual`` exactly so the solver sees a
        consistent (residual, jacobian) pair. Probes are separated by joint
        color, component, and frame-shift class so every row reads exactly
        one perturbed column per probe.
        """
        check_optimizer_budget()
        fd_step = np.sqrt(np.finfo(float).eps)
        cached = last_residual_state
        if (cached is not None
                and np.array_equal(np.asarray(values, dtype=float), cached['values'])):
            coordinates = cached['coordinates']
            candidate = cached['candidate']
            unconstrained_candidate = cached['unconstrainedCandidate']
            subframe_coordinates = cached['subframeCoordinates']
            subframe = cached['subframe']
            unconstrained_subframe = cached['unconstrainedSubframe']
            contact_weight = cached['contactWeight']
            grip_weight = cached['gripWeight']
            cached_rows = cached['rows']
        else:
            coordinates = np.asarray(values, dtype=float).reshape(count, rig.width)
            candidate = rig.decode(coordinates)
            unconstrained_candidate = rig.decode(coordinates, project_socket=False)
            subframe_coordinates = sample_rig_coordinates(
                {**playback_rig, 'coordinates': coordinates}, subframe_cursors, wrap=cyclic)
            subframe = rig.decode(subframe_coordinates)
            unconstrained_subframe = rig.decode(subframe_coordinates, project_socket=False)
            contact_weight = CONTACT_FIT_WEIGHT * contact_polish_weight
            grip_weight = grip_fit_weight * equipment_polish_weight
            cached_rows = None
        check_optimizer_budget()
        fk = rig.fk_jacobian(coordinates)
        check_optimizer_budget()
        fk_unc = rig.fk_jacobian(coordinates, project_socket=False)

        def sparse_from(entries, rows, columns, shape):
            if not entries:
                return csr_matrix(shape)
            return coo_matrix((np.concatenate(entries),
                               (np.concatenate(rows), np.concatenate(columns))),
                              shape=shape).tocsr()

        def joint_colors(supports):
            # Greedy coloring of the joint conflict graph. Supports are
            # directional-probe response masks - a conservative superset of
            # true dependencies - so joints sharing a color never co-occur in
            # any row and their component probes are exact.
            order = sorted(range(len(supports)),
                           key=lambda j: int(np.count_nonzero(supports[j])), reverse=True)
            colors = []
            for j in order:
                for group in colors:
                    if all(not (supports[j] & supports[other]).any() for other in group):
                        group.append(j)
                        break
                else:
                    colors.append([j])
            return colors

        def pattern_joint_support(row_indices):
            """Sound per-joint row masks from the solver dependency pattern: a
            row can read joint j's points only if the pattern ties it to a
            rotation slot of j or an ancestor (every point-reading row also
            reads that point's rotation inputs, so this is a superset).
            Directional probes cannot be used here: difference rows such as
            bone-length contrasts cancel along a (1,1,1) probe direction and
            would silently drop true dependencies."""
            key = np.asarray(row_indices).tobytes()
            cached = pattern_support_cache.get(key)
            if cached is not None:
                return cached
            csc = pattern.tocsc()
            masks = np.zeros((len(row_indices), joints), dtype=bool)
            for j in range(joints):
                check_optimizer_budget()
                slots = set()
                ancestor = j
                while ancestor >= 0:
                    if ancestor in rig.slots:
                        slots.add(rig.slots[ancestor])
                    ancestor = rig.parents[ancestor]
                cols = (np.arange(count)[:, None] * rig.width
                        + np.fromiter(sorted(slots), dtype=int)[None, :]).ravel()
                rows_nz = np.unique(csc[:, cols].indices)
                full = np.zeros(pattern.shape[0], dtype=bool)
                full[rows_nz] = True
                masks[:, j] = full[row_indices]
            pattern_support_cache[key] = masks
            return masks

        def colored_composite_probe(evaluate, base_rows, bases, ownership, shifts,
                                    col_offsets, row0, stride,
                                    previous_sample_rows=None):
            """FD of a per-sample section composite w.r.t. decoded points.

            ``bases`` are the point arrays the sections read (constrained and
            unconstrained decodes); ``ownership`` maps each column range to
            the array it reads. Rows read one sample (shifts=1) or a stencil
            of ``shifts`` consecutive samples. ``col_offsets`` maps each
            composite column to its offset inside the residual's per-sample
            row layout, so supports come from the residual pattern rows
            ``row0 + sample * stride + offset``.
            """
            n_frames = len(bases[0])
            width_total = base_rows.shape[1]
            flat = np.arange(n_frames * width_total)
            residual_rows = (row0 + (flat // width_total) * stride
                             + np.asarray(col_offsets)[flat % width_total])
            pattern_masks = pattern_joint_support(residual_rows)
            supports = []
            for j in range(joints):
                check_optimizer_budget()
                # Neither source alone is sound: the pattern can
                # under-declare an anatomy row's endpoint joints (which
                # breaks the exact translation-invariance cancellations),
                # and directional probes cancel on difference rows.
                # This probe perturbs every base and is independent of row
                # ownership, so calculate it once for all composite sections.
                probes = [base.copy() for base in bases]
                for base in probes:
                    base[:, j, :] += fd_step
                directional = (evaluate(*probes) - base_rows).ravel() != 0.
                supports.append(pattern_masks[:, j] | directional)
            rows, columns, entries = [], [], []
            for start, end, array_index in ownership:
                sup = supports
                for group in joint_colors(sup):
                    for comp in range(3):
                        for c in range(shifts):
                            check_optimizer_budget()
                            frames = np.arange(c, n_frames, shifts)
                            # Keep unchanged bases by identity so their residual
                            # sections can reuse this Jacobian's baseline rows.
                            probes = list(bases)
                            probes[array_index] = bases[array_index].copy()
                            for j in group:
                                if shifts == 1:
                                    probes[array_index][:, j, comp] += fd_step
                                else:
                                    probes[array_index][frames, j, comp] += fd_step
                            diff = ((evaluate(*probes) - base_rows) / fd_step).ravel()
                            for j in group:
                                hit = np.nonzero(np.where(sup[j], diff, 0.))[0]
                                if not hit.size:
                                    continue
                                output_frames = hit // width_total
                                ordinary_hits = []
                                ordinary_frames = []
                                ordinary_entries = []
                                for hit_index, output_frame in zip(hit, output_frames):
                                    candidates = [int(output_frame)]
                                    if previous_sample_rows is not None:
                                        previous = int(previous_sample_rows.flat[hit_index])
                                        if previous >= 0:
                                            candidates.append(previous)
                                    selected = [frame for frame in candidates
                                                if frame % shifts == c]
                                    if len(selected) == 1:
                                        ordinary_hits.append(hit_index)
                                        ordinary_frames.append(selected[0])
                                        ordinary_entries.append(diff[hit_index])
                                    elif len(selected) > 1:
                                        # A cyclic seam on an odd frame count
                                        # can put both neighbors in one color.
                                        # Probe only these colliding rows/frame
                                        # pairs separately instead of assigning
                                        # their summed derivative to one frame.
                                        for frame in selected:
                                            exact_probes = list(bases)
                                            exact_probes[array_index] = bases[array_index].copy()
                                            exact_probes[array_index][frame, j, comp] += fd_step
                                            exact_diff = (
                                                evaluate(*exact_probes).ravel()[hit_index]
                                                - base_rows.reshape(-1)[hit_index]
                                            ) / fd_step
                                            if exact_diff:
                                                ordinary_hits.append(hit_index)
                                                ordinary_frames.append(frame)
                                                ordinary_entries.append(exact_diff)
                                if ordinary_hits:
                                    rows.append(np.asarray(ordinary_hits, dtype=int))
                                    columns.append((np.asarray(ordinary_frames) * joints + j)
                                                   * 3 + comp)
                                    entries.append(np.asarray(ordinary_entries))
            return sparse_from(entries, rows, columns,
                               (n_frames * width_total, n_frames * joints * 3))

        def interleave_rows(blocks, n_samples):
            # Reorder section-stacked rows into the residual's per-sample
            # interleaved layout. Blocks are (width, offset inside a composite
            # section, source base, composite per-sample width).
            total = sum(width for width, _, _, _ in blocks)
            order = np.empty((n_samples, total), dtype=int)
            off = 0
            for width, inside, base, source_width in blocks:
                sample = np.arange(n_samples, dtype=int)[:, None]
                if inside is None:
                    order[:, off:off + width] = base + sample * width + np.arange(width)[None, :]
                else:
                    order[:, off:off + width] = base + sample * source_width + inside + np.arange(width)[None, :]
                off += width
            return order.ravel()

        pre = (cached_rows['keyframe_pre'] if cached_rows is not None
               else keyframe_pre_rows(candidate, contact_weight))
        mid = (cached_rows['keyframe_mid'] if cached_rows is not None
               else keyframe_mid_rows(candidate))
        post = (cached_rows['keyframe_post'] if cached_rows is not None
                else keyframe_post_rows(candidate, grip_weight, contact_weight))
        base_anat = (cached_rows['anatomy'] if cached_rows is not None
                     else anatomy_rows(unconstrained_candidate))
        w_pre, w_mid, w_post = pre.shape[1], mid.shape[1], post.shape[1]
        w_key = w_pre + w_mid + w_post
        wan = base_anat.shape[1]
        w_key_total = w_key + wan

        def keyframe_composite(points, unconstrained):
            return np.concatenate([
                pre if points is candidate else keyframe_pre_rows(points, contact_weight),
                mid if points is candidate else keyframe_mid_rows(points),
                post if points is candidate else keyframe_post_rows(points, grip_weight, contact_weight),
                base_anat if unconstrained is unconstrained_candidate else anatomy_rows(unconstrained),
            ], axis=1)
        base_key = (np.concatenate([pre, mid, post, base_anat], axis=1)
                    if cached_rows is not None
                    else keyframe_composite(candidate, unconstrained_candidate))
        wrp = 3 * len(rig.active)
        wp_stride = w_key + wan + wrp
        keyframe_phase_previous = None
        if timed_foot_articulation_tracks:
            keyframe_phase_previous = np.full(base_key.shape, -1, dtype=int)
            phase_start = 7 * joints + len(specs)
            for track_index, (label, _, _) in enumerate(timed_foot_articulation_tracks):
                if not label.endswith('_knee'):
                    continue
                for frame_index in range(count):
                    if cyclic:
                        previous_frame = (frame_index - 1) % count
                    elif frame_index:
                        previous_frame = frame_index - 1
                    else:
                        continue
                    keyframe_phase_previous[frame_index, phase_start + track_index] = previous_frame
        J_key_mixed = colored_composite_probe(
            keyframe_composite, base_key, [candidate, unconstrained_candidate],
            [(0, w_key, 0), (w_key, w_key_total, 1)],
            2 if keyframe_phase_previous is not None else 1,
            # residual per-frame layout: [pre | rotation_prior | mid | anatomy | post]
            np.concatenate([np.arange(w_pre),
                            w_pre + wrp + np.arange(w_mid),
                            w_pre + wrp + w_mid + wan + np.arange(w_post),
                            w_pre + wrp + w_mid + np.arange(wan)]),
            0, wp_stride, previous_sample_rows=keyframe_phase_previous)
        keyframe_samples = base_key.shape[0]
        sample_rows = np.arange(keyframe_samples * w_key_total).reshape(keyframe_samples, w_key_total)
        # Chain constrained-decode rows through fk and unconstrained rows
        # (anatomy) through fk_unc, splitting by the composite's column
        # ranges and restoring each row to its composite position (the two
        # row sets partition every composite row).
        key_point_rows = sample_rows[:, :w_key].ravel()
        key_anat_rows = sample_rows[:, w_key:].ravel()
        J_key_chain = vstack([
            J_key_mixed[key_point_rows] @ fk,
            J_key_mixed[key_anat_rows] @ fk_unc], format='csr')[
                np.argsort(np.concatenate([key_point_rows, key_anat_rows]))]

        def rotation_prior_rows(point_coordinates):
            return .01*(initial_rotations.inv()*Rotation.from_rotvec(
                point_coordinates[:, 3:].reshape(-1, 3))).as_rotvec().reshape(count, -1)
        base_rp = rotation_prior_rows(coordinates)
        n_rot = len(rig.active)
        rp_rows, rp_columns, rp_entries = [], [], []
        # SO(3) log rows of a joint read only that joint's rotation vector,
        # so one probe per component covers every joint exactly.
        for comp in range(3):
            check_optimizer_budget()
            probes = coordinates.copy()
            probes[:, 3 + comp::3] += fd_step
            diff = (rotation_prior_rows(probes) - base_rp) / fd_step
            fr, out = np.nonzero(diff)
            rp_rows.append(fr * (3 * n_rot) + out)
            rp_columns.append(fr * rig.width + 3 + 3 * (out // 3) + comp)
            rp_entries.append(diff[fr, out])
        J_rp = sparse_from(rp_entries, rp_rows, rp_columns, (count * 3 * n_rot, count * rig.width))

        wrp = base_rp.shape[1]
        J_pf = vstack([J_key_chain, J_rp], format='csr')[np.concatenate([
            interleave_rows((
                (w_pre, 0, 0, w_key_total),
                (wrp, None, count * w_key_total, None),
                (w_mid, w_pre, 0, w_key_total),
                (wan, w_key, 0, w_key_total),
                (w_post, w_pre + w_mid, 0, w_key_total),
            ), count)])]

        # The linear temporal rows are exact stencils over points: row
        # (k, joint, comp) is a frame-stencil gain times the root-relative
        # (or root-only) point components. Settling and orientation are
        # nonlinear (body axes mix components), so they stay on probes whose
        # frames are recoverable arithmetically from the row index.
        J3 = joints * 3
        point_idx = np.arange(J3)
        root_cols = rig.root * 3 + (point_idx % 3)
        root_removed = eye(J3, format='csr') - csr_matrix(
            (np.ones(J3), (point_idx, root_cols)), shape=(J3, J3))
        accel_gain = 10. / np.repeat(acceleration_fit_scale, 3)
        root_factor = 4. if body_support.get('required') else 1.
        J_accel_pt = kron(d2, csr_matrix(np.diag(accel_gain)) @ root_removed)
        J_jerk_pt = kron(d3, csr_matrix(np.diag(np.full(J3, (fps * .10) ** 3 / scale))) @ root_removed)
        J_root_acc_pt = kron(d2, csr_matrix(
            (np.full(3, root_factor * (fps * .10) ** 2 * np.sqrt(joints) / scale),
             (np.arange(3), rig.root * 3 + np.arange(3))), shape=(3, J3)))
        J_root_jerk_pt = kron(d3, csr_matrix(
            (np.full(3, root_factor * (fps * .07) ** 3 * np.sqrt(joints) / scale),
             (np.arange(3), rig.root * 3 + np.arange(3))), shape=(3, J3)))
        world_gain = 10. / (TEMPORAL_FIT_TARGET_RATIO * jerk_limit * np.sqrt(world_d3.shape[0] * J3))
        J_world_pt = kron(world_d3, csr_matrix(np.diag(np.full(J3, world_gain))))

        base_so = np.r_[settling_rows(candidate), orientation_rows(candidate)]
        L_s = settling_rows(candidate).size
        X_s = max(L_s // max(count - 1, 1), 1)
        # d2/d3 are wrap stencils on cyclic clips (count rows); settling's
        # plain diff always has count-1 rows.
        orient_rows = d2.shape[0]
        X_o = max((base_so.size - L_s) // max(orient_rows, 1), 1)
        if (base_so.size - L_s) % max(orient_rows, 1) or L_s % max(count - 1, 1):
            raise RuntimeError(f'settle/orient layout mismatch: L_s {L_s} L_o {base_so.size - L_s} count {count} d2 {d2.shape} d3 {d3.shape} cyclic {cyclic}')
        # residual temporal layout: [accel | jerk | settling | root_acc | root_jerk | orient]
        so_row0 = (count * wp_stride + J_accel_pt.shape[0] + J_jerk_pt.shape[0])
        so_pattern = pattern_joint_support(so_row0 + np.arange(base_so.size))
        supports_so = []
        for j in range(joints):
            check_optimizer_budget()
            probes = candidate.copy()
            probes[:, j, :] += fd_step
            directional = (np.r_[settling_rows(probes), orientation_rows(probes)] - base_so) != 0.
            supports_so.append(so_pattern[:, j] | directional)
        so_rows, so_cols, so_entries = [], [], []
        orientation_frame_colors, orientation_color_count = (
            _cyclic_frame_probe_colors(count) if cyclic
            else (np.arange(count, dtype=int) % 3, 3)
        )
        for group in joint_colors(supports_so):
            for comp in range(3):
                for c in range(orientation_color_count):
                    check_optimizer_budget()
                    frames = np.flatnonzero(orientation_frame_colors == c)
                    probes = candidate.copy()
                    for j in group:
                        probes[frames, j, comp] += fd_step
                    diff = (np.r_[settling_rows(probes), orientation_rows(probes)] - base_so) / fd_step
                    for j in group:
                        hit = np.nonzero(np.where(supports_so[j], diff, 0.))[0]
                        if not hit.size:
                            continue
                        frames_hit = np.empty(hit.size, dtype=int)
                        settle_mask = hit < L_s
                        ks = hit[settle_mask] // X_s
                        # Select the unique probed frame from each stencil.
                        # Cyclic color classes reserve distinct colors for the
                        # tail when count is not divisible by three, avoiding
                        # a two-frame perturbation in stencils that cross 0.
                        settle_stencils = np.column_stack((ks, ks + 1))
                        settle_matches = orientation_frame_colors[settle_stencils] == c
                        frames_hit[settle_mask] = settle_stencils[
                            np.arange(ks.size), settle_matches.argmax(axis=1)]
                        ko = (hit[~settle_mask] - L_s) // X_o
                        orient_stencils = np.column_stack(
                            (ko % count, (ko + 1) % count, (ko + 2) % count))
                        orient_matches = orientation_frame_colors[orient_stencils] == c
                        frames_hit[~settle_mask] = orient_stencils[
                            np.arange(ko.size), orient_matches.argmax(axis=1)]
                        so_rows.append(hit)
                        so_cols.append((frames_hit * joints + j) * 3 + comp)
                        so_entries.append(diff[hit])
        J_settle_orient = sparse_from(so_entries, so_rows, so_cols,
                                      (base_so.size, count * joints * 3))
        J_temporal = vstack([J_accel_pt, J_jerk_pt, J_settle_orient[:L_s],
                             J_root_acc_pt, J_root_jerk_pt, J_settle_orient[L_s:]],
                            format='csr') @ fk
        J_world = J_world_pt @ fk

        if cached_rows is not None:
            section_widths = cached_rows['subframeSectionWidths']
            w_sub_pts = sum(section_widths)
            base_sub_anat = cached_rows['subframeAnatomy']
            base_sub = cached_rows['subframe']
            w_sub_anat = base_sub_anat.shape[1]
            w_sub_total = base_sub.shape[1]
            base_sub_points = base_sub[:, :w_sub_pts]
        else:
            sub_sections_list = subframe_point_sections(subframe, contact_weight, grip_weight)
            section_widths = tuple(section.shape[1] for section in sub_sections_list)
            base_sub_anat = subframe_anatomy_rows(unconstrained_subframe)
            w_sub_pts = sum(section.shape[1] for section in sub_sections_list)
            w_sub_anat = base_sub_anat.shape[1]
            w_sub_total = w_sub_pts + w_sub_anat
            base_sub_points = np.concatenate(sub_sections_list, axis=1)

        def subframe_composite(points, unconstrained):
            return np.concatenate([
                base_sub_points if points is subframe else subframe_point_rows(points, contact_weight, grip_weight),
                base_sub_anat if unconstrained is unconstrained_subframe else subframe_anatomy_rows(unconstrained),
            ], axis=1)
        if cached_rows is None:
            base_sub = subframe_composite(subframe, unconstrained_subframe)
        check_optimizer_budget()
        # Both the composite and residual append anatomy after point rows.
        sub_col_offsets = np.arange(w_sub_total)
        row_t = (J_accel_pt.shape[0] + J_jerk_pt.shape[0] + L_s
                 + J_root_acc_pt.shape[0] + J_root_jerk_pt.shape[0] + base_so.size - L_s)
        J_sub_mixed = colored_composite_probe(
            subframe_composite, base_sub, [subframe, unconstrained_subframe],
            [(0, w_sub_pts, 0), (w_sub_pts, w_sub_total, 1)], 1,
            sub_col_offsets, count * wp_stride + row_t, w_sub_total)
        subframe_samples = base_sub.shape[0]
        sub_rows = np.arange(subframe_samples * w_sub_total).reshape(subframe_samples, w_sub_total)
        J_hermite_rows, J_hermite_columns, J_hermite_entries = [], [], []
        def collect_hermite(diff, c, columns_of):
            ir, out = np.nonzero(diff)
            if not ir.size:
                return
            # This class probe is unambiguous for non-collision cursors; wrap
            # cursors with colliding classes are collected from single-frame
            # probes below.
            stencil_frames = neighbors[ir]
            match = stencil_frames % 4 == c
            keep = np.flatnonzero(match.any(axis=1))
            if not keep.size:
                return
            ir, out = ir[keep], out[keep]
            keep_non_collision = ~hermite_collision_cursors[ir]
            ir, out = ir[keep_non_collision], out[keep_non_collision]
            if not ir.size:
                return
            stencil_frames = neighbors[ir]
            match = stencil_frames % 4 == c
            frames_hit = stencil_frames[
                np.arange(ir.size), match.argmax(axis=1)
            ]
            J_hermite_rows.append(ir * rig.width + out)
            J_hermite_columns.append(frames_hit * rig.width + columns_of(out))
            J_hermite_entries.append(diff[ir, out])

        for c in range(4):
            frames = np.arange(c, count, 4)
            for comp in range(3):
                check_optimizer_budget()
                probes = coordinates.copy()
                probes[frames, comp] += fd_step
                diff = (sample_rig_coordinates(
                    {**playback_rig, 'coordinates': probes}, subframe_cursors, wrap=cyclic)
                    - subframe_coordinates) / fd_step
                collect_hermite(diff, c, lambda out, comp=comp: np.full(out.shape, comp))
            # Rotation joints are per-joint decoupled in the interpolant, so
            # all joints batch per component; each responding output row maps
            # back to its own joint's perturbed column.
            for comp in range(3):
                check_optimizer_budget()
                probes = coordinates.copy()
                probes[frames[:, None], (3 + comp + 3 * np.arange(n_rot))[None, :]] += fd_step
                diff = (sample_rig_coordinates(
                    {**playback_rig, 'coordinates': probes}, subframe_cursors, wrap=cyclic)
                    - subframe_coordinates) / fd_step
                collect_hermite(diff, c, lambda out, comp=comp: np.where(
                    out < 3, 3 + comp, 3 + 3 * ((out - 3) // 3) + comp))
        if np.any(hermite_collision_cursors):
            collision_frames = np.unique(neighbors[hermite_collision_cursors])

            def collect_hermite_collision(diff, frame, columns_of):
                ir, out = np.nonzero(diff)
                if not ir.size:
                    return
                keep = hermite_collision_cursors[ir] & np.any(
                    neighbors[ir] == frame, axis=1
                )
                ir, out = ir[keep], out[keep]
                if not ir.size:
                    return
                J_hermite_rows.append(ir * rig.width + out)
                J_hermite_columns.append(
                    np.full(ir.size, frame * rig.width) + columns_of(out)
                )
                J_hermite_entries.append(diff[ir, out])

            for frame in collision_frames:
                frame = int(frame)
                for comp in range(3):
                    check_optimizer_budget()
                    probes = coordinates.copy()
                    probes[frame, comp] += fd_step
                    diff = (sample_rig_coordinates(
                        {**playback_rig, 'coordinates': probes},
                        subframe_cursors,
                        wrap=cyclic,
                    ) - subframe_coordinates) / fd_step
                    collect_hermite_collision(
                        diff, frame, lambda out, comp=comp: np.full(out.shape, comp)
                    )
                for comp in range(3):
                    check_optimizer_budget()
                    probes = coordinates.copy()
                    probes[frame, 3 + comp::3] += fd_step
                    diff = (sample_rig_coordinates(
                        {**playback_rig, 'coordinates': probes},
                        subframe_cursors,
                        wrap=cyclic,
                    ) - subframe_coordinates) / fd_step
                    collect_hermite_collision(
                        diff,
                        frame,
                        lambda out, comp=comp: np.where(
                            out < 3, 3 + comp, 3 + 3 * ((out - 3) // 3) + comp
                        ),
                    )
        J_hermite = sparse_from(J_hermite_entries, J_hermite_rows, J_hermite_columns,
                                (subframe_count * rig.width, count * rig.width))
        check_optimizer_budget()
        fk_sub = rig.fk_jacobian(subframe_coordinates)
        check_optimizer_budget()
        fk_sub_unc = rig.fk_jacobian(subframe_coordinates, project_socket=False)
        # Same split-and-restore as the keyframe composite: the two row sets
        # partition every composite row, so argsort restores the residual's
        # per-cursor interleaving exactly.
        sub_point_rows = sub_rows[:, :w_sub_pts].ravel()
        sub_anat_rows = sub_rows[:, w_sub_pts:].ravel()
        J_sub_src = vstack([
            J_sub_mixed[sub_point_rows] @ fk_sub,
            J_sub_mixed[sub_anat_rows] @ fk_sub_unc], format='csr')[
                np.argsort(np.concatenate([sub_point_rows, sub_anat_rows]))] @ J_hermite
        # point_rows appends subframe anatomy after the point sections, so the
        # composite row order already matches the residual exactly.
        J_sub = J_sub_src

        parts = [J_pf, J_temporal, J_sub]
        if cyclic:
            check_optimizer_budget()
            def seam_flat(points):
                closure, excess, velocity = seam_rows(points)
                return np.r_[closure.ravel(), excess.ravel(), velocity.ravel()]
            base_seam = seam_flat(candidate)
            seam_rows_idx, seam_cols_idx, seam_entries = [], [], []
            for frame in (0, 1, count - 2, count - 1):
                check_optimizer_budget()
                for j in range(joints):
                    for comp in range(3):
                        probes = candidate.copy()
                        probes[frame, j, comp] += fd_step
                        diff = (seam_flat(probes) - base_seam) / fd_step
                        dr = np.nonzero(diff)[0]
                        if not dr.size:
                            continue
                        seam_rows_idx.append(dr)
                        seam_cols_idx.append(np.full(dr.size, (frame * joints + j) * 3 + comp))
                        seam_entries.append(diff[dr])
            parts.append(sparse_from(seam_entries, seam_rows_idx, seam_cols_idx,
                                     (base_seam.size, count * joints * 3)) @ fk)
        parts.append(J_world)
        if source_projection_constraint.get('available'):
            check_optimizer_budget()
            parts.append(_source_projection_fit_jacobian(
                source_projection_constraint,
                frame_count=count,
                joint_count=joints,
                rig=rig,
                coordinates=coordinates,
                fk_jacobian=fk,
            ))
            parts.append(_source_support_relative_fit_jacobian(
                source_projection_constraint,
                frame_count=count,
                joint_count=joints,
                rig=rig,
                coordinates=coordinates,
                fk_jacobian=fk,
            ))
            parts.append(_source_endpoint_posture_fit_jacobian(
                source_projection_constraint,
                frame_count=count,
                joint_count=joints,
                rig=rig,
                coordinates=coordinates,
                fk_jacobian=fk,
            ))
        check_optimizer_budget()
        return vstack(parts, format='csr')

    solver_options = {}
    if hybrid_jacobian_enabled:
        solver_options['local_jacobian'] = hybrid_jacobian
        report['hybridJacobian'] = True
    def fit_tail_jacobian(values):
        parts = []
        if support_range_fit_tracks:
            parts.append(support_range_jacobian(values, rig, support_range_fit_tracks))
        coordinates = np.asarray(values).reshape(count, rig.width)
        parts.append(root_travel_preservation_jacobian(
            coordinates[:, :3], target[:, rig.root], body_scale=scale,
            coordinate_width=rig.width))
        parts.append(world_jerk_feasibility_jacobian(
            coordinates, rig, world_d3, jerk_fit_target))
        return vstack(parts, format='csr')

    solver_options['tail_jacobian'] = fit_tail_jacobian

    trajectory_solver = partial(solve_trajectory, **solver_options) if solver_options else solve_trajectory
    try:
        if fit_should_yield_for_priority() or monotonic()-started > timeout_seconds:
            raise TimeoutError
        # Soft LS must leave room for first validation and the normal polish window.
        # Keep the full reserve (do not shrink with leftover); conditional plant
        # polish can use any time left after those protected phases.
        outer_remaining = max(0., started + timeout_seconds - monotonic())
        polish_left = min(float(reserved_polish), max(0., outer_remaining - 20.))
        if cyclic and outer_remaining >= 8.:
            # Cyclic near-miss seam closure needs a real Stage-B/C window after solve.
            polish_left = max(polish_left, min(float(reserved_polish), min(20., 0.25 * outer_remaining)))
        polish_left = max(polish_left, min(12., max(0., outer_remaining - 30.))) if outer_remaining >= 40. else polish_left
        initial_points = rig.decode(rig.initial)
        # Rig feasibility belongs to the observed pose. Comparing against the
        # smoothed target needlessly refits already clean, small articulations
        # and can introduce solver noise larger than their original jerk.
        already_rigid = np.max(abs(initial_points-points)) < 1e-7
        already_smooth = np.max(np.linalg.norm(np.diff(initial_points,n=3,axis=0),axis=-1))*(fps/30.)**3 < .00003*scale
        anchored = np.max(np.linalg.norm((initial_points-contact_targets)[pinned],axis=-1),initial=0.) < PLAYBACK_CONTACT_LIMIT_METERS
        playback_anchored = _playback_contact_sample_error(
            rig.initial, rig, pinned, contact_targets, cyclic=cyclic) < PLAYBACK_CONTACT_LIMIT_METERS
        plant_polish = 22. if (
            np.any(pinned) and not playback_anchored
            and report.get('supportInitializationStrategy') == 'plant_projection'
        ) else 0.
        height_anchored = np.max(np.abs(
            (initial_points[:, :, 1] - height_only_targets[:, :, 1])[height_only_mask]
        ), initial=0.) <= PLAYBACK_FLOOR_LIMIT_METERS
        playback_height_anchored = _playback_vertical_contact_sample_error(
            rig.initial, rig, height_only_mask, height_only_targets, cyclic=cyclic,
        ) <= PLAYBACK_FLOOR_LIMIT_METERS
        playback_support_geometry_passed = _playback_support_geometry_passed(
            rig.initial, rig, payload, cyclic=cyclic)
        floor_clear = _playback_floor_penetration(
            rig.initial, rig, cyclic=cyclic, floor=floor) <= PLAYBACK_FLOOR_LIMIT_METERS
        source_support_initial = _source_support_relative_fit_evidence(
            initial_points, source_projection_constraint,
        )
        report['sourceSupportTrajectoryInitial'] = source_support_initial
        already_valid = (not cyclic and already_rigid and already_smooth and anchored
                         and height_anchored and playback_height_anchored
                         and playback_support_geometry_passed
                         and source_support_initial['passed']
                         and playback_anchored and floor_clear
                         and validate_physical_motion(initial_points,names,fps=fps)['passed']
                         and validate_grip(initial_points,names,equipment)['passed'])
        geometry_ready = supported_geometry_ready_for_skip_soft_solve(
            anchored=anchored, playback_anchored=playback_anchored, floor_clear=floor_clear,
            points=initial_points, names=names, equipment=equipment, payload=payload,
            support_strategy=report.get('supportInitializationStrategy'),
            playback_support_geometry_passed=playback_support_geometry_passed,
            source_support_trajectory_passed=source_support_initial['passed'])
        geometry_ready = geometry_ready and height_anchored and playback_height_anchored
        nominal_solve = max(45., min(150., 1.25 * float(count)))
        # Protect the ordinary polish window from the solve. Mid-sample plant
        # polish remains opportunistic; reserving its full 22s here can starve
        # the main fit before we know whether that extra window is needed.
        post_validation_polish_reserve = max(float(polish_left), 12.)
        optimization_deadline, solve_phase_budget = fit_soft_solve_deadline(
            fit_started=started,
            timeout_seconds=timeout_seconds,
            now=monotonic(),
            nominal_solve_seconds=nominal_solve,
            validation_reserve_seconds=validation_reserve,
            post_validation_polish_seconds=post_validation_polish_reserve,
        )
        report['solvePhaseBudgetSeconds'] = float(solve_phase_budget)
        report['polishReserveRemainingSeconds'] = float(polish_left)
        report['postValidationPolishReserveSeconds'] = float(post_validation_polish_reserve)
        report['conditionalPlantPolishSeconds'] = float(plant_polish)
        if (already_valid or geometry_ready) and not heel_contacts.pairs:
            # Avoid introducing solver noise into an already controlled / supported
            # rig. Soft LS on long plant-only clips raised jerk and ate Stage-C.
            solved = SimpleNamespace(x=rig.initial.ravel(),nfev=0)
            report['skippedSoftSolve'] = (
                'already_valid' if already_valid else 'supported_geometry_ready')
            # Hard Stage-A/C only after a geometry-ready skip — leave room for
            # one playback/grip polish pass, not a soft-LS-sized leftover.
            polish_left = min(float(polish_left), 18.)
        else:
            solve_start = rig.initial.ravel()
            if fit_session is not None and trajectory_key in fit_session.trajectories:
                proposal = np.asarray(fit_session.trajectories[trajectory_key], dtype=float)
                if proposal.shape == solve_start.shape and np.isfinite(proposal).all():
                    initial_error, proposed_error = residual(solve_start), residual(proposal)
                    if proposed_error@proposed_error <= initial_error@initial_error:
                        solve_start = proposal
                        report['resumedTrajectory'] = True
            # Keep one trust-region lifecycle for this fixed objective. Restarting
            # least_squares in short blocks can repeat rejected trials at the same x.
            current = solve_start
            solved = SimpleNamespace(x=current, nfev=0, status=1)
            minimum_update_seconds = 0.
            if int(max_evaluations) <= 0:
                report['optimizerTermination'] = 'evaluation_limit'
            elif monotonic() >= optimization_deadline - 1.0:
                report['optimizerTermination'] = 'solve_phase_budget'
                polish_left += max(0., optimization_deadline - monotonic())
            else:
                block_started = monotonic()
                solved = trajectory_solver(
                    residual, current, pattern, int(max_evaluations))
                block_evaluations = int(solved.nfev or max_evaluations)
                minimum_update_seconds = 2. * (monotonic() - block_started) / max(1, block_evaluations)
                if allow_refinement and minimum_update_seconds > 0.:
                    stage_c_minimum_remaining = stage_fit_refinement_minimum_remaining_seconds(
                        minimum_update_seconds, stage='C', prioritize_fit=True,
                    )
                    outer_remaining_after_block = max(
                        0., started + timeout_seconds - monotonic())
                    available_post_validation = max(
                        0., outer_remaining_after_block - validation_reserve)
                    requested_post_validation_reserve = max(
                        post_validation_polish_reserve, stage_c_minimum_remaining)
                    post_validation_polish_reserve = min(
                        requested_post_validation_reserve, available_post_validation)
                    polish_left = min(
                        max(float(polish_left), stage_c_minimum_remaining),
                        available_post_validation,
                    )
                    unfunded_stage_c_reserve = max(
                        0., stage_c_minimum_remaining - post_validation_polish_reserve)
                    report['stageCMinimumPostValidationSeconds'] = float(
                        stage_c_minimum_remaining)
                    report['stageCUnfundedPostValidationSeconds'] = float(
                        unfunded_stage_c_reserve)
                    report['polishReserveRemainingSeconds'] = float(polish_left)
                    report['postValidationPolishReserveSeconds'] = float(
                        post_validation_polish_reserve)
                    if unfunded_stage_c_reserve > 1e-6:
                        report['stageCPolishReservationStatus'] = 'unfunded_within_outer_budget'
                solved.nfev = block_evaluations
                if getattr(solved, 'status', 0) > 0:
                    report['optimizerTermination'] = 'converged'
                else:
                    report['optimizerTermination'] = (
                        'solve_phase_budget' if monotonic() >= optimization_deadline
                        else 'evaluation_limit')
            preferred = (
                best_feasible_coordinates
                if best_feasible_coordinates is not None else best_coordinates)
            if preferred is not None:
                if (best_feasible_coordinates is not None
                        and best_coordinates is not None
                        and best_feasible_coordinates is not best_coordinates):
                    report['selectedContactFeasibleIterate'] = True
                solved = SimpleNamespace(x=preferred, nfev=getattr(solved, 'nfev', 0),
                                         status=getattr(solved, 'status', 0))
    except TimeoutError:
        # A budget ends optimization, not validation. Prefer the best soft-LS
        # iterate; if none was scored yet, still try the initialized rig rather
        # than discarding all pre-solve work as a bare fit_timeout.
        preferred = (
            best_feasible_coordinates
            if best_feasible_coordinates is not None else best_coordinates)
        if preferred is None:
            fallback = np.asarray(rig.initial, dtype=float).ravel()
            if fallback.size and np.isfinite(fallback).all():
                preferred = fallback.copy()
                report['validatedInitializedCoordinatesOnTimeout'] = True
            else:
                return payload,{**report,'reason':'fit_timeout','elapsedSeconds':monotonic()-started}
        if (best_feasible_coordinates is not None
                and best_coordinates is not None
                and best_feasible_coordinates is not best_coordinates):
            report['selectedContactFeasibleIterate'] = True
        solved = SimpleNamespace(x=preferred, nfev=None, status=0)
        # Solve-phase caps leave outer candidate time for short polish of
        # repairable near-misses; only the true outer deadline is time_budget.
        outer_deadline = started + timeout_seconds
        report['optimizerTermination'] = (
            'time_budget' if monotonic() >= outer_deadline - post_validation_polish_reserve
            - validation_reserve
            else 'solve_phase_budget')
    finally:
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = (
                best_feasible_coordinates if best_feasible_coordinates is not None
                else best_coordinates).tolist()
    if getattr(solved, 'status', 1) == 0:
        report.setdefault('optimizerTermination', 'evaluation_limit')
    spike_projection_inputs = set()

    def validate_solution(solved, *, project_playback_plants=True, repair_deadline=None,
                          contact_foot_tracks=None):
        # A finite soft-constrained solve can cross the socket boundary again after
        # initialization. Enforce its analytic attachment on the exported coordinates
        # too, then validate geometry, temporal quality and interpolated playback.
        # project_playback_plants=False means the caller already owns mid-sample
        # plants / C1 continuity — do not re-run floor clearance or playback TRF
        # that recreate knot velocity jumps.
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        repair_deadline = min(
            polish_until if repair_deadline is None else float(repair_deadline),
            started + timeout_seconds,
        )
        rig.initial[:] = solved.x.reshape(count, rig.width)
        unprojected = rig.decode(rig.initial)
        # Neck / numerical anatomy projection can reintroduce C1 knot jumps after
        # velocity continuity repair — skip when the caller owns the path.
        if project_playback_plants:
            rig.project_neck_attachment(
                maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
            # Interpolated socket clearance changes the pelvis-to-neck axis.
            # Establish it before anatomy polish so a tiny neck correction cannot
            # reopen an already boundary-tight spine constraint afterward.
            rig.initial[:] = project_playback_neck_clearance(
                rig.initial, rig, cyclic=cyclic, deadline=repair_deadline)
            numerical_errors, _ = repair_residuals(
                rig.decode(rig.initial), names, reference=fit_anatomy_reference)
            largest_error = float(np.max(numerical_errors, initial=0.))
            if 1e-6 < largest_error <= ANATOMY_FIT_MARGIN and monotonic() < repair_deadline:
                previous_coordinates, previous_offsets = rig.initial.copy(), rig.offsets.copy()
                polish_started = monotonic()
                try:
                    _, polish = repair_rig_anatomy(
                        rig, rig.decode(rig.initial), deadline=repair_deadline,
                        reference=fit_anatomy_reference)
                except TimeoutError:
                    polish = {'passed': False, 'reason': 'time_budget'}
                polish['elapsedSeconds'] = monotonic()-polish_started
                report['numericalAnatomyPolish'] = polish
                if not polish['passed']:
                    rig.initial[:], rig.offsets[:] = previous_coordinates, previous_offsets
        solved.x = rig.initial.ravel().copy()
        result = rig.decode(rig.initial)
        report['finalSocketProjectionMaximumMeters'] = float(
            np.max(np.linalg.norm(result-unprojected, axis=-1)))
        fixed_rig_payload = {'version':1,'jointNames':names,'parents':rig.parents,'order':rig.order,
                             'offsets':rig.offsets.tolist(),'interpolation':INTERPOLATION,
                             'rotationJointNames':[names[j] for j in rig.active],
                             'coordinates':rig.initial.tolist()}
        if contact_foot_tracks is not None:
            fixed_rig_payload['contactFootTracks'] = deepcopy(contact_foot_tracks)
        if (project_playback_plants and monotonic() < repair_deadline
                and np.any(pinned) and _playback_failing_intervals(
                rig.initial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor)):
            # Support already spent a play pass on plant_projection; keep validate
            # repair short so Stage-C temporal still gets wall time.
            if report.get('supportPlaybackPlantsApplied') or report.get('skippedSoftSolve'):
                plant_cap = 28.0
                plant_nfev = 16
            else:
                plant_cap = 8.0
                plant_nfev = 12
            rig.initial[:] = project_interval_playback_plants(
                rig.initial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor,
                max_nfev=plant_nfev,
                deadline=min(repair_deadline, monotonic() + plant_cap), spike_reference=spike_reference)
            result = rig.decode(rig.initial)
            solved.x = rig.initial.ravel().copy()
            fixed_rig_payload['coordinates'] = rig.initial.tolist()
            report['validatePlaybackPlantsApplied'] = True
        spike_projection_digest = hashlib.sha256(
            np.ascontiguousarray(result).tobytes()).hexdigest()
        if (contact_foot_tracks is None and spike_projection_digest not in spike_projection_inputs
                and monotonic() < repair_deadline):
            spikes = relative_motion_quality(
                result, result, names, fps, spike_reference=spike_reference)['introducedSpikes']
            if spikes['severe'] and monotonic() < repair_deadline:
                spike_projection_inputs.add(spike_projection_digest)
                report['introducedSpikeProjectionAttempted'] = True
                report['introducedSpikesBeforeProjection'] = spikes
                rig.initial[:] = project_introduced_spikes_coordinates(
                    rig.initial, rig, pinned, contact_targets, spike_reference,
                    fps=fps, cyclic=cyclic, floor=floor,
                    deadline=min(repair_deadline, monotonic() + 16.))
                result = rig.decode(rig.initial)
                solved.x = rig.initial.ravel().copy()
                fixed_rig_payload['coordinates'] = rig.initial.tolist()
        floor_lift = 0.0
        if (project_playback_plants
                and not body_support.get('required')
                and not payload.get('elevatedSupportSurfaces')):
            rig.initial[:], floor_lift = apply_supported_floor_clearance(
                rig.initial, rig, pinned, contact_targets, floor, cyclic=cyclic)
            solved.x = rig.initial.ravel().copy()
            fixed_rig_payload['coordinates'] = rig.initial.tolist()
            result = rig.decode(rig.initial)
        report['unanchoredFloorClearanceLiftMeters'] = floor_lift
        # Root-rotation smoothing repair: the fit's root orientation DOFs can
        # wobble at movement frequency, adding torso-axis roughness the
        # sourceJoints reference does not have (measured 3-4x on ballistic
        # lifts; smoothing the spine tracks provably cannot remove it). Each
        # pass gaussian-smooths the root rotation columns and is accepted
        # only if the contact anchors still hold within the fit's own
        # keyframe standard and the rotation noise drops — escalate until
        # accepted or the pass budget ends.
        from .temporal_quality import body_orientation_noise as _body_noise
        _rotation_noise = _body_noise(result, names, spike_reference, fps)
        if contact_foot_tracks is None and _rotation_noise.get('severe'):
            _original = result.copy()
            _noise_before_smoothing = _rotation_noise
            _pinned_joints = [names.index(n) for n in
                              ('left_ankle', 'left_foot', 'right_ankle', 'right_foot')
                              if n in names]
            _sigma = max(1.0, fps * 0.05)
            _attempt_reports = []
            for _attempt in range(3):
                # Root-rotation smoothing displaces the planted joints; the
                # compensation is encoded in root travel so the accepted pose
                # and serialized fit coordinates agree.
                _candidate, _trial = _smooth_root_rotation_candidate(
                    rig, rig.initial, _original, _pinned_joints,
                    _sigma * (1. + 0.5 * _attempt))
                _after = _body_noise(_trial, names, spike_reference, fps)
                _contact = float(np.max(np.linalg.norm(
                    (_trial - contact_targets)[pinned], axis=-1), initial=0.))
                _accepted = not _after.get('severe') and _contact <= 0.0005
                _attempt_reports.append({
                    'sigmaFrames': round(_sigma * (1. + 0.5 * _attempt), 2),
                    'outputRmsDegreesAt30Hz': round(float(
                        _after.get('outputRmsDegreesAt30Hz') or 0.), 4),
                    'severe': bool(_after.get('severe')),
                    'maxPinnedContactErrorMeters': round(_contact, 7),
                    'accepted': _accepted,
                })
                if _accepted:
                    rig.initial[:] = _candidate
                    result = _trial
                    _rotation_noise = _after
                    report['rootRotationSmoothing'] = {
                        'applied': True,
                        'sigmaFrames': round(_sigma * (1. + 0.5 * _attempt), 2),
                        'passes': _attempt + 1,
                        'rmsBefore': round(float(_noise_before_smoothing.get('outputRmsDegreesAt30Hz') or 0.), 4),
                        'rmsAfter': round(float(_after.get('outputRmsDegreesAt30Hz') or 0.), 4),
                        'attempts': _attempt_reports,
                    }
                    break
            else:
                report['rootRotationSmoothing'] = {
                    'applied': False, 'reason': 'no_pass_satisfied_both_screens',
                    'rmsBefore': round(float(_noise_before_smoothing.get('outputRmsDegreesAt30Hz') or 0.), 4),
                    'attempts': _attempt_reports,
                }
        if contact_foot_tracks is None and monotonic() < repair_deadline:
            knee_projected, knee_projection_report = project_reliable_knee_hinge_planes(
                rig.initial, rig,
                (reference, pre_contact_articulation_reference, anatomical_reference),
                playback_reference=anatomical_reference, fps=fps, cyclic=cyclic,
                deadline=repair_deadline, max_passes=3)
            report['kneeHingePlaneProjection'] = knee_projection_report
            if knee_projection_report.get('applied'):
                rig.initial[:] = knee_projected
                result = rig.decode(rig.initial)
                solved.x = rig.initial.ravel().copy()
                fixed_rig_payload['coordinates'] = rig.initial.tolist()
        bilateral_support = np.all(pinned[:,[names.index(n) for n in ('left_ankle','left_foot','right_ankle','right_foot')]],axis=1)
        physical = validate_physical_motion(
            result, names, reference=source_conditioned_articulation_reference,
            anatomy_reference=fit_anatomy_reference,
            fps=fps, support_mask=bilateral_support)
        # Fixed-rig lengths are checked directly below; source per-frame length
        # fidelity is intentionally superseded, not anatomical/branch checks.
        source_events = physical['events']
        physical['events'] = [e for e in source_events if e['reason'] != 'repair_bone_length_distortion']
        physical['reasons'] = sorted({e['reason'] for e in physical['events']})
        physical['passed'] = not physical['events']
        lengths = np.array([np.linalg.norm(result[:,j]-result[:,rig.parents[j]],axis=1)
                            for j in rig.order[1:]])
        contact_error = float(np.max(np.linalg.norm((result-contact_targets)[pinned],axis=-1),initial=0.))
        height_contact_error = float(np.max(np.abs(
            (result[:, :, 1] - height_only_targets[:, :, 1])[height_only_mask]
        ), initial=0.))
        playback_height_contact_error = _playback_vertical_contact_sample_error(
            rig.initial, rig, height_only_mask, height_only_targets, cyclic=cyclic,
            contact_foot_tracks=contact_foot_tracks,
        )
        change = np.max(abs(np.stack([angles(*(result[:,i] for i in cols)) for _,cols,_ in specs],axis=1)-reference_angles))
        travel_before = np.linalg.norm(np.ptp(target[:,rig.root],axis=0))
        travel_after = np.linalg.norm(np.ptp(result[:,rig.root],axis=0))
        fit_error = float(np.sqrt(np.mean((result-target)**2)))
        source_camera = ((payload.get('sourcePoseCameraReference') or {}).get('camera') or {})
        trajectory_fit = trajectory_fit_evidence(
            result, target, names, scale, root_index=rig.root, pinned=pinned,
            support_evidence=fit_support_evidence,
            source_projection_constraint=source_projection_constraint,
            source_camera=source_camera,
        )
        report['trajectoryFitEvidence'] = trajectory_fit
        jerk_after = float(np.sqrt(np.mean(np.diff(result,n=3,axis=0)**2)))
        if jerk_after > jerk_limit:
            source_times = np.asarray([
                frame.get('sourceTimeSec', np.nan) for frame in frames
            ], dtype=float)
            jerk_evidence = third_difference_jerk_failure_evidence(
                result, jerk_basis, names, fps=fps, fit_times=times,
                source_times=source_times,
            )
            if jerk_evidence.get('available'):
                jerk_evidence['acceptanceLimitRms'] = float(jerk_limit)
                jerk_evidence['limitRatio'] = float(jerk_after / max(jerk_limit, 1e-12))
                report['jerkFailureEvidence'] = jerk_evidence
        target_span = np.linalg.norm(np.ptp(target-target[:,rig.root:rig.root+1],axis=0),axis=-1)
        result_span = np.linalg.norm(np.ptp(result-result[:,rig.root:rig.root+1],axis=0),axis=-1)
        moving = target_span > .1*scale
        if support_articulation_tracks:
            # Preserve articulation excursion independently of the fitted target.
            # Positional spans also encode torso placement/orientation, which the
            # observed support is explicitly allowed to correct.
            ratios = {label: float(np.ptp(angles(*(result[:, j] for j in cols)))/np.ptp(track))
                      for label, cols, track in support_articulation_tracks}
            episode_ratios, episode_details = supported_ankle_episode_range_ratios(
                support_articulation_reference, result, names,
                full_sole_excursion_masks, ankle_evidence_masks)
            for side in full_sole_excursion_masks:
                label = f'{side}_ankle'
                ratios.pop(label, None)
            ratios.update(episode_ratios)
            report['supportArticulationRangeRatios'] = ratios
            if episode_details:
                report['supportAnkleExcursionEpisodes'] = episode_details
        if body_support.get('required'):
            range_preserved = support_joint_range_preserved(ratios)
        else:
            range_preserved = bool(np.all(result_span[moving] >= .85*target_span[moving]))
        # Same authority as settling/jerk: under support, shake baselines belong
        # to the supported working reference, not the pre-support source.
        acceleration_after = np.sqrt(np.mean(np.diff(result,n=2,axis=0)**2,axis=(0,2)))
        shake_ratios = acceleration_after / np.maximum(shake_limits, 1e-12)
        no_new_shake = bool(np.all(shake_ratios <= 1.))
        settling_after = weighted_settling_speed(result, names, fps, hold_weights)
        settling_preserved = settling_after <= settling_limit
        relative_quality = relative_motion_quality(
            result, shake_basis, names, fps, spike_reference=spike_reference)
        root_quality = root_motion_quality(result[:,rig.root], fps, scale)
        root_travel_small = bool(
            travel_before < ROOT_TRAVEL_SMALL_MOTION_BODY_RATIO * scale)
        root_travel_shortfall = max(
            0., ROOT_TRAVEL_MINIMUM_PRESERVED_RATIO * travel_before - travel_after)
        root_travel_preserved = bool(
            root_travel_shortfall <= ROOT_TRAVEL_PRESERVATION_TOLERANCE_METERS)
        report['rootTravelEvidence'] = {
            'targetRangeMeters': float(travel_before),
            'fittedRangeMeters': float(travel_after),
            'preservedRatio': float(travel_after / max(travel_before, 1e-9)),
            'smallTravelAllowanceMeters': float(.05 * scale),
            'minimumPreservedRatio': ROOT_TRAVEL_MINIMUM_PRESERVED_RATIO,
            'preservationToleranceMeters': ROOT_TRAVEL_PRESERVATION_TOLERANCE_METERS,
            'preservationShortfallMeters': float(root_travel_shortfall),
            'smallTravelAllowancePassed': root_travel_small,
            'preservedRangePassed': root_travel_preserved,
        }
        source_support_trajectory = _source_support_relative_fit_evidence(
            result, source_projection_constraint,
        )
        report['sourceSupportTrajectory'] = source_support_trajectory
        report['sourceFootRay'] = _source_foot_ray_fit_evidence(result, source_projection_constraint)
        source_foot_phase = _source_foot_phase_fit_evidence(
            result, source_projection_constraint,
        )
        report['sourceFootHeelPhase'] = source_foot_phase
        report['sourceFootHeelTrajectory'] = {
            'available': bool(source_projection_constraint.get(
                'sourceFootHeelTrajectoryObservations')),
            'passed': True,
            'evaluation': 'pending_serialized_candidate',
            'observationCount': len(source_projection_constraint.get(
                'sourceFootHeelTrajectoryObservations') or []),
            'eventCount': len(source_projection_constraint.get(
                'sourceFootHeelTrajectoryEvents') or []),
        }
        foot_contact_owned = pinned_foot_contact_owned or bool(
            foot_contact_indices and np.any(height_only_mask[:, foot_contact_indices]))
        foot_articulation_regressions = (
            support_initialization_articulation_regressions(
                support_articulation_reference, result, names, fps=fps,
                ankle_excursion_masks=full_sole_excursion_masks,
                ankle_evidence_masks=ankle_evidence_masks)
            if foot_contact_owned else [])
        fit_subframe_coordinates = sample_rig_coordinates(
            {**playback_rig, 'coordinates': rig.initial}, subframe_cursors, wrap=cyclic)
        fit_subframe_points = rig.decode(fit_subframe_coordinates)
        fit_subframe_directions, fit_subframe_direction_masks = source_foot_direction_targets_at(
            subframe_first, subframe_last, subframe_alpha[:, 0, 0])
        source_foot_direction_evidence = _source_foot_direction_fit_evidence(
            np.concatenate([result, fit_subframe_points], axis=0),
            np.concatenate([source_foot_direction_targets, fit_subframe_directions], axis=0),
            np.concatenate([source_foot_direction_masks, fit_subframe_direction_masks], axis=0),
            names,
        )
        source_foot_direction_evidence['samplePolicy'] = 'fit_keys_and_quarterframes'
        if (source_projection_constraint.get('sourceFootHeelTrajectoryObservations')
                and not source_foot_direction_evidence['available']):
            source_foot_direction_evidence['passed'] = False
            source_foot_direction_evidence['reason'] = 'source_foot_direction_authority_unavailable'
        report['sourceFootContactArticulation'] = {
            'available': foot_contact_owned,
            'passed': (not bool(foot_articulation_regressions)
                       and source_foot_direction_evidence['passed']),
            'reference': 'source_shin_with_independently_observed_foot_direction',
            'fullSoleEpisodeMasks': {
                side: int(np.count_nonzero(mask))
                for side, mask in full_sole_excursion_masks.items()
            },
            'regressions': foot_articulation_regressions,
            'nativeHeelPhase': source_foot_phase,
            'sourceFootDirection': source_foot_direction_evidence,
        }
        patch_clock_failure = source_foot_patch_clock_failure(
            payload, fit_support_evidence)
        report['sourceFootPatchClock'] = patch_clock_failure or {
            'passed': True, 'reason': None}
        checks = {'anatomy':physical['passed'], 'contacts':contact_error<KEYFRAME_CONTACT_LIMIT_METERS,
                  'heightOnlyContacts': (
                      height_contact_error <= PLAYBACK_FLOOR_LIMIT_METERS
                      and playback_height_contact_error <= PLAYBACK_FLOOR_LIMIT_METERS),
                  'sourceArticulation':bool(change<np.deg2rad(20.)),
                  'trajectoryFit':trajectory_fit['passed'],
                  'rootTravel': root_travel_small or root_travel_preserved,
                  'jointRange':range_preserved, 'jointShake':no_new_shake, 'settling':settling_preserved,
                  'jerk':jerk_after<=jerk_limit,
                  'fixedRig':bool(np.max(np.ptp(lengths,axis=1))<1e-9),
                  'relativeJointShake':relative_quality['relativeJointShake'],
                  'bodyRotation':relative_quality['bodyRotation'],
                  'rootContinuity':root_quality['passed'],
                  'sourceFootPatchClock': patch_clock_failure is None,
                  'sourceFootContactArticulation': report['sourceFootContactArticulation']['passed']}
        equipment_report = validate_grip(result,names,equipment)
        checks['equipment'] = equipment_report['passed']
        report['bodySupport'] = validate_support_geometry(payload, result, names)
        checks['bodySupport'] = report['bodySupport']['passed']
        report['supportAlignment'] = validate_alignment(result, alignment_source, names, body_support)
        checks['supportAlignment'] = report['supportAlignment']['passed']
        checks['sourceSupportTrajectory'] = source_support_trajectory['passed']
        from .temporal_quality import track_discontinuity_metrics
        discontinuity = track_discontinuity_metrics({name: result[:, j].tolist() for j, name in enumerate(names)},
                                                    root_joint=names[rig.root], fps=fps,
                                                    body_height=float(np.median(np.linalg.norm(np.ptp(result, axis=1), axis=-1))))
        checks['motionDiscontinuity'] = discontinuity['available'] and not discontinuity['severe']
        report['motionDiscontinuity'] = discontinuity
        report['equipment'] = equipment_report
        accepted = all(checks.values())
        report.update(evidence=evidence,checks=checks,reason='validated_controlled_motion' if accepted else 'fit_validation_failed',
                      applied=bool(accepted),evaluations=solved.nfev,elapsedSeconds=monotonic()-started,
                      maximumBoneLengthVariationMeters=float(np.max(np.ptp(lengths,axis=1))),
                      maximumContactErrorMeters=contact_error,maximumArticulationChangeDegrees=float(np.rad2deg(change)),
                      maximumHeightOnlyContactErrorMeters=height_contact_error,
                      maximumPlaybackHeightOnlyContactErrorMeters=playback_height_contact_error,
                      targetRmsMeters=fit_error,
                      jointTargetRmsMeters={n:float(np.sqrt(np.mean((result[:,j]-target[:,j])**2))) for j,n in enumerate(names)},
                      jerkBefore=jerk_before,jerkAfter=jerk_after,
                      rangePreserved=range_preserved,noNewJointShake=no_new_shake,
                      jointShakeFailureEvidence=(
                          {
                              'failedJoints': [names[j] for j in np.flatnonzero(shake_ratios > 1.)],
                              'maximumLimitRatio': float(np.max(shake_ratios)),
                              'topLimitRatios': [
                                  {'joint': names[j], 'ratio': float(shake_ratios[j]),
                                   'accelerationBefore': float(acceleration_before[j]),
                                   'accelerationAfter': float(acceleration_after[j]),
                                   'limit': float(shake_limits[j])}
                                  for j in np.argsort(shake_ratios)[-5:][::-1]
                              ],
                          }
                          if not no_new_shake else None
                      ),
                      jointRangeRatios={names[j]:float(result_span[j]/target_span[j]) for j in np.flatnonzero(moving)},
                      settlingSpeedBefore=settling_before,settlingSpeedAfter=settling_after,settlingPreserved=settling_preserved,
                      settlingLimit=settling_limit,
                      relativeMotionQuality=relative_quality,
                      rootMotionQuality=root_quality,
                      physicalReasons=physical['reasons'],physicalEvents=physical['events'][:12],
                      balance=physical['balance'],balancePolicy='advisory_only',
                      maximumAnkleAnchorCalibrationMeters=ankle_anchor_calibration)
        if not accepted and getattr(solved, 'status', 1) == 0:
            term = report.get('optimizerTermination')
            # A finished check vector is a decisive reject. Optimizer
            # time_budget/eval caps are how the soft LS stopped — not missing
            # processing evidence. Only pre-validation aborts stay fit_timeout.
            if term in {'time_budget', 'solve_phase_budget', 'objective_stalled', 'converged'}:
                report['reason'] = 'fit_validation_failed'
            else:
                report['reason'] = 'fit_evaluation_limit'
        # Always build the export candidate and score playback/seam so polish and
        # diagnosis see the full acceptance vector (equipment must not hide seam).
        candidate = deepcopy(payload)
        candidate['equipmentConstraints'] = equipment
        if repaired_reference is not None:
            candidate['anatomicalSourceRepair'] = report['anatomicalSourceRepair']
            for frame, corrected in zip(candidate['frames'], repaired_reference):
                frame['correctedAnatomicalReferenceJoints'] = dict(zip(names, corrected.tolist()))
        candidate.pop('scenePlacement', None)
        for index, (frame,values,registered_source) in enumerate(zip(candidate['frames'],result,points)):
            if not (candidate.get('sourcePoseCameraReference') and frame.get('controlledSourceJoints')):
                frame['controlledSourceJoints']={n:v.tolist() for n,v in zip(names,registered_source)}
            # Same articulation reference keyframe anatomy acceptance uses.
            frame['controlledArticulationReferenceJoints'] = {
                n: v.tolist() for n, v in zip(
                    names, source_conditioned_articulation_reference[index])}
            frame['joints']={n:v.tolist() for n,v in zip(names,values)}
            # Preserve source-projection anchor adjustments in playback authority.
            frame['supportContactReferenceJoints'] = dict(zip(names, contact_targets[index].tolist()))
            if body_support.get('required'):
                frame['supportAlignmentReferenceJoints'] = dict(zip(names, alignment_source[index].tolist()))
                frame['supportCorrectedReferenceJoints'] = dict(zip(names, reference[index].tolist()))
                if not plant_only:
                    for name in body_support.get('stationaryJoints', []):
                        frame['supportContactReferenceJoints'][name] = support_pose[names.index(name)].tolist()
        candidate['fixedRig'] = fixed_rig_payload
        transport_corrected_bone_sides(frames,candidate)
        refresh_motion_bounds(candidate)
        from .scene_placement import normalize_scene_placement
        candidate = normalize_scene_placement(candidate)
        from .rig_playback import sample_rig as sample_playback_rig
        from scipy.spatial.transform import Rotation
        placement_rotation = np.asarray(
            (candidate.get('scenePlacement') or {}).get('rotationVector', [0., 0., 0.]),
            dtype=float)
        direction_rotation = Rotation.from_rotvec(placement_rotation)
        final_direction_targets = direction_rotation.apply(
            source_foot_direction_targets.reshape(-1, 3)).reshape(count, 2, 3)
        final_subframe_direction_targets, final_subframe_direction_masks = (
            source_foot_direction_targets_at(
                subframe_first, subframe_last, subframe_alpha[:, 0, 0]))
        final_subframe_direction_targets = direction_rotation.apply(
            final_subframe_direction_targets.reshape(-1, 3)).reshape(-1, 2, 3)
        direction_cursors = np.concatenate([
            np.arange(count, dtype=float), subframe_cursors])
        final_direction_points = sample_playback_rig(
            candidate['fixedRig'], direction_cursors, wrap=cyclic)
        final_direction_targets = np.concatenate([
            final_direction_targets, final_subframe_direction_targets], axis=0)
        final_direction_masks = np.concatenate([
            source_foot_direction_masks, final_subframe_direction_masks], axis=0)
        serialized_direction_evidence = _source_foot_direction_fit_evidence(
            final_direction_points, final_direction_targets, final_direction_masks,
            names)
        serialized_direction_evidence['samplePolicy'] = (
            'serialized_renderer_keys_and_quarterframes')
        if (source_projection_constraint.get('sourceFootHeelTrajectoryObservations')
                and not serialized_direction_evidence['available']):
            serialized_direction_evidence['passed'] = False
            serialized_direction_evidence['reason'] = 'source_foot_direction_authority_unavailable'
        report['sourceFootDirection'] = serialized_direction_evidence
        report['sourceFootContactArticulation']['sourceFootDirection'] = (
            serialized_direction_evidence)
        report['sourceFootContactArticulation']['passed'] = bool(
            report['sourceFootContactArticulation']['passed']
            and serialized_direction_evidence['passed'])
        report['checks']['sourceFootContactArticulation'] = report[
            'sourceFootContactArticulation']['passed']
        material_heel_evidence = _source_foot_material_heel_fit_evidence(
            candidate, source_projection_constraint)
        report['sourceFootHeelTrajectory'] = material_heel_evidence
        report['sourceFootContactArticulation']['materialHeelTrajectory'] = (
            material_heel_evidence)
        report['sourceFootContactArticulation']['passed'] = bool(
            report['sourceFootContactArticulation']['passed']
            and material_heel_evidence['passed'])
        report['checks']['sourceFootContactArticulation'] = report[
            'sourceFootContactArticulation']['passed']
        candidate.setdefault('loop',{'enabled':False})
        from .rig_playback import validate_rig_playback
        playback = validate_rig_playback(candidate)
        report['playback'] = playback
        report['checks']['playback'] = playback['passed']
        if cyclic:
            report['checks']['loopSeam'] = playback['seamContinuous']
        accepted = all(report['checks'].values())
        if not accepted:
            failed = set(failed_check_names(report['checks']))
            # Keep the seam failure visible to bounded Stage-B projection.
            # Declaring an open seam applied here bypasses that repair entirely.
            # The final fallback below retains usable open motion after polish.
            if not playback['passed'] and failed <= {'playback', 'loopSeam'}:
                report.update(applied=False, reason='playback_validation_failed')
            else:
                report.update(applied=False, reason='fit_validation_failed')
            return (candidate if failed <= {'loopSeam', 'playback'} else payload), report
        if candidate.get('loop',{}).get('enabled'):
            candidate['loop'] = {**candidate['loop'],'transition':'continuous',
                                 'restartFadeMillis':0}
        candidate.pop('sequenceStabilization', None)
        report['outputPoseDigest']=pose_digest(candidate)
        report.update(applied=True, reason='validated_controlled_motion')
        return candidate,report

    validation_started = monotonic()
    validation_repair_deadline = min(
        started + timeout_seconds - post_validation_polish_reserve,
        validation_started + validation_reserve,
    )
    # Initial validation has its own bounded repair window. Later Stage-A/B/C
    # work owns the remaining outer budget, so validation cannot spend it first.
    polish_until = validation_repair_deadline
    report['postValidationPolishReserveSeconds'] = float(post_validation_polish_reserve)
    report['initialValidationRepairDeadlineSeconds'] = float(
        validation_repair_deadline - started)
    report['initialValidationRepairBudgetSeconds'] = float(
        max(0., validation_repair_deadline - validation_started))
    candidate, report = validate_solution(
        solved, repair_deadline=validation_repair_deadline)
    polish_until = min(
        started + timeout_seconds,
        validation_repair_deadline + post_validation_polish_reserve + plant_polish,
    )
    report['initialValidationSeconds'] = monotonic() - validation_started
    report['polishUntilSeconds'] = float(polish_until - started)
    contact_heel_repair_attempted = False

    def attempt_contact_heel_repair():
        nonlocal solved, candidate, report, contact_heel_repair_attempted
        if (contact_heel_repair_attempted
                or not allow_refinement
        or not contact_heel_repair_eligible(
            report.get('checks'), report.get('jointRangeRatios'))
                or not source_projection_constraint.get('sourceFootHeelTrajectoryObservations')
                or monotonic() >= started + timeout_seconds
                or fit_should_yield_for_priority()):
            return
        contact_heel_repair_attempted = True
        from .contact_heel_repair import propose_contact_heel_repair
        previous_coordinates = rig.initial.copy()
        previous_offsets = rig.offsets.copy()
        previous_candidate, previous_report = candidate, deepcopy(report)
        previous_solved = solved
        local_started = monotonic()
        local_deadline = min(started + timeout_seconds, local_started + 45.)
        local_report = {'attempted': True, 'accepted': False}
        proposal_failure = {}
        try:
            proposal = propose_contact_heel_repair(
                rig, previous_coordinates, payload=payload,
                source_projection_constraint=source_projection_constraint,
                anatomical_reference=support_articulation_reference, pinned=pinned,
                fps=fps, cyclic=cyclic,
                deadline=local_deadline,
                jerk_reference=jerk_basis, shake_reference=shake_basis,
                jerk_limit=jerk_limit, body_scale=scale,
                failure_report=proposal_failure)
            if proposal is not None:
                if monotonic() >= local_deadline:
                    raise TimeoutError('contact heel proposal exhausted its validation budget')
                coordinates, tracks, details = proposal
                local_report.update(details)
                trial = SimpleNamespace(x=np.asarray(coordinates).ravel().copy(),
                                        nfev=solved.nfev, status=1)
                trial_candidate, trial_report = validate_solution(
                    trial, project_playback_plants=False,
                    contact_foot_tracks=tracks, repair_deadline=local_deadline)
                local_report['failedChecksAfter'] = failed_check_names(trial_report.get('checks'))
                if trial_report.get('applied'):
                    solved, candidate, report = trial, trial_candidate, trial_report
                    local_report['accepted'] = True
                    if fit_session is not None:
                        fit_session.trajectories[trajectory_key] = trial.x.tolist()
            else:
                if proposal_failure:
                    local_report.update(proposal_failure)
                else:
                    local_report['reason'] = 'no_feasible_proposal'
        except (ValueError, TimeoutError) as error:
            local_report.update(reason=type(error).__name__, detail=str(error))
        finally:
            if not local_report['accepted']:
                rig.initial[:], rig.offsets[:] = previous_coordinates, previous_offsets
                solved, candidate, report = previous_solved, previous_candidate, previous_report
            local_report['elapsedSeconds'] = monotonic() - local_started
            report['contactHeelRepair'] = local_report

    attempt_contact_heel_repair()
    anatomy_projection_attempted = False

    def attempt_bounded_anatomy_projection():
        nonlocal solved, candidate, report, anatomy_projection_attempted
        if anatomy_projection_attempted:
            return
        current_failed = set(failed_check_names(report.get('checks')))
        repairable_anatomy = bool(
            set(report.get('physicalReasons') or []) & ANATOMICAL_REPAIR_INPUT_REASONS)
        if not (allow_refinement and bounded_anatomy_projection_eligible(
            current_failed,
            report.get('checks') or {},
            repairable_anatomy=repairable_anatomy,
            cyclic=cyclic,
        )):
            return

        # A failed structural check can make the projection unsafe on the first
        # validation. Revisit once bounded contact/equipment cleanup has cleared
        # those gates, while still limiting anatomy projection to one attempt.
        anatomy_projection_attempted = True
        remaining = started + timeout_seconds - monotonic()
        repair_budget = min(5., max(0., remaining - 3.))
        projection = {'attempted': repair_budget >= 0.5,
                      'budgetSeconds': round(repair_budget, 3)}
        if repair_budget < 0.5:
            projection['reason'] = 'insufficient_budget'
            report['postFitAnatomicalProjection'] = projection
            return

        baseline_candidate = candidate
        baseline_report = deepcopy(report)
        baseline_coordinates = solved.x.copy()
        baseline_nfev = solved.nfev
        baseline_status = getattr(solved, 'status', 0)
        previous_initial = rig.initial.copy()
        previous_offsets = rig.offsets.copy()
        try:
            rig.initial[:] = baseline_coordinates.reshape(count, rig.width)
            observed = rig.decode(rig.initial)
            _, repair_report = repair_rig_anatomy(
                rig, observed, reference=fit_anatomy_reference,
                deadline=min(started + timeout_seconds,
                             monotonic() + repair_budget))
            projection['repair'] = repair_report
            trial_coordinates = rig.initial.copy()
            if not (np.isfinite(trial_coordinates).all()
                    and np.isfinite(rig.offsets).all()):
                projection['accepted'] = False
                projection['reason'] = 'nonfinite_projection'
                raise ValueError('anatomy projection produced nonfinite coordinates')

            trial = SimpleNamespace(
                x=trial_coordinates.ravel(), nfev=baseline_nfev,
                status=baseline_status)
            # This projection already owns anatomy and contact targets; a second
            # neck/plant projection could reopen the structure constraint.
            trial_candidate, trial_report = validate_solution(
                trial, project_playback_plants=False)
            trial_failed = set(failed_check_names(trial_report.get('checks')))
            improved = fit_report_improves_acceptance(baseline_report, trial_report)
            projection['failedChecksAfter'] = sorted(trial_failed)
            projection['accepted'] = improved
            if improved:
                # Validation creates a fresh report. Preserve the refinement
                # trace and outer timing metadata accumulated before this point.
                for key in ('boundedRefinement', 'initialValidationSeconds',
                            'polishUntilSeconds'):
                    if key in baseline_report:
                        trial_report[key] = baseline_report[key]
                solved = trial
                candidate, report = trial_candidate, trial_report
            else:
                rig.initial[:] = previous_initial
                rig.offsets[:] = previous_offsets
                solved = SimpleNamespace(
                    x=baseline_coordinates, nfev=baseline_nfev,
                    status=baseline_status)
                candidate, report = baseline_candidate, baseline_report
        except Exception as error:
            projection['accepted'] = False
            projection.setdefault('reason', 'projection_exception')
            projection['error'] = type(error).__name__
            rig.initial[:] = previous_initial
            rig.offsets[:] = previous_offsets
            solved = SimpleNamespace(
                x=baseline_coordinates, nfev=baseline_nfev,
                status=baseline_status)
            candidate, report = baseline_candidate, baseline_report
        report['postFitAnatomicalProjection'] = projection

    failed_checks = set(failed_check_names(report.get('checks')))
    attempt_bounded_anatomy_projection()
    failed_checks = set(failed_check_names(report.get('checks')))
    # Evidence-first: accept or proven unreachable/conflict ends the fit.
    # Time budget is only a watchdog for polishable near-misses still moving.
    if report.get('applied'):
        return candidate, report
    if unreachable_without_polish(report):
        report['termination'] = 'unreachable_conflict'
        report['reason'] = 'fit_validation_failed'
        report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_check_names(report.get('checks')),
            'evaluationsPerBlock': 0, 'blocks': [],
            'stopReason': 'unreachable_conflict',
        })
        return payload, report
    # Soft solve often overruns into the polish reserve. Cheap Stage-C hard ops
    # (playback plants, jerk smooth) still clear near-misses — run them once
    # even slightly past the soft deadline before giving up.
    failed_checks = failed_check_names(report.get('checks'))
    skip_hard_only = bool(report.get('skippedSoftSolve'))
    if (allow_refinement and polishable_near_miss(failed_checks)
            and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B) or skip_hard_only)
            and (report.get('maximumContactErrorMeters') or 0.) < 0.0005
            and monotonic() < started + timeout_seconds
            and not fit_should_yield_for_priority()):
        refinement = report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []})
        if (skip_hard_only and 'equipment' in failed_checks
                and 'contacts' not in failed_checks
                and not refinement.get('rigidPairGripProjection')
                and equipment.get('handRelationship') == 'rigid_pair'
                and equipment.get('available')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            grip_budget = min(10., max(2., polish_until - monotonic() - 1.))
            projected = project_rigid_pair_grip_coordinates(
                solved.x.reshape(count, rig.width), rig, names, equipment,
                pinned=pinned, max_nfev=25, deadline=min(started + timeout_seconds, monotonic() + max(1., grip_budget)))
            if np.any(pinned):
                projected = project_contact_root_translation(
                    projected, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = monotonic() + min(8., max(1., polish_until - monotonic()))
                if plant_deadline > monotonic():
                    projected = project_contact_plant_coordinates(
                        projected, rig, pinned, contact_targets, max_nfev=20,
                        deadline=min(started + timeout_seconds, plant_deadline))
                    if _playback_failing_intervals(
                            projected, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                        projected = project_interval_playback_plants(
                            projected, rig, pinned, contact_targets, cyclic=cyclic,
                            floor=floor, max_nfev=16,
                            deadline=min(started + timeout_seconds, monotonic() + min(10., max(1., polish_until - monotonic()))), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['rigidPairGripProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'rigid_pair_grip_projection',
                'stage': 'A', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            failed_checks = failed_check_names(report.get('checks'))
        if ('playback' in failed_checks and np.any(pinned)
                and not refinement.get('playbackPlantProjection')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            plant_nfev = 16 if report.get('skippedSoftSolve') else 12
            plant_seconds = 24.0 if report.get('skippedSoftSolve') else 8.0
            if report.get('supportPlaybackPlantsApplied') and report.get('validatePlaybackPlantsApplied'):
                plant_seconds = min(plant_seconds, 20.0)
            projected = project_interval_playback_plants(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, floor=floor, max_nfev=plant_nfev,
                deadline=min(started + timeout_seconds, monotonic() + plant_seconds), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['playbackPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'playback_plant_projection',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or play_after > previous_play * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            failed_checks = failed_check_names(report.get('checks'))
        # Playback can fail nested equipment / velocity while keyframe checks pass.
        nested = _playback_nested_failures(report.get('playback'))
        if (playback_path_repair_eligible(report, skip_hard_only=skip_hard_only)
                and (not skip_hard_only or np.any(pinned))
                and not refinement.get('playbackPathRepair')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = set(nested)
            projected = solved.x.reshape(count, rig.width).copy()
            # Grip gets its own slice; velocity budget is refreshed after grip so
            # a long grip validate cannot skip continuity repair entirely.
            outer_left = max(0., started + timeout_seconds - monotonic() - 5.)
            grip_deadline = monotonic() + min(16., max(4., 0.35 * outer_left))
            kept = previous_coordinates
            kept_play = previous_play
            kept_nested = previous_nested

            def _accept_path(trial, label):
                nonlocal kept, kept_play, kept_nested, solved, candidate, report, failed_checks
                previous_playback = report.get('playback') or {}
                previous_equipment = previous_playback.get('equipment') or {}
                solved = SimpleNamespace(
                    x=trial.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                nested_after = _playback_nested_failures(report.get('playback'))
                failed_after = set(failed_check_names(report.get('checks')))
                trial_equipment = (report.get('playback') or {}).get('equipment') or {}
                reject_reasons = []
                # Never keep a trial that reopens the playback plant gate.
                if contact_after >= 0.0005:
                    reject_reasons.append('keyframe_contact_regressed')
                if 'contact' in nested_after:
                    reject_reasons.append('playback_contact_regressed')
                if play_after > max(previous_play * 1.5, 0.00075) + 1e-9:
                    reject_reasons.append('playback_contact_error_increased')
                if not failed_after <= previous_failed:
                    reject_reasons.append('new_acceptance_failures')
                jerk_regressed = polish_worsened_jerk(report, previous_jerk)
                if jerk_regressed:
                    reject_reasons.append('jerk_regressed')
                attempt_record = {
                    'method': label,
                    'retained': False,
                    'rejectionReasons': reject_reasons,
                    'failedChecks': sorted(failed_after),
                    'nestedPlaybackFailures': sorted(nested_after),
                    'maximumContactErrorMeters': contact_after,
                    'playbackContactErrorMeters': play_after,
                    'previousEquipmentSpacingErrorMeters': previous_equipment.get(
                        'maximumSpacingErrorMeters'),
                    'trialEquipmentSpacingErrorMeters': trial_equipment.get(
                        'maximumSpacingErrorMeters'),
                    'previousJerkAfter': previous_jerk,
                    'trialJerkAfter': report.get('jerkAfter'),
                    'jerkRegressed': jerk_regressed,
                }
                if reject_reasons:
                    refinement.setdefault('playbackPathRepairAttempts', []).append(
                        attempt_record)
                    return False
                cleared_velocity = (
                    'velocity' in (kept_nested | previous_nested)
                    and 'velocity' not in nested_after)
                cleared_equipment = (
                    'equipment' in (kept_nested | previous_nested)
                    and 'equipment' not in nested_after)
                improved = (
                    report.get('applied')
                    or (not nested_after and previous_nested)
                    or cleared_velocity
                    or (cleared_equipment and 'velocity' not in nested_after)
                    or (len(nested_after) < len(kept_nested)
                        and not ({'velocity'} & nested_after - kept_nested)))
                if improved:
                    attempt_record['retained'] = True
                else:
                    attempt_record['rejectionReasons'].append(
                        'playback_failure_not_reduced')
                refinement.setdefault('playbackPathRepairAttempts', []).append(
                    attempt_record)
                if improved:
                    kept = trial.copy()
                    kept_play = play_after
                    kept_nested = nested_after
                    refinement['blocks'].append({
                        'costBefore': None, 'costAfter': None, 'method': label,
                        'stage': 'C', 'failedChecks': failed_check_names(report.get('checks')),
                        'nestedBefore': sorted(previous_nested),
                        'nestedAfter': sorted(nested_after)})
                    failed_checks = failed_check_names(report.get('checks'))
                    return True
                return False

            if 'equipment' in nested and equipment.get('handRelationship') == 'rigid_pair':
                trial = project_rigid_pair_grip_coordinates(
                    projected, rig, names, equipment, pinned=pinned, max_nfev=25,
                    deadline=min(started + timeout_seconds, grip_deadline))
                trial = project_playback_rigid_pair_grip(
                    trial, rig, names, equipment, pinned=pinned, cyclic=cyclic,
                    max_nfev=16, deadline=grip_deadline,
                    shake_limits=shake_limits)
                if playback_contact_repair_needed(
                        trial, rig, pinned, contact_targets, cyclic=cyclic):
                    trial = project_contact_plant_coordinates(
                        trial, rig, pinned, contact_targets, max_nfev=16,
                        freeze_root=True, deadline=min(started + timeout_seconds, grip_deadline))
                    if _playback_failing_intervals(
                            trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                        trial = project_interval_playback_plants(
                            trial, rig, pinned, contact_targets, cyclic=cyclic,
                            floor=floor, max_nfev=12, deadline=min(started + timeout_seconds, grip_deadline), spike_reference=spike_reference)
                if _accept_path(trial, 'playback_grip_repair'):
                    projected = kept.reshape(count, rig.width)
                    if report.get('applied'):
                        refinement['playbackPathRepair'] = True
                        return candidate, report
            # Always continue velocity repair from the best kept state, even when
            # the last validate rejected a grip trial.
            projected = np.asarray(kept, dtype=float).reshape(count, rig.width)
            nested = set(kept_nested)
            path_window = (
                min(60., max(20., started + timeout_seconds - monotonic() - 5.))
                if skip_hard_only
                else min(20., max(4., started + timeout_seconds - monotonic() - 5.))
            )
            path_deadline = monotonic() + path_window
            if nested & {'velocity', 'physical', 'equipment'} and monotonic() < path_deadline:
                trial = repair_playback_velocity_continuity(
                    projected, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.75,
                    names=names, equipment=equipment,
                    deadline=min(started + timeout_seconds, path_deadline), floor=floor, spike_reference=spike_reference, fps=fps)
                # Keep the velocity/plant win first — mid-sample anatomy polish must
                # not discard a cleared C1 jump when it fails or reopens plants.
                _accept_path(trial, 'playback_velocity_repair')
                if (report.get('applied')
                        or ('physical' not in set(kept_nested))
                        or monotonic() >= path_deadline):
                    pass
                else:
                    anatomy_trial = np.asarray(kept, dtype=float).reshape(count, rig.width)
                    previous_initial = rig.initial.copy()
                    previous_offsets = rig.offsets.copy()
                    rig.initial[:] = anatomy_trial
                    try:
                        from .anatomical_repair import repair_rig_anatomy
                        _, polish = repair_rig_anatomy(
                            rig, rig.decode(rig.initial),
                            deadline=min(path_deadline, monotonic() + 8.),
                            reference=fit_anatomy_reference)
                        if polish.get('passed'):
                            anatomy_trial = rig.initial.copy()
                            if np.any(pinned):
                                anatomy_trial = project_contact_plant_coordinates(
                                    anatomy_trial, rig, pinned, contact_targets,
                                    max_nfev=12, freeze_root=True, deadline=min(started + timeout_seconds, path_deadline))
                                if _playback_failing_intervals(
                                        anatomy_trial, rig, pinned, contact_targets,
                                        cyclic=cyclic, floor=floor):
                                    anatomy_trial = project_interval_playback_plants(
                                        anatomy_trial, rig, pinned, contact_targets,
                                        cyclic=cyclic, floor=floor, max_nfev=12,
                                        deadline=min(started + timeout_seconds, path_deadline), spike_reference=spike_reference)
                            if not _accept_path(anatomy_trial, 'playback_anatomy_repair'):
                                rig.initial[:] = previous_initial
                                rig.offsets[:] = previous_offsets
                        else:
                            rig.initial[:] = previous_initial
                            rig.offsets[:] = previous_offsets
                    except Exception:
                        rig.initial[:] = previous_initial
                        rig.offsets[:] = previous_offsets
            # Restore best kept trial if the last validate rejected it.
            if not np.allclose(solved.x.reshape(count, -1), kept.reshape(count, -1)):
                solved = SimpleNamespace(
                    x=kept.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                failed_checks = failed_check_names(report.get('checks'))
            refinement['playbackPathRepairKept'] = bool(
                report.get('applied')
                or not np.allclose(kept.ravel(), previous_coordinates, rtol=0., atol=1e-12)
            )
            refinement['playbackPathRepair'] = True
            if report.get('applied'):
                return candidate, report
            # If path repair reopened the plant gate, roll back.
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
                failed_checks = failed_check_names(report.get('checks'))
        if (({'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and not refinement.get('temporalShakeSmooth')
                and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B | {'anatomy', 'playback'})
                     or refinement.get('playbackPathRepair'))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = _playback_nested_failures(report.get('playback'))
            keep_path = bool(refinement.get('playbackPathRepairKept'))
            # After path repair, aggressive shake smooth recreates C1 jumps and
            # lifts plants; use a mild pass then restore velocity continuity.
            shake_sigma = 0.55 if keep_path else 1.5
            shaken = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=shake_sigma)
            if np.any(pinned):
                shaken = project_contact_plant_coordinates(
                    shaken, rig, pinned, contact_targets, max_nfev=8, freeze_root=True,
                    deadline=started + timeout_seconds)
            if keep_path and np.any(pinned):
                shaken = repair_playback_velocity_continuity(
                    shaken, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.45,
                    deadline=min(started + timeout_seconds, monotonic() + 12.), floor=floor, spike_reference=spike_reference, fps=fps)
            solved = SimpleNamespace(
                x=shaken.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(
                solved, project_playback_plants=(
                    False if keep_path else ('playback' in failed_checks)))
            refinement['temporalShakeSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)
                    or ('velocity' not in previous_nested and 'velocity' in nested_after)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(
                    solved, project_playback_plants=not keep_path)
            failed_checks = failed_check_names(report.get('checks'))
        defer_broad_temporal_smoothing = prioritize_fit_before_broad_temporal_smoothing(
            failed_checks,
            playback_passed=(report.get('playback') or {}).get('passed'),
            contact_error_meters=report.get('maximumContactErrorMeters'),
            playback_path_repair_attempted=bool(
                refinement.get('playbackPathRepair')
                or refinement.get('playbackPlantProjection')
            ),
        )
        if defer_broad_temporal_smoothing:
            refinement['broadTemporalSmoothingDeferredForJerkFit'] = True
        if (report.get('checks') and 'jerk' in failed_checks
                and not defer_broad_temporal_smoothing
                and not refinement.get('temporalJerkSmooth')
                and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B | {'anatomy', 'playback'})
                     or refinement.get('playbackPathRepair'))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = _playback_nested_failures(report.get('playback'))
            keep_path = bool(refinement.get('playbackPathRepairKept'))
            # Milder than the default Stage-C smooth — sigma=1 often re-broke
            # plants/anatomy on long plant-only clips after grip projection.
            jerk_sigma = 0.4 if keep_path else 0.5
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=jerk_sigma)
            if np.any(pinned):
                smoothed = project_contact_plant_coordinates(
                    smoothed, rig, pinned, contact_targets, max_nfev=8, freeze_root=True,
                    deadline=started + timeout_seconds)
            if keep_path and np.any(pinned):
                smoothed = repair_playback_velocity_continuity(
                    smoothed, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.4,
                    deadline=min(started + timeout_seconds, monotonic() + 10.), floor=floor, spike_reference=spike_reference, fps=fps)
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(
                solved, project_playback_plants=(
                    False if keep_path else ('playback' in failed_checks)))
            refinement['temporalJerkSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            block = {
                'costBefore': None, 'costAfter': None, 'method': 'temporal_smooth',
                'stage': 'C', 'failedChecks': block_failed,
                'contactBeforeMeters': previous_contact,
                'contactAfterMeters': contact_after,
                'contactLimitMeters': KEYFRAME_CONTACT_LIMIT_METERS,
                'playbackContactBeforeMeters': previous_play,
                'playbackContactAfterMeters': play_after,
            }
            refinement['blocks'].append(block)
            if report.get('applied'):
                block['retained'] = True
                return candidate, report
            rejection_reasons = stage_c_temporal_smoothing_rejection_reasons(
                contact_after=contact_after, playback_contact_after=play_after,
                failed_checks=block_failed, previous_failed_checks=previous_failed,
                previous_jerk=previous_jerk, report=report,
                previous_nested=previous_nested, nested_after=nested_after)
            block['retained'] = not bool(rejection_reasons)
            block['rejectionReasons'] = rejection_reasons
            # Contact error may rise within the unchanged hard gate; reject only
            # when smoothing crosses a validator boundary or breaks other gates.
            if rejection_reasons:
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(
                    solved, project_playback_plants=not keep_path)
            failed_checks = failed_check_names(report.get('checks'))
        # With playback already passing, use free-DOF smoothing for temporal
        # near-misses; it leaves planted chains locked and restores source-aware
        # anatomy after smoothing unplanted joints.
        if (not refinement.get('temporalPathStrong')
                and not prioritize_fit_before_broad_temporal_smoothing(
                    failed_checks,
                    playback_passed=(report.get('playback') or {}).get('passed'),
                    contact_error_meters=report.get('maximumContactErrorMeters'),
                    playback_path_repair_attempted=bool(
                        refinement.get('playbackPathRepair')
                        or refinement.get('playbackPlantProjection')
                    ),
                )
                and (report.get('playback') or {}).get('passed')
                and ({'jerk', 'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_jerk = report.get('jerkAfter')
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            previous_initial = rig.initial.copy()
            previous_offsets = rig.offsets.copy()
            strong = polish_free_temporal_preserving_anatomy(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, sigma=2.5,
                deadline=min(started + timeout_seconds, monotonic() + min(18., max(6., started + timeout_seconds - monotonic()))),
                floor=floor, fps=fps, spike_reference=spike_reference,
                reference=fit_anatomy_reference)
            solved = SimpleNamespace(
                x=strong.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['temporalPathStrong'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_path_strong',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or play_after > previous_play * 1.05 + 1e-9
                    or not (report.get('playback') or {}).get('passed')
                    or 'velocity' in nested_after
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)):
                rig.initial[:] = previous_initial
                rig.offsets[:] = previous_offsets
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved, project_playback_plants=False)
            failed_checks = failed_check_names(report.get('checks'))
            # Path repair often outlives the original polish fence; give Stage-C a
            # fresh outer-bounded window when only temporal leftovers remain.
            if (not report.get('applied')
                    and (report.get('playback') or {}).get('passed')
                    and set(failed_checks) <= POLISH_STAGE_C):
                leftover_budget = max(0., started + timeout_seconds - monotonic())
                if leftover_budget >= 4.:
                    polish_until = min(
                        started + timeout_seconds,
                        monotonic() + min(20., leftover_budget))
                    report['polishUntilSeconds'] = float(polish_until - started)
        if (report.get('skippedSoftSolve') and not report.get('applied')
                and polishable_near_miss(failed_check_names(report.get('checks')))):
            leftover = set(failed_check_names(report.get('checks')))
            nested_left = _playback_nested_failures(report.get('playback'))
            play_ok = bool((report.get('playback') or {}).get('passed'))
            seam_pending = cyclic and play_ok and leftover == {'loopSeam'}
            if seam_pending:
                # Reserve the bounded 10-second projection plus its before/after
                # validation; the approach window must not lose its solve budget
                # to the earlier cheap nudge.
                polish_until = min(started + timeout_seconds, max(polish_until, monotonic() + 16.))
            # Exhaust only when playback path issues remain. Pure temporal leftovers
            # after a cleared path keep polishing (free-DOF Stage-C / soft loop).
            if not seam_pending and (leftover & (POLISH_STAGE_A | POLISH_STAGE_B)
                    or nested_left & {'equipment', 'velocity', 'contact', 'physical'}
                    or ('playback' in leftover and nested_left)
                    or not (play_ok and leftover <= POLISH_STAGE_C)):
                refinement = report.setdefault('boundedRefinement', {
                    'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []})
                refinement['stopReason'] = 'hard_polish_exhausted'
                report['termination'] = 'hard_polish_exhausted'
    # Spend remaining outer time on staged post-solve polish:
    # A contacts/equipment → B seam/playback → C temporal.
    while (allow_refinement and not report.get('applied') and report.get('checks')
            and monotonic() < polish_until
            and report.get('termination') not in EVIDENCE_TERMINATIONS
            and not fit_should_yield_for_priority()):
        attempt_bounded_anatomy_projection()
        if report.get('applied'):
            break
        failed_checks = failed_check_names(report['checks'])
        remaining = max(0., polish_until - monotonic())
        if remaining < 0.5:
            break
        if unreachable_without_polish(report):
            report['termination'] = 'unreachable_conflict'
            report.setdefault('boundedRefinement', {
                'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []
            })['stopReason'] = 'unreachable_conflict'
            break
        near_miss = polishable_near_miss(failed_checks)
        # Near-miss leftovers should keep polishing even after a solve time_budget label.
        # Reserved polish window (polish_until) is authoritative — do not abort early
        # just because the soft LS reported time_budget.
        if (report.get('optimizerTermination') == 'time_budget'
                and not near_miss
                and remaining < 1.):
            break
        if hard_trajectory_and_root_failure(report.get('checks')):
            report.setdefault('boundedRefinement', {
                'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 5, 'blocks': []
            })['stopReason'] = 'hard_trajectory_root_failure'
            report['termination'] = 'hard_trajectory_root_failure'
            break
        stage = polish_stage_for_failures(failed_checks)
        polish_evaluations = 5 if remaining < 40. else min(8, int(max_evaluations))
        refinement = report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_checks, 'evaluationsPerBlock': polish_evaluations, 'blocks': []})
        refinement['evaluationsPerBlock'] = polish_evaluations
        refinement['stage'] = stage
        if report.get('optimizerTermination') in {'solve_phase_budget', 'time_budget', 'evaluation_limit'}:
            prioritize_fit = prioritize_fit_before_broad_temporal_smoothing(
                failed_checks,
                playback_passed=(report.get('playback') or {}).get('passed'),
                contact_error_meters=report.get('maximumContactErrorMeters'),
                playback_path_repair_attempted=bool(
                    refinement.get('playbackPathRepair')
                    or refinement.get('playbackPlantProjection')
                ),
            )
            block_budget = stage_fit_refinement_budget(
                remaining,
                stage=stage,
                minimum_update_seconds=minimum_update_seconds,
                prioritize_fit=prioritize_fit,
            )
            if block_budget is None:
                report['optimizerTermination'] = 'solve_phase_budget'
                report['deferredStageCOptimizerBlock'] = {
                    'minimumUpdateSeconds': float(minimum_update_seconds),
                    'remainingPolishSeconds': float(remaining),
                    'reason': 'deferred_to_outer_fit_continuation',
                }
                required_stage_window = stage_fit_refinement_minimum_remaining_seconds(
                    minimum_update_seconds, stage=stage,
                    prioritize_fit=prioritize_fit,
                )
                if stage == 'C':
                    report['stageCUnfundedPostValidationSeconds'] = float(
                        max(0., required_stage_window - remaining)
                    )
                    report['stageCPolishReservationStatus'] = 'unfunded_after_validation'
                refinement['fitUpdateDeferredToEvaluationContinuation'] = True
                break
            optimization_deadline = monotonic() + block_budget
            report['optimizerTermination'] = 'evaluation_limit'
        # Soft LS rarely beats contact-dominated cost on jerk-only near-misses.
        # One cheap rotation smooth often clears excess third differences without
        # another long least-squares burn.
        if (stage == 'C' and 'playback' in failed_checks
                and not refinement.get('playbackPlantProjection')
                and np.any(pinned)
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            remaining = started + timeout_seconds - monotonic()
            plant_budget = max(0.5, min(4.0, remaining)) if remaining > 0.5 else 0.5
            projected = project_interval_playback_plants(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, floor=floor, deadline=min(started + timeout_seconds, monotonic() + plant_budget), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            # Plants already projected; skip a second clip-wide plant TRF in validate.
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['playbackPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'playback_plant_projection',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        if (stage == 'C' and 'jerk' in failed_checks and not refinement.get('temporalJerkSmooth')
                and not prioritize_fit_before_broad_temporal_smoothing(
                    failed_checks,
                    playback_passed=(report.get('playback') or {}).get('passed'),
                    contact_error_meters=report.get('maximumContactErrorMeters'),
                    playback_path_repair_attempted=bool(
                        refinement.get('playbackPathRepair')
                        or refinement.get('playbackPlantProjection')
                    ),
                )
                and set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B)
                and (report.get('maximumContactErrorMeters') or 0.) < 0.00035):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = _playback_nested_failures(report.get('playback'))
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic).ravel()
            solved = SimpleNamespace(x=smoothed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['temporalJerkSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            block = {
                'costBefore': None, 'costAfter': None, 'method': 'temporal_smooth', 'stage': stage,
                'failedChecks': block_failed,
                'contactBeforeMeters': previous_contact,
                'contactAfterMeters': contact_after,
                'contactLimitMeters': KEYFRAME_CONTACT_LIMIT_METERS,
                'playbackContactBeforeMeters': previous_play,
                'playbackContactAfterMeters': play_after,
            }
            refinement['blocks'].append(block)
            if report.get('applied'):
                block['retained'] = True
                break
            rejection_reasons = stage_c_temporal_smoothing_rejection_reasons(
                contact_after=contact_after, playback_contact_after=play_after,
                failed_checks=block_failed, previous_failed_checks=previous_failed,
                previous_jerk=previous_jerk, report=report,
                previous_nested=previous_nested, nested_after=nested_after)
            block['retained'] = not bool(rejection_reasons)
            block['rejectionReasons'] = rejection_reasons
            if rejection_reasons:
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # Stage-C: hard root continuity smooth before soft LS burns the leftover.
        if (stage == 'C' and 'rootContinuity' in failed_checks
                and not refinement.get('rootContinuitySmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            smoothed = smooth_root_translation_coordinates(
                solved.x.reshape(count, rig.width), fps, scale=scale)
            if np.any(pinned):
                # Continuity edits move world plants. Recover with limb DOFs only
                # (frozen root) so contact repair cannot reintroduce pelvis spikes.
                smoothed = project_contact_plant_coordinates(
                    smoothed, rig, pinned, contact_targets, max_nfev=40, freeze_root=True,
                    deadline=started + timeout_seconds)
                if not root_motion_quality(smoothed[:, :3], fps, scale)['passed']:
                    smoothed = project_root_continuity_coordinates(smoothed, fps, scale)
                    smoothed = project_contact_plant_coordinates(
                        smoothed, rig, pinned, contact_targets, max_nfev=30, freeze_root=True,
                        deadline=started + timeout_seconds)
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['rootContinuitySmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'root_continuity_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            introduced = set(block_failed) - previous_failed
            # Never keep a continuity edit that invents anatomy/articulation damage
            # or re-breaks planted contacts / support.
            if (introduced & {'anatomy', 'sourceArticulation', 'jointRange'}
                    or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'contacts', 'bodySupport', 'supportAlignment'} & introduced)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        if (stage == 'C' and 'motionDiscontinuity' in failed_checks
                and not refinement.get('motionDiscontinuitySmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            # Mild single-pass extremity smooth left ~0.2 body-ratio swing-foot
            # spikes intact; escalate free distal-chain repair until the gate clears.
            smoothed = repair_motion_discontinuity_coordinates(
                solved.x.reshape(count, rig.width), rig, names, cyclic=cyclic, fps=fps,
                pinned=pinned, scale=scale, contact_targets=contact_targets)
            # Skip plant recovery when only free extremities moved.
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['motionDiscontinuitySmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'motion_discontinuity_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            introduced = set(block_failed) - previous_failed
            if (introduced & {'anatomy', 'sourceArticulation', 'jointRange', 'rootContinuity'}
                    or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'contacts', 'bodySupport', 'supportAlignment'} & introduced)
                    or polish_worsened_jerk(report, previous_jerk)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
                block_failed = failed_check_names(report.get('checks'))
            # Continuity smooth often leaves shake; apply the cheap temporal
            # shake pass immediately so Stage-B/open-seam is reachable.
            if (not report.get('applied')
                    and ({'jointShake', 'relativeJointShake', 'settling'} & set(block_failed))
                    and not refinement.get('temporalShakeSmooth')
                    and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
                previous_coordinates = solved.x.copy()
                previous_failed = set(block_failed)
                previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
                previous_jerk = report.get('jerkAfter')
                shaken = temporal_coordinate_smooth(
                    solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=2.0)
                shaken = temporal_coordinate_smooth(shaken, cyclic=cyclic, sigma=2.5)
                if np.any(pinned):
                    contact_err = float(np.max(np.linalg.norm(
                        (rig.decode(shaken) - contact_targets)[pinned], axis=-1), initial=0.))
                    if contact_err >= 0.0005:
                        shaken = project_contact_plant_coordinates(
                            shaken, rig, pinned, contact_targets, max_nfev=15, freeze_root=True,
                            deadline=started + timeout_seconds)
                solved = SimpleNamespace(
                    x=shaken.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['temporalShakeSmooth'] = True
                block_failed = failed_check_names(report.get('checks'))
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                    'stage': 'C', 'failedChecks': block_failed})
                if report.get('applied'):
                    break
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                introduced = set(block_failed) - previous_failed
                if (introduced & {'anatomy', 'sourceArticulation', 'jointRange', 'rootContinuity',
                                  'motionDiscontinuity'}
                        or contact_after >= 0.0005
                        or ({'contacts', 'bodySupport'} & introduced)
                        or polish_worsened_jerk(report, previous_jerk)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
            continue
        # Stage-A: hard root translation onto contact targets before soft LS.
        if (stage == 'A' and 'contacts' in failed_checks
                and not refinement.get('contactRootProjection')):
            previous_coordinates = solved.x.copy()
            previous_report = deepcopy(report)
            previous_candidate = candidate
            previous_rig_initial = rig.initial.copy()
            previous_rig_offsets = rig.offsets.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            projected = project_contact_root_translation(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets).ravel()
            solved = SimpleNamespace(x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['contactRootProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'contact_root_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            new_contact = float(report.get('maximumContactErrorMeters') or 0.)
            regression = (new_contact > previous_contact * 1.01 + 1e-9
                    or set(block_failed) - previous_failed
                    or polish_worsened_jerk(report, previous_report.get('jerkAfter')))
            refinement['blocks'][-1]['retained'] = not bool(regression)
            if regression:
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                rig.initial[:], rig.offsets[:] = previous_rig_initial, previous_rig_offsets
                candidate, report = previous_candidate, previous_report
                report['boundedRefinement'] = refinement
            continue
        if (stage == 'A' and 'contacts' in failed_checks
                and refinement.get('contactRootProjection')
                and not refinement.get('contactPlantProjection')):
            previous_coordinates = solved.x.copy()
            previous_report = deepcopy(report)
            previous_candidate = candidate
            previous_rig_initial = rig.initial.copy()
            previous_rig_offsets = rig.offsets.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            plant_budget = min(12., max(1., remaining - 1.))
            projected = project_contact_plant_coordinates(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                max_nfev=25 if remaining >= 8. else 12,
                deadline=min(started + timeout_seconds, monotonic() + plant_budget)).ravel()
            solved = SimpleNamespace(x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['contactPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'contact_plant_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            new_contact = float(report.get('maximumContactErrorMeters') or 0.)
            regression = (new_contact > previous_contact * 1.01 + 1e-9
                    or set(block_failed) - previous_failed
                    or polish_worsened_jerk(report, previous_report.get('jerkAfter')))
            refinement['blocks'][-1]['retained'] = not bool(regression)
            if regression:
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                rig.initial[:], rig.offsets[:] = previous_rig_initial, previous_rig_offsets
                candidate, report = previous_candidate, previous_report
                report['boundedRefinement'] = refinement
            continue
        # Stage-A: hard arm projection onto rigid_pair spacing once plants hold.
        if (stage == 'A' and 'equipment' in failed_checks
                and 'contacts' not in failed_checks
                and not refinement.get('rigidPairGripProjection')
                and equipment.get('handRelationship') == 'rigid_pair'
                and equipment.get('available')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            grip_budget = min(10., max(1., remaining - 1.))
            projected = project_rigid_pair_grip_coordinates(
                solved.x.reshape(count, rig.width), rig, names, equipment,
                pinned=pinned, max_nfev=25, deadline=min(started + timeout_seconds, monotonic() + grip_budget))
            if np.any(pinned):
                projected = project_contact_root_translation(
                    projected, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = monotonic() + min(
                    8., max(1., started + timeout_seconds - monotonic() - 0.5))
                if plant_deadline > monotonic():
                    projected = project_contact_plant_coordinates(
                        projected, rig, pinned, contact_targets, max_nfev=20,
                        deadline=min(started + timeout_seconds, plant_deadline))
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['rigidPairGripProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'rigid_pair_grip_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            # Keep grip when plants stay under the gate; a small contact rise under
            # 0.5 mm is not worth discarding a rigid_pair fix.
            if (contact_after >= 0.0005
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # After contacts clear, Stage-C soft LS often re-breaks them or times out.
        # Prefer one temporal smooth for shake before burning soft LS.
        if (stage == 'C'
                and ({'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and not refinement.get('temporalShakeSmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic).ravel()
            solved = SimpleNamespace(x=smoothed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['temporalShakeSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # Stage-B: cheap nudge, then hard free-DOF wrap projection. Soft LS does
        # not close near-miss seams under support — do not burn polish on it.
        if (stage == 'B' and cyclic and 'loopSeam' in failed_checks
                and set(failed_checks) <= POLISH_STAGE_B
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005
                and (report.get('maximumArticulationChangeDegrees') or 0.) < 15.):
            stage_b_start = solved.x.copy()
            stage_b_ratios = seam_over_limit_ratios(report.get('playback') or {})
            ratios = stage_b_ratios
            large_seam = bool(ratios) and max(ratios) > SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE
            if not refinement.get('seamBoundaryNudge'):
                previous_coordinates = solved.x.copy()
                previous_ratios = seam_over_limit_ratios(report.get('playback') or {})
                previous_score = max(previous_ratios) if previous_ratios else None
                closed = close_loop_seam_coordinates(
                    solved.x.reshape(count, rig.width), rig, pinned,
                    scale=scale, fps=fps).ravel()
                solved = SimpleNamespace(x=closed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['seamBoundaryNudge'] = True
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'seam_boundary_nudge', 'stage': stage,
                    'failedChecks': failed_check_names(report.get('checks'))})
                if report.get('applied'):
                    break
                new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                new_score = max(new_ratios) if new_ratios else None
                nudge_failed = failed_check_names(report.get('checks'))
                if ((previous_score is not None
                     and (new_score is None or float(new_score) > float(previous_score) + 1e-9))
                        or (nudge_failed and not set(nudge_failed) <= POLISH_STAGE_B)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
            if (not refinement.get('seamHardProjection')
                    or refinement.pop('seamProjectionRetryPending', False)):
                if not refinement.get('seamHardProjection'):
                    # Bound admission of new solves across the seam episode;
                    # time spent validating also consumes this allowance.
                    # A fixed attempt count can discard a converging solve even
                    # when its next short step fits the original allowance.
                    seam_repair_deadline = min(started + timeout_seconds, monotonic() + 30.)
                previous_coordinates = solved.x.copy()
                previous_ratios = seam_over_limit_ratios(report.get('playback') or {})
                previous_score = max(previous_ratios) if previous_ratios else None
                projected = project_loop_seam_coordinates(
                    solved.x.reshape(count, rig.width), rig, pinned,
                    scale=scale, fps=fps, settling_weights=hold_weights,
                    settling_limit=settling_limit,
                    span_targets=span_targets,
                    equipment=equipment,
                    source_projection_constraint=source_projection_constraint,
                    # Nudge validation can consume the polish reserve. Give
                    # each bounded solve its own window, still inside
                    # the candidate's outer deadline.
                    deadline=min(seam_repair_deadline, monotonic() + 10.),
                    max_nfev=80).ravel()
                solved = SimpleNamespace(
                    x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['seamHardProjection'] = True
                refinement['seamHardProjectionAttempts'] = refinement.get('seamHardProjectionAttempts', 0) + 1
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'seam_hard_projection',
                    'stage': stage, 'failedChecks': failed_check_names(report.get('checks'))})
                if report.get('applied'):
                    break
                new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                new_score = max(new_ratios) if new_ratios else None
                block_failed = failed_check_names(report.get('checks'))
                if (block_failed and set(block_failed) <= POLISH_STAGE_C
                        and (report.get('checks') or {}).get('loopSeam') is True
                        and (report.get('playback') or {}).get('passed')
                        and monotonic() < started + timeout_seconds):
                    # A closed, body-valid seam with temporal leftovers belongs
                    # to Stage C. Rolling it back here prevents that stage from
                    # ever seeing the repaired loop; acceptance still requires
                    # every temporal and seam check to pass together.
                    refinement['seamClosedNeedsTemporalPolish'] = True
                    polish_until = min(started + timeout_seconds,
                                       max(polish_until, monotonic() + 16.))
                    continue
                # Revert if wrap score worsened or body checks regressed.
                if ((previous_score is not None
                     and (new_score is None or float(new_score) > float(previous_score) + 1e-9))
                        or (block_failed and not set(block_failed) <= POLISH_STAGE_B)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
                    new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                    block_failed = failed_check_names(report.get('checks'))
                if not report.get('applied') and (
                        block_failed and not set(block_failed) <= POLISH_STAGE_B):
                    solved = SimpleNamespace(x=stage_b_start, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
                    new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                # Continue only with measured progress and clear body checks,
                # inside the original episode and candidate deadlines.
                if (block_failed and set(block_failed) <= POLISH_STAGE_B
                        and previous_score is not None and new_ratios
                        and max(new_ratios) < previous_score - 1e-4
                        and seam_repair_deadline - monotonic() >= 5.):
                    refinement['seamProjectionRetryPending'] = True
                    polish_until = min(seam_repair_deadline,
                                       max(polish_until, monotonic() + 12.))
                    continue
                ratios_now = new_ratios or previous_ratios or stage_b_ratios or []
                if ratios_now and max(ratios_now) > SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE:
                    refinement['stopReason'] = 'seam_excess_needs_different_cycle'
                    report['termination'] = 'seam_excess_needs_different_cycle'
                else:
                    refinement['stopReason'] = 'seam_playback_only'
                    report['termination'] = 'seam_playback_only'
                break
            # Already projected once; do not soft-LS Stage-B seam leftovers.
            refinement['stopReason'] = 'seam_playback_only'
            report['termination'] = 'seam_playback_only'
            break
        if stage == 'B' and cyclic and 'loopSeam' in failed_checks and set(failed_checks) <= POLISH_STAGE_B:
            # Seam-only Stage-B must not fall through into soft LS.
            continue
        if report.get('skippedSoftSolve'):
            leftover = set(failed_checks)
            play_ok = bool((report.get('playback') or {}).get('passed'))
            # Geometry-ready skips must not soft-LS plant-only clips, but after a
            # cleared playback path free-DOF temporal can still clear Stage-C.
            if (play_ok and leftover <= POLISH_STAGE_C
                    and ({'jerk', 'jointShake', 'relativeJointShake', 'settling'} & leftover)
                    and not prioritize_fit_before_broad_temporal_smoothing(
                        leftover,
                        playback_passed=play_ok,
                        contact_error_meters=report.get('maximumContactErrorMeters'),
                        playback_path_repair_attempted=bool(
                            refinement.get('playbackPathRepair')
                            or refinement.get('playbackPlantProjection')
                        ),
                    )
                    and not refinement.get('temporalFreeStageC')):
                previous_acceptance = {
                    'applied': False,
                    'checks': deepcopy(report.get('checks') or {}),
                }
                previous_coordinates = solved.x.copy()
                previous_failed = set(failed_checks)
                previous_jerk = report.get('jerkAfter')
                previous_play = float(
                    (report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                previous_initial = rig.initial.copy()
                previous_offsets = rig.offsets.copy()
                free_sigma = 1.75 if refinement.get('temporalPathStrong') else 1.25
                smoothed = polish_free_temporal_preserving_anatomy(
                    solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                    cyclic=cyclic, sigma=free_sigma,
                    deadline=min(started + timeout_seconds, monotonic() + min(16., max(5., remaining))),
                    floor=floor, fps=fps, spike_reference=spike_reference,
                    reference=fit_anatomy_reference)
                solved = SimpleNamespace(
                    x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                refinement['temporalFreeStageC'] = True
                block_failed = failed_check_names(report.get('checks'))
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'temporal_free_stage_c',
                    'stage': 'C', 'failedChecks': block_failed})
                if report.get('applied'):
                    break
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                play_after = float(
                    (report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                nested_after = _playback_nested_failures(report.get('playback'))
                if (contact_after >= 0.0005
                        or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                        or play_after > previous_play * 1.05 + 1e-9
                        or not (report.get('playback') or {}).get('passed')
                        or 'velocity' in nested_after
                        or not fit_report_improves_acceptance(previous_acceptance, report)
                        or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed))
                        - previous_failed
                        or polish_worsened_jerk(report, previous_jerk)):
                    rig.initial[:] = previous_initial
                    rig.offsets[:] = previous_offsets
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved, project_playback_plants=False)
                continue
            refinement['stopReason'] = 'hard_polish_exhausted'
            report['termination'] = 'hard_polish_exhausted'
            break
        initial_evaluations = solved.nfev or 0
        previous_coordinates = solved.x.copy()
        previous_failed = set(failed_checks)
        previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
        previous_jerk = report.get('jerkAfter')
        contacts_were_clear = previous_contact < 0.0005 and 'contacts' not in previous_failed
        cost_before = cost_after = None
        stalled = False
        if stage == 'A':
            # Only boost the terms that actually failed; raising contacts for an
            # equipment-only miss starves the grip residual.
            if 'contacts' in failed_checks:
                contact_polish_weight = STAGE_A_CONTACT_POLISH_WEIGHT
        if 'equipment' in failed_checks:
            equipment_polish_weight = STAGE_A_EQUIPMENT_POLISH_WEIGHT
        elif contacts_were_clear:
            # Protect a hard-won contact clearance while Stage-C soft LS works.
            contact_polish_weight = max(STAGE_A_CONTACT_POLISH_WEIGHT * 0.5, 2.)
        if (stage == 'C'
                and refinement.get('broadTemporalSmoothingDeferredForJerkFit')):
            refinement['stageCFitAttemptedBeforeBroadTemporalSmoothing'] = True
        try:
            errors = residual(solved.x)
            cost_before = float(errors@errors)
            solved = trajectory_solver(residual, solved.x, pattern, polish_evaluations)
            solved.nfev = (solved.nfev or 0) + initial_evaluations
            errors = residual(solved.x)
            cost_after = float(errors@errors)
            stalled = cost_before-cost_after <= max(1e-12, abs(cost_before)*1e-6)
        except TimeoutError:
            report['optimizerTermination'] = 'time_budget'
            # Prefer the block start over a partial best_coordinates that often
            # improves soft cost while re-breaking planted contacts.
            solved = SimpleNamespace(x=previous_coordinates, nfev=None, status=0)
            hard_stage_c_tried = any(
                refinement.get(key) for key in (
                    'temporalShakeSmooth', 'temporalJerkSmooth',
                    'rootContinuitySmooth', 'motionDiscontinuitySmooth',
                    'broadTemporalSmoothingDeferredForJerkFit'))
            if stage == 'A' and refinement.get('contactRootProjection'):
                stalled = True
            elif (stage == 'C' and timed_out_stage_c_fit_is_stalled(
                    failed_checks, hard_stage_c_tried)):
                # Hard Stage-C ops already ran; another timed-out soft LS will
                # not clear settling/shake under contact protection.
                stalled = True
            else:
                stalled = max(0., started + timeout_seconds - monotonic()) < 3.
        finally:
            seam_polish_weight = 1.
            contact_polish_weight = 1.
            equipment_polish_weight = 1.
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = (
                best_feasible_coordinates if best_feasible_coordinates is not None
                else best_coordinates).tolist()
        candidate, report = validate_solution(solved)
        block_failed = failed_check_names(report.get('checks'))
        contact_after = float(report.get('maximumContactErrorMeters') or 0.)
        # Soft polish must not re-break contacts, invent anatomy/articulation, or
        # raise jerk when acceptance did not improve (common Stage-C trap).
        acceptance_improved = bool(previous_failed) and set(block_failed) < previous_failed
        if ((stage == 'A'
                and ({'anatomy', 'sourceArticulation'} & set(block_failed))
                and not ({'anatomy', 'sourceArticulation'} & previous_failed))
                or (contacts_were_clear and (
                    'contacts' in block_failed or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9))
                or (stage == 'C' and polish_worsened_jerk(report, previous_jerk)
                    and not acceptance_improved)):
            solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
            candidate, report = validate_solution(solved)
            block_failed = failed_check_names(report.get('checks'))
            stalled = True
        refinement['blocks'].append({'costBefore': cost_before, 'costAfter': cost_after,
            'failedChecks': block_failed, 'stage': stage,
            **({'method': 'stage_a_contact_boost'} if stage == 'A' else {})})
        hard_blocks = sum(
            1 for block in refinement['blocks']
            if 'trajectoryFit' in (block.get('failedChecks') or [])
            and 'rootTravel' in (block.get('failedChecks') or [])
        )
        remaining = max(0., started + timeout_seconds - monotonic())
        if hard_trajectory_and_root_failure(report.get('checks')) and (
                stalled or hard_blocks >= 2 or remaining < 0.2 * timeout_seconds):
            refinement['stopReason'] = 'hard_trajectory_root_failure'
            report['termination'] = 'hard_trajectory_root_failure'
            break
        if acceptance_stalled_after_refinement(refinement):
            # Same-stage near-misses can keep the failed-check set while cost moves;
            # only stop hard when the stage itself is not a polishable near-miss.
            if not polishable_near_miss(block_failed):
                refinement['stopReason'] = 'acceptance_stalled'
                report['termination'] = 'acceptance_stalled'
                break
        if stalled and not report.get('applied'):
            if set(block_failed) <= POLISH_STAGE_B and 'loopSeam' in block_failed:
                refinement['stopReason'] = 'seam_playback_only'
                report['termination'] = 'seam_playback_only'
                break
            if polishable_near_miss(block_failed) and contacts_were_clear and 'contacts' not in block_failed:
                # Soft LS could not improve temporal terms without breaking
                # contacts; keep the cleared-contact state and stop burning.
                refinement['stopReason'] = 'polish_stalled'
                report['termination'] = 'polish_stalled'
                break
            if polishable_near_miss(block_failed):
                refinement['stopReason'] = 'polish_stalled'
                report['termination'] = 'polish_stalled'
            else:
                refinement['stopReason'] = 'objective_stalled'
                report['termination'] = 'objective_stalled'
            break
    # Map evidence stops to decisive outcomes; do not leave fit_timeout when we
    # already know acceptance cannot move.
    stop = (report.get('boundedRefinement') or {}).get('stopReason') or report.get('termination')
    if (not report.get('applied') and stop in EVIDENCE_TERMINATIONS
            and report.get('checks')):
        report['termination'] = stop
        failed = set(failed_check_names(report.get('checks')))
        playback = report.get('playback') or {}
        if (cyclic and failed <= {'loopSeam', 'playback'}
                and (report.get('checks') or {}).get('loopSeam') is False
                and not playback.get('seamContinuous', True)
                and candidate is not None
                and loop_disabled_playback_passed(candidate)):
            candidate['loop'] = {
                **(candidate.get('loop') or {}),
                'enabled': True,
                'transition': 'requires_cycle_repair',
                'restartFadeMillis': 0,
            }
            candidate.pop('sequenceStabilization', None)
            report['outputPoseDigest'] = pose_digest(candidate)
            report['loopSeamOpen'] = True
            report['seamStepExcessMeters'] = playback.get('seamStepExcessMeters')
            report['seamVelocityMismatchMetersPerSecond'] = playback.get(
                'seamVelocityMismatchMetersPerSecond')
            report.update(applied=True, reason='validated_controlled_motion_open_seam')
            return candidate, report
        if report.get('reason') in {
                None, 'fit_timeout', 'fit_evaluation_limit', 'fit_validation_failed'}:
            if failed <= {'loopSeam', 'playback'}:
                if (report.get('checks') or {}).get('loopSeam') is False:
                    report['reason'] = 'loop_requires_cycle_repair'
                else:
                    report['reason'] = 'playback_validation_failed'
            else:
                report['reason'] = 'fit_validation_failed'
        return (candidate if report.get('applied') else payload), report
    # Use leftover outer budget for another full polish block when acceptance is
    # still moving, or a staged near-miss remains.
    remaining = max(0., started + timeout_seconds - monotonic())
    refinement = report.get('boundedRefinement') or {}
    failed_now = failed_check_names(report.get('checks'))
    polishable_only = polishable_near_miss(failed_now)
    if (allow_refinement and not report.get('applied')
            and remaining >= 5.
            and stop not in EVIDENCE_TERMINATIONS
            and not report.get('skippedSoftSolve')
            and (
                report.get('optimizerTermination') != 'time_budget'
                or polishable_only
            )
            and (
                (report.get('reason') == 'fit_evaluation_limit'
                 and refinement_improved_acceptance(refinement))
                or polishable_only
                or deferred_fit_update_ready(report, remaining)
            )
            and refinement.get('stopReason') not in EVIDENCE_TERMINATIONS
            and not fit_should_yield_for_priority()):
        continuation = {
            'remainingSeconds': round(remaining, 3),
            'extraEvaluations': int(max_evaluations),
            'stage': polish_stage_for_failures(failed_now),
        }
        continuation_started = monotonic()
        previous_coordinates = solved.x.copy()
        previous_nfev = solved.nfev
        previous_status = getattr(solved, 'status', 0)
        previous_candidate = candidate
        previous_report = deepcopy(report)
        previous_rig_initial = rig.initial.copy()
        previous_rig_offsets = rig.offsets.copy()
        previous_failed = set(failed_check_names(previous_report.get('checks')))
        initial_evaluations = solved.nfev or 0
        if report.get('optimizerTermination') in {'solve_phase_budget', 'time_budget'}:
            optimization_deadline = started + timeout_seconds - min(5., max(0., timeout_seconds) * .05)
            report['optimizerTermination'] = 'evaluation_limit'
        try:
            solved = trajectory_solver(residual, solved.x, pattern, max_evaluations)
            solved.nfev = (solved.nfev or 0) + initial_evaluations
        except TimeoutError:
            report['optimizerTermination'] = 'time_budget'
            solved = SimpleNamespace(
                x=(best_feasible_coordinates if best_feasible_coordinates is not None
                   else best_coordinates if best_coordinates is not None
                   else previous_coordinates),
                nfev=None, status=0)
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = (
                best_feasible_coordinates if best_feasible_coordinates is not None
                else best_coordinates).tolist()
        candidate, report = validate_solution(solved)
        retained = fit_report_improves_acceptance(previous_report, report)
        continuation.update({
            'elapsedSeconds': monotonic() - continuation_started,
            'applied': bool(report.get('applied')),
            'reason': report.get('reason'),
            'retained': retained,
            'failedChecksBefore': sorted(previous_failed),
            'failedChecksAfter': sorted(failed_check_names(report.get('checks'))),
        })
        if not retained:
            # Normal polish stages all guard against regressions. The terminal
            # solver continuation needs the same protection or it can replace
            # a better bounded-refinement candidate with a worse one.
            rig.initial[:] = previous_rig_initial
            rig.offsets[:] = previous_rig_offsets
            solved = SimpleNamespace(
                x=previous_coordinates, nfev=previous_nfev,
                status=previous_status)
            candidate, report = previous_candidate, previous_report
            if fit_session is not None:
                fit_session.trajectories[trajectory_key] = previous_coordinates.tolist()
        report['evaluationContinuation'] = continuation
        report['elapsedSeconds'] = monotonic() - started
    elif (not report.get('applied')
          and report.get('reason') in {'fit_evaluation_limit', 'fit_timeout', 'fit_validation_failed'}
          and report.get('checks')
          and (
              (report.get('boundedRefinement') or {}).get('stopReason') in EVIDENCE_TERMINATIONS
              or report.get('termination') in EVIDENCE_TERMINATIONS
              or (report.get('optimizerTermination') in {'time_budget', 'solve_phase_budget', 'objective_stalled'}
                  and not refinement_improved_acceptance(report.get('boundedRefinement') or {})))):
        report['reason'] = 'fit_validation_failed'
        if report.get('optimizerTermination') == 'objective_stalled':
            report['termination'] = 'objective_stalled'
    attempt_contact_heel_repair()
    # Final safety: completed checks must never leave an incomplete fit_timeout
    # label just because the soft LS burned its watchdog.
    if (not report.get('applied') and report.get('checks')
            and report.get('reason') in {'fit_timeout', 'fit_evaluation_limit'}):
        report['reason'] = 'fit_validation_failed'
    report['elapsedSeconds'] = monotonic() - started
    return candidate, report


def main():
    """Run an isolated comparison without replacing a library artifact."""
    import argparse
    import json
    from pathlib import Path
    from .preview import write_baked_preview_html
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output_directory', type=Path)
    parser.add_argument('--max-evaluations', type=int, help='Hard evaluation cap; default: 25 then short refinements while improving within the time budget.')
    parser.add_argument('--timeout-seconds', type=float, help='Override the frame-count-based 150-300 second solve budget.')
    args = parser.parse_args()
    if (args.max_evaluations is not None and args.max_evaluations < 1) or (args.timeout_seconds is not None and args.timeout_seconds <= 0):
        parser.error('Solver bounds must be positive.')
    output = args.output_directory.resolve()
    if args.input.resolve() == output/'motion.json':
        parser.error('Comparison output must not overwrite the input.')
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    candidate, report = fit_controlled_motion(payload, max_evaluations=args.max_evaluations,
                                             timeout_seconds=args.timeout_seconds)
    candidate = deepcopy(candidate)
    candidate['controlledMotionFit'] = report
    output.mkdir(parents=True, exist_ok=True)
    (output/'motion.json').write_text(json.dumps(candidate), encoding='utf-8')
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    write_baked_preview_html(output/'preview.html', candidate)
    print(json.dumps(report, indent=2))
    return 0 if report['applied'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

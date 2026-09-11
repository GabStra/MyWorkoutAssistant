from __future__ import annotations

import math
from dataclasses import replace
from statistics import median
from typing import Any

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3
from exercise_motion_pkg.bilateral_evidence import source_arm_symmetry_evidence
from exercise_motion_pkg.kinematic_policy import (
    DISTAL_STEP_BODY_RATIO,
    DISTAL_STEP_SPIKE_RATIO,
)
from exercise_motion_pkg.pose_fidelity import (
    source_to_motion_pose_fidelity_metrics,
    source_to_motion_pose_fidelity_metrics_for_projection,
)
import exercise_motion_pkg.pose_fidelity as pose_fidelity
from exercise_motion_pkg.render_geometry import UNIFORM_CAPSULE_RADIUS, support_surface_height

ARM_PAIRS = (
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hand", "right_hand"),
)
LEG_PAIRS = (
    ("left_knee", "right_knee"),
    ("left_ankle", "right_ankle"),
    ("left_foot", "right_foot"),
)
CORE_BILATERAL_PAIRS = (
    ("left_collar", "right_collar"),
    ("left_shoulder", "right_shoulder"),
    ("left_hip", "right_hip"),
)
AXIAL_CENTERLINE_JOINTS = (
    "pelvis",
    "spine1",
    "spine2",
    "spine3",
    "neck",
    "head",
)
STRUCTURAL_BONES = (
    ("pelvis", "spine1"),
    ("spine1", "spine2"),
    ("spine2", "spine3"),
    ("spine3", "neck"),
    ("neck", "head"),
    ("spine3", "left_collar"),
    ("left_collar", "left_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("left_wrist", "left_hand"),
    ("spine3", "right_collar"),
    ("right_collar", "right_shoulder"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("right_wrist", "right_hand"),
    ("pelvis", "left_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("left_ankle", "left_foot"),
    ("pelvis", "right_hip"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("right_ankle", "right_foot"),
)
TORSO_STABILITY_JOINTS = (
    "spine1",
    "spine2",
    "spine3",
    "neck",
    "head",
    "left_collar",
    "right_collar",
    "left_shoulder",
    "right_shoulder",
)
LOW_MOTION_SMOOTHING_THRESHOLD_METERS = 0.018
DOMINANT_CHAIN_RATIO = 0.35
NON_DOMINANT_CHAIN_RATIO = 0.65
MAX_SUPPRESSION_CORRECTION_METERS = 0.035
MAX_TORSO_CORRECTION_METERS = 0.025
MAX_STABLE_HEAD_TO_TORSO_ANGLE_RADIANS = math.radians(15.0)
MAX_PLAUSIBLE_HEAD_TO_TORSO_ANGLE_RADIANS = math.radians(30.0)
SYMMETRY_MIN_RATIO = 0.55
SYMMETRY_MIN_CORRELATION = 0.30
SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO = 0.08
SYMMETRY_MAX_POSE_ERROR_BODY_RATIO = 0.16
SOFT_LEG_SYMMETRY_MIN_BLEND = 0.16
SOFT_LEG_SYMMETRY_MAX_BLEND = 0.34
SOFT_LEG_SYMMETRY_BLEND_SCALE = 0.45
SOFT_LEG_SYMMETRY_MAX_CORRECTION_METERS = 0.028
SOFT_ARM_SYMMETRY_MIN_BLEND = 0.25
SOFT_ARM_SYMMETRY_MAX_BLEND = 0.80
SOFT_ARM_SYMMETRY_BLEND_SCALE = 0.80
SOFT_ARM_SYMMETRY_MAX_CORRECTION_METERS = 0.050
ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO = 0.70
ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION = 0.90
ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO = 0.20
ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO = 0.38
ROOT_VERTICAL_MOTION_PRESERVATION_MIN_RANGE_METERS = 0.04
ROOT_VERTICAL_MOTION_PRESERVATION_RANGE_RATIO = 0.85
ROOT_VERTICAL_MOTION_JOINTS = ("pelvis", "hips", "root")
DOMINANT_CHAIN_TOTAL_RANGE_RATIO = 0.45
DOMINANT_CHAIN_MIN_TOTAL_RANGE_BODY_RATIO = 0.08
DOMINANT_CHAIN_MIN_TOTAL_RANGE_METERS = 0.08
STRUCTURAL_BONE_STABILITY_MAX_VARIATION_RATIO = 0.18
SOURCE_FIDELITY_PROTECTED_METRICS = (
    "p90JointErrorBodyRatio",
    "medianLowerJointErrorBodyRatio",
    "p90JointAngleErrorDegrees",
)
TEMPORAL_POLISH_FIDELITY_TOLERANCES = {
    "p90JointErrorBodyRatio": 0.003,
    "medianLowerJointErrorBodyRatio": 0.003,
    "p90JointAngleErrorDegrees": 0.5,
}
SOURCE_FIDELITY_MAX_RELATIVE_METRIC_REGRESSION = 0.10
SOURCE_ARTICULATION_ENVELOPE_TOLERANCE_DEGREES = 1.0
SOURCE_PRESERVED_ARTICULATION_CHAINS = (
    (
        "left_elbow", "left_shoulder", "left_elbow", "left_wrist",
        ("left_wrist", "left_hand"),
    ),
    (
        "right_elbow", "right_shoulder", "right_elbow", "right_wrist",
        ("right_wrist", "right_hand"),
    ),
    (
        "left_knee", "left_hip", "left_knee", "left_ankle",
        ("left_ankle", "left_foot"),
    ),
    (
        "right_knee", "right_hip", "right_knee", "right_ankle",
        ("right_ankle", "right_foot"),
    ),
)


def _motion_clip_pose_payload(clip: MotionClip) -> dict[str, object]:
    return {
        "fps": clip.fps,
        "jointNames": list(clip.joint_names),
        "frames": [
            {
                "timeSec": frame.time_sec,
                "joints": {
                    name: [float(point[0]), float(point[1]), float(point[2])]
                    for name, point in frame.joints.items()
                },
            }
            for frame in clip.frames
        ]
    }


def _point_angle_degrees_3d(
    first: Point3,
    middle: Point3,
    last: Point3,
) -> float | None:
    left = _subtract(first, middle)
    right = _subtract(last, middle)
    denominator = _length(left) * _length(right)
    if denominator <= 1e-9:
        return None
    cosine = max(-1.0, min(1.0, _dot(left, right) / denominator))
    return math.degrees(math.acos(cosine))


def _rotate_hinge_descendants(joints, *, parent, hinge, child, descendants, target_child):
    """Move a hinge's child by rotating its complete distal chain rigidly."""
    origin = joints[hinge]
    before = _normalize(_subtract(joints[child], origin))
    after = _normalize(_subtract(target_child, origin))
    if before is None or after is None:
        return
    cross = _cross(before, after)
    sine = _length(cross)
    cosine = max(-1., min(1., _dot(before, after)))
    if sine > 1e-9:
        axis = _scale(cross, 1 / sine)
    elif cosine < 0:
        proximal = _subtract(joints[parent], origin)
        axis = _normalize(_subtract(proximal, _scale(before, _dot(proximal, before))))
        if axis is None:
            basis = min(((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), key=lambda v: abs(_dot(v, before)))
            axis = _normalize(_cross(before, basis))
    else:
        return
    angle = math.atan2(sine, cosine)
    for name in descendants:
        if name in joints:
            joints[name] = _add(origin, _rotate_vector_about_axis(
                _subtract(joints[name], origin), axis=axis, angle_radians=angle))
    joints[child] = target_child


def _transport_hinge_bend(bend, source_parent, proposed_parent):
    """Compare bend direction after transporting it with the parent bone."""
    cross = _cross(source_parent, proposed_parent)
    sine = _length(cross)
    cosine = max(-1., min(1., _dot(source_parent, proposed_parent)))
    if sine > 1e-9:
        return _rotate_vector_about_axis(bend, axis=_scale(cross, 1 / sine),
                                         angle_radians=math.atan2(sine, cosine))
    # For an antipodal parent, the known bend is a valid rotation axis and
    # stays unchanged. A parallel parent likewise needs no transport.
    return bend


def _local_hinge_bend(frame, parent, hinge, child):
    body = _body_local_frame(frame)
    if body is None or any(name not in frame.joints for name in (parent, hinge, child)):
        return None
    parent_axis = _normalize(_subtract(frame.joints[parent], frame.joints[hinge]))
    child_axis = _normalize(_subtract(frame.joints[child], frame.joints[hinge]))
    if parent_axis is None or child_axis is None:
        return None
    bend = _normalize(_subtract(child_axis, _scale(parent_axis, _dot(child_axis, parent_axis))))
    if bend is None:
        return None
    axes = (body.right, body.up, body.forward)
    return tuple(_dot(parent_axis, axis) for axis in axes), tuple(_dot(bend, axis) for axis in axes)


def _source_branch_is_temporally_supported(track, index, radius):
    if index < radius or index + radius >= len(track):
        return True
    current, left, right = track[index], track[index - radius], track[index + radius]
    if current is None or left is None or right is None:
        return True
    parent, bend = current
    left_bend = _transport_hinge_bend(left[1], left[0], parent)
    right_bend = _transport_hinge_bend(right[1], right[0], parent)
    # Only discount an isolated source branch when the observations on both
    # sides agree and the current branch is in their opposite hemisphere.
    # Compare after parent transport so a real leg swing is not a branch flip.
    return not (_dot(left_bend, right_bend) > 0 and _dot(bend, _add(left_bend, right_bend)) < 0)


def constrain_to_source_articulation_envelope(
    source: MotionClip,
    proposed: MotionClip,
    *,
    phase_tolerance_degrees: float | None = None,
) -> tuple[MotionClip, dict[str, object]]:
    """Keep cleanup from inventing articulation absent from the 3D source.

    Monocular 2D evidence can improve where a limb appears in the camera plane,
    but it cannot resolve the hidden-depth branch reliably.  Preserve the 3D
    reconstruction's observed hinge envelope and constrain only proposals that
    leave it; the remaining correction is retained.
    """
    from .contact_constraints import ANGLE_NUMERICAL_TOLERANCE_RADIANS

    numerical_tolerance_degrees = math.degrees(ANGLE_NUMERICAL_TOLERANCE_RADIANS)
    constrained_frames = [
        MotionFrame(time_sec=frame.time_sec, joints=dict(frame.joints))
        for frame in proposed.frames
    ]
    constrained_samples = 0
    prevented_branch_flips = 0
    ignored_unstable_source_branches = 0
    maximum_excess_degrees = 0.0
    constrained_joints: set[str] = set()
    envelopes: dict[str, dict[str, float]] = {}
    for name, parent, hinge, child, descendants in SOURCE_PRESERVED_ARTICULATION_CHAINS:
        source_angles = [
            angle
            for frame in source.frames
            if all(joint_name in frame.joints for joint_name in (parent, hinge, child))
            for angle in (
                _point_angle_degrees_3d(
                    frame.joints[parent], frame.joints[hinge], frame.joints[child]
                ),
            )
            if angle is not None
        ]
        if not source_angles:
            continue
        minimum = min(source_angles) - SOURCE_ARTICULATION_ENVELOPE_TOLERANCE_DEGREES
        maximum = max(source_angles) + SOURCE_ARTICULATION_ENVELOPE_TOLERANCE_DEGREES
        envelopes[name] = {"minimumDegrees": minimum, "maximumDegrees": maximum}
        source_bend_track = [_local_hinge_bend(frame, parent, hinge, child) for frame in source.frames]
        for frame_index, (source_frame, frame) in enumerate(zip(source.frames, constrained_frames)):
            joints = frame.joints
            if any(
                joint_name not in joints or joint_name not in source_frame.joints
                for joint_name in (parent, hinge, child)
            ):
                continue
            source_body_frame = _body_local_frame(source_frame)
            proposed_body_frame = _body_local_frame(frame)
            if source_body_frame is not None and proposed_body_frame is not None:
                source_parent = _normalize(
                    _subtract(source_frame.joints[parent], source_frame.joints[hinge])
                )
                source_child = _normalize(
                    _subtract(source_frame.joints[child], source_frame.joints[hinge])
                )
                proposed_parent = _normalize(_subtract(joints[parent], joints[hinge]))
                proposed_child = _normalize(_subtract(joints[child], joints[hinge]))
                if all(
                    direction is not None
                    for direction in (
                        source_parent,
                        source_child,
                        proposed_parent,
                        proposed_child,
                    )
                ):
                    source_bend = _normalize(
                        _subtract(
                            source_child,
                            _scale(source_parent, _dot(source_child, source_parent)),
                        )
                    )
                    proposed_bend = _normalize(
                        _subtract(
                            proposed_child,
                            _scale(proposed_parent, _dot(proposed_child, proposed_parent)),
                        )
                    )
                    branch_supported = _source_branch_is_temporally_supported(
                        source_bend_track, frame_index, max(1, round(source.fps * .10)))
                    if not branch_supported:
                        ignored_unstable_source_branches += 1
                    # Near extension, tiny positional errors can reverse the
                    # normalized bend vector. It cannot establish an IK branch.
                    # Angle-envelope checks below still apply in these poses.
                    minimum_branch_bend = math.sin(math.radians(15.0))
                    source_branch_reliable = _length(_cross(source_parent, source_child)) > minimum_branch_bend
                    proposed_branch_reliable = _length(_cross(proposed_parent, proposed_child)) > minimum_branch_bend
                    if (source_bend is not None and proposed_bend is not None and branch_supported
                            and source_branch_reliable and proposed_branch_reliable):
                        source_local_bend = (
                            _dot(source_bend, source_body_frame.right),
                            _dot(source_bend, source_body_frame.up),
                            _dot(source_bend, source_body_frame.forward),
                        )
                        proposed_local_bend = (
                            _dot(proposed_bend, proposed_body_frame.right),
                            _dot(proposed_bend, proposed_body_frame.up),
                            _dot(proposed_bend, proposed_body_frame.forward),
                        )
                        source_local_bend = _transport_hinge_bend(
                            source_local_bend,
                            tuple(_dot(source_parent, axis) for axis in
                                  (source_body_frame.right, source_body_frame.up, source_body_frame.forward)),
                            tuple(_dot(proposed_parent, axis) for axis in
                                  (proposed_body_frame.right, proposed_body_frame.up, proposed_body_frame.forward)),
                        )
                        # Crossing the opposite hemisphere is a discrete IK
                        # branch change, not ordinary articulation. Preserve
                        # the reconstructed branch instead of allowing a
                        # post-process solver to turn a knee or elbow backward.
                        if _dot(source_local_bend, proposed_local_bend) < 0.0:
                            child_length = _length(_subtract(joints[child], joints[hinge]))
                            reference_bend = _normalize(
                                _add(
                                    _add(
                                        _scale(proposed_body_frame.right, source_local_bend[0]),
                                        _scale(proposed_body_frame.up, source_local_bend[1]),
                                    ),
                                    _scale(proposed_body_frame.forward, source_local_bend[2]),
                                )
                            )
                            # Restore the hinge branch about the CURRENT
                            # parent axis. Copying the source's absolute child
                            # direction changes flexion when the parent moved,
                            # and can turn a bent knee into a straight leg.
                            restored_bend = (
                                _normalize(_subtract(reference_bend, _scale(proposed_parent,
                                    _dot(reference_bend, proposed_parent))))
                                if reference_bend is not None else None
                            )
                            cosine = max(-1., min(1., _dot(proposed_parent, proposed_child)))
                            restored_direction = (
                                _add(_scale(proposed_parent, cosine),
                                     _scale(restored_bend, math.sqrt(max(0., 1 - cosine * cosine))))
                                if restored_bend is not None else None
                            )
                            if restored_direction is not None and child_length > 1e-8:
                                restored_child = _add(
                                    joints[hinge],
                                    _scale(restored_direction, child_length),
                                )
                                _rotate_hinge_descendants(joints, parent=parent, hinge=hinge, child=child,
                                                          descendants=descendants, target_child=restored_child)
                                prevented_branch_flips += 1
                                constrained_samples += 1
                                constrained_joints.add(name)
            angle = _point_angle_degrees_3d(
                joints[parent], joints[hinge], joints[child]
            )
            frame_minimum, frame_maximum = minimum, maximum
            if phase_tolerance_degrees is not None:
                source_angle = _point_angle_degrees_3d(
                    source_frame.joints[parent], source_frame.joints[hinge], source_frame.joints[child]
                )
                if source_angle is not None:
                    frame_minimum = max(minimum, source_angle - phase_tolerance_degrees)
                    frame_maximum = min(maximum, source_angle + phase_tolerance_degrees)
            if (
                angle is None
                or frame_minimum - numerical_tolerance_degrees <= angle <= frame_maximum + numerical_tolerance_degrees
            ):
                continue
            target_angle = min(max(angle, frame_minimum), frame_maximum)
            target_child = _child_point_for_target_hinge_angle(
                parent=joints[parent],
                hinge=joints[hinge],
                child=joints[child],
                target_angle_degrees=target_angle,
            )
            if target_child is None:
                continue
            _rotate_hinge_descendants(joints, parent=parent, hinge=hinge, child=child,
                                      descendants=descendants, target_child=target_child)
            constrained_samples += 1
            constrained_joints.add(name)
            maximum_excess_degrees = max(maximum_excess_degrees, abs(angle - target_angle))
    return replace(proposed, frames=constrained_frames), {
        "applied": constrained_samples > 0,
        "strategy": "source_3d_articulation_envelope_constraint",
        "constrainedSampleCount": constrained_samples,
        "preventedHingeBranchFlipCount": prevented_branch_flips,
        "ignoredUnstableSourceBranchCount": ignored_unstable_source_branches,
        "constrainedJoints": sorted(constrained_joints),
        "maximumPreventedExcessDegrees": maximum_excess_degrees,
        "toleranceDegrees": SOURCE_ARTICULATION_ENVELOPE_TOLERANCE_DEGREES,
        "sourceEnvelopes": envelopes,
        "phaseToleranceDegrees": phase_tolerance_degrees,
        "numericalToleranceDegrees": numerical_tolerance_degrees,
    }


def stabilize_distal_foot_heading(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    """Remove direction noise without changing anatomical heading or foot size."""
    from .foot_kinematics import stabilize_rigid_feet

    return stabilize_rigid_feet(clip)


def suppress_post_ik_anatomical_spikes(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    """Repair isolated distal-chain discontinuities introduced after IK."""
    # Independent XYZ averaging changes bone lengths and can introduce a new
    # hinge discontinuity when the following articulation pass restores them.
    # Use the same rigid-chain rotational fitting as terminal refinement.
    core_candidate, core_metadata = _stabilize_core_temporal_continuity(clip)
    repaired, limb_metadata = _stabilize_arm_temporal_continuity(core_candidate)
    return repaired, {
        **limb_metadata,
        "applied": core_metadata.get("applied", False) or limb_metadata.get("applied", False),
        "coreTemporalContinuity": core_metadata,
    }


def stabilize_forefoot_ground_contacts(
    clip: MotionClip,
    support_evidence: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    """Solve rigid feet with ankle limits relative to each lower leg."""
    from .foot_kinematics import solve_rigid_foot_contacts
    from .contact_constraints import InfeasibleContactCorrection
    from .whole_body_repair import repair_whole_body, stationary_full_sole_proposal

    try:
        direct_proposal = stationary_full_sole_proposal(clip, support_evidence)
        proposal, contact_report = (direct_proposal if direct_proposal is not None
                                    else solve_rigid_foot_contacts(clip, support_evidence))
        if not contact_report.get("applied"):
            return proposal, contact_report
        result, physical_report = repair_whole_body(clip, proposal, support_evidence)
        if not physical_report.get("applied"):
            return clip, {"applied": False, "reason": "physical_contact_repair_rejected",
                          "requiresReconstruction": True, "wholeBodyRepair": physical_report,
                          "contactProposal": contact_report}
        return result, {**contact_report, "wholeBodyRepair": physical_report}
    except InfeasibleContactCorrection as exc:
        # An infeasible proposal is not a failure of the entire candidate.
        # The unchanged clip must still pass the downstream support gates.
        return clip, {"applied": False, "reason": "infeasible_contact_correction", "detail": str(exc)}


def _accept_source_preserving_refinement_step(
    before: MotionClip,
    proposed: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None,
    step_name: str,
    allow_temporal_noise_tradeoff: bool = False,
    source_guided_articulation: bool = False,
    preserve_rigid_constraints: bool = False,
) -> tuple[MotionClip, dict[str, object]]:
    if proposed.frames == before.frames:
        return before, {
            "step": step_name,
            "accepted": True,
            "reason": "step_changed_no_joint_positions",
        }
    if preserve_rigid_constraints:
        # Evaluate the complete rigid proposal or reject it. Moving individual
        # descendants before validation would break its shared endpoints.
        articulation_constraint = {"applied": False, "reason": "rigid_proposal_requires_atomic_validation"}
    elif source_guided_articulation and isinstance(source_pose_payload, dict):
        # Independent source evidence may correct the reconstruction itself.
        # Clamping that proposal to the erroneous input before evaluating it
        # prevents the fidelity comparison from ever seeing the actual repair.
        articulation_constraint = {"applied": False, "reason": "source_guided_proposal_requires_fidelity_validation"}
    else:
        proposed, articulation_constraint = constrain_to_source_articulation_envelope(before, proposed)
    if not isinstance(source_pose_payload, dict):
        from .articulation_trajectory import temporal_quality_comparison
        temporal_quality = temporal_quality_comparison(before, proposed)
        return (proposed if temporal_quality["passed"] else before), {
            "step": step_name,
            "accepted": temporal_quality["passed"],
            "reason": ("source_pose_reference_unavailable" if temporal_quality["passed"]
                       else "temporal_quality_degraded"),
            "articulationConstraint": articulation_constraint,
            "temporalQuality": temporal_quality,
        }
    before_metrics = source_to_motion_pose_fidelity_metrics(
        source_pose_payload,
        _motion_clip_pose_payload(before),
    )
    proposed_metrics = source_to_motion_pose_fidelity_metrics_for_projection(
        source_pose_payload,
        _motion_clip_pose_payload(proposed),
        projection_reference=before_metrics,
    )
    if not before_metrics.get("available") or not proposed_metrics.get("available"):
        return before, {
            "step": step_name,
            "accepted": False,
            "reason": "source_fidelity_comparison_unavailable",
            "before": before_metrics,
            "proposed": proposed_metrics,
            "articulationConstraint": articulation_constraint,
        }
    degraded_metrics: list[str] = []
    deltas: dict[str, float] = {}
    relative_deltas: dict[str, float] = {}
    for metric_name in SOURCE_FIDELITY_PROTECTED_METRICS:
        before_value = before_metrics.get(metric_name)
        proposed_value = proposed_metrics.get(metric_name)
        if not isinstance(before_value, (int, float)) or not isinstance(
            proposed_value, (int, float)
        ):
            continue
        delta = float(proposed_value) - float(before_value)
        deltas[metric_name] = delta
        relative_deltas[metric_name] = delta / max(abs(float(before_value)), 1e-6)
        if delta > 1e-6:
            degraded_metrics.append(metric_name)
    temporal_noise_tradeoff: dict[str, object] | None = None
    # These metrics use different units, so compare their relative changes.
    # A correction is accepted when the combined source error improves and no
    # single signal regresses materially. This avoids rejecting a clear pose
    # improvement for numerical noise in one percentile while still guarding
    # against trading away an entire body region.
    relative_values = list(relative_deltas.values())
    combined_relative_delta = (
        sum(relative_values) / len(relative_values)
        if relative_values
        else 0.0
    )
    accepted = bool(
        not degraded_metrics
        or (
            combined_relative_delta < -1e-6
            and max(relative_values, default=0.0)
            <= SOURCE_FIDELITY_MAX_RELATIVE_METRIC_REGRESSION
        )
    )
    if degraded_metrics and allow_temporal_noise_tradeoff:
        body_height = max(_median_body_height(before), 0.5)
        before_noise = _motion_noise_metrics(before, body_height=body_height)
        proposed_noise = _motion_noise_metrics(proposed, body_height=body_height)
        fidelity_within_tolerance = all(
            deltas[metric_name] <= TEMPORAL_POLISH_FIDELITY_TOLERANCES[metric_name]
            for metric_name in degraded_metrics
        )
        noise_improved = (
            proposed_noise["p90Residual"] < before_noise["p90Residual"]
            and proposed_noise["medianResidual"] <= before_noise["medianResidual"]
        )
        accepted = fidelity_within_tolerance and noise_improved
        temporal_noise_tradeoff = {
            "evaluated": True,
            "accepted": accepted,
            "fidelityWithinTolerance": fidelity_within_tolerance,
            "noiseImproved": noise_improved,
            "fidelityTolerances": TEMPORAL_POLISH_FIDELITY_TOLERANCES,
            "beforeNoise": before_noise,
            "proposedNoise": proposed_noise,
        }
    from .articulation_trajectory import temporal_quality_comparison
    temporal_quality = temporal_quality_comparison(before, proposed)
    accepted = accepted and temporal_quality["passed"]
    return (proposed if accepted else before), {
        "step": step_name,
        "accepted": accepted,
        "reason": (
            (
                "bounded_source_fidelity_tradeoff_for_lower_temporal_noise"
                if temporal_noise_tradeoff is not None
                else "source_fidelity_preserved_or_improved"
            )
            if accepted
            else ("temporal_quality_degraded" if not temporal_quality["passed"]
                  else "protected_source_fidelity_degraded")
        ),
        "degradedMetrics": degraded_metrics,
        "metricDeltas": deltas,
        "relativeMetricDeltas": relative_deltas,
        "combinedRelativeMetricDelta": combined_relative_delta,
        "before": before_metrics,
        "proposed": proposed_metrics,
        "temporalNoiseTradeoff": temporal_noise_tradeoff,
        "articulationConstraint": articulation_constraint,
        "temporalQuality": temporal_quality,
    }


def refine_motion_clip_structurally(
    clip: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None = None,
    rigid_paired_hands_required: bool = False,
    horizontal_torso_required: bool = False,
    dominant_chain_ratio: float = NON_DOMINANT_CHAIN_RATIO,
    non_dominant_damping: float = 1.0,
    non_dominant_radius_scale: float = 1.0,
) -> MotionClip:
    if clip.frame_count < 3:
        return clip
    clip, source_contact_timing_metadata = _align_terminal_contact_to_source_pose(
        clip,
        source_pose_payload=source_pose_payload,
    )
    dominant_chain_ratio = min(max(dominant_chain_ratio, 0.1), 1.0)
    non_dominant_damping = min(max(non_dominant_damping, 0.0), 1.0)
    non_dominant_radius_scale = max(0.1, non_dominant_radius_scale)
    yaw_candidate, travel_yaw_metadata = _align_root_travel_to_body_yaw(clip)
    clip, travel_yaw_transaction = _accept_source_preserving_refinement_step(
        clip,
        yaw_candidate,
        source_pose_payload=source_pose_payload,
        step_name="root_travel_body_yaw_alignment",
    )
    travel_yaw_metadata["transaction"] = travel_yaw_transaction
    vertical_candidate, source_vertical_metadata = _align_intermittent_vertical_trajectory_to_source_pose(
        clip,
        source_pose_payload=source_pose_payload,
    )
    clip, source_vertical_transaction = _accept_source_preserving_refinement_step(
        clip,
        vertical_candidate,
        source_pose_payload=source_pose_payload,
        step_name="source_guided_vertical_trajectory",
    )
    source_vertical_metadata["transaction"] = source_vertical_transaction
    torso_candidate, source_torso_metadata = _align_torso_axis_to_source_pose(
        clip,
        source_pose_payload=source_pose_payload,
    )
    clip, source_torso_transaction = _accept_source_preserving_refinement_step(
        clip,
        torso_candidate,
        source_pose_payload=source_pose_payload,
        step_name="source_guided_torso_axis",
        source_guided_articulation=True,
    )
    source_torso_metadata["transaction"] = source_torso_transaction
    source_guided_candidate, source_guided_metadata = _align_hinge_articulation_to_source_pose(
        clip,
        source_pose_payload=source_pose_payload,
    )
    clip, source_guided_transaction = _accept_source_preserving_refinement_step(
        clip,
        source_guided_candidate,
        source_pose_payload=source_pose_payload,
        step_name="source_guided_hinge_articulation",
        source_guided_articulation=True,
    )
    source_guided_metadata["transaction"] = source_guided_transaction
    source_guided_arm_steps: list[dict[str, object]] = []
    for arm_chain in SOURCE_GUIDED_ARM_CHAINS:
        arm_candidate, arm_metadata = _align_hinge_articulation_to_source_pose(
            clip,
            source_pose_payload=source_pose_payload,
            chains=(arm_chain,),
        )
        clip, arm_transaction = _accept_source_preserving_refinement_step(
            clip,
            arm_candidate,
            source_pose_payload=source_pose_payload,
            step_name=f"source_guided_{arm_chain[0]}_articulation",
            source_guided_articulation=True,
        )
        arm_metadata["transaction"] = arm_transaction
        source_guided_arm_steps.append(arm_metadata)
    source_clip = clip
    articulation_reference_clip = clip

    chain_motion = _chain_motion_summary(clip)
    chain_range = _chain_range_summary(clip)
    body_height = _median_body_height(clip)
    strongest_chain_motion = max(chain_motion.values(), default=0.0)
    active_threshold = max(LOW_MOTION_SMOOTHING_THRESHOLD_METERS, strongest_chain_motion * DOMINANT_CHAIN_RATIO)

    dominant_profile = _dominant_motion_profile(
        chain_motion,
        strongest_chain_motion,
        chain_range=chain_range,
        body_height=body_height,
        active_threshold=active_threshold,
        dominant_chain_ratio=dominant_chain_ratio,
    )
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    bilateral_modes = _dominant_bilateral_motion_modes(clip, dominant_groups)
    source_arm_symmetry = source_arm_symmetry_evidence(source_pose_payload)
    symmetric_rigid_hold = rigid_paired_hands_required and source_arm_symmetry["accepted"]
    if symmetric_rigid_hold:
        # A held implement need not produce correlated arm-motion signals.
        bilateral_modes["arms"] = {
            **bilateral_modes.get("arms", {}),
            "mode": "same_phase_symmetric", "samePhase": True,
            "symmetryStrength": 1.0,
            "motionDrivenPoseSymmetryAcceptance": {
                "accepted": True, "reason": "source_confirmed_rigid_bilateral_pose",
                "sourceEvidence": source_arm_symmetry,
            },
        }
    if bilateral_modes:
        dominant_profile = {
            **dominant_profile,
            "bilateralModes": bilateral_modes,
        }
    noise_metrics = _motion_noise_metrics(clip, body_height=body_height)
    has_directional_noise = (
        clip.frame_count >= 15
        and
        noise_metrics["medianResidual"] > max(0.001, body_height * 0.0006)
        and noise_metrics["p90Residual"] > max(0.004, body_height * 0.0025)
    )
    if "torso" in dominant_groups or has_directional_noise:
        dynamic_child_joints = _range_dominant_chain_child_joints(dominant_profile)
        stabilize_body_orientation = any(
            isinstance(mode, dict) and mode.get("mode") == "same_phase_symmetric"
            for mode in bilateral_modes.values()
        )
        directional_input = clip
        directional_candidate, directional_denoising = _denoise_along_dominant_motion_axis(
            clip,
            dynamic_length_child_joints=dynamic_child_joints,
            stabilize_body_orientation=stabilize_body_orientation,
        )
        directional_denoising = {
            **directional_denoising,
            "noiseMetrics": noise_metrics,
        }
        clip, directional_transaction = _accept_source_preserving_refinement_step(
            directional_input,
            directional_candidate,
            source_pose_payload=source_pose_payload,
            step_name="directional_denoising",
        )
        directional_denoising["transaction"] = directional_transaction
    else:
        directional_denoising = {
            "applied": False,
            "reason": "no_significant_directional_noise",
            "noiseMetrics": noise_metrics,
        }
    if "torso" in dominant_groups:
        refined, refinement_metadata = _refine_torso_dominant_motion_conservatively(
            clip,
            active_threshold=active_threshold,
            strongest_chain_motion=strongest_chain_motion,
            dominant_profile=dominant_profile,
            non_dominant_radius_scale=non_dominant_radius_scale,
            source_pose_payload=source_pose_payload,
        )
    else:
        refined, refinement_metadata = _preserve_non_torso_dominant_motion(
            clip,
            dominant_profile=dominant_profile,
        )
    if isinstance(source_pose_payload, dict) or _has_authoritative_support_anchors(refined):
        temporal_input = refined
        temporal_candidate, temporal_polish_metadata = _polish_motion_clip_temporally(refined)
        refined, temporal_transaction = _accept_source_preserving_refinement_step(
            temporal_input,
            temporal_candidate,
            source_pose_payload=source_pose_payload,
            step_name="clip_wide_temporal_polish",
            allow_temporal_noise_tradeoff=True,
        )
        temporal_polish_metadata["transaction"] = temporal_transaction
    else:
        temporal_polish_metadata = {
            "applied": False,
            "reason": "source_pose_and_authoritative_support_unavailable",
        }
    if _has_authoritative_support_anchors(refined):
        refined, final_bone_projection_metadata = _preserve_reference_bone_lengths(
            refined,
            reference_clip=source_clip,
            excluded_child_joints={
                "left_knee",
                "right_knee",
                "left_ankle",
                "right_ankle",
                "left_foot",
                "right_foot",
            },
        )
    else:
        final_bone_projection_metadata = {
            "applied": False,
            "reason": "no_authoritative_support_anchors",
        }
    refined, support_anchor_metadata = _restore_authoritative_support_anchors(refined)
    refined, whole_skeleton_metadata = _solve_clip_wide_skeleton_constraints(
        refined,
        reference_clip=source_clip,
        bilateral_modes=bilateral_modes,
        dominant_profile=dominant_profile,
    )
    refinement_changed_joints = refinement_metadata.get("applied") is not False
    if not _has_authoritative_support_anchors(refined) and refinement_changed_joints:
        terminal_input = refined
        terminal_candidate, terminal_bone_projection_metadata = _preserve_reference_bone_lengths(
            refined,
            reference_clip=source_clip,
        )
        refined, terminal_transaction = _accept_source_preserving_refinement_step(
            terminal_input,
            terminal_candidate,
            source_pose_payload=source_pose_payload,
            step_name="terminal_bone_length_projection",
        )
        terminal_bone_projection_metadata["transaction"] = terminal_transaction
    elif not refinement_changed_joints:
        terminal_bone_projection_metadata = {
            "applied": False,
            "reason": "source_preserving_refinement_changed_no_joints",
        }
    else:
        terminal_bone_projection_metadata = {
            "applied": False,
            "reason": "authoritative_support_solver_owns_terminal_chain_lengths",
        }
    refined, rigid_support_restoration = _restore_rigid_bilateral_support(refined)
    refined, lateral_support_restoration = _restore_support_relative_lateral_root_trajectory(
        refined,
        reference_clip=source_clip,
    )
    source_bone_variation = _maximum_structural_bone_length_variation(source_clip)
    refined_bone_variation = _maximum_structural_bone_length_variation(refined)
    structural_rollback = refined_bone_variation > source_bone_variation + 1e-6
    if structural_rollback:
        # Refinement is not allowed to manufacture articulation by stretching
        # the skeleton. This is an invariant, not a quality threshold: if the
        # input has more stable bone lengths, preserve the input and let later
        # validators judge the original reconstruction.
        refined = source_clip
    refined, symmetric_core_metadata = _align_core_for_same_phase_bilateral_travel(
        refined,
        bilateral_modes=bilateral_modes,
    )
    final_leg_symmetry_candidate, final_leg_symmetry_metadata = _apply_soft_same_phase_leg_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    refined, final_leg_symmetry_transaction = _accept_source_preserving_refinement_step(
        refined,
        final_leg_symmetry_candidate,
        source_pose_payload=source_pose_payload,
        step_name="final_same_phase_leg_symmetry",
    )
    leg_motion_acceptance = (
        bilateral_modes.get("legs", {}).get("motionDrivenPoseSymmetryAcceptance")
        if isinstance(bilateral_modes.get("legs"), dict)
        else None
    )
    if (
        final_leg_symmetry_transaction.get("accepted") is False
        and isinstance(leg_motion_acceptance, dict)
        and leg_motion_acceptance.get("accepted") is True
    ):
        refined = final_leg_symmetry_candidate
        final_leg_symmetry_transaction = {
            **final_leg_symmetry_transaction,
            "accepted": True,
            "reason": "independent_same_phase_3d_symmetry_evidence_overrides_ambiguous_2d_pose",
            "sourcePoseGateOverridden": True,
        }
    final_leg_symmetry_metadata["transaction"] = final_leg_symmetry_transaction
    refined, symmetric_travel_metadata = _straighten_same_phase_bilateral_travel(
        refined,
        bilateral_modes=bilateral_modes,
    )
    refined, bilateral_landing_metadata = _repair_terminal_bilateral_landing(refined)
    surface_candidate, contact_surface_metadata = _stabilize_distinct_contact_surfaces(refined)
    refined, contact_surface_transaction = _accept_source_preserving_refinement_step(
        refined,
        surface_candidate,
        source_pose_payload=source_pose_payload,
        step_name="distinct_contact_surface_stabilization",
    )
    if (
        contact_surface_transaction.get("accepted") is False
        and contact_surface_metadata.get("bilateralFootAnchors")
    ):
        # A monocular 2D projection cannot disprove a stationary 3D support
        # constraint.  Contact evidence owns planted-foot translation; source
        # fidelity continues to own the unconstrained articulation.
        refined = surface_candidate
        contact_surface_transaction = {
            **contact_surface_transaction,
            "accepted": True,
            "reason": "bilateral_3d_contact_constraint_overrides_ambiguous_2d_projection",
            "sourcePoseGateOverridden": True,
        }
    contact_surface_metadata["transaction"] = contact_surface_transaction
    initial_contact_surface_metadata = contact_surface_metadata
    final_yaw_candidate, final_travel_yaw_metadata = _align_root_travel_to_body_yaw(refined)
    refined, final_travel_yaw_transaction = _accept_source_preserving_refinement_step(
        refined,
        final_yaw_candidate,
        source_pose_payload=source_pose_payload,
        step_name="final_root_travel_body_yaw_alignment",
    )
    final_travel_yaw_metadata["transaction"] = final_travel_yaw_transaction
    refined, final_symmetric_travel_metadata = _straighten_same_phase_bilateral_travel(
        refined,
        bilateral_modes=bilateral_modes,
    )
    final_symmetric_travel_metadata["initialPass"] = symmetric_travel_metadata
    symmetric_travel_metadata = final_symmetric_travel_metadata
    final_surface_candidate, contact_surface_metadata = _stabilize_distinct_contact_surfaces(refined)
    refined, final_contact_surface_transaction = _accept_source_preserving_refinement_step(
        refined,
        final_surface_candidate,
        source_pose_payload=source_pose_payload,
        step_name="final_distinct_contact_surface_stabilization",
    )
    if (
        final_contact_surface_transaction.get("accepted") is False
        and contact_surface_metadata.get("bilateralFootAnchors")
    ):
        refined = final_surface_candidate
        final_contact_surface_transaction = {
            **final_contact_surface_transaction,
            "accepted": True,
            "reason": "bilateral_3d_contact_constraint_overrides_ambiguous_2d_projection",
            "sourcePoseGateOverridden": True,
        }
    contact_surface_metadata["transaction"] = final_contact_surface_transaction
    contact_surface_metadata["initialPass"] = initial_contact_surface_metadata
    refined, core_temporal_continuity = _stabilize_core_temporal_continuity(refined)
    limb_candidate, limb_temporal_continuity = _stabilize_arm_temporal_continuity(refined)
    refined, limb_transaction = _accept_source_preserving_refinement_step(
        refined, limb_candidate, source_pose_payload=source_pose_payload,
        step_name="terminal_limb_rotation_smoothing",
    )
    limb_temporal_continuity["transaction"] = limb_transaction
    final_arm_symmetry_candidate, final_arm_symmetry_metadata = _apply_soft_same_phase_arm_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    refined, final_arm_symmetry_transaction = _accept_source_preserving_refinement_step(
        refined,
        final_arm_symmetry_candidate,
        source_pose_payload=source_pose_payload,
        step_name="terminal_same_phase_arm_symmetry",
    )
    arm_motion_acceptance = (
        bilateral_modes.get("arms", {}).get("motionDrivenPoseSymmetryAcceptance")
        if isinstance(bilateral_modes.get("arms"), dict)
        else None
    )
    if (
        final_arm_symmetry_transaction.get("accepted") is False
        and isinstance(arm_motion_acceptance, dict)
        and arm_motion_acceptance.get("accepted") is True
    ):
        refined = final_arm_symmetry_candidate
        final_arm_symmetry_transaction = {
            **final_arm_symmetry_transaction,
            "accepted": True,
            "reason": "independent_same_phase_3d_symmetry_evidence_overrides_ambiguous_2d_pose",
            "sourcePoseGateOverridden": True,
        }
    final_arm_symmetry_metadata["transaction"] = final_arm_symmetry_transaction
    # Unconstrained cleanup must respect the accepted source-guided pose.
    # Apply this before equipment constraints: moving individual descendants
    # afterwards would break the shared hand endpoints and supported torso.
    refined, final_articulation_constraint = constrain_to_source_articulation_envelope(
        articulation_reference_clip, refined,
    )
    terminal_arm_symmetry_candidate, terminal_arm_symmetry_metadata = _apply_soft_same_phase_arm_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    terminal_arm_mode = bilateral_modes.get("arms")
    if (
        isinstance(terminal_arm_mode, dict)
        and terminal_arm_mode.get("mode") == "same_phase_symmetric"
    ):
        refined = terminal_arm_symmetry_candidate
        terminal_arm_symmetry_metadata["transaction"] = {
            "step": "pre_equipment_same_phase_arm_symmetry",
            "accepted": True,
            "reason": "terminal_bilateral_3d_symmetry_invariant",
        }
    else:
        terminal_arm_symmetry_metadata["transaction"] = {
            "step": "pre_equipment_same_phase_arm_symmetry",
            "accepted": True,
            "reason": "step_changed_no_joint_positions",
        }
    if horizontal_torso_required:
        refined, horizontal_torso_metadata = _align_upper_body_to_horizontal_support(
            refined, level_shoulders=rigid_paired_hands_required,
        )
    else:
        horizontal_torso_metadata = {
            "applied": False,
            "reason": "horizontal_torso_not_required",
        }
    if rigid_paired_hands_required:
        rigid_hand_candidate, rigid_paired_hands_metadata = _stabilize_rigid_paired_hand_spacing(
            refined, supported_bilateral=horizontal_torso_required or symmetric_rigid_hold,
        )
        if isinstance(source_pose_payload, dict):
            refined, rigid_hand_transaction = _accept_source_preserving_refinement_step(
                refined,
                rigid_hand_candidate,
                source_pose_payload=source_pose_payload,
                step_name="rigid_paired_hand_spacing",
                preserve_rigid_constraints=True,
            )
            rigid_paired_hands_metadata["transaction"] = rigid_hand_transaction
            if not rigid_hand_transaction["accepted"]:
                rigid_paired_hands_metadata["applied"] = False
        else:
            refined = rigid_hand_candidate
    else:
        rigid_paired_hands_metadata = {
            "applied": False,
            "reason": "rigid_paired_hands_not_required",
        }
    # Head posture must be solved after every core/bone/contact operation;
    # otherwise a later terminal projection can restore the noisy reference
    # neck-to-head direction and undo the anatomical-axis constraint.
    head_input = refined
    head_candidate, head_metadata = _preserve_reference_head_pose(
        refined,
        reference_clip=refined if horizontal_torso_required else clip,
        force_spine_alignment=horizontal_torso_required,
    )
    refined, head_transaction = _accept_source_preserving_refinement_step(
        head_input,
        head_candidate,
        source_pose_payload=source_pose_payload,
        step_name="final_head_pose_preservation",
    )
    head_metadata["transaction"] = head_transaction
    refined, foot_heading_metadata = stabilize_distal_foot_heading(refined)
    refined, final_invariant = enforce_final_structural_invariant(source_clip, refined)
    refinement_metadata = {
        **refinement_metadata,
        "travelYawAlignment": travel_yaw_metadata,
        "finalTravelYawAlignment": final_travel_yaw_metadata,
        "contactSurfaceStabilization": contact_surface_metadata,
        "sourceContactTiming": source_contact_timing_metadata,
        "rigidPairedHandsStabilization": rigid_paired_hands_metadata,
        "bilateralLandingRepair": bilateral_landing_metadata,
        "finalSamePhaseLegSymmetry": final_leg_symmetry_metadata,
        "finalSamePhaseArmSymmetry": final_arm_symmetry_metadata,
        "terminalSamePhaseArmSymmetry": terminal_arm_symmetry_metadata,
        "horizontalTorsoAlignment": horizontal_torso_metadata,
        "symmetricCoreAlignment": symmetric_core_metadata,
        "symmetricTravelPath": symmetric_travel_metadata,
        "sourceGuidedVerticalTrajectory": source_vertical_metadata,
        "sourceGuidedTorsoAxis": source_torso_metadata,
        "sourceGuidedArticulation": source_guided_metadata,
        "sourceGuidedArmArticulation": source_guided_arm_steps,
        "coreTemporalContinuity": core_temporal_continuity,
        "limbTemporalContinuity": limb_temporal_continuity,
        "directionalDenoising": directional_denoising,
        "headPosePreservation": head_metadata,
        "finalArticulationConstraint": final_articulation_constraint,
        "distalFootHeading": foot_heading_metadata,
        "finalInvariant": final_invariant,
        "temporalPolish": temporal_polish_metadata,
        "finalBoneProjection": final_bone_projection_metadata,
        "supportAnchorRestoration": support_anchor_metadata,
        "wholeSkeletonSolver": whole_skeleton_metadata,
        "terminalBoneProjection": terminal_bone_projection_metadata,
        "rigidSupportRestoration": rigid_support_restoration,
        "lateralSupportRestoration": lateral_support_restoration,
        "structuralRollback": {
            "applied": structural_rollback,
            "reason": (
                "refinement_increased_structural_bone_length_variation"
                if structural_rollback
                else "structural_bone_length_invariant_preserved"
            ),
            "sourceMaximumVariationRatio": source_bone_variation,
            "refinedMaximumVariationRatio": refined_bone_variation,
        },
    }
    metadata = dict(refined.metadata)
    metadata["structuralRefinement"] = {
        "applied": True,
        "strategy": refinement_metadata.get("strategy", "structural_refinement"),
        "inputFrames": [
            {
                "frameIndex": index,
                "timeSec": frame.time_sec,
                "joints": {
                    joint_name: [float(point[0]), float(point[1]), float(point[2])]
                    for joint_name, point in frame.joints.items()
                },
            }
            for index, frame in enumerate(source_clip.frames)
        ],
        "strongestChainMotion": strongest_chain_motion,
        "activeThreshold": active_threshold,
        "chainMotion": chain_motion,
        "chainRange": chain_range,
        "bodyHeight": body_height,
        "dominantProfile": dominant_profile,
        "settings": {
            "dominantChainRatio": dominant_chain_ratio,
            "nonDominantDamping": non_dominant_damping,
            "nonDominantRadiusScale": non_dominant_radius_scale,
        },
        **refinement_metadata,
    }
    return replace(refined, metadata=metadata)


SOURCE_GUIDED_HINGE_CHAINS = (
    ("left_knee", "left_hip", "left_knee", "left_ankle", ("left_ankle", "left_foot")),
    ("right_knee", "right_hip", "right_knee", "right_ankle", ("right_ankle", "right_foot")),
)

SOURCE_GUIDED_TORSO_JOINTS = frozenset(
    (
        "spine1", "spine2", "spine3", "neck", "head",
        "left_collar", "right_collar", "left_shoulder", "right_shoulder",
        "left_elbow", "right_elbow", "left_wrist", "right_wrist",
        "left_hand", "right_hand",
    )
)


def _align_torso_axis_to_source_pose(
    clip: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    """Resolve WHAM's forward/backward torso branch from the fixed source view."""

    source_frames = _source_pose_frames_with_normalized_time(source_pose_payload)
    if len(source_frames) < 2:
        return clip, {"applied": False, "reason": "source_pose_reference_unavailable"}
    fidelity = source_to_motion_pose_fidelity_metrics(
        source_pose_payload or {},
        _motion_clip_pose_payload(clip),
    )
    horizontal_vector_value = fidelity.get("projectionHorizontalVector")
    if not fidelity.get("available") or not isinstance(horizontal_vector_value, list) or len(horizontal_vector_value) < 2:
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}
    horizontal_vector = (float(horizontal_vector_value[0]), float(horizontal_vector_value[1]))
    mirror = fidelity.get("mirrored") is True
    swap_bilateral = fidelity.get("bilateralAssignment") == "swapped"
    motion_frames = pose_fidelity._pose_frames(_motion_clip_pose_payload(clip), source=False)
    transform = pose_fidelity._global_similarity_transform(
        source_frames,
        motion_frames,
        horizontal_vector=horizontal_vector,
        mirror=mirror,
        swap_bilateral=swap_bilateral,
    )
    if transform is None:
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}

    duration = max(0.0, clip.frames[-1].time_sec - clip.frames[0].time_sec)
    corrected_frames: list[MotionFrame] = []
    corrections: list[Point3] = []
    for frame_index, frame in enumerate(clip.frames):
        normalized_time = (
            (frame.time_sec - clip.frames[0].time_sec) / duration
            if duration > 1e-9
            else frame_index / max(1, clip.frame_count - 1)
        )
        source_joints = _interpolated_source_joints(source_frames, normalized_time)
        joints = dict(frame.joints)
        pelvis = joints.get("pelvis") or joints.get("hips")
        shoulder_midpoint = (
            _scale(_add(joints["left_shoulder"], joints["right_shoulder"]), 0.5)
            if "left_shoulder" in joints and "right_shoulder" in joints
            else None
        )
        source_pelvis = source_joints.get("pelvis") or source_joints.get("hips")
        source_shoulders = source_joints.get("shoulders")
        if source_shoulders is None and "left_shoulder" in source_joints and "right_shoulder" in source_joints:
            source_shoulders = [
                (float(source_joints["left_shoulder"][axis]) + float(source_joints["right_shoulder"][axis])) * 0.5
                for axis in range(2)
            ]
        if pelvis is None or shoulder_midpoint is None or source_pelvis is None or source_shoulders is None:
            corrected_frames.append(frame)
            continue
        desired_projection = _source_relative_endpoint_projection(
            source_parent=source_pelvis,
            source_child=source_shoulders,
            parent=pelvis,
            transform=transform,
            horizontal_vector=horizontal_vector,
            mirror=mirror,
        )
        target_shoulder_midpoint = _point_for_projected_endpoint_with_fixed_length(
            hinge=pelvis,
            child=shoulder_midpoint,
            desired_projection=desired_projection,
            horizontal_vector=horizontal_vector,
            mirror=mirror,
        )
        if target_shoulder_midpoint is None:
            corrected_frames.append(frame)
            continue
        current_axis = _normalize(_subtract(shoulder_midpoint, pelvis))
        target_axis = _normalize(_subtract(target_shoulder_midpoint, pelvis))
        if current_axis is None or target_axis is None:
            corrected_frames.append(frame)
            continue
        cross = _cross(current_axis, target_axis)
        cross_length = _length(cross)
        alignment = max(-1.0, min(1.0, _dot(current_axis, target_axis)))
        angle = math.acos(alignment)
        if cross_length <= 1e-8 or angle <= 1e-8:
            corrected_frames.append(frame)
            continue
        axis = _scale(cross, 1.0 / cross_length)
        for name in SOURCE_GUIDED_TORSO_JOINTS:
            if name not in joints:
                continue
            relative = _subtract(joints[name], pelvis)
            joints[name] = _add(
                pelvis,
                _rotate_vector_about_axis(relative, axis=axis, angle_radians=angle),
            )
        corrections.append(math.dist(shoulder_midpoint, target_shoulder_midpoint))
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    if not corrections:
        return clip, {"applied": False, "reason": "source_torso_axis_already_matched"}
    return replace(clip, frames=corrected_frames), {
        "applied": True,
        "strategy": "fixed_source_projection_torso_axis_rotation",
        "correctedFrameCount": len(corrections),
        "averageShoulderMidpointCorrection": sum(corrections) / len(corrections),
        "maximumShoulderMidpointCorrection": max(corrections),
    }


def _fixed_endpoint_bend(
    root: Point3, end: Point3, preferred_mid: Point3, *, upper: float, lower: float,
) -> Point3 | None:
    """Solve a hinge without moving its endpoint or changing either bone."""
    delta = _subtract(end, root)
    distance = _length(delta)
    if distance < 1e-9 or distance > upper + lower + 1e-9 or distance < abs(upper - lower) - 1e-9:
        return None
    axis = _scale(delta, 1.0 / distance)
    along = (upper * upper - lower * lower + distance * distance) / (2.0 * distance)
    center = _add(root, _scale(axis, along))
    height = math.sqrt(max(0., upper * upper - along * along))
    if height < 1e-9:
        return center
    preference = _subtract(preferred_mid, center)
    bend = _normalize(_subtract(preference, _scale(axis, _dot(preference, axis))))
    return _add(center, _scale(bend, height)) if bend is not None else None


def _project_core_targets_with_fixed_endpoints(
    frame: MotionFrame, targets: dict[str, Point3], *, preserve_shoulders: bool = False,
) -> tuple[dict[str, Point3], float]:
    """Project core edits onto rigid bones and reattach limbs to unchanged endpoints.

    Reduce an unreachable correction, instead of stretching a limb or dragging
    its planted foot/held implement. Every attempt starts from the input frame.
    """
    limb_roots = {f"{side}_{part}" for side in ("left", "right") for part in ("shoulder", "hip")}
    limb_children = {f"{side}_{part}" for side in ("left", "right")
                     for part in ("elbow", "wrist", "hand", "knee", "ankle", "foot")}
    if preserve_shoulders:
        limb_children.update(f"{side}_{part}" for side in ("left", "right") for part in ("collar", "shoulder"))
    for scale in (1., .5, .25, .125, .0625, .03125):
        joints = dict(frame.joints)
        if "pelvis" in joints and "pelvis" in targets:
            joints["pelvis"] = _lerp_point(joints["pelvis"], targets["pelvis"], scale)
        for parent, child in STRUCTURAL_BONES:
            if child in limb_children or parent not in joints or child not in joints:
                continue
            desired = _lerp_point(frame.joints[child], targets.get(child, frame.joints[child]), scale)
            direction = _normalize(_subtract(desired, joints[parent]))
            length = _distance(frame.joints[parent], frame.joints[child])
            if direction is not None:
                joints[child] = _add(joints[parent], _scale(direction, length))
        feasible = True
        if preserve_shoulders:
            for side in ("left", "right"):
                collar, shoulder = f"{side}_collar", f"{side}_shoulder"
                if any(name not in joints for name in ("spine3", collar, shoulder)):
                    continue
                solved = _fixed_endpoint_bend(
                    joints["spine3"], frame.joints[shoulder], frame.joints[collar],
                    upper=_distance(frame.joints["spine3"], frame.joints[collar]),
                    lower=_distance(frame.joints[collar], frame.joints[shoulder]),
                )
                if solved is None:
                    feasible = False
                    break
                joints[collar] = solved
            if not feasible:
                continue
        for root in limb_roots:
            side, suffix = root.split("_", 1)
            mid, end = (f"{side}_elbow", f"{side}_wrist") if suffix == "shoulder" else (f"{side}_knee", f"{side}_ankle")
            if any(name not in joints for name in (root, mid, end)):
                continue
            solved = _fixed_endpoint_bend(
                joints[root], frame.joints[end], frame.joints[mid],
                upper=_distance(frame.joints[root], frame.joints[mid]),
                lower=_distance(frame.joints[mid], frame.joints[end]),
            )
            if solved is None:
                feasible = False
                break
            joints[mid] = solved
        if feasible and all(
            abs(_distance(joints[parent], joints[child]) - _distance(frame.joints[parent], frame.joints[child])) < 1e-8
            for parent, child in STRUCTURAL_BONES if parent in joints and child in joints
        ):
            return joints, scale
    return dict(frame.joints), 0.


def _align_core_for_same_phase_bilateral_travel(
    clip: MotionClip,
    *,
    bilateral_modes: dict[str, dict[str, object]],
) -> tuple[MotionClip, dict[str, object]]:
    legs_mode = bilateral_modes.get("legs")
    if not isinstance(legs_mode, dict) or legs_mode.get("mode") != "same_phase_symmetric":
        return clip, {"applied": False, "reason": "legs_not_same_phase_symmetric"}
    pairs = CORE_BILATERAL_PAIRS
    shoulder_width = median(
        _distance(frame.joints["left_shoulder"], frame.joints["right_shoulder"])
        for frame in clip.frames
        if "left_shoulder" in frame.joints and "right_shoulder" in frame.joints
    ) if all(name in clip.joint_names for name in ("left_shoulder", "right_shoulder")) else None
    collar_width = median(
        _distance(frame.joints["left_collar"], frame.joints["right_collar"])
        for frame in clip.frames
        if "left_collar" in frame.joints and "right_collar" in frame.joints
    ) if all(name in clip.joint_names for name in ("left_collar", "right_collar")) else None
    frames: list[MotionFrame] = []
    maximum_correction = 0.0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for left_name, right_name in pairs:
            left = joints.get(left_name)
            right = joints.get(right_name)
            if left is None or right is None:
                continue
            midpoint = _scale(_add(left, right), 0.5)
            pair_vector = _subtract(right, left)
            pair_length = _length(pair_vector)
            horizontal_direction = _normalize((pair_vector[0], 0.0, pair_vector[2]))
            if left_name == "left_collar" and collar_width is not None:
                left_hip = joints.get("left_hip")
                right_hip = joints.get("right_hip")
                if left_hip is not None and right_hip is not None:
                    hip_direction = _normalize((
                        right_hip[0] - left_hip[0],
                        0.0,
                        right_hip[2] - left_hip[2],
                    ))
                    if hip_direction is not None:
                        horizontal_direction = hip_direction
                        pair_length = collar_width
            if left_name == "left_shoulder" and shoulder_width is not None:
                left_hip = joints.get("left_hip")
                right_hip = joints.get("right_hip")
                if left_hip is not None and right_hip is not None:
                    hip_direction = _normalize((
                        right_hip[0] - left_hip[0],
                        0.0,
                        right_hip[2] - left_hip[2],
                    ))
                    if hip_direction is not None:
                        horizontal_direction = hip_direction
                        pair_length = shoulder_width
                # Preserve the observed shoulder midpoint. Symmetry constrains
                # bilateral orientation, not shoulder elevation relative to the spine.
            if horizontal_direction is None or pair_length <= 1e-9:
                continue
            half_vector = _scale(horizontal_direction, pair_length * 0.5)
            targets = {
                left_name: _subtract(midpoint, half_vector),
                right_name: _add(midpoint, half_vector),
            }
            for name, target in targets.items():
                correction = _subtract(target, joints[name])
                maximum_correction = max(maximum_correction, _length(correction))
                joints[name] = target
                if name in {"left_shoulder", "right_shoulder"}:
                    side = name.removesuffix("_shoulder")
                    for descendant in (f"{side}_elbow", f"{side}_wrist", f"{side}_hand"):
                        if descendant in joints:
                            joints[descendant] = _add(joints[descendant], correction)
        if "left_hip" in joints and "right_hip" in joints and "pelvis" in joints:
            lateral_axis = _normalize((
                joints["right_hip"][0] - joints["left_hip"][0],
                0.0,
                joints["right_hip"][2] - joints["left_hip"][2],
            ))
            if lateral_axis is not None:
                pelvis = joints["pelvis"]
                for name in ("spine1", "spine2", "spine3", "neck", "head"):
                    point = joints.get(name)
                    if point is None:
                        continue
                    lateral_offset = _dot(_subtract(point, pelvis), lateral_axis)
                    target = _subtract(point, _scale(lateral_axis, lateral_offset))
                    maximum_correction = max(maximum_correction, _distance(point, target))
                    joints[name] = target
        # Leg symmetry is not evidence for changing the arms. Keep the shoulder
        # anchors too, avoiding near-extension elbow snaps from torso leveling.
        joints, _ = _project_core_targets_with_fixed_endpoints(frame, joints, preserve_shoulders=True)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    maximum_correction = max((_distance(before.joints[name], after.joints[name])
                              for before, after in zip(clip.frames, frames)
                              for name in before.joints), default=0.)
    return replace(clip, frames=frames), {
        "applied": maximum_correction > 1e-9,
        "strategy": "core_pair_leveling_with_rigid_bones_and_fixed_limb_endpoints",
        "pairs": [list(pair) for pair in pairs],
        "axialChain": ["pelvis", "spine1", "spine2", "spine3", "neck", "head"],
        "maximumCorrection": maximum_correction,
        "shoulderWidth": shoulder_width,
        "collarWidth": collar_width,
        "limbEndpointsPreserved": True,
    }


def _straighten_same_phase_bilateral_travel(
    clip: MotionClip,
    *,
    bilateral_modes: dict[str, dict[str, object]],
) -> tuple[MotionClip, dict[str, object]]:
    legs_mode = bilateral_modes.get("legs")
    if not isinstance(legs_mode, dict) or legs_mode.get("mode") != "same_phase_symmetric":
        return clip, {"applied": False, "reason": "legs_not_same_phase_symmetric"}
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    vertical_grounding = cleanup.get("verticalGrounding") if isinstance(cleanup, dict) else None
    intermittent = (
        isinstance(vertical_grounding, dict)
        and str(vertical_grounding.get("groundContactMode") or "").casefold() == "intermittent"
    )
    if not intermittent:
        return clip, {"applied": False, "reason": "authoritative_travel_unavailable"}
    root_name = next((name for name in ROOT_VERTICAL_MOTION_JOINTS if name in clip.joint_names), None)
    if root_name is None or clip.frame_count < 3:
        return clip, {"applied": False, "reason": "root_trajectory_unavailable"}
    first = clip.frames[0].joints[root_name]
    last = clip.frames[-1].joints[root_name]
    direction_start = first
    direction_end = last
    direction_source = "clip_endpoints"
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if isinstance(contacts, list):
        contact_indices = [
            index
            for index, state in enumerate(contacts[:clip.frame_count])
            if isinstance(state, dict) and bool(state.get("contactJoints"))
        ]
        contact_episodes: list[list[int]] = []
        for index in contact_indices:
            if not contact_episodes or index != contact_episodes[-1][-1] + 1:
                contact_episodes.append([index])
            else:
                contact_episodes[-1].append(index)
        if len(contact_episodes) >= 2:
            departure_index = contact_episodes[0][-1]
            landing_index = contact_episodes[-1][0]
            def support_center(frame_index: int) -> Point3 | None:
                state = contacts[frame_index]
                names = state.get("contactJoints") if isinstance(state, dict) else None
                points = [
                    clip.frames[frame_index].joints[name]
                    for name in names or []
                    if isinstance(name, str) and name in clip.frames[frame_index].joints
                ]
                if not points:
                    return None
                return tuple(
                    sum(point[axis] for point in points) / len(points)
                    for axis in range(3)
                )

            departure_support = support_center(departure_index)
            landing_support = support_center(landing_index)
            direction_start = (
                departure_support
                if departure_support is not None
                else clip.frames[departure_index].joints[root_name]
            )
            direction_end = (
                landing_support
                if landing_support is not None
                else clip.frames[landing_index].joints[root_name]
            )
            direction_source = (
                "takeoff_to_landing_support_centers"
                if departure_support is not None and landing_support is not None
                else "takeoff_to_landing_contacts"
            )
    direction = _normalize((
        direction_end[0] - direction_start[0],
        0.0,
        direction_end[2] - direction_start[2],
    ))
    if direction is None:
        return clip, {"applied": False, "reason": "degenerate_root_travel"}
    lateral = (-direction[2], 0.0, direction[0])
    corrections: list[float] = []
    frames: list[MotionFrame] = []
    for frame in clip.frames:
        root = frame.joints[root_name]
        lateral_offset = _dot(_subtract(root, direction_start), lateral)
        correction = _scale(lateral, -lateral_offset)
        corrections.append(abs(lateral_offset))
        frames.append(MotionFrame(
            time_sec=frame.time_sec,
            joints={name: _add(point, correction) for name, point in frame.joints.items()},
        ))
    return replace(clip, frames=frames), {
        "applied": any(value > 1e-9 for value in corrections),
        "strategy": "rigid_per_frame_lateral_projection_to_travel_line",
        "directionSource": direction_source,
        "maximumLateralCorrection": max(corrections, default=0.0),
        "preservedComponents": ["vertical_root_motion", "longitudinal_root_motion", "articulation"],
    }


def _align_terminal_contact_to_source_pose(
    clip: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    grounding = cleanup.get("verticalGrounding") if isinstance(cleanup, dict) else None
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if (
        not isinstance(grounding, dict)
        or grounding.get("groundContactMode") != "intermittent"
        or not isinstance(contacts, list)
    ):
        return clip, {"applied": False, "reason": "intermittent_contacts_unavailable"}
    source_frames = _source_pose_frames_with_normalized_time(source_pose_payload)
    if len(source_frames) < 3:
        return clip, {"applied": False, "reason": "source_pose_frames_unavailable"}
    ankle_pairs: list[tuple[float, tuple[float, float], tuple[float, float]]] = []
    stance_widths: list[float] = []
    for frame in source_frames:
        joints = frame["joints"]
        left = joints.get("left_ankle")
        right = joints.get("right_ankle")
        if not (
            isinstance(left, (list, tuple))
            and isinstance(right, (list, tuple))
            and len(left) >= 2
            and len(right) >= 2
        ):
            continue
        left_xy = (float(left[0]), float(left[1]))
        right_xy = (float(right[0]), float(right[1]))
        stance_widths.append(math.dist(left_xy, right_xy))
        ankle_pairs.append((float(frame.get("normalizedTime", 0.0)), left_xy, right_xy))
    if len(ankle_pairs) < 3 or not stance_widths:
        return clip, {"applied": False, "reason": "bilateral_source_ankles_unavailable"}
    stationary_step_tolerance = median(stance_widths) * 0.30
    terminal_sample_count = min(3, len(ankle_pairs))
    terminal_left = tuple(
        median(pair[1][axis] for pair in ankle_pairs[-terminal_sample_count:])
        for axis in range(2)
    )
    terminal_right = tuple(
        median(pair[2][axis] for pair in ankle_pairs[-terminal_sample_count:])
        for axis in range(2)
    )
    suffix_start = len(ankle_pairs) - 1
    while suffix_start > 0:
        _previous_time, previous_left, previous_right = ankle_pairs[suffix_start - 1]
        if max(
            math.dist(previous_left, terminal_left),
            math.dist(previous_right, terminal_right),
        ) > stationary_step_tolerance:
            break
        suffix_start -= 1
    source_landing_time = ankle_pairs[suffix_start][0]
    source_landing_frame = round(source_landing_time * (clip.frame_count - 1))

    contact_indices = [
        index
        for index, state in enumerate(contacts)
        if isinstance(state, dict) and state.get("contactJoints")
    ]
    contact_runs: list[list[int]] = []
    for index in contact_indices:
        if not contact_runs or index != contact_runs[-1][-1] + 1:
            contact_runs.append([index])
        else:
            contact_runs[-1].append(index)
    if len(contact_runs) < 2:
        return clip, {"applied": False, "reason": "distinct_contact_episodes_unavailable"}
    departure_end = contact_runs[0][-1]
    detected_landing_start = contact_runs[-1][0]
    if not departure_end < source_landing_frame < detected_landing_start:
        return clip, {
            "applied": False,
            "reason": "source_landing_does_not_precede_detected_landing",
            "sourceLandingFrame": source_landing_frame,
            "detectedLandingFrame": detected_landing_start,
        }
    root_name = next(
        (name for name in ROOT_VERTICAL_MOTION_JOINTS if name in clip.joint_names),
        None,
    )
    source_takeoff_frame = departure_end
    if root_name is not None and source_landing_frame > departure_end + 1:
        vertical_velocities = [
            (
                frame_index,
                (
                    clip.frames[frame_index].joints[root_name][1]
                    - clip.frames[frame_index - 1].joints[root_name][1]
                )
                / max(
                    clip.frames[frame_index].time_sec
                    - clip.frames[frame_index - 1].time_sec,
                    1e-9,
                ),
            )
            for frame_index in range(departure_end + 1, source_landing_frame)
        ]
        source_takeoff_frame = max(vertical_velocities, key=lambda item: item[1])[0]
    terminal_state = contacts[detected_landing_start]
    terminal_names = list(terminal_state.get("contactJoints") or [])
    repaired_contacts = [dict(state) if isinstance(state, dict) else {} for state in contacts]
    for frame_index in range(departure_end + 1, source_takeoff_frame + 1):
        state = repaired_contacts[frame_index]
        state.update({
            "contactJoints": terminal_names,
            "leftInContact": "left_foot" in terminal_names,
            "rightInContact": "right_foot" in terminal_names,
            "leftHandInContact": False,
            "rightHandInContact": False,
            "supportJoint": terminal_names[0] if terminal_names else None,
            "supportFoot": terminal_names[0] if terminal_names else None,
            "state": "double_support" if len(terminal_names) >= 2 else "planted",
            "contactInference": "root_peak_upward_velocity",
        })
    for frame_index in range(source_landing_frame, detected_landing_start):
        state = repaired_contacts[frame_index]
        state.update({
            "contactJoints": terminal_names,
            "leftInContact": "left_foot" in terminal_names,
            "rightInContact": "right_foot" in terminal_names,
            "leftHandInContact": False,
            "rightHandInContact": False,
            "supportJoint": terminal_names[0] if terminal_names else None,
            "supportFoot": terminal_names[0] if terminal_names else None,
            "state": "double_support" if len(terminal_names) >= 2 else "planted",
            "contactInference": "source_pose_terminal_foot_plateau",
        })
    updated_cleanup = dict(cleanup)
    updated_cleanup["footContacts"] = repaired_contacts
    updated_profile = dict(updated_cleanup.get("supportProfile") or {})
    promoted_departure_count = source_takeoff_frame - departure_end
    promoted_landing_count = detected_landing_start - source_landing_frame
    promoted_count = promoted_departure_count + promoted_landing_count
    updated_profile["groundContactFrames"] = int(
        updated_profile.get("groundContactFrames") or 0
    ) + promoted_count
    updated_profile["leftFootContactFrames"] = int(
        updated_profile.get("leftFootContactFrames") or 0
    ) + promoted_count
    updated_profile["rightFootContactFrames"] = int(
        updated_profile.get("rightFootContactFrames") or 0
    ) + promoted_count
    updated_cleanup["supportProfile"] = updated_profile
    metadata = dict(clip.metadata)
    metadata["cleanup"] = updated_cleanup
    return replace(clip, metadata=metadata), {
        "applied": True,
        "strategy": "terminal_bilateral_source_ankle_plateau",
        "sourceLandingFrame": source_landing_frame,
        "previousLandingFrame": detected_landing_start,
        "sourceTakeoffFrame": source_takeoff_frame,
        "previousTakeoffFrame": departure_end,
        "promotedDepartureFrames": list(
            range(departure_end + 1, source_takeoff_frame + 1)
        ),
        "promotedLandingFrames": list(range(source_landing_frame, detected_landing_start)),
        "stationaryStepTolerance": stationary_step_tolerance,
    }


def _stabilize_distinct_contact_surfaces(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    vertical_grounding = cleanup.get("verticalGrounding") if isinstance(cleanup, dict) else None
    mode = str(
        vertical_grounding.get("groundContactMode")
        if isinstance(vertical_grounding, dict)
        else ""
    ).strip().casefold()
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if mode != "intermittent" or not isinstance(contacts, list):
        return clip, {"applied": False, "reason": "distinct_contact_surfaces_unavailable"}

    episodes: list[list[tuple[int, tuple[str, ...], float, float, float]]] = []
    active: list[tuple[int, tuple[str, ...], float, float, float]] = []
    for frame_index, frame in enumerate(clip.frames):
        state = contacts[frame_index] if frame_index < len(contacts) else None
        raw_names = state.get("contactJoints") if isinstance(state, dict) else None
        names = tuple(
            name
            for name in raw_names or []
            if isinstance(name, str) and name in frame.joints
        )
        heights = [support_surface_height(frame.joints[name][1]) for name in names]
        if heights:
            active.append((
                frame_index,
                names,
                min(heights),
                sum(frame.joints[name][0] for name in names) / len(names),
                sum(frame.joints[name][2] for name in names) / len(names),
            ))
        elif active:
            episodes.append(active)
            active = []
    if active:
        episodes.append(active)
    if not episodes:
        return clip, {"applied": False, "reason": "no_contact_episodes"}

    corrections: list[Point3 | None] = [None] * clip.frame_count
    episode_payloads: list[dict[str, object]] = []
    first_surface_height = median(sample[2] for sample in episodes[0])
    last_surface_height = median(sample[2] for sample in episodes[-1])
    ascending_to_distinct_surface = (
        last_surface_height > first_surface_height + UNIFORM_CAPSULE_RADIUS
    )
    descending_to_distinct_surface = (
        first_surface_height > last_surface_height + UNIFORM_CAPSULE_RADIUS
    )
    def episode_target_height(
        episode_index: int,
        episode: list[tuple[int, tuple[str, ...], float, float, float]],
    ) -> float:
        if ascending_to_distinct_surface and episode_index == len(episodes) - 1:
            # The physical landing plane is established at first touchdown.
            # Later monocular reconstruction drift must not lift the surface.
            return episode[0][2]
        return median(sample[2] for sample in episode)
    pruned_contact_frames: list[int] = []
    if len(episodes) > 2 and (ascending_to_distinct_surface or descending_to_distinct_surface):
        retained_episodes = [episodes[0]]
        for episode in episodes[1:-1]:
            surface_height = median(sample[2] for sample in episode)
            lies_between_distinct_surfaces = (
                first_surface_height + UNIFORM_CAPSULE_RADIUS
                < surface_height
                < last_surface_height - UNIFORM_CAPSULE_RADIUS
            ) if ascending_to_distinct_surface else (
                last_surface_height + UNIFORM_CAPSULE_RADIUS
                < surface_height
                < first_surface_height - UNIFORM_CAPSULE_RADIUS
            )
            if lies_between_distinct_surfaces:
                retained_episodes.append(episode)
            else:
                pruned_contact_frames.extend(sample[0] for sample in episode)
        retained_episodes.append(episodes[-1])
        episodes = retained_episodes
    extended_departure_contact_frames: list[int] = []
    contact_timing_is_inferred = any(
        isinstance(state, dict) and state.get("contactInference") in {
            "ballistic_root_phase",
            "source_pose_terminal_foot_plateau",
            "root_peak_upward_velocity",
        }
        for state in contacts
    )
    if ascending_to_distinct_surface and len(episodes) >= 2 and not contact_timing_is_inferred:
        departure_episode = episodes[0]
        departure_end = departure_episode[-1][0]
        landing_start = episodes[-1][0][0]
        feet = ("left_foot", "right_foot")
        if all(foot in clip.joint_names for foot in feet):
            lift_off_index = next(
                (
                    frame_index
                    for frame_index in range(departure_end + 1, landing_start)
                    if min(
                        support_surface_height(clip.frames[frame_index].joints[foot][1])
                        - first_surface_height
                        for foot in feet
                    ) > UNIFORM_CAPSULE_RADIUS
                ),
                landing_start,
            )
            for frame_index in range(departure_end + 1, lift_off_index):
                frame = clip.frames[frame_index]
                heights = [support_surface_height(frame.joints[foot][1]) for foot in feet]
                departure_episode.append((
                    frame_index,
                    feet,
                    min(heights),
                    sum(frame.joints[foot][0] for foot in feet) / len(feet),
                    sum(frame.joints[foot][2] for foot in feet) / len(feet),
                ))
                extended_departure_contact_frames.append(frame_index)
            if extended_departure_contact_frames:
                extended_set = set(extended_departure_contact_frames)
                pruned_contact_frames = [
                    frame_index
                    for frame_index in pruned_contact_frames
                    if frame_index not in extended_set
                ]
    bilateral_surface_episodes: set[int] = set()
    bilateral_horizontal_corrections: dict[int, tuple[float, float]] = {}
    for episode_index, episode in enumerate(episodes):
        target_height = episode_target_height(episode_index, episode)
        target_x = median(sample[3] for sample in episode)
        target_z = median(sample[4] for sample in episode)
        bilateral_frame_indices = list(range(episode[0][0], episode[-1][0] + 1))
        if episode_index == 0 and ascending_to_distinct_surface:
            bilateral_frame_indices = list(range(0, episode[-1][0] + 1))
        feet = ("left_foot", "right_foot")
        if all(foot in clip.joint_names for foot in feet) and all(
            median(
                abs(
                    support_surface_height(clip.frames[index].joints[foot][1])
                    - target_height
                )
                for index in bilateral_frame_indices
            ) <= UNIFORM_CAPSULE_RADIUS * 2.0
            for foot in feet
        ):
            bilateral_surface_episodes.add(episode_index)
            # Bilateral foot reconstruction noise must not redefine the body's
            # accepted horizontal trajectory. Per-foot anchors and leg IK own
            # the support correction without translating the pelvis episode.
            bilateral_horizontal_corrections[episode_index] = (0.0, 0.0)
        episode_horizontal = bilateral_horizontal_corrections.get(episode_index)
        for frame_index, _names, measured_height, measured_x, measured_z in episode:
            corrections[frame_index] = (
                episode_horizontal[0] if episode_horizontal is not None else target_x - measured_x,
                target_height - measured_height,
                episode_horizontal[1] if episode_horizontal is not None else target_z - measured_z,
            )
        if episode_index == 0 and ascending_to_distinct_surface and episode[0][0] > 0:
            support_names = sorted({
                name
                for _index, names, _height, _x, _z in episode
                for name in names
            })
            for frame_index in range(episode[0][0]):
                frame = clip.frames[frame_index]
                available = [name for name in support_names if name in frame.joints]
                if not available:
                    continue
                measured_height = min(
                    support_surface_height(frame.joints[name][1]) for name in available
                )
                measured_x = sum(frame.joints[name][0] for name in available) / len(available)
                measured_z = sum(frame.joints[name][2] for name in available) / len(available)
                corrections[frame_index] = (
                    episode_horizontal[0] if episode_horizontal is not None else target_x - measured_x,
                    target_height - measured_height,
                    episode_horizontal[1] if episode_horizontal is not None else target_z - measured_z,
                )
        episode_payloads.append({
            "episodeIndex": episode_index,
            "startFrame": episode[0][0],
            "endFrame": episode[-1][0],
            "surfaceHeight": target_height,
            "supportCenter": [target_x, target_height, target_z],
            "contactJoints": sorted({name for _index, names, _height, _x, _z in episode for name in names}),
        })

    known = [index for index, value in enumerate(corrections) if value is not None]
    resolved: list[Point3] = []
    for frame_index, correction in enumerate(corrections):
        if correction is not None:
            resolved.append(correction)
            continue
        previous = max((index for index in known if index < frame_index), default=None)
        following = min((index for index in known if index > frame_index), default=None)
        if previous is None and following is None:
            resolved.append((0.0, 0.0, 0.0))
        elif previous is None:
            resolved.append(corrections[following])  # type: ignore[arg-type]
        elif following is None:
            resolved.append(corrections[previous])  # type: ignore[arg-type]
        else:
            blend = (frame_index - previous) / (following - previous)
            left = corrections[previous]
            right = corrections[following]
            resolved.append(tuple(
                left[axis] * (1.0 - blend) + right[axis] * blend  # type: ignore[index]
                for axis in range(3)
            ))

    stabilized_frames = [
        MotionFrame(
            time_sec=frame.time_sec,
            joints={
                name: _add(point, resolved[frame_index])
                for name, point in frame.joints.items()
            },
        )
        for frame_index, frame in enumerate(clip.frames)
    ]
    # A rigid episode correction fixes the support centroid, but it cannot stop
    # the two planted feet from sliding in opposite directions around that
    # centroid.  Anchor each foot independently when both feet occupy the same
    # contact surface, and let the two-bone leg solve absorb that correction.
    bilateral_anchor_payloads: list[dict[str, object]] = []
    departure_anchor_center: Point3 | None = None
    departure_pelvis: Point3 | None = None
    departure_end_index: int | None = None
    for episode_index, episode in enumerate(episodes):
        start_index = episode[0][0]
        if episode_index == 0 and ascending_to_distinct_surface:
            start_index = 0
        end_index = episode[-1][0]
        frame_indices = list(range(start_index, end_index + 1))
        target_height = episode_target_height(episode_index, episode)
        feet = ("left_foot", "right_foot")
        if episode_index not in bilateral_surface_episodes:
            continue
        terminal_landing_episode = (
            ascending_to_distinct_surface
            and episode_index == len(episodes) - 1
        )
        # A landing becomes planted at first contact. Using the median position
        # of the complete landing episode as its anchor can snap the shoes
        # backward on touchdown when the source feet drift afterward.
        boundary_index = (
            start_index if terminal_landing_episode
            else end_index if episode_index == 0 and ascending_to_distinct_surface
            else None
        )
        if boundary_index is not None and "pelvis" in stabilized_frames[boundary_index].joints:
            if terminal_landing_episode:
                # First contact is authoritative. Recentring this pair under
                # the pelvis discards a valid measured touchdown and visibly
                # snaps both feet backward before locking them.
                anchors = {
                    foot: (
                        stabilized_frames[boundary_index].joints[foot][0],
                        target_height + UNIFORM_CAPSULE_RADIUS,
                        stabilized_frames[boundary_index].joints[foot][2],
                    )
                    for foot in feet
                }
            else:
                boundary_left = clip.frames[boundary_index].joints[feet[0]]
                boundary_right = clip.frames[boundary_index].joints[feet[1]]
                boundary_center = _scale(_add(boundary_left, boundary_right), 0.5)
                boundary_pelvis = stabilized_frames[boundary_index].joints["pelvis"]
                anchors = {
                    foot: (
                        boundary_pelvis[0]
                        + clip.frames[boundary_index].joints[foot][0]
                        - boundary_center[0],
                        target_height + UNIFORM_CAPSULE_RADIUS,
                        boundary_pelvis[2]
                        + clip.frames[boundary_index].joints[foot][2]
                        - boundary_center[2],
                    )
                    for foot in feet
                }
        else:
            anchors = {
                foot: (
                    median(clip.frames[index].joints[foot][0] for index in frame_indices),
                    target_height + UNIFORM_CAPSULE_RADIUS,
                    median(clip.frames[index].joints[foot][2] for index in frame_indices),
                )
                for foot in feet
            }
        stable_ankle_to_foot = {
            foot: tuple(
                median(
                    clip.frames[index].joints[foot][axis]
                    - clip.frames[index].joints[f"{foot.removesuffix('_foot')}_ankle"][axis]
                    for index in frame_indices
                )
                for axis in range(3)
            )
            for foot in feet
        }
        anchor_center = _scale(_add(anchors[feet[0]], anchors[feet[1]]), 0.5)
        support_travel_correction = (0.0, 0.0, 0.0)
        maximum_airborne_foot_lateral_correction = 0.0
        maximum_airborne_foot_clearance_correction = 0.0
        maximum_departure_transition_correction = 0.0
        if episode_index == 0 and "pelvis" in clip.joint_names:
            departure_anchor_center = anchor_center
            departure_pelvis = stabilized_frames[end_index].joints["pelvis"]
            departure_end_index = end_index
        elif (
            episode_index == len(episodes) - 1
            and departure_anchor_center is not None
            and departure_pelvis is not None
            and departure_end_index is not None
            and start_index > departure_end_index
        ):
            for frame_index in range(start_index, end_index + 1):
                frame = stabilized_frames[frame_index]
                pelvis = frame.joints["pelvis"]
                landing_placement = (
                    anchor_center[0] - pelvis[0],
                    0.0,
                    anchor_center[2] - pelvis[2],
                )
                stabilized_frames[frame_index] = MotionFrame(
                    time_sec=frame.time_sec,
                    joints={
                        name: _add(point, landing_placement)
                        for name, point in frame.joints.items()
                    },
                )
            landing_start_pelvis = stabilized_frames[start_index].joints["pelvis"]
            current_landing_pelvis = stabilized_frames[start_index].joints["pelvis"]
            airborne_count = start_index - departure_end_index
            pelvis_displacement = _subtract(current_landing_pelvis, departure_pelvis)
            for frame_index in range(departure_end_index + 1, start_index):
                blend = (frame_index - departure_end_index) / airborne_count
                target_pelvis = _add(departure_pelvis, _scale(pelvis_displacement, blend))
                frame = stabilized_frames[frame_index]
                current_pelvis = frame.joints["pelvis"]
                correction = (
                    target_pelvis[0] - current_pelvis[0],
                    0.0,
                    target_pelvis[2] - current_pelvis[2],
                )
                stabilized_frames[frame_index] = MotionFrame(
                    time_sec=frame.time_sec,
                    joints={name: _add(point, correction) for name, point in frame.joints.items()},
                )
            travel_horizontal = (pelvis_displacement[0], 0.0, pelvis_displacement[2])
            travel_length = _length(travel_horizontal)
            if travel_length > 1e-9:
                travel_direction = _scale(travel_horizontal, 1.0 / travel_length)
                lateral_direction = (-travel_direction[2], 0.0, travel_direction[0])
                for frame_index in range(departure_end_index + 1, start_index):
                    frame = stabilized_frames[frame_index]
                    joints = dict(frame.joints)
                    if any(
                        name not in joints
                        for name in ("pelvis", "left_foot", "right_foot")
                    ):
                        continue
                    foot_center = _scale(
                        _add(joints["left_foot"], joints["right_foot"]),
                        0.5,
                    )
                    lateral_error = _dot(
                        _subtract(joints["pelvis"], foot_center),
                        lateral_direction,
                    )
                    distal_correction = _scale(lateral_direction, lateral_error)
                    maximum_airborne_foot_lateral_correction = max(
                        maximum_airborne_foot_lateral_correction,
                        abs(lateral_error),
                    )
                    for side in ("left", "right"):
                        ankle_name = f"{side}_ankle"
                        foot_name = f"{side}_foot"
                        hip_name = f"{side}_hip"
                        knee_name = f"{side}_knee"
                        if any(
                            name not in joints
                            for name in (hip_name, knee_name, ankle_name, foot_name)
                        ):
                            continue
                        target_ankle = _add(joints[ankle_name], distal_correction)
                        target_foot = _add(joints[foot_name], distal_correction)
                        body_frame = _body_local_frame(frame)
                        fallback_axis = (
                            body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
                        )
                        solved_knee, _ = _solve_two_bone(
                            root=joints[hip_name],
                            current_mid=joints[knee_name],
                            target_end=target_ankle,
                            upper_len=_median_bone_length(clip, hip_name, knee_name),
                            lower_len=_median_bone_length(clip, knee_name, ankle_name),
                            fallback_axis=fallback_axis,
                        )
                        joints[knee_name] = solved_knee
                        joints[ankle_name] = target_ankle
                        joints[foot_name] = target_foot
                    stabilized_frames[frame_index] = MotionFrame(
                        time_sec=frame.time_sec,
                        joints=joints,
                    )
                # Symmetric jumps should not retain a source-reconstruction
                # stagger where one foot sits ahead of the other. Preserve the
                # lateral stance and each foot's height while removing only the
                # pair's fore-aft separation.
                # Departure support has already been solved to exact anchors.
                # Restrict fore-aft symmetry repair to flight so this later
                # pass cannot reintroduce planted-foot slide.
                for frame_index in range(departure_end_index + 1, start_index):
                    frame = stabilized_frames[frame_index]
                    joints = dict(frame.joints)
                    if any(name not in joints for name in ("left_foot", "right_foot")):
                        continue
                    foot_center = _scale(
                        _add(joints["left_foot"], joints["right_foot"]),
                        0.5,
                    )
                    pair_vector = _subtract(joints["right_foot"], joints["left_foot"])
                    body_frame = _body_local_frame(frame)
                    stance_axis = (
                        _normalize((body_frame.right[0], 0.0, body_frame.right[2]))
                        if body_frame is not None
                        else None
                    ) or lateral_direction
                    lateral_sign = -1.0 if _dot(pair_vector, stance_axis) < 0.0 else 1.0
                    signed_half_width = lateral_sign * math.hypot(
                        pair_vector[0], pair_vector[2]
                    ) * 0.5
                    for side, sign in (("left", -1.0), ("right", 1.0)):
                        foot_name = f"{side}_foot"
                        ankle_name = f"{side}_ankle"
                        hip_name = f"{side}_hip"
                        knee_name = f"{side}_knee"
                        if any(
                            name not in joints
                            for name in (hip_name, knee_name, ankle_name, foot_name)
                        ):
                            continue
                        current_foot = joints[foot_name]
                        target_foot = (
                            foot_center[0] + stance_axis[0] * signed_half_width * sign,
                            current_foot[1],
                            foot_center[2] + stance_axis[2] * signed_half_width * sign,
                        )
                        distal_correction = _subtract(target_foot, current_foot)
                        target_ankle = _add(joints[ankle_name], distal_correction)
                        body_frame = _body_local_frame(frame)
                        solved_knee, _ = _solve_two_bone(
                            root=joints[hip_name],
                            current_mid=joints[knee_name],
                            target_end=target_ankle,
                            upper_len=_median_bone_length(clip, hip_name, knee_name),
                            lower_len=_median_bone_length(clip, knee_name, ankle_name),
                            fallback_axis=(
                                body_frame.forward
                                if body_frame is not None
                                else (0.0, 0.0, 1.0)
                            ),
                        )
                        joints[knee_name] = solved_knee
                        joints[ankle_name] = target_ankle
                        joints[foot_name] = target_foot
                    stabilized_frames[frame_index] = MotionFrame(
                        time_sec=frame.time_sec,
                        joints=joints,
                    )
                landing_pair = _subtract(anchors["right_foot"], anchors["left_foot"])
                landing_body_frame = _body_local_frame(stabilized_frames[start_index])
                landing_stance_axis = (
                    _normalize((
                        landing_body_frame.right[0],
                        0.0,
                        landing_body_frame.right[2],
                    ))
                    if landing_body_frame is not None
                    else None
                ) or lateral_direction
                landing_sign = -1.0 if _dot(landing_pair, landing_stance_axis) < 0.0 else 1.0
                landing_half_width = landing_sign * math.hypot(
                    landing_pair[0], landing_pair[2]
                ) * 0.5
                anchors = {
                    foot: (
                        anchor_center[0]
                        + landing_stance_axis[0] * landing_half_width * sign,
                        point[1],
                        anchor_center[2]
                        + landing_stance_axis[2] * landing_half_width * sign,
                    )
                    for foot, point, sign in (
                        ("left_foot", anchors["left_foot"], -1.0),
                        ("right_foot", anchors["right_foot"], 1.0),
                    )
                }
                apex_index = max(
                    range(departure_end_index + 1, start_index),
                    key=lambda index: stabilized_frames[index].joints["pelvis"][1],
                )
                departure_foot_offsets = {
                    foot: _subtract(point, departure_pelvis)
                    for foot, point in (
                        ("left_foot", stabilized_frames[departure_end_index].joints["left_foot"]),
                        ("right_foot", stabilized_frames[departure_end_index].joints["right_foot"]),
                    )
                }
                departure_duration = apex_index - departure_end_index
                if departure_duration > 0:
                    for frame_index in range(departure_end_index + 1, apex_index):
                        # The first free frame must continue from the planted
                        # pose. Starting the blend at a nonzero fraction leaks
                        # a reconstruction discontinuity straight through the
                        # contact boundary, especially in short jumps.
                        transition_span = max(1, departure_duration - 1)
                        blend = (
                            frame_index - departure_end_index - 1
                        ) / transition_span
                        smooth_blend = blend * blend * (3.0 - 2.0 * blend)
                        frame = stabilized_frames[frame_index]
                        joints = dict(frame.joints)
                        pelvis = joints["pelvis"]
                        for side in ("left", "right"):
                            foot_name = f"{side}_foot"
                            ankle_name = f"{side}_ankle"
                            hip_name = f"{side}_hip"
                            knee_name = f"{side}_knee"
                            if any(
                                name not in joints
                                for name in (hip_name, knee_name, ankle_name, foot_name)
                            ):
                                continue
                            current_foot = joints[foot_name]
                            rigid_departure_foot = _add(
                                pelvis,
                                departure_foot_offsets[foot_name],
                            )
                            target_foot = (
                                rigid_departure_foot[0] * (1.0 - smooth_blend)
                                + current_foot[0] * smooth_blend,
                                current_foot[1],
                                rigid_departure_foot[2] * (1.0 - smooth_blend)
                                + current_foot[2] * smooth_blend,
                            )
                            distal_correction = _subtract(target_foot, current_foot)
                            maximum_departure_transition_correction = max(
                                maximum_departure_transition_correction,
                                math.hypot(distal_correction[0], distal_correction[2]),
                            )
                            target_ankle = _add(joints[ankle_name], distal_correction)
                            body_frame = _body_local_frame(frame)
                            solved_knee, _ = _solve_two_bone(
                                root=joints[hip_name],
                                current_mid=joints[knee_name],
                                target_end=target_ankle,
                                upper_len=_median_bone_length(clip, hip_name, knee_name),
                                lower_len=_median_bone_length(clip, knee_name, ankle_name),
                                fallback_axis=(
                                    body_frame.forward
                                    if body_frame is not None
                                    else (0.0, 0.0, 1.0)
                                ),
                            )
                            joints[knee_name] = solved_knee
                            joints[ankle_name] = target_ankle
                            joints[foot_name] = target_foot
                        stabilized_frames[frame_index] = MotionFrame(
                            time_sec=frame.time_sec,
                            joints=joints,
                        )
                approach_start = apex_index
                approach_duration = start_index - approach_start
                if approach_duration > 0:
                    approach_start_feet = {
                        foot: stabilized_frames[approach_start].joints[foot]
                        for foot in ("left_foot", "right_foot")
                    }
                    for frame_index in range(approach_start, start_index):
                        blend = (frame_index - approach_start) / approach_duration
                        smooth_blend = blend * blend * blend * (
                            blend * (blend * 6.0 - 15.0) + 10.0
                        )
                        frame = stabilized_frames[frame_index]
                        joints = dict(frame.joints)
                        for side in ("left", "right"):
                            foot_name = f"{side}_foot"
                            ankle_name = f"{side}_ankle"
                            hip_name = f"{side}_hip"
                            knee_name = f"{side}_knee"
                            if any(
                                name not in joints
                                for name in (hip_name, knee_name, ankle_name, foot_name)
                            ):
                                continue
                            current_foot = joints[foot_name]
                            approach_foot = approach_start_feet[foot_name]
                            anchor = anchors[foot_name]
                            target_foot = (
                                approach_foot[0] * (1.0 - smooth_blend)
                                + anchor[0] * smooth_blend,
                                current_foot[1],
                                approach_foot[2] * (1.0 - smooth_blend)
                                + anchor[2] * smooth_blend,
                            )
                            distal_correction = _subtract(target_foot, current_foot)
                            target_ankle = _add(joints[ankle_name], distal_correction)
                            body_frame = _body_local_frame(frame)
                            solved_knee, _ = _solve_two_bone(
                                root=joints[hip_name],
                                current_mid=joints[knee_name],
                                target_end=target_ankle,
                                upper_len=_median_bone_length(clip, hip_name, knee_name),
                                lower_len=_median_bone_length(clip, knee_name, ankle_name),
                                fallback_axis=(
                                    body_frame.forward
                                    if body_frame is not None
                                    else (0.0, 0.0, 1.0)
                                ),
                            )
                            joints[knee_name] = solved_knee
                            joints[ankle_name] = target_ankle
                            joints[foot_name] = target_foot
                        stabilized_frames[frame_index] = MotionFrame(
                            time_sec=frame.time_sec,
                            joints=joints,
                        )
                # A monocular reconstruction can briefly invert the vertical
                # foot trajectory after takeoff even when the root follows a
                # valid jump arc. The two known support surfaces provide a
                # physical lower envelope: feet must clear a smooth transition
                # between departure and landing while airborne.
                departure_surface_height = (
                    departure_anchor_center[1] - UNIFORM_CAPSULE_RADIUS
                )
                landing_surface_height = anchor_center[1] - UNIFORM_CAPSULE_RADIUS
                airborne_count = start_index - departure_end_index
                for frame_index in range(departure_end_index + 1, start_index):
                    blend = (frame_index - departure_end_index) / airborne_count
                    smooth_blend = blend * blend * (3.0 - 2.0 * blend)
                    minimum_surface_height = (
                        departure_surface_height * (1.0 - smooth_blend)
                        + landing_surface_height * smooth_blend
                    )
                    frame = stabilized_frames[frame_index]
                    joints = dict(frame.joints)
                    for side in ("left", "right"):
                        hip_name = f"{side}_hip"
                        knee_name = f"{side}_knee"
                        ankle_name = f"{side}_ankle"
                        foot_name = f"{side}_foot"
                        if any(
                            name not in joints
                            for name in (hip_name, knee_name, ankle_name, foot_name)
                        ):
                            continue
                        current_surface_height = support_surface_height(
                            joints[foot_name][1]
                        )
                        correction_y = max(
                            0.0,
                            minimum_surface_height - current_surface_height,
                        )
                        if correction_y <= 0.0:
                            continue
                        maximum_airborne_foot_clearance_correction = max(
                            maximum_airborne_foot_clearance_correction,
                            correction_y,
                        )
                        target_ankle = _add(
                            joints[ankle_name],
                            (0.0, correction_y, 0.0),
                        )
                        target_foot = _add(
                            joints[foot_name],
                            (0.0, correction_y, 0.0),
                        )
                        body_frame = _body_local_frame(frame)
                        solved_knee, _ = _solve_two_bone(
                            root=joints[hip_name],
                            current_mid=joints[knee_name],
                            target_end=target_ankle,
                            upper_len=_median_bone_length(clip, hip_name, knee_name),
                            lower_len=_median_bone_length(clip, knee_name, ankle_name),
                            fallback_axis=(
                                body_frame.forward
                                if body_frame is not None
                                else (0.0, 0.0, 1.0)
                            ),
                        )
                        joints[knee_name] = solved_knee
                        joints[ankle_name] = target_ankle
                        joints[foot_name] = target_foot
                    stabilized_frames[frame_index] = MotionFrame(
                        time_sec=frame.time_sec,
                        joints=joints,
                    )
        maximum_pelvis_settlement_correction = 0.0
        terminal_distinct_landing = (
            ascending_to_distinct_surface
            and episode_index == len(episodes) - 1
            and end_index == clip.frame_count - 1
            and "pelvis" in clip.joint_names
        )
        if terminal_distinct_landing and len(frame_indices) > 1:
            start_pelvis = stabilized_frames[start_index].joints["pelvis"]
            end_pelvis = stabilized_frames[end_index].joints["pelvis"]
            end_pelvis = (anchor_center[0], end_pelvis[1], anchor_center[2])
            denominator = len(frame_indices) - 1
            for position, frame_index in enumerate(frame_indices):
                blend = position / denominator
                smooth_blend = blend * blend * (3.0 - 2.0 * blend)
                target_x = start_pelvis[0] * (1.0 - smooth_blend) + end_pelvis[0] * smooth_blend
                target_z = start_pelvis[2] * (1.0 - smooth_blend) + end_pelvis[2] * smooth_blend
                frame = stabilized_frames[frame_index]
                pelvis = frame.joints["pelvis"]
                correction = (target_x - pelvis[0], 0.0, target_z - pelvis[2])
                maximum_pelvis_settlement_correction = max(
                    maximum_pelvis_settlement_correction,
                    math.hypot(correction[0], correction[2]),
                )
                stabilized_frames[frame_index] = MotionFrame(
                    time_sec=frame.time_sec,
                    joints={name: _add(point, correction) for name, point in frame.joints.items()},
                )
        maximum_displacement = 0.0
        for frame_index in frame_indices:
            frame = stabilized_frames[frame_index]
            joints = dict(frame.joints)
            for foot_name in feet:
                side = foot_name.removesuffix("_foot")
                hip_name = f"{side}_hip"
                knee_name = f"{side}_knee"
                ankle_name = f"{side}_ankle"
                if any(name not in joints for name in (hip_name, knee_name, ankle_name)):
                    continue
                ankle_to_foot = stable_ankle_to_foot[foot_name]
                target_foot = anchors[foot_name]
                target_ankle = _subtract(target_foot, ankle_to_foot)
                body_frame = _body_local_frame(frame)
                fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
                solved_knee, _reachable_ankle = _solve_two_bone(
                    root=joints[hip_name],
                    current_mid=joints[knee_name],
                    target_end=target_ankle,
                    upper_len=_median_bone_length(clip, hip_name, knee_name),
                    lower_len=_median_bone_length(clip, knee_name, ankle_name),
                    fallback_axis=fallback_axis,
                )
                solved_ankle = target_ankle
                solved_foot = target_foot
                maximum_displacement = max(
                    maximum_displacement,
                    _distance(joints[knee_name], solved_knee),
                    _distance(joints[ankle_name], solved_ankle),
                    _distance(joints[foot_name], solved_foot),
                )
                joints[knee_name] = solved_knee
                joints[ankle_name] = solved_ankle
                joints[foot_name] = solved_foot
            stabilized_frames[frame_index] = MotionFrame(time_sec=frame.time_sec, joints=joints)
        bilateral_anchor_payloads.append({
            "episodeIndex": episode_index,
            "startFrame": start_index,
            "endFrame": end_index,
            "anchors": {name: list(point) for name, point in anchors.items()},
            "maximumDisplacement": maximum_displacement,
            "terminalPelvisSettlement": {
                "applied": terminal_distinct_landing,
                "strategy": "smooth_support_relative_arrival_to_final_offset",
                "maximumCorrection": maximum_pelvis_settlement_correction,
            },
            "supportCenterTravelCorrection": list(support_travel_correction),
            "maximumAirborneFootLateralCorrection": maximum_airborne_foot_lateral_correction,
            "maximumAirborneFootClearanceCorrection": maximum_airborne_foot_clearance_correction,
            "maximumDepartureTransitionCorrection": maximum_departure_transition_correction,
        })
    output_metadata = clip.metadata
    if pruned_contact_frames and isinstance(cleanup, dict):
        repaired_contacts = [dict(state) if isinstance(state, dict) else {} for state in contacts]
        for frame_index in pruned_contact_frames:
            state = repaired_contacts[frame_index]
            state["contactJoints"] = []
            state["leftInContact"] = False
            state["rightInContact"] = False
            state["state"] = "flight"
        output_metadata = dict(clip.metadata)
        updated_cleanup = dict(cleanup)
        updated_cleanup["footContacts"] = repaired_contacts
        output_metadata["cleanup"] = updated_cleanup
    if extended_departure_contact_frames and isinstance(cleanup, dict):
        existing_cleanup = output_metadata.get("cleanup") if isinstance(output_metadata, dict) else None
        existing_contacts = (
            existing_cleanup.get("footContacts")
            if isinstance(existing_cleanup, dict)
            else contacts
        )
        repaired_contacts = [dict(state) if isinstance(state, dict) else {} for state in existing_contacts]
        for frame_index in extended_departure_contact_frames:
            state = repaired_contacts[frame_index]
            state["contactJoints"] = ["left_foot", "right_foot"]
            state["leftInContact"] = True
            state["rightInContact"] = True
            state["state"] = "double_support"
        output_metadata = dict(output_metadata)
        updated_cleanup = dict(existing_cleanup) if isinstance(existing_cleanup, dict) else dict(cleanup)
        updated_cleanup["footContacts"] = repaired_contacts
        output_metadata["cleanup"] = updated_cleanup
    return replace(clip, frames=stabilized_frames, metadata=output_metadata), {
        "applied": any(_length(value) > 1e-9 for value in resolved),
        "strategy": "rigid_per_contact_episode_3d_support_lock",
        "episodeCount": len(episodes),
        "episodes": episode_payloads,
        "maximumAbsCorrection": max((_length(value) for value in resolved), default=0.0),
        "maximumHorizontalCorrection": max((math.hypot(value[0], value[2]) for value in resolved), default=0.0),
        "posePreservation": "rigid_body_translation_plus_contact_leg_ik",
        "horizontalCorrectionOwnership": {
            "unilateralSupport": "rigid_body_translation",
            "bilateralSupport": "constant_episode_placement_plus_independent_foot_anchors",
        },
        "bilateralFootAnchors": bilateral_anchor_payloads,
        "prunedPhysicallyUnorderedContactFrames": pruned_contact_frames,
        "extendedDepartureContactFrames": extended_departure_contact_frames,
        "contactTimingSource": (
            "ballistic_root_phase"
            if contact_timing_is_inferred
            else "support_joint_height"
        ),
    }


def _repair_terminal_bilateral_landing(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if not isinstance(contacts, list) or not clip.frames:
        return clip, {"applied": False, "reason": "contact_states_unavailable"}
    terminal_indices: list[int] = []
    for frame_index in range(clip.frame_count - 1, -1, -1):
        state = contacts[frame_index] if frame_index < len(contacts) else None
        names = state.get("contactJoints") if isinstance(state, dict) else None
        if isinstance(names, list) and names:
            terminal_indices.append(frame_index)
        elif terminal_indices:
            break
    terminal_indices.reverse()
    if not terminal_indices or terminal_indices[-1] != clip.frame_count - 1:
        return clip, {"applied": False, "reason": "no_terminal_contact_episode"}
    terminal_names = {
        name
        for frame_index in terminal_indices
        for name in (
            contacts[frame_index].get("contactJoints", [])
            if isinstance(contacts[frame_index], dict)
            else []
        )
        if name in {"left_foot", "right_foot"}
    }
    if len(terminal_names) != 1:
        return clip, {"applied": False, "reason": "terminal_support_not_single_foot"}
    contact_foot = next(iter(terminal_names))
    opposite_foot = "right_foot" if contact_foot == "left_foot" else "left_foot"
    side = opposite_foot.removesuffix("_foot")
    hip_name = f"{side}_hip"
    knee_name = f"{side}_knee"
    ankle_name = f"{side}_ankle"
    required = (contact_foot, opposite_foot, hip_name, knee_name, ankle_name)
    if any(name not in clip.joint_names for name in required):
        return clip, {"applied": False, "reason": "bilateral_leg_chain_unavailable"}
    surface_height = median(
        support_surface_height(clip.frames[index].joints[contact_foot][1])
        for index in terminal_indices
    )
    opposite_clearances = [
        support_surface_height(clip.frames[index].joints[opposite_foot][1]) - surface_height
        for index in terminal_indices
    ]
    geometry_cluster_extent = UNIFORM_CAPSULE_RADIUS * 2.0
    if max(abs(value) for value in opposite_clearances) > geometry_cluster_extent:
        return clip, {
            "applied": False,
            "reason": "opposite_foot_not_in_same_surface_cluster",
            "maximumOppositeFootClearance": max(abs(value) for value in opposite_clearances),
            "surfaceClusterExtent": geometry_cluster_extent,
        }
    opposite_points = [clip.frames[index].joints[opposite_foot] for index in terminal_indices]
    horizontal_range = math.hypot(
        max(point[0] for point in opposite_points) - min(point[0] for point in opposite_points),
        max(point[2] for point in opposite_points) - min(point[2] for point in opposite_points),
    )
    if horizontal_range > geometry_cluster_extent:
        return clip, {
            "applied": False,
            "reason": "opposite_foot_not_stationary",
            "oppositeFootHorizontalRange": horizontal_range,
            "surfaceClusterExtent": geometry_cluster_extent,
        }

    detected_episode_start = terminal_indices[0]
    # Reaching the eventual support height does not imply contact: during a
    # jump the feet can cross that height well before touchdown. The stationary
    # terminal cluster is the authoritative landing onset.
    recovery_tolerance = UNIFORM_CAPSULE_RADIUS * 0.55
    entry_tolerance = UNIFORM_CAPSULE_RADIUS * 0.25
    arrival_region_start = detected_episode_start
    for frame_index in range(detected_episode_start - 1, -1, -1):
        frame = clip.frames[frame_index]
        clearances = [
            support_surface_height(frame.joints[foot][1]) - surface_height
            for foot in ("left_foot", "right_foot")
        ]
        current_center = _scale(
            _add(frame.joints["left_foot"], frame.joints["right_foot"]),
            0.5,
        )
        next_frame = clip.frames[frame_index + 1]
        next_center = _scale(
            _add(next_frame.joints["left_foot"], next_frame.joints["right_foot"]),
            0.5,
        )
        horizontal_step = math.hypot(
            next_center[0] - current_center[0],
            next_center[2] - current_center[2],
        )
        if (
            max(abs(value) for value in clearances) > recovery_tolerance
            or horizontal_step > UNIFORM_CAPSULE_RADIUS
        ):
            break
        arrival_region_start = frame_index
    physical_touchdown_start = next(
        (
            frame_index
            for frame_index in range(arrival_region_start, detected_episode_start + 1)
            if max(
                abs(
                    support_surface_height(clip.frames[frame_index].joints[foot][1])
                    - surface_height
                )
                for foot in ("left_foot", "right_foot")
            ) <= entry_tolerance
        ),
        detected_episode_start,
    )
    preceding_contact_end = -1
    for frame_index in range(detected_episode_start):
        state = contacts[frame_index]
        names = state.get("contactJoints") if isinstance(state, dict) else None
        if names:
            preceding_contact_end = frame_index
    strict_surface_arrival = next(
        (
            frame_index
            for frame_index in range(preceding_contact_end + 1, detected_episode_start + 1)
            if max(
                abs(
                    support_surface_height(clip.frames[frame_index].joints[foot][1])
                    - surface_height
                )
                for foot in ("left_foot", "right_foot")
            ) <= entry_tolerance
            and math.hypot(
                (
                    clip.frames[min(frame_index + 1, detected_episode_start)].joints["left_foot"][0]
                    + clip.frames[min(frame_index + 1, detected_episode_start)].joints["right_foot"][0]
                    - clip.frames[frame_index].joints["left_foot"][0]
                    - clip.frames[frame_index].joints["right_foot"][0]
                ) * 0.5,
                (
                    clip.frames[min(frame_index + 1, detected_episode_start)].joints["left_foot"][2]
                    + clip.frames[min(frame_index + 1, detected_episode_start)].joints["right_foot"][2]
                    - clip.frames[frame_index].joints["left_foot"][2]
                    - clip.frames[frame_index].joints["right_foot"][2]
                ) * 0.5,
            ) <= UNIFORM_CAPSULE_RADIUS
        ),
        detected_episode_start,
    )
    physical_touchdown_start = min(physical_touchdown_start, strict_surface_arrival)
    terminal_indices = list(range(physical_touchdown_start, clip.frame_count))

    upper_len = _median_bone_length(clip, hip_name, knee_name)
    lower_len = _median_bone_length(clip, knee_name, ankle_name)
    repaired_frames = list(clip.frames)
    maximum_displacement = 0.0
    for frame_index in terminal_indices:
        frame = clip.frames[frame_index]
        joints = dict(frame.joints)
        ankle_to_foot = _subtract(joints[opposite_foot], joints[ankle_name])
        target_foot = (joints[opposite_foot][0], surface_height + UNIFORM_CAPSULE_RADIUS, joints[opposite_foot][2])
        target_ankle = _subtract(target_foot, ankle_to_foot)
        body_frame = _body_local_frame(frame)
        fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
        solved_knee, solved_ankle = _solve_two_bone(
            root=joints[hip_name],
            current_mid=joints[knee_name],
            target_end=target_ankle,
            upper_len=upper_len,
            lower_len=lower_len,
            fallback_axis=fallback_axis,
        )
        foot_segment_length = _length(ankle_to_foot)
        target_foot_y = surface_height + UNIFORM_CAPSULE_RADIUS
        vertical_component = target_foot_y - solved_ankle[1]
        if foot_segment_length > 1e-8 and abs(vertical_component) <= foot_segment_length:
            horizontal_direction = _normalize((ankle_to_foot[0], 0.0, ankle_to_foot[2]))
            if horizontal_direction is None:
                horizontal_direction = (1.0, 0.0, 0.0)
            horizontal_length = math.sqrt(
                max(0.0, foot_segment_length * foot_segment_length - vertical_component * vertical_component)
            )
            solved_foot = (
                solved_ankle[0] + horizontal_direction[0] * horizontal_length,
                target_foot_y,
                solved_ankle[2] + horizontal_direction[2] * horizontal_length,
            )
        else:
            solved_foot = _add(solved_ankle, ankle_to_foot)
        maximum_displacement = max(
            maximum_displacement,
            _distance(joints[knee_name], solved_knee),
            _distance(joints[ankle_name], solved_ankle),
            _distance(joints[opposite_foot], solved_foot),
        )
        joints[knee_name] = solved_knee
        joints[ankle_name] = solved_ankle
        joints[opposite_foot] = solved_foot
        repaired_frames[frame_index] = MotionFrame(time_sec=frame.time_sec, joints=joints)

    # The originally detected support can also contain vertical reconstruction
    # jitter. Re-solve it to the same episode surface so bilateral support is
    # geometrically coplanar rather than merely sharing a contact label.
    contact_side = contact_foot.removesuffix("_foot")
    contact_hip = f"{contact_side}_hip"
    contact_knee = f"{contact_side}_knee"
    contact_ankle = f"{contact_side}_ankle"
    contact_upper_len = _median_bone_length(clip, contact_hip, contact_knee)
    contact_lower_len = _median_bone_length(clip, contact_knee, contact_ankle)
    for frame_index in terminal_indices:
        frame = repaired_frames[frame_index]
        joints = dict(frame.joints)
        ankle_to_foot = _subtract(joints[contact_foot], joints[contact_ankle])
        target_foot = (
            joints[contact_foot][0],
            surface_height + UNIFORM_CAPSULE_RADIUS,
            joints[contact_foot][2],
        )
        target_ankle = _subtract(target_foot, ankle_to_foot)
        body_frame = _body_local_frame(frame)
        fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
        solved_knee, solved_ankle = _solve_two_bone(
            root=joints[contact_hip],
            current_mid=joints[contact_knee],
            target_end=target_ankle,
            upper_len=contact_upper_len,
            lower_len=contact_lower_len,
            fallback_axis=fallback_axis,
        )
        joints[contact_knee] = solved_knee
        joints[contact_ankle] = solved_ankle
        joints[contact_foot] = _add(solved_ankle, ankle_to_foot)
        repaired_frames[frame_index] = MotionFrame(time_sec=frame.time_sec, joints=joints)

    repaired_contacts = [dict(state) if isinstance(state, dict) else {} for state in contacts]
    for frame_index in terminal_indices:
        state = repaired_contacts[frame_index]
        joint_names = list(state.get("contactJoints") or [])
        for foot_name in (contact_foot, opposite_foot):
            if foot_name not in joint_names:
                joint_names.append(foot_name)
        state["contactJoints"] = joint_names
        state["leftInContact"] = True
        state["rightInContact"] = True
        state["state"] = "double_support"
    metadata = dict(clip.metadata)
    updated_cleanup = dict(cleanup)
    updated_cleanup["footContacts"] = repaired_contacts
    metadata["cleanup"] = updated_cleanup
    return replace(clip, frames=repaired_frames, metadata=metadata), {
        "applied": True,
        "strategy": "terminal_stationary_surface_cluster_bilateral_promotion",
        "episodeStartFrame": terminal_indices[0],
        "episodeEndFrame": terminal_indices[-1],
        "detectedEpisodeStartFrame": detected_episode_start,
        "physicalTouchdownStartFrame": physical_touchdown_start,
        "contactFoot": contact_foot,
        "promotedFoot": opposite_foot,
        "surfaceHeight": surface_height,
        "maximumOppositeFootClearanceBefore": max(abs(value) for value in opposite_clearances),
        "oppositeFootHorizontalRange": horizontal_range,
        "maximumJointDisplacement": maximum_displacement,
    }


def _align_root_travel_to_body_yaw(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    vertical_grounding = cleanup.get("verticalGrounding") if isinstance(cleanup, dict) else None
    ground_contact_mode = str(
        vertical_grounding.get("groundContactMode")
        if isinstance(vertical_grounding, dict)
        else ""
    ).strip().casefold()
    if ground_contact_mode != "intermittent" or clip.frame_count < 3:
        return clip, {"applied": False, "reason": "no_intermediate_support_travel"}
    root_joint = next((name for name in ROOT_VERTICAL_MOTION_JOINTS if name in clip.joint_names), None)
    if root_joint is None:
        return clip, {"applied": False, "reason": "root_joint_unavailable"}
    roots = [frame.joints[root_joint] for frame in clip.frames]
    travel_start_index = 0
    travel_end_index = clip.frame_count - 1
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if isinstance(contacts, list):
        contact_episodes: list[list[int]] = []
        active_episode: list[int] = []
        for frame_index in range(min(len(contacts), clip.frame_count)):
            state = contacts[frame_index]
            names = state.get("contactJoints") if isinstance(state, dict) else None
            if names:
                active_episode.append(frame_index)
            elif active_episode:
                contact_episodes.append(active_episode)
                active_episode = []
        if active_episode:
            contact_episodes.append(active_episode)
        if len(contact_episodes) >= 2:
            travel_start_index = contact_episodes[0][-1]
            travel_end_index = contact_episodes[-1][0]
    travel = (
        roots[travel_end_index][0] - roots[travel_start_index][0],
        0.0,
        roots[travel_end_index][2] - roots[travel_start_index][2],
    )
    travel_length = _length(travel)
    step_lengths = [
        math.hypot(right[0] - left[0], right[2] - left[2])
        for left, right in zip(roots, roots[1:])
    ]
    noise_scale = median(step_lengths) * math.sqrt(max(1, len(step_lengths)))
    if travel_length <= max(1e-9, noise_scale):
        return clip, {
            "applied": False,
            "reason": "net_root_travel_not_distinguishable_from_frame_noise",
            "travelLength": travel_length,
            "noiseScale": noise_scale,
        }
    travel_direction = _scale(travel, 1.0 / travel_length)
    right_samples = [
        body_frame.right
        for frame in clip.frames
        if (body_frame := _body_local_frame(frame)) is not None
    ]
    if not right_samples:
        return clip, {"applied": False, "reason": "body_right_axis_unavailable"}
    horizontal_right = _normalize(
        (
            median([point[0] for point in right_samples]),
            0.0,
            median([point[2] for point in right_samples]),
        )
    )
    forward = (
        (-horizontal_right[2], 0.0, horizontal_right[0])
        if horizontal_right is not None
        else None
    )
    if forward is None:
        return clip, {"applied": False, "reason": "body_forward_axis_degenerate"}
    signed_forward = forward if _dot(forward, travel_direction) >= 0.0 else _scale(forward, -1.0)
    yaw_radians = math.atan2(
        signed_forward[0] * travel_direction[2]
        - signed_forward[2] * travel_direction[0],
        _dot(travel_direction, signed_forward),
    )
    corrected_frames: list[MotionFrame] = []
    root_origin = roots[travel_start_index]
    for frame in clip.frames:
        current_root = frame.joints[root_joint]
        root_displacement = _subtract(current_root, root_origin)
        rotated_horizontal = _rotate_vector_about_axis(
                (root_displacement[0], 0.0, root_displacement[2]),
                axis=(0.0, 1.0, 0.0),
                angle_radians=yaw_radians,
            )
        target_root = (
            root_origin[0] + rotated_horizontal[0],
            current_root[1],
            root_origin[2] + rotated_horizontal[2],
        )
        translation = _subtract(target_root, current_root)
        joints = {
            name: _add(point, translation)
            for name, point in frame.joints.items()
        }
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=corrected_frames), {
        "applied": True,
        "strategy": "horizontal_root_trajectory_alignment_perpendicular_to_body_right_axis",
        "travelLength": travel_length,
        "travelStartFrame": travel_start_index,
        "travelEndFrame": travel_end_index,
        "noiseScale": noise_scale,
        "trajectoryYawCorrectionDegrees": math.degrees(yaw_radians),
        "bodyAxisSign": "forward" if signed_forward == forward else "reverse_forward",
    }
SOURCE_GUIDED_ARM_CHAINS = (
    ("left_elbow", "left_shoulder", "left_elbow", "left_wrist", ("left_wrist", "left_hand")),
    ("right_elbow", "right_shoulder", "right_elbow", "right_wrist", ("right_wrist", "right_hand")),
)


def _stabilize_core_temporal_continuity(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    """Denoise coherent torso tracking wobble after structural reconstruction."""
    core_joint_names = tuple(
        joint_name
        for joint_name in (
            "pelvis", "spine1", "spine2", "spine3", "neck", "head",
            "left_hip", "right_hip", "left_collar", "right_collar",
            "left_shoulder", "right_shoulder",
        )
        if joint_name in clip.joint_names
    )
    if clip.frame_count < 5 or not core_joint_names:
        return clip, {"applied": False, "reason": "insufficient_core_trajectory"}

    def trajectory_jerk(frames: list[MotionFrame]) -> float:
        squared_jerk: list[float] = []
        for joint_name in core_joint_names:
            points = [frame.joints[joint_name] for frame in frames]
            for index in range(3, len(points)):
                jerk = _add(
                    _subtract(points[index], _scale(points[index - 1], 3.0)),
                    _subtract(_scale(points[index - 2], 3.0), points[index - 3]),
                )
                squared_jerk.append(_dot(jerk, jerk))
        return math.sqrt(sum(squared_jerk) / len(squared_jerk)) if squared_jerk else 0.0

    smoothing_radius = max(1, round(clip.fps * 0.10))
    tracks = {
        joint_name: [frame.joints[joint_name] for frame in clip.frames]
        for joint_name in core_joint_names
    }
    smoothed_tracks = {
        joint_name: _zero_phase_smooth_points(track, radius=smoothing_radius)
        for joint_name, track in tracks.items()
    }
    proposed_frames: list[MotionFrame] = []
    projected_scales: list[float] = []
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        for joint_name in core_joint_names:
            joints[joint_name] = _lerp_point(
                tracks[joint_name][frame_index],
                smoothed_tracks[joint_name][frame_index],
                1.0,
            )
        # Smooth the core as a connected skeleton. Re-solve attached limbs to
        # unchanged wrists/ankles instead of leaving stretched bones behind.
        joints, scale = _project_core_targets_with_fixed_endpoints(frame, joints)
        projected_scales.append(scale)
        proposed_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    jerk_before = trajectory_jerk(list(clip.frames))
    jerk_proposed = trajectory_jerk(proposed_frames)
    # Hip/shoulder smoothing also changes the roots of attached limbs. A
    # smoother torso is not an improvement if stationary descendants make
    # those bones stretch. Preserve each frame's incoming bone lengths.
    changed_bones: dict[str, float] = {}
    for parent, child in STRUCTURAL_BONES:
        if parent not in clip.joint_names or child not in clip.joint_names:
            continue
        maximum_relative_change = max(
            abs(_distance(after.joints[parent], after.joints[child])
                - _distance(before.joints[parent], before.joints[child]))
            / max(_distance(before.joints[parent], before.joints[child]), 1e-9)
            for before, after in zip(clip.frames, proposed_frames)
        )
        if maximum_relative_change > 1e-6:
            changed_bones[f"{parent}:{child}"] = maximum_relative_change
    from .articulation_trajectory import temporal_quality_comparison
    temporal_quality = temporal_quality_comparison(clip, replace(clip, frames=proposed_frames))
    accepted = jerk_proposed < jerk_before and not changed_bones and temporal_quality["passed"]
    refined = replace(clip, frames=proposed_frames) if accepted else clip
    return refined, {
        "applied": accepted,
        "strategy": "zero_phase_core_smoothing_with_rigid_bones_and_fixed_endpoints",
        "windowSeconds": smoothing_radius / clip.fps,
        "smoothingStrength": 1.0,
        "jerkBefore": jerk_before,
        "jerkProposed": jerk_proposed,
        "reason": (
            "core_smoothing_changes_bone_lengths" if changed_bones
            else "temporal_quality_degraded" if not temporal_quality["passed"]
            else "lower_core_jerk" if accepted else "core_jerk_not_improved"
        ),
        "temporalQuality": temporal_quality,
        "reducedCorrectionFrameCount": sum(scale < 1. for scale in projected_scales),
        "proposedBoneLengthChanges": changed_bones,
        "jointNames": list(core_joint_names),
    }


def _stabilize_arm_temporal_continuity(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    from .limb_bend_repair import repair_limb_bend_bursts

    burst_candidate, burst_repair = repair_limb_bend_bursts(clip)
    if burst_repair["applied"]:
        from .articulation_trajectory import temporal_quality_comparison
        comparison = temporal_quality_comparison(clip, burst_candidate)
        burst_repair["temporalQuality"] = comparison
        burst_repair["applied"] = comparison["passed"]
        if comparison["passed"]:
            clip = burst_candidate
    def chain_jerk(
        candidate_frames: list[MotionFrame],
        joint_names: tuple[str, ...],
    ) -> float:
        squared_jerk: list[float] = []
        for joint_name in joint_names:
            points = [frame.joints[joint_name] for frame in candidate_frames]
            for index in range(3, len(points)):
                jerk = _add(
                    _subtract(points[index], _scale(points[index - 1], 3.0)),
                    _subtract(_scale(points[index - 2], 3.0), points[index - 3]),
                )
                squared_jerk.append(_dot(jerk, jerk))
        return math.sqrt(sum(squared_jerk) / len(squared_jerk)) if squared_jerk else 0.0

    frames = list(clip.frames)
    side_payloads: list[dict[str, object]] = []
    maximum_correction = 0.0
    smoothing_radius = max(1, round(clip.fps * 0.10))
    limb_chains = (
        ("arm", "shoulder", "elbow", "wrist", "hand"),
        ("leg", "hip", "knee", "ankle", "foot"),
    )
    for limb_group, root_suffix, middle_suffix, end_suffix, tip_suffix, side in (
        (*chain, side)
        for chain in limb_chains
        for side in ("left", "right")
    ):
        root_name = f"{side}_{root_suffix}"
        middle_name = f"{side}_{middle_suffix}"
        end_name = f"{side}_{end_suffix}"
        tip_name = f"{side}_{tip_suffix}"
        if any(
            name not in clip.joint_names
            for name in (root_name, middle_name, end_name, tip_name)
        ):
            continue
        offsets = [
            _subtract(frame.joints[end_name], frame.joints[root_name])
            for frame in frames
        ]
        offset_steps = [
            _distance(left, right)
            for left, right in zip(offsets, offsets[1:])
        ]
        peak_step = max(offset_steps, default=0.0)
        from .articulation_trajectory import fit_chain_rotations, temporal_quality_comparison
        chain_names = (root_name, middle_name, end_name, tip_name)
        if set(chain_names[1:]).intersection(_locked_support_anchor_names(clip)):
            continue
        source_chain_frames = frames
        source_chain = replace(clip, frames=source_chain_frames)
        repaired = fit_chain_rotations(source_chain, chain_names)
        repaired_frames = list(repaired.frames)
        corrections = [max(_distance(before.joints[name], after.joints[name])
                           for name in chain_names[1:])
                       for before, after in zip(source_chain_frames, repaired_frames)]
        side_maximum = max(corrections, default=0.0)
        ordered_residuals = sorted(corrections)
        p90_residual = ordered_residuals[int(.9 * (len(ordered_residuals) - 1))]
        smoothing_strength = 1.0
        temporal_quality = temporal_quality_comparison(source_chain, repaired)
        chain_names = (root_name, middle_name, end_name, tip_name)
        before_jerk = chain_jerk(source_chain_frames, chain_names)
        proposed_jerk = chain_jerk(repaired_frames, chain_names)
        accepted = proposed_jerk < before_jerk and temporal_quality["passed"]
        if accepted:
            frames = repaired_frames
            maximum_correction = max(maximum_correction, side_maximum)
        side_payloads.append({
            "side": side,
            "limbGroup": limb_group,
            "applied": accepted,
            "peakRelativeEndpointStep": peak_step,
            "p90SmoothingResidual": p90_residual,
            "smoothingStrength": smoothing_strength,
            "jerkBefore": before_jerk,
            "jerkProposed": proposed_jerk,
            "reason": ("lower_chain_jerk" if accepted else
                       "temporal_quality_degraded" if not temporal_quality["passed"] else "chain_jerk_not_improved"),
            "temporalQuality": temporal_quality,
            "maximumCorrection": side_maximum,
        })
    return replace(clip, frames=frames), {
        "applied": burst_repair["applied"] or any(bool(item.get("applied")) for item in side_payloads),
        "bendBurstRepair": burst_repair,
        "strategy": "body_local_rotation_smoothing_with_rigid_bones",
        "windowSeconds": smoothing_radius / clip.fps,
        "maximumCorrection": maximum_correction,
        "sides": side_payloads,
    }


def _align_intermittent_vertical_trajectory_to_source_pose(
    clip: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    vertical_grounding = cleanup.get("verticalGrounding") if isinstance(cleanup, dict) else None
    ground_contact_mode = str(
        (vertical_grounding or {}).get("groundContactMode")
        if isinstance(vertical_grounding, dict)
        else ""
    ).strip().casefold()
    if ground_contact_mode != "intermittent":
        return clip, {"applied": False, "reason": "support_mode_is_not_intermittent"}
    source_frames = _source_pose_frames_with_normalized_time(source_pose_payload)
    if len(source_frames) < 2:
        return clip, {"applied": False, "reason": "source_pose_reference_unavailable"}
    root_joint = next((name for name in ROOT_VERTICAL_MOTION_JOINTS if name in clip.joint_names), None)
    if root_joint is None:
        return clip, {"applied": False, "reason": "motion_root_unavailable"}
    fidelity = source_to_motion_pose_fidelity_metrics(
        source_pose_payload or {},
        _motion_clip_pose_payload(clip),
    )
    horizontal_vector_value = fidelity.get("projectionHorizontalVector")
    if (
        not fidelity.get("available")
        or not isinstance(horizontal_vector_value, (list, tuple))
        or len(horizontal_vector_value) < 2
    ):
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}
    horizontal_vector = (float(horizontal_vector_value[0]), float(horizontal_vector_value[1]))
    mirror = fidelity.get("mirrored") is True
    swap_bilateral = fidelity.get("bilateralAssignment") == "swapped"
    motion_frames = pose_fidelity._pose_frames(_motion_clip_pose_payload(clip), source=False)
    transform = pose_fidelity._global_similarity_transform(
        source_frames,
        motion_frames,
        horizontal_vector=horizontal_vector,
        mirror=mirror,
        swap_bilateral=swap_bilateral,
    )
    if transform is None:
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}
    duration = max(0.0, clip.duration_sec)
    corrected_frames: list[MotionFrame] = []
    corrections: list[float] = []
    for frame_index, frame in enumerate(clip.frames):
        normalized_time = (
            (frame.time_sec - clip.frames[0].time_sec) / duration
            if duration > 1e-9
            else frame_index / max(1, clip.frame_count - 1)
        )
        source_joints = _interpolated_source_joints(source_frames, normalized_time)
        source_root = source_joints.get("pelvis") or source_joints.get("hips")
        if not isinstance(source_root, (list, tuple)) or len(source_root) < 2:
            correction = corrections[-1] if corrections else (0.0, 0.0, 0.0)
        else:
            desired_projection = _inverse_similarity_point(
                (float(source_root[0]), float(source_root[1])),
                transform,
            )
            current_root = frame.joints[root_joint]
            current_projection = pose_fidelity._project_motion_point(
                current_root,
                horizontal_vector=horizontal_vector,
                mirror=mirror,
            )
            projected_horizontal_delta = (
                float(desired_projection[0]) - float(current_projection[0])
            )
            world_horizontal_delta = (
                -projected_horizontal_delta if mirror else projected_horizontal_delta
            )
            desired_root_y = -float(desired_projection[1])
            correction = (
                horizontal_vector[0] * world_horizontal_delta,
                desired_root_y - current_root[1],
                horizontal_vector[1] * world_horizontal_delta,
            )
        corrections.append(correction)
        corrected_frames.append(
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    name: _add(point, correction)
                    for name, point in frame.joints.items()
                },
            )
        )
    return replace(clip, frames=corrected_frames), {
        "applied": True,
        "strategy": "fixed_projection_source_root_trajectory",
        "rootJoint": root_joint,
        "startCorrection": list(corrections[0]),
        "endCorrection": list(corrections[-1]),
        "maximumCorrection": max(_length(value) for value in corrections),
    }


def _align_hinge_articulation_to_source_pose(
    clip: MotionClip,
    *,
    source_pose_payload: dict[str, Any] | None,
    chains: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = SOURCE_GUIDED_HINGE_CHAINS,
) -> tuple[MotionClip, dict[str, object]]:
    """Fit distal hinge endpoints to the source projection without stretching.

    A 2D camera angle is not a true 3D joint angle.  Instead, align WHAM's torso
    projection to the observed pose per frame, inverse-project the observed
    wrist/ankle endpoint, and solve the missing depth from the existing bone
    length.  WHAM therefore remains authoritative for depth branch and global
    motion while the source corrects only what the camera actually observed.
    """
    source_frames = _source_pose_frames_with_normalized_time(source_pose_payload)
    if len(source_frames) < 2:
        return clip, {"applied": False, "reason": "source_pose_reference_unavailable"}

    fidelity = source_to_motion_pose_fidelity_metrics(
        source_pose_payload or {},
        _motion_clip_pose_payload(clip),
    )
    if not fidelity.get("available"):
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}
    horizontal_vector_value = fidelity.get("projectionHorizontalVector")
    if (
        isinstance(horizontal_vector_value, (list, tuple))
        and len(horizontal_vector_value) >= 2
    ):
        horizontal_vector = (
            float(horizontal_vector_value[0]),
            float(horizontal_vector_value[1]),
        )
    else:
        horizontal_vector = (
            (1.0, 0.0)
            if fidelity.get("projectionHorizontalAxis") == "x"
            else (0.0, 1.0)
        )
    mirror = fidelity.get("mirrored") is True
    swap_bilateral = fidelity.get("bilateralAssignment") == "swapped"
    locked_support_joints = _locked_support_anchor_names(clip)

    motion_frames = pose_fidelity._pose_frames(
        _motion_clip_pose_payload(clip),
        source=False,
    )
    global_transform = pose_fidelity._global_similarity_transform(
        source_frames,
        motion_frames,
        horizontal_vector=horizontal_vector,
        mirror=mirror,
        swap_bilateral=swap_bilateral,
    )
    if global_transform is None:
        return clip, {"applied": False, "reason": "source_projection_alignment_unavailable"}

    duration = max(0.0, clip.frames[-1].time_sec - clip.frames[0].time_sec)
    corrected_frames: list[MotionFrame] = []
    corrections: list[float] = []
    corrected_chains: set[str] = set()
    for frame_index, frame in enumerate(clip.frames):
        normalized_time = (
            (frame.time_sec - clip.frames[0].time_sec) / duration
            if duration > 1e-9
            else frame_index / max(1, clip.frame_count - 1)
        )
        joints = dict(frame.joints)
        source_joints = _interpolated_source_joints(source_frames, normalized_time)
        fit_names = [
            source_name
            for source_name in pose_fidelity.ALIGNMENT_JOINTS
            if source_name in source_joints
            and pose_fidelity._bilateral_name(source_name, swap=swap_bilateral) in joints
        ]
        if len(fit_names) < 3:
            corrected_frames.append(frame)
            continue
        transform = global_transform
        for name, parent, hinge, child, descendants in chains:
            if set((hinge, child, *descendants)).intersection(locked_support_joints):
                continue
            source_parent = pose_fidelity._bilateral_name(parent, swap=swap_bilateral)
            source_hinge = pose_fidelity._bilateral_name(hinge, swap=swap_bilateral)
            source_child = pose_fidelity._bilateral_name(child, swap=swap_bilateral)
            if (
                parent not in joints
                or hinge not in joints
                or child not in joints
                or source_hinge not in source_joints
                or source_child not in source_joints
                or source_parent not in source_joints
            ):
                continue
            if hinge not in locked_support_joints:
                desired_hinge_projection = _source_relative_endpoint_projection(
                    source_parent=source_joints[source_parent],
                    source_child=source_joints[source_hinge],
                    parent=joints[parent], transform=transform,
                    horizontal_vector=horizontal_vector, mirror=mirror,
                )
                proposed_hinge = _point_for_projected_endpoint_with_fixed_length(
                    hinge=joints[parent],
                    child=joints[hinge],
                    desired_projection=desired_hinge_projection,
                    horizontal_vector=horizontal_vector,
                    mirror=mirror,
                )
                if proposed_hinge is not None:
                    hinge_delta = _subtract(proposed_hinge, joints[hinge])
                    if _length(hinge_delta) > 1e-8:
                        _rotate_hinge_descendants(
                            joints, parent=parent, hinge=parent, child=hinge,
                            descendants=(hinge, *descendants), target_child=proposed_hinge,
                        )
                        corrections.append(_length(hinge_delta))
                        corrected_chains.add(name)
            desired_projection = _source_relative_endpoint_projection(
                source_parent=source_joints[source_hinge],
                source_child=source_joints[source_child],
                parent=joints[hinge], transform=transform,
                horizontal_vector=horizontal_vector, mirror=mirror,
            )
            proposed_child = _point_for_projected_endpoint_with_fixed_length(
                hinge=joints[hinge],
                child=joints[child],
                desired_projection=desired_projection,
                horizontal_vector=horizontal_vector,
                mirror=mirror,
            )
            if proposed_child is None:
                continue
            delta = _subtract(proposed_child, joints[child])
            if _length(delta) <= 1e-8:
                continue
            _rotate_hinge_descendants(
                joints, parent=parent, hinge=hinge, child=child,
                descendants=descendants, target_child=proposed_child,
            )
            corrections.append(_length(delta))
            corrected_chains.add(name)
        # Endpoint solves use the reconstructed depth branch. Rotate distal
        # chains rigidly rather than altering their articulation by translation.
        # Restoring body-local widths afterwards moves both sides (including
        # an arm outside `chains`) and destroys those solved constraints.
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    if not corrections:
        return clip, {"applied": False, "reason": "source_hinge_angles_already_matched"}
    from .articulation_trajectory import fit_chain_rotations
    proposed = replace(clip, frames=corrected_frames)
    fitted = clip
    for _, parent, hinge, child, descendants in chains:
        chain = tuple(dict.fromkeys((parent, hinge, child, *descendants)))
        if set(chain[1:]).intersection(locked_support_joints):
            continue
        fitted = fit_chain_rotations(fitted, chain, proposal=proposed)
    return fitted, {
        "applied": True,
        "strategy": "temporally_fitted_source_rotation_correction_with_fixed_bone_length",
        "correctedChains": sorted(corrected_chains),
        "correctedFrameJointCount": len(corrections),
        "averageCorrection": sum(corrections) / len(corrections),
        "maxCorrection": max(corrections),
    }


def _source_relative_endpoint_projection(
    *, source_parent, source_child, parent: Point3, transform,
    horizontal_vector: tuple[float, float], mirror: bool,
) -> tuple[float, float]:
    """Fit articulation independently of residual global translation error."""
    start = _inverse_similarity_point(tuple(source_parent[:2]), transform)
    end = _inverse_similarity_point(tuple(source_child[:2]), transform)
    horizontal = parent[0] * horizontal_vector[0] + parent[2] * horizontal_vector[1]
    if mirror:
        horizontal = -horizontal
    return horizontal + end[0] - start[0], -parent[1] + end[1] - start[1]


def _inverse_similarity_point(
    point: tuple[float, float],
    transform: tuple[float, float, float, float, float, float],
) -> tuple[float, float]:
    scale_cos, scale_sin, source_x, source_y, target_x, target_y = transform
    determinant = scale_cos * scale_cos + scale_sin * scale_sin
    if determinant <= 1e-12:
        return source_x, source_y
    target_delta_x = point[0] - target_x
    target_delta_y = point[1] - target_y
    return (
        source_x + (scale_cos * target_delta_x + scale_sin * target_delta_y) / determinant,
        source_y + (-scale_sin * target_delta_x + scale_cos * target_delta_y) / determinant,
    )


def _point_for_projected_endpoint_with_fixed_length(
    *,
    hinge: Point3,
    child: Point3,
    desired_projection: tuple[float, float],
    horizontal_axis: int | None = None,
    horizontal_vector: tuple[float, float] | None = None,
    mirror: bool,
) -> Point3 | None:
    bone_length = _length(_subtract(child, hinge))
    if bone_length <= 1e-8:
        return None
    if horizontal_vector is None:
        horizontal_vector = (1.0, 0.0) if horizontal_axis == 0 else (0.0, 1.0)
    axis_length = math.hypot(*horizontal_vector)
    if axis_length <= 1e-9:
        return None
    visible_axis = (
        horizontal_vector[0] / axis_length,
        horizontal_vector[1] / axis_length,
    )
    hidden_axis = (-visible_axis[1], visible_axis[0])
    desired_horizontal = -desired_projection[0] if mirror else desired_projection[0]
    desired_vertical = -desired_projection[1]
    hinge_horizontal = hinge[0] * visible_axis[0] + hinge[2] * visible_axis[1]
    visible_delta = [desired_horizontal - hinge_horizontal, desired_vertical - hinge[1]]
    visible_length = math.hypot(*visible_delta)
    if visible_length > bone_length:
        scale = bone_length / visible_length
        visible_delta = [component * scale for component in visible_delta]
        visible_length = bone_length
    current_hidden_delta = (
        (child[0] - hinge[0]) * hidden_axis[0]
        + (child[2] - hinge[2]) * hidden_axis[1]
    )
    # The camera does not observe this axis. Re-solving its magnitude from a
    # 2D target independently for every limb can produce corkscrew poses that
    # project correctly but are anatomically wrong. Preserve WHAM's exact
    # hidden-depth offset and fit only the observable direction.
    hidden_delta = current_hidden_delta
    visible_radius = math.sqrt(
        max(0.0, bone_length * bone_length - hidden_delta * hidden_delta)
    )
    if visible_length > 1e-9:
        visible_scale = visible_radius / visible_length
        visible_delta = [component * visible_scale for component in visible_delta]
    else:
        current_horizontal_delta = (
            (child[0] - hinge[0]) * visible_axis[0]
            + (child[2] - hinge[2]) * visible_axis[1]
        )
        current_vertical_delta = child[1] - hinge[1]
        current_visible_length = math.hypot(current_horizontal_delta, current_vertical_delta)
        if current_visible_length <= 1e-9:
            return None
        visible_delta = [
            current_horizontal_delta * visible_radius / current_visible_length,
            current_vertical_delta * visible_radius / current_visible_length,
        ]
    horizontal_delta = (
        visible_axis[0] * visible_delta[0] + hidden_axis[0] * hidden_delta,
        visible_axis[1] * visible_delta[0] + hidden_axis[1] * hidden_delta,
    )
    return (
        hinge[0] + horizontal_delta[0],
        hinge[1] + visible_delta[1],
        hinge[2] + horizontal_delta[1],
    )


def _source_pose_frames_with_normalized_time(
    source_pose_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(source_pose_payload, dict):
        return []
    raw_frames = source_pose_payload.get("frames")
    if not isinstance(raw_frames, list):
        return []
    frames: list[dict[str, Any]] = []
    for index, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, dict) or not isinstance(raw_frame.get("joints"), dict):
            continue
        try:
            time_sec = float(raw_frame.get("sourceTimeSec", index))
        except (TypeError, ValueError):
            time_sec = float(index)
        frames.append({"timeSec": time_sec, "joints": raw_frame["joints"]})
    if len(frames) < 2:
        return frames
    start = float(frames[0]["timeSec"])
    duration = float(frames[-1]["timeSec"]) - start
    for index, frame in enumerate(frames):
        frame["normalizedTime"] = (
            (float(frame["timeSec"]) - start) / duration
            if duration > 1e-9
            else index / max(1, len(frames) - 1)
        )
    return frames


def _source_angle_track(
    source_frames: list[dict[str, Any]],
    parent: str,
    hinge: str,
    child: str,
) -> list[tuple[float, float]]:
    track: list[tuple[float, float]] = []
    for frame in source_frames:
        joints = frame["joints"]
        if any(name not in joints for name in (parent, hinge, child)):
            continue
        angle = _point_angle_degrees(joints[parent], joints[hinge], joints[child])
        if angle is not None:
            track.append((float(frame.get("normalizedTime", 0.0)), angle))
    return track


def _interpolated_source_joints(
    source_frames: list[dict[str, Any]],
    normalized_time: float,
) -> dict[str, list[float]]:
    if not source_frames:
        return {}
    if normalized_time <= float(source_frames[0].get("normalizedTime", 0.0)):
        return dict(source_frames[0]["joints"])
    if normalized_time >= float(source_frames[-1].get("normalizedTime", 1.0)):
        return dict(source_frames[-1]["joints"])
    for left, right in zip(source_frames, source_frames[1:]):
        left_time = float(left.get("normalizedTime", 0.0))
        right_time = float(right.get("normalizedTime", 1.0))
        if not left_time <= normalized_time <= right_time:
            continue
        span = right_time - left_time
        alpha = (normalized_time - left_time) / span if span > 1e-9 else 0.0
        left_joints = left["joints"]
        right_joints = right["joints"]
        interpolated: dict[str, list[float]] = {}
        for name in left_joints.keys() & right_joints.keys():
            left_point = left_joints[name]
            right_point = right_joints[name]
            if not isinstance(left_point, (list, tuple)) or not isinstance(
                right_point, (list, tuple)
            ):
                continue
            dimensions = min(len(left_point), len(right_point))
            if dimensions < 2:
                continue
            interpolated[name] = [
                float(left_point[axis]) * (1.0 - alpha)
                + float(right_point[axis]) * alpha
                for axis in range(dimensions)
            ]
        return interpolated
    return dict(source_frames[-1]["joints"])


def _point_angle_degrees(first: Any, middle: Any, last: Any) -> float | None:
    try:
        left = tuple(float(first[index]) - float(middle[index]) for index in range(2))
        right = tuple(float(last[index]) - float(middle[index]) for index in range(2))
    except (IndexError, TypeError, ValueError):
        return None
    denominator = math.hypot(*left) * math.hypot(*right)
    if denominator <= 1e-9:
        return None
    cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _interpolated_scalar_track(track: list[tuple[float, float]], position: float) -> float:
    if position <= track[0][0]:
        return track[0][1]
    if position >= track[-1][0]:
        return track[-1][1]
    for left, right in zip(track, track[1:]):
        if left[0] <= position <= right[0]:
            span = right[0] - left[0]
            alpha = (position - left[0]) / span if span > 1e-9 else 0.0
            return left[1] * (1.0 - alpha) + right[1] * alpha
    return track[-1][1]


def _child_point_for_target_hinge_angle(
    *,
    parent: Point3,
    hinge: Point3,
    child: Point3,
    target_angle_degrees: float,
) -> Point3 | None:
    parent_vector = _subtract(parent, hinge)
    child_vector = _subtract(child, hinge)
    parent_direction = _normalize(parent_vector)
    child_direction = _normalize(child_vector)
    child_length = _length(child_vector)
    if parent_direction is None or child_direction is None or child_length <= 1e-8:
        return None
    current_cosine = max(-1.0, min(1.0, _dot(parent_direction, child_direction)))
    current_angle = math.acos(current_cosine)
    target_angle = math.radians(max(0.0, min(180.0, target_angle_degrees)))
    axis = _normalize(_cross(child_direction, parent_direction))
    if axis is None:
        axis = _normalize(_cross(child_direction, (0.0, 1.0, 0.0)))
    if axis is None:
        axis = _normalize(_cross(child_direction, (1.0, 0.0, 0.0)))
    if axis is None:
        return None
    delta = current_angle - target_angle
    candidates = [
        _rotate_vector_about_axis(child_vector, axis=axis, angle_radians=delta),
        _rotate_vector_about_axis(child_vector, axis=axis, angle_radians=-delta),
    ]
    best = min(
        candidates,
        key=lambda vector: abs(
            math.acos(max(-1.0, min(1.0, _dot(parent_direction, _normalize(vector) or child_direction))))
            - target_angle
        ),
    )
    return _add(hinge, _scale(_normalize(best) or child_direction, child_length))


def _restore_support_relative_lateral_root_trajectory(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    if len(clip.frames) != len(reference_clip.frames) or not clip.frames:
        return clip, {"applied": False, "reason": "reference_frame_count_mismatch"}
    required = {"pelvis", "left_knee", "right_knee"}
    if any(name not in clip.joint_names or name not in reference_clip.joint_names for name in required):
        return clip, {"applied": False, "reason": "support_relative_root_joints_missing"}
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup = metadata.get("cleanup")
    constraint = cleanup.get("supportSurfaceConstraint") if isinstance(cleanup, dict) else None
    knee_lock = constraint.get("kneeLock") if isinstance(constraint, dict) else None
    anchors = knee_lock.get("anchors") if isinstance(knee_lock, dict) else None
    if not isinstance(anchors, dict) or not anchors:
        return clip, {"applied": False, "reason": "no_authoritative_knee_anchors"}
    first = clip.frames[0]
    lateral_axis = _normalize(_subtract(first.joints["right_knee"], first.joints["left_knee"]))
    if lateral_axis is None:
        return clip, {"applied": False, "reason": "degenerate_knee_lateral_axis"}
    support_joints = {
        "left_knee", "right_knee",
        "left_ankle", "right_ankle",
        "left_foot", "right_foot",
    }
    frames: list[MotionFrame] = []
    maximum_correction = 0.0
    for frame, reference_frame in zip(clip.frames, reference_clip.frames):
        current_coordinate = _dot(frame.joints["pelvis"], lateral_axis)
        reference_coordinate = _dot(reference_frame.joints["pelvis"], lateral_axis)
        correction = _scale(lateral_axis, reference_coordinate - current_coordinate)
        maximum_correction = max(maximum_correction, _length(correction))
        joints = {
            name: point if name in support_joints else _add(point, correction)
            for name, point in frame.joints.items()
        }
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "strategy": "preserve_support_relative_lateral_root_trajectory",
        "maximumCorrection": maximum_correction,
    }


def enforce_final_structural_invariant(
    reference: MotionClip, proposed: MotionClip,
) -> tuple[MotionClip, dict[str, Any]]:
    """Final transaction boundary, including late contact and equipment edits."""
    topology_valid = len(reference.frames) == len(proposed.frames) and all(
        before.time_sec == after.time_sec and before.joints.keys() == after.joints.keys()
        and all(math.isfinite(coordinate) for point in after.joints.values() for coordinate in point)
        for before, after in zip(reference.frames, proposed.frames)
    )
    baseline = _maximum_structural_bone_length_variation(reference)
    candidate = _maximum_structural_bone_length_variation(proposed) if topology_valid else None
    accepted = topology_valid and candidate <= baseline + 1e-6
    return (proposed if accepted else reference), {
        "accepted": accepted, "rolledBack": not accepted,
        "reason": "structural_invariant_preserved" if accepted else "final_structural_invariant_failed",
        "topologyValid": topology_valid,
        "sourceMaximumVariationRatio": baseline,
        "proposedMaximumVariationRatio": candidate,
    }


def _maximum_structural_bone_length_variation(clip: MotionClip) -> float:
    maximum = 0.0
    for parent_name, child_name in STRUCTURAL_BONES:
        lengths = [
            math.dist(frame.joints[parent_name], frame.joints[child_name])
            for frame in clip.frames
            if parent_name in frame.joints and child_name in frame.joints
        ]
        if not lengths:
            continue
        reference = median(lengths)
        if reference <= 1e-8:
            continue
        maximum = max(maximum, (max(lengths) - min(lengths)) / reference)
    return maximum


def _source_dynamic_bone_length_child_joints(clip: MotionClip) -> set[str]:
    articulating_children = {
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hand",
        "right_hand",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
        "left_foot",
        "right_foot",
    }
    dynamic_children: set[str] = set()
    for parent_name, child_name in STRUCTURAL_BONES:
        if child_name not in articulating_children:
            continue
        lengths = [
            math.dist(frame.joints[parent_name], frame.joints[child_name])
            for frame in clip.frames
            if parent_name in frame.joints and child_name in frame.joints
        ]
        if not lengths:
            continue
        reference = median(lengths)
        if reference <= 1e-8:
            continue
        # This is the same structural distinction used by the kinematic gate:
        # stable rigid bones are projected; highly variable source segments
        # retain their per-frame length because it may encode the source
        # representation's articulation rather than refinement damage.
        if (
            (max(lengths) - min(lengths)) / reference
            > STRUCTURAL_BONE_STABILITY_MAX_VARIATION_RATIO
        ):
            dynamic_children.add(child_name)
    return dynamic_children


def _has_authoritative_support_anchors(clip: MotionClip) -> bool:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    support_constraint = (
        cleanup_metadata.get("supportSurfaceConstraint")
        if isinstance(cleanup_metadata, dict)
        else None
    )
    knee_lock = (
        support_constraint.get("kneeLock")
        if isinstance(support_constraint, dict)
        else None
    )
    anchors = knee_lock.get("anchors") if isinstance(knee_lock, dict) else None
    return (
        isinstance(anchors, dict)
        and bool(anchors)
        and knee_lock.get("allowWholeSkeletonSolver", True) is not False
    )


def _locked_support_anchor_names(clip: MotionClip) -> set[str]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    support_constraint = (
        cleanup_metadata.get("supportSurfaceConstraint")
        if isinstance(cleanup_metadata, dict)
        else None
    )
    knee_lock = (
        support_constraint.get("kneeLock")
        if isinstance(support_constraint, dict)
        else None
    )
    anchors = knee_lock.get("anchors") if isinstance(knee_lock, dict) else None
    return set(anchors) if isinstance(anchors, dict) else set()


def _solve_clip_wide_skeleton_constraints(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    bilateral_modes: dict[str, dict[str, object]],
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    if not _has_authoritative_support_anchors(clip):
        return clip, {
            "applied": False,
            "reason": "no_authoritative_support_anchors",
        }
    bone_lengths = {
        (parent, child): _median_bone_length(reference_clip, parent, child)
        for parent, child in STRUCTURAL_BONES
        if parent in clip.joint_names
        and child in clip.joint_names
        and parent in reference_clip.joint_names
        and child in reference_clip.joint_names
    }
    bilateral_pairs = list(CORE_BILATERAL_PAIRS)
    arms_mode = bilateral_modes.get("arms", {})
    legs_mode = bilateral_modes.get("legs", {})
    clip_metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    clip_cleanup_metadata = clip_metadata.get("cleanup")
    clip_support_constraint = (
        clip_cleanup_metadata.get("supportSurfaceConstraint")
        if isinstance(clip_cleanup_metadata, dict)
        else None
    )
    clip_knee_lock = (
        clip_support_constraint.get("kneeLock")
        if isinstance(clip_support_constraint, dict)
        else None
    )
    authoritative_chain_lengths = (
        clip_knee_lock.get("referenceBoneLengths")
        if isinstance(clip_knee_lock, dict)
        else None
    )
    if isinstance(authoritative_chain_lengths, dict):
        for side in ("left", "right"):
            knee_name = f"{side}_knee"
            hip_name = f"{side}_hip"
            lengths = authoritative_chain_lengths.get(knee_name)
            if not isinstance(lengths, dict):
                continue
            pelvis_to_hip = _optional_float(lengths.get("pelvisToHip"))
            hip_to_knee = _optional_float(lengths.get("hipToKnee"))
            if pelvis_to_hip is not None:
                bone_lengths[("pelvis", hip_name)] = pelvis_to_hip
            if hip_to_knee is not None:
                bone_lengths[(hip_name, knee_name)] = hip_to_knee
    has_bilateral_knee_anchors = (
        isinstance(clip_knee_lock, dict)
        and {
            name
            for name in clip_knee_lock.get("supportJoints", [])
            if isinstance(name, str)
        }
        >= {"left_knee", "right_knee"}
    )
    if (
        arms_mode.get("mode") == "same_phase_symmetric"
        or arms_mode.get("motionSymmetric") is True
    ):
        bilateral_pairs.extend(ARM_PAIRS)
    if (
        legs_mode.get("mode") == "same_phase_symmetric"
        or legs_mode.get("motionSymmetric") is True
        or has_bilateral_knee_anchors
    ):
        bilateral_pairs.extend(LEG_PAIRS)
    bilateral_pairs = [
        pair
        for pair in bilateral_pairs
        if all(
            joint in clip.joint_names and joint in reference_clip.joint_names
            for joint in pair
        )
    ]
    bilateral_widths = {
        pair: median(
            _distance(frame.joints[pair[0]], frame.joints[pair[1]])
            for frame in reference_clip.frames
        )
        for pair in bilateral_pairs
    }
    for (parent, child), target_length in list(bone_lengths.items()):
        if "left_" not in parent and "left_" not in child:
            continue
        opposite_bone = (
            parent.replace("left_", "right_"),
            child.replace("left_", "right_"),
        )
        if opposite_bone not in bone_lengths:
            continue
        child_pair = (child, opposite_bone[1])
        if child_pair not in bilateral_pairs:
            continue
        shared_length = (target_length + bone_lengths[opposite_bone]) * 0.5
        bone_lengths[(parent, child)] = shared_length
        bone_lengths[opposite_bone] = shared_length
    body_frames = [
        body_frame
        for frame in clip.frames
        if (body_frame := _body_local_frame(frame)) is not None
    ]
    median_lateral = (
        _median_point([frame.right for frame in body_frames])
        if body_frames
        else None
    )
    lateral_axis = (
        _normalize((median_lateral[0], 0.0, median_lateral[2]))
        if median_lateral is not None
        else None
    )
    pair_groups = {
        **{pair: "torso" for pair in CORE_BILATERAL_PAIRS},
        **{pair: "arms" for pair in ARM_PAIRS},
        **{pair: "legs" for pair in LEG_PAIRS},
    }
    pair_parents = {
        ("left_collar", "right_collar"): ("neck", "neck"),
        ("left_shoulder", "right_shoulder"): ("left_collar", "right_collar"),
        ("left_elbow", "right_elbow"): ("left_shoulder", "right_shoulder"),
        ("left_wrist", "right_wrist"): ("left_elbow", "right_elbow"),
        ("left_hand", "right_hand"): ("left_wrist", "right_wrist"),
        ("left_hip", "right_hip"): ("pelvis", "pelvis"),
        ("left_knee", "right_knee"): ("left_hip", "right_hip"),
        ("left_ankle", "right_ankle"): ("left_knee", "right_knee"),
        ("left_foot", "right_foot"): ("left_ankle", "right_ankle"),
    }
    motion_dominant_groups = set(
        dominant_profile.get("motionDominantGroups", [])
    )
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    support_constraint = (
        cleanup_metadata.get("supportSurfaceConstraint")
        if isinstance(cleanup_metadata, dict)
        else None
    )
    knee_lock = (
        support_constraint.get("kneeLock")
        if isinstance(support_constraint, dict)
        else None
    )
    support_names = (
        knee_lock.get("supportJoints")
        if isinstance(knee_lock, dict)
        else None
    )
    anchored_joints = {
        name
        for name in support_names or []
        if isinstance(name, str) and name in clip.joint_names
    }
    anchor_positions = {
        name: clip.frames[0].joints[name]
        for name in anchored_joints
    }
    movement_plane_coordinate = None
    if lateral_axis is not None:
        body_center_coordinates = [
            _dot(frame.joints["pelvis"], lateral_axis)
            for frame in clip.frames
            if "pelvis" in frame.joints
        ]
        body_center_coordinate = (
            median(body_center_coordinates)
            if body_center_coordinates
            else None
        )
        movement_plane_coordinate = body_center_coordinate
        for pair, target_width in bilateral_widths.items():
            if not all(joint in anchored_joints for joint in pair):
                continue
            midpoint = _average_points(
                [anchor_positions[pair[0]], anchor_positions[pair[1]]]
            )
            if body_center_coordinate is not None:
                midpoint = _add(
                    midpoint,
                    _scale(
                        lateral_axis,
                        body_center_coordinate - _dot(midpoint, lateral_axis),
                    ),
                )
            half_width = target_width * 0.5
            anchor_positions[pair[0]] = _subtract(
                midpoint,
                _scale(lateral_axis, half_width),
            )
            anchor_positions[pair[1]] = _add(
                midpoint,
                _scale(lateral_axis, half_width),
            )
    static_joint_names = set(anchored_joints)
    changed = True
    while changed:
        changed = False
        for pair in bilateral_pairs:
            if pair_groups.get(pair) in motion_dominant_groups:
                continue
            parent_pair = pair_parents.get(pair)
            if (
                parent_pair is None
                or not all(joint in static_joint_names for joint in parent_pair)
            ):
                continue
            for joint_name in pair:
                if joint_name not in static_joint_names:
                    static_joint_names.add(joint_name)
                    changed = True
    stable_head_angle = None
    head_length = bone_lengths.get(("neck", "head"))
    if lateral_axis is not None and head_length is not None:
        head_angles = []
        for frame in clip.frames:
            if not all(
                joint in frame.joints
                for joint in ("pelvis", "neck", "head")
            ):
                continue
            torso_vector = _subtract(
                frame.joints["neck"],
                frame.joints["pelvis"],
            )
            head_vector = _subtract(
                frame.joints["head"],
                frame.joints["neck"],
            )
            torso_direction = _normalize(
                _subtract(
                    torso_vector,
                    _scale(lateral_axis, _dot(torso_vector, lateral_axis)),
                )
            )
            head_direction = _normalize(
                _subtract(
                    head_vector,
                    _scale(lateral_axis, _dot(head_vector, lateral_axis)),
                )
            )
            if torso_direction is None or head_direction is None:
                continue
            head_angles.append(
                math.atan2(
                    _dot(_cross(torso_direction, head_direction), lateral_axis),
                    _dot(torso_direction, head_direction),
                )
            )
        if head_angles:
            stable_head_angle = max(
                -MAX_STABLE_HEAD_TO_TORSO_ANGLE_RADIANS,
                min(
                    MAX_STABLE_HEAD_TO_TORSO_ANGLE_RADIANS,
                    median(head_angles),
                ),
            )

    def project_distance_constraint(
        joints: dict[str, Point3],
        first_name: str,
        second_name: str,
        target_distance: float,
    ) -> None:
        first = joints.get(first_name)
        second = joints.get(second_name)
        if first is None or second is None:
            return
        delta = _subtract(second, first)
        distance = _length(delta)
        if distance <= 1e-8:
            return
        first_weight = 0.0 if first_name in anchored_joints else 1.0
        second_weight = 0.0 if second_name in anchored_joints else 1.0
        total_weight = first_weight + second_weight
        if total_weight <= 1e-8:
            return
        correction = _scale(delta, (distance - target_distance) / distance)
        if first_weight > 0.0:
            joints[first_name] = _add(
                first,
                _scale(correction, first_weight / total_weight),
            )
        if second_weight > 0.0:
            joints[second_name] = _subtract(
                second,
                _scale(correction, second_weight / total_weight),
            )

    def project_mirrored_pair(
        joints: dict[str, Point3],
        pair: tuple[str, str],
        target_width: float,
    ) -> None:
        if lateral_axis is None:
            project_distance_constraint(
                joints,
                pair[0],
                pair[1],
                target_width,
            )
            return
        left = joints.get(pair[0])
        right = joints.get(pair[1])
        if left is None or right is None:
            return
        left_anchored = pair[0] in anchored_joints
        right_anchored = pair[1] in anchored_joints
        if left_anchored and right_anchored:
            return
        if left_anchored:
            joints[pair[1]] = _add(left, _scale(lateral_axis, target_width))
            return
        if right_anchored:
            joints[pair[0]] = _subtract(right, _scale(lateral_axis, target_width))
            return
        midpoint = _average_points([left, right])
        if movement_plane_coordinate is not None:
            midpoint = _add(
                midpoint,
                _scale(
                    lateral_axis,
                    movement_plane_coordinate - _dot(midpoint, lateral_axis),
                ),
            )
        half_width = target_width * 0.5
        joints[pair[0]] = _subtract(
            midpoint,
            _scale(lateral_axis, half_width),
        )
        joints[pair[1]] = _add(
            midpoint,
            _scale(lateral_axis, half_width),
        )

    def project_axial_centerline(joints: dict[str, Point3]) -> None:
        if lateral_axis is None or movement_plane_coordinate is None:
            return
        for joint_name in AXIAL_CENTERLINE_JOINTS:
            point = joints.get(joint_name)
            if point is None:
                continue
            joints[joint_name] = _add(
                point,
                _scale(
                    lateral_axis,
                    movement_plane_coordinate - _dot(point, lateral_axis),
                ),
            )
        if stable_head_angle is None or head_length is None:
            return
        pelvis = joints.get("pelvis")
        neck = joints.get("neck")
        if pelvis is None or neck is None or "head" not in joints:
            return
        torso_direction = _normalize(_subtract(neck, pelvis))
        if torso_direction is None:
            return
        head_direction = _rotate_vector_about_axis(
            torso_direction,
            axis=lateral_axis,
            angle_radians=stable_head_angle,
        )
        joints["head"] = _add(
            neck,
            _scale(head_direction, head_length),
        )

    frames = [
        MotionFrame(time_sec=frame.time_sec, joints=dict(frame.joints))
        for frame in clip.frames
    ]
    for _ in range(4):
        tracks = {
            joint_name: [frame.joints[joint_name] for frame in frames]
            for joint_name in clip.joint_names
        }
        temporal_targets = {
            joint_name: (
                [_median_point(track)] * len(track)
                if joint_name in static_joint_names
                else _zero_phase_smooth_points(track, radius=2)
            )
            for joint_name, track in tracks.items()
        }
        solved_frames: list[MotionFrame] = []
        for frame_index, frame in enumerate(frames):
            joints = dict(frame.joints)
            for joint_name in clip.joint_names:
                if joint_name in anchored_joints:
                    continue
                if joint_name in static_joint_names:
                    joints[joint_name] = temporal_targets[joint_name][frame_index]
                else:
                    joints[joint_name] = _limited_lerp_point(
                        joints[joint_name],
                        temporal_targets[joint_name][frame_index],
                        0.35,
                        0.004,
                    )
            for _constraint_iteration in range(32):
                for (parent, child), target_length in bone_lengths.items():
                    project_distance_constraint(
                        joints,
                        parent,
                        child,
                        target_length,
                    )
                for pair, target_width in bilateral_widths.items():
                    project_mirrored_pair(
                        joints,
                        pair,
                        target_width,
                    )
                for joint_name, anchor in anchor_positions.items():
                    joints[joint_name] = anchor
                project_axial_centerline(joints)
            solved_frames.append(
                MotionFrame(time_sec=frame.time_sec, joints=joints)
            )
        frames = solved_frames

    solved = replace(clip, frames=frames)
    displacement = _average_joint_displacement(
        clip,
        solved,
        list(clip.joint_names),
    )
    maximum_bone_error = max(
        (
            abs(
                _distance(frame.joints[parent], frame.joints[child])
                - target_length
            )
            for frame in solved.frames
            for (parent, child), target_length in bone_lengths.items()
        ),
        default=0.0,
    )
    maximum_width_error = max(
        (
            abs(
                _distance(frame.joints[pair[0]], frame.joints[pair[1]])
                - target_width
            )
            for frame in solved.frames
            for pair, target_width in bilateral_widths.items()
        ),
        default=0.0,
    )
    maximum_mirror_error = (
        max(
            (
                _distance(
                    _subtract(
                        frame.joints[pair[1]],
                        frame.joints[pair[0]],
                    ),
                    _scale(lateral_axis, target_width),
                )
                for frame in solved.frames
                for pair, target_width in bilateral_widths.items()
                if not all(joint in anchored_joints for joint in pair)
            ),
            default=0.0,
        )
        if lateral_axis is not None
        else 0.0
    )
    maximum_axial_plane_error = (
        max(
            (
                abs(
                    _dot(frame.joints[joint_name], lateral_axis)
                    - movement_plane_coordinate
                )
                for frame in solved.frames
                for joint_name in AXIAL_CENTERLINE_JOINTS
                if joint_name in frame.joints
            ),
            default=0.0,
        )
        if lateral_axis is not None and movement_plane_coordinate is not None
        else 0.0
    )
    return solved, {
        "applied": True,
        "strategy": "clip_wide_temporal_graph_constraint_projection",
        "temporalPasses": 4,
        "constraintIterationsPerPass": 32,
        "boneConstraintCount": len(bone_lengths),
        "bilateralConstraintCount": len(bilateral_widths),
        "staticTrajectoryJoints": sorted(
            static_joint_names - anchored_joints
        ),
        "anchoredJoints": sorted(anchored_joints),
        "averageCorrection": displacement["average"],
        "maxCorrection": displacement["max"],
        "maximumBoneLengthError": maximum_bone_error,
        "maximumBilateralWidthError": maximum_width_error,
        "maximumBilateralMirrorError": maximum_mirror_error,
        "maximumAxialPlaneError": maximum_axial_plane_error,
        "stableHeadToTorsoAngleDegrees": (
            math.degrees(stable_head_angle)
            if stable_head_angle is not None
            else None
        ),
    }


def _polish_motion_clip_temporally(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    if clip.frame_count < 5 or "pelvis" not in clip.joint_names:
        return clip, {"applied": False, "reason": "insufficient_root_track"}
    source_root_track = [frame.joints["pelvis"] for frame in clip.frames]
    smoothed_root_track = _zero_phase_smooth_points(source_root_track, radius=3)
    polished_root_track = [
        _limited_lerp_point(
            source,
            smoothed,
            0.60,
            0.008,
        )
        for source, smoothed in zip(source_root_track, smoothed_root_track)
    ]
    offset_tracks = {
        joint_name: [
            _subtract(frame.joints[joint_name], frame.joints["pelvis"])
            for frame in clip.frames
        ]
        for joint_name in clip.joint_names
        if joint_name != "pelvis"
    }
    smoothed_offset_tracks = {
        joint_name: _zero_phase_smooth_points(points, radius=2)
        for joint_name, points in offset_tracks.items()
    }
    locked_support_joints = _locked_support_anchor_names(clip)
    frames: list[MotionFrame] = []
    maximum_correction = 0.0
    total_correction = 0.0
    samples = 0
    for frame_index, frame in enumerate(clip.frames):
        source_root = source_root_track[frame_index]
        polished_root = polished_root_track[frame_index]
        joints = {"pelvis": polished_root}
        for joint_name, point in frame.joints.items():
            if joint_name == "pelvis":
                continue
            if joint_name in locked_support_joints:
                joints[joint_name] = point
                continue
            translated = _add(
                point,
                _subtract(polished_root, source_root),
            )
            target = _add(
                polished_root,
                smoothed_offset_tracks[joint_name][frame_index],
            )
            polished = _limited_lerp_point(
                translated,
                target,
                0.58,
                0.006,
            )
            correction = _distance(point, polished)
            maximum_correction = max(maximum_correction, correction)
            total_correction += correction
            samples += 1
            joints[joint_name] = polished
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    polished_clip = replace(clip, frames=frames)
    return polished_clip, {
        "applied": True,
        "strategy": "clip_wide_zero_phase_root_and_root_relative_polish",
        "rootWindowRadius": 3,
        "jointWindowRadius": 2,
        "maximumRootCorrection": 0.008,
        "maximumRelativeCorrection": 0.006,
        "averageCorrection": total_correction / samples if samples else 0.0,
        "maxCorrection": maximum_correction,
    }


def _solve_clip_wide_reachable_pelvis_track(
    clip: MotionClip,
    *,
    reachable_configs: list[tuple[str, Point3, float, float]],
) -> list[Point3]:
    source_track = [
        frame.joints.get("pelvis", (0.0, 0.0, 0.0))
        for frame in clip.frames
    ]
    if not reachable_configs:
        return source_track

    def project_to_reachable_region(point: Point3) -> Point3:
        projected = point
        for _ in range(12):
            for _hip_name, anchor, pelvis_to_hip, hip_to_knee in reachable_configs:
                anchor_to_pelvis = _subtract(projected, anchor)
                distance = _length(anchor_to_pelvis)
                maximum_reach = max(
                    1e-6,
                    pelvis_to_hip + hip_to_knee - 1e-5,
                )
                if distance > maximum_reach:
                    projected = _add(
                        anchor,
                        _scale(anchor_to_pelvis, maximum_reach / distance),
                    )
        return projected

    solved_track = [project_to_reachable_region(point) for point in source_track]
    for _ in range(8):
        corrections = [
            _subtract(solved, source)
            for source, solved in zip(source_track, solved_track)
        ]
        smoothed_corrections = _zero_phase_smooth_points(corrections, radius=3)
        solved_track = [
            project_to_reachable_region(
                _add(
                    source,
                    _lerp_point(correction, smoothed, 0.75),
                )
            )
            for source, correction, smoothed in zip(
                source_track,
                corrections,
                smoothed_corrections,
            )
        ]
    return solved_track


def _solve_clip_wide_two_bone_mid_track(
    clip: MotionClip,
    *,
    hip_name: str,
    pelvis_track: list[Point3],
    knee_anchor: Point3,
    pelvis_to_hip: float,
    hip_to_knee: float,
) -> list[Point3]:
    line_directions: list[Point3] = []
    projection_lengths: list[float] = []
    bend_heights: list[float] = []
    bend_directions: list[Point3] = []
    previous_bend: Point3 | None = None
    for frame, solved_pelvis in zip(clip.frames, pelvis_track):
        source_pelvis = frame.joints["pelvis"]
        translated_hip = _add(
            frame.joints[hip_name],
            _subtract(solved_pelvis, source_pelvis),
        )
        root_to_knee = _subtract(knee_anchor, solved_pelvis)
        distance = max(_length(root_to_knee), 1e-6)
        direction = _scale(root_to_knee, 1.0 / distance)
        projection_length = (
            pelvis_to_hip * pelvis_to_hip
            - hip_to_knee * hip_to_knee
            + distance * distance
        ) / (2.0 * distance)
        bend_height = math.sqrt(
            max(
                0.0,
                pelvis_to_hip * pelvis_to_hip
                - projection_length * projection_length,
            )
        )
        projected_hip = _add(
            solved_pelvis,
            _scale(direction, projection_length),
        )
        bend = _normalize(_subtract(translated_hip, projected_hip))
        if bend is None:
            bend = previous_bend or _normalize(_cross(direction, (0.0, 1.0, 0.0)))
        if bend is None:
            bend = (1.0, 0.0, 0.0)
        if previous_bend is not None and _dot(bend, previous_bend) < 0.0:
            bend = _scale(bend, -1.0)
        previous_bend = bend
        line_directions.append(direction)
        projection_lengths.append(projection_length)
        bend_heights.append(bend_height)
        bend_directions.append(bend)

    smoothed_bends = bend_directions
    for _ in range(4):
        smoothed_bends = _zero_phase_smooth_points(smoothed_bends, radius=3)
        smoothed_bends = [
            _normalize(
                _subtract(smoothed, _scale(line, _dot(smoothed, line)))
            )
            or original
            for smoothed, line, original in zip(
                smoothed_bends,
                line_directions,
                bend_directions,
            )
        ]
    return [
        _add(
            _add(pelvis, _scale(line, projection_length)),
            _scale(bend, bend_height),
        )
        for pelvis, line, projection_length, bend, bend_height in zip(
            pelvis_track,
            line_directions,
            projection_lengths,
            smoothed_bends,
            bend_heights,
        )
    ]


def _solve_coupled_bilateral_hip_tracks(
    *,
    pelvis_track: list[Point3],
    left_knee_anchor: Point3,
    right_knee_anchor: Point3,
    left_pelvis_to_hip: float,
    right_pelvis_to_hip: float,
    left_hip_to_knee: float,
    right_hip_to_knee: float,
    target_hip_width: float,
    left_initial_track: list[Point3],
    right_initial_track: list[Point3],
) -> tuple[list[Point3], list[Point3]]:
    def project_distance(point: Point3, anchor: Point3, distance: float) -> Point3:
        direction = _subtract(point, anchor)
        length = _length(direction)
        if length <= 1e-8:
            return point
        return _add(anchor, _scale(direction, distance / length))

    def solve_frame(
        pelvis: Point3,
        left: Point3,
        right: Point3,
    ) -> tuple[Point3, Point3]:
        for _ in range(48):
            left = project_distance(left, pelvis, left_pelvis_to_hip)
            left = project_distance(left, left_knee_anchor, left_hip_to_knee)
            right = project_distance(right, pelvis, right_pelvis_to_hip)
            right = project_distance(right, right_knee_anchor, right_hip_to_knee)
            separation = _subtract(right, left)
            separation_length = _length(separation)
            if separation_length > 1e-8:
                correction = _scale(
                    separation,
                    (target_hip_width - separation_length)
                    / separation_length
                    * 0.5,
                )
                left = _subtract(left, correction)
                right = _add(right, correction)
        return left, right

    left_track = list(left_initial_track)
    right_track = list(right_initial_track)
    for _ in range(4):
        smoothed_left = _zero_phase_smooth_points(left_track, radius=2)
        smoothed_right = _zero_phase_smooth_points(right_track, radius=2)
        solved_pairs = [
            solve_frame(
                pelvis,
                _lerp_point(left, left_smoothed, 0.45),
                _lerp_point(right, right_smoothed, 0.45),
            )
            for pelvis, left, right, left_smoothed, right_smoothed in zip(
                pelvis_track,
                left_track,
                right_track,
                smoothed_left,
                smoothed_right,
            )
        ]
        left_track = [pair[0] for pair in solved_pairs]
        right_track = [pair[1] for pair in solved_pairs]
    return left_track, right_track


def _restore_authoritative_support_anchors(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    if not isinstance(cleanup_metadata, dict):
        return clip, {"applied": False, "reason": "missing_cleanup_metadata"}
    support_constraint = cleanup_metadata.get("supportSurfaceConstraint")
    knee_lock = (
        support_constraint.get("kneeLock")
        if isinstance(support_constraint, dict)
        else None
    )
    # Only anchors emitted by the contact solver are authoritative. The
    # orientation stabilizer also uses support joints as per-frame rotation
    # pivots, but their median positions are not planted-contact constraints.
    # Treating those pivots as anchors collapses legitimate foot/hand motion
    # and stretches the connected limb chains.
    raw_anchors = knee_lock.get("anchors") if isinstance(knee_lock, dict) else None
    if isinstance(knee_lock, dict) and knee_lock.get("allowWholeSkeletonSolver", True) is False:
        return clip, {"applied": False, "reason": "support_solver_disabled_for_local_lock"}
    if not isinstance(raw_anchors, dict):
        return clip, {"applied": False, "reason": "no_authoritative_support_anchors"}

    anchors: dict[str, Point3] = {}
    for joint_name, value in raw_anchors.items():
        if (
            isinstance(joint_name, str)
            and isinstance(value, list)
            and len(value) >= 3
            and all(isinstance(component, (int, float)) for component in value[:3])
        ):
            anchors[joint_name] = (
                float(value[0]),
                float(value[1]),
                float(value[2]),
            )
    if not anchors:
        return clip, {"applied": False, "reason": "invalid_support_anchors"}

    support_descendants = {
        "left_knee": ("left_ankle", "left_foot"),
        "right_knee": ("right_ankle", "right_foot"),
    }
    raw_reference_lengths = (
        knee_lock.get("referenceBoneLengths")
        if isinstance(knee_lock, dict)
        else None
    )
    reference_lengths = (
        raw_reference_lengths
        if isinstance(raw_reference_lengths, dict)
        else {}
    )
    reachable_configs: list[tuple[str, Point3, float, float]] = []
    for joint_name, anchor in anchors.items():
        side = joint_name.removesuffix("_knee")
        hip_name = f"{side}_hip"
        lengths = reference_lengths.get(joint_name)
        pelvis_to_hip = (
            _optional_float(lengths.get("pelvisToHip"))
            if isinstance(lengths, dict)
            else None
        )
        hip_to_knee = (
            _optional_float(lengths.get("hipToKnee"))
            if isinstance(lengths, dict)
            else None
        )
        if (
            hip_name in clip.joint_names
            and pelvis_to_hip is not None
            and hip_to_knee is not None
        ):
            reachable_configs.append(
                (hip_name, anchor, pelvis_to_hip, hip_to_knee)
            )
    solved_pelvis_track = _solve_clip_wide_reachable_pelvis_track(
        clip,
        reachable_configs=reachable_configs,
    )
    solved_hip_tracks = {
        hip_name: _solve_clip_wide_two_bone_mid_track(
            clip,
            hip_name=hip_name,
            pelvis_track=solved_pelvis_track,
            knee_anchor=anchor,
            pelvis_to_hip=pelvis_to_hip,
            hip_to_knee=hip_to_knee,
        )
        for hip_name, anchor, pelvis_to_hip, hip_to_knee in reachable_configs
    }
    reference_hip_width = (
        _optional_float(knee_lock.get("referenceHipWidth"))
        if isinstance(knee_lock, dict)
        else None
    )
    config_by_hip = {
        hip_name: (anchor, pelvis_to_hip, hip_to_knee)
        for hip_name, anchor, pelvis_to_hip, hip_to_knee in reachable_configs
    }
    if (
        reference_hip_width is not None
        and "left_hip" in solved_hip_tracks
        and "right_hip" in solved_hip_tracks
        and "left_hip" in config_by_hip
        and "right_hip" in config_by_hip
    ):
        left_config = config_by_hip["left_hip"]
        right_config = config_by_hip["right_hip"]
        left_track, right_track = _solve_coupled_bilateral_hip_tracks(
            pelvis_track=solved_pelvis_track,
            left_knee_anchor=left_config[0],
            right_knee_anchor=right_config[0],
            left_pelvis_to_hip=left_config[1],
            right_pelvis_to_hip=right_config[1],
            left_hip_to_knee=left_config[2],
            right_hip_to_knee=right_config[2],
            target_hip_width=reference_hip_width,
            left_initial_track=solved_hip_tracks["left_hip"],
            right_initial_track=solved_hip_tracks["right_hip"],
        )
        solved_hip_tracks["left_hip"] = left_track
        solved_hip_tracks["right_hip"] = right_track
    frames: list[MotionFrame] = []
    maximum_correction = 0.0
    maximum_pelvis_correction = 0.0
    maximum_thigh_length_error = 0.0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        pelvis = joints.get("pelvis")
        if pelvis is not None and reachable_configs:
            solved_pelvis = solved_pelvis_track[frame_index]
            pelvis_correction = _subtract(solved_pelvis, pelvis)
            pelvis_correction_length = _length(pelvis_correction)
            maximum_pelvis_correction = max(
                maximum_pelvis_correction,
                pelvis_correction_length,
            )
            if pelvis_correction_length > 1e-8:
                distal_joints = {
                    joint_name
                    for support_joint in anchors
                    for joint_name in (
                        support_joint,
                        *support_descendants.get(support_joint, ()),
                    )
                }
                joints = {
                    name: (
                        point
                        if name in distal_joints
                        else _add(point, pelvis_correction)
                    )
                    for name, point in joints.items()
                }
            for hip_name, anchor, pelvis_to_hip, hip_to_knee in reachable_configs:
                solved_hip = solved_hip_tracks[hip_name][frame_index]
                joints[hip_name] = solved_hip
                maximum_thigh_length_error = max(
                    maximum_thigh_length_error,
                    abs(_distance(solved_hip, anchor) - hip_to_knee),
                )
        for joint_name, anchor in anchors.items():
            current = joints.get(joint_name)
            if current is None:
                continue
            correction = _subtract(anchor, current)
            maximum_correction = max(maximum_correction, _length(correction))
            joints[joint_name] = anchor
            for descendant_name in support_descendants.get(joint_name, ()):
                descendant = joints.get(descendant_name)
                if descendant is not None:
                    joints[descendant_name] = _add(descendant, correction)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    solved_hip_widths = [
        _distance(frame.joints["left_hip"], frame.joints["right_hip"])
        for frame in frames
        if "left_hip" in frame.joints and "right_hip" in frame.joints
    ]
    output_metadata = dict(clip.metadata)
    output_metadata.pop("_orientationSupportAnchors", None)
    return replace(clip, frames=frames, metadata=output_metadata), {
        "applied": True,
        "strategy": "clip_wide_temporal_planted_support_ik",
        "supportJoints": sorted(anchors),
        "temporalSmoothingPasses": 8,
        "hipBendSmoothingPasses": 4,
        "targetHipWidth": reference_hip_width,
        "hipWidthRange": (
            max(solved_hip_widths) - min(solved_hip_widths)
            if solved_hip_widths
            else 0.0
        ),
        "maximumCorrection": maximum_correction,
        "maximumPelvisReachCorrection": maximum_pelvis_correction,
        "maximumThighLengthError": maximum_thigh_length_error,
    }


def _denoise_along_dominant_motion_axis(
    clip: MotionClip,
    *,
    dynamic_length_child_joints: set[str],
    stabilize_body_orientation: bool,
) -> tuple[MotionClip, dict[str, object]]:
    if clip.frame_count < 5:
        return clip, {"applied": False, "reason": "too_few_frames"}
    axis, confidence = _dominant_motion_axis(clip)
    if axis is None or confidence < 0.45:
        return clip, {
            "applied": False,
            "reason": "no_coherent_dominant_motion_axis",
            "confidence": confidence,
        }

    body_height = max(_median_body_height(clip), 0.5)
    max_correction = min(0.04, max(0.012, body_height * 0.025))
    joint_tracks = {
        joint_name: [
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ]
        for joint_name in clip.joint_names
    }
    denoised_by_joint: dict[str, list[Point3]] = {}
    joint_coherence: dict[str, float] = {}
    total_correction = 0.0
    maximum_correction = 0.0
    correction_samples = 0

    for joint_name, points in joint_tracks.items():
        if len(points) != clip.frame_count:
            continue
        center = _median_point(points)
        axial_values = [_dot(_subtract(point, center), axis) for point in points]
        orthogonal_values = [
            _subtract(_subtract(point, center), _scale(axis, axial))
            for point, axial in zip(points, axial_values)
        ]
        axial_range = max(axial_values) - min(axial_values)
        orthogonal_range = _point_cloud_extent(orthogonal_values)
        coherence = axial_range / max(axial_range + orthogonal_range, 1e-8)
        joint_coherence[joint_name] = coherence

        motion_range = _point_cloud_extent(points)
        if motion_range <= max(0.008, body_height * 0.008):
            targets = [center] * clip.frame_count
            axial_blend = 0.70
            orthogonal_blend = 0.82
        else:
            targets = _zero_phase_smooth_points(points, radius=2)
            axial_blend = 0.52 if coherence >= 0.55 else 0.38
            orthogonal_blend = 0.88 if coherence >= 0.55 else 0.62

        denoised_points: list[Point3] = []
        for point, target in zip(points, targets):
            raw_delta = _subtract(point, center)
            target_delta = _subtract(target, center)
            raw_axial = _dot(raw_delta, axis)
            target_axial = _dot(target_delta, axis)
            raw_orthogonal = _subtract(raw_delta, _scale(axis, raw_axial))
            target_orthogonal = _subtract(target_delta, _scale(axis, target_axial))
            solved_delta = _add(
                _scale(
                    axis,
                    raw_axial + (target_axial - raw_axial) * axial_blend,
                ),
                _lerp_point(raw_orthogonal, target_orthogonal, orthogonal_blend),
            )
            solved = _limit_point_correction(
                point,
                _add(center, solved_delta),
                max_correction=max_correction,
            )
            correction = _distance(point, solved)
            if correction > 1e-8:
                total_correction += correction
                maximum_correction = max(maximum_correction, correction)
                correction_samples += 1
            denoised_points.append(solved)
        denoised_by_joint[joint_name] = denoised_points

    trajectory_frames: list[MotionFrame] = []
    for frame_index, frame in enumerate(clip.frames):
        joints = {
            joint_name: denoised_by_joint.get(joint_name, [point] * clip.frame_count)[frame_index]
            for joint_name, point in frame.joints.items()
        }
        trajectory_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    trajectory_clip = replace(clip, frames=trajectory_frames)
    if stabilize_body_orientation:
        trajectory_clip, orientation_metadata = _stabilize_body_orientation_to_motion_plane(
            trajectory_clip,
            dominant_axis=axis,
        )
    else:
        orientation_metadata = {
            "applied": False,
            "reason": "bilateral_motion_is_not_same_phase_symmetric",
        }
    solved_clip, skeleton_metadata = _reconstruct_denoised_skeleton(
        trajectory_clip,
        reference_clip=clip,
        dynamic_length_child_joints=dynamic_length_child_joints,
    )
    return solved_clip, {
        "applied": True,
        "strategy": "clip_wide_dominant_axis_zero_phase_denoising_with_skeletal_reconstruction",
        "dominantAxis": [float(axis[0]), float(axis[1]), float(axis[2])],
        "confidence": confidence,
        "maximumCorrection": max_correction,
        "averageTrajectoryCorrection": (
            total_correction / correction_samples if correction_samples else 0.0
        ),
        "maxTrajectoryCorrection": maximum_correction,
        "jointDirectionalCoherence": joint_coherence,
        "bodyOrientationStabilization": orientation_metadata,
        "skeletalReconstruction": skeleton_metadata,
    }


def _dominant_motion_axis(clip: MotionClip) -> tuple[Point3 | None, float]:
    centered_samples: list[Point3] = []
    for joint_name in clip.joint_names:
        points = [
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ]
        if len(points) != clip.frame_count:
            continue
        center = _median_point(points)
        centered_samples.extend(_subtract(point, center) for point in points)
    if not centered_samples:
        return None, 0.0

    covariance = [[0.0] * 3 for _ in range(3)]
    for sample in centered_samples:
        for row in range(3):
            for column in range(3):
                covariance[row][column] += sample[row] * sample[column]
    sample_count = float(len(centered_samples))
    covariance = [
        [value / sample_count for value in row]
        for row in covariance
    ]
    trace = covariance[0][0] + covariance[1][1] + covariance[2][2]
    if trace <= 1e-10:
        return None, 0.0

    largest_diagonal = max(range(3), key=lambda axis_index: covariance[axis_index][axis_index])
    direction = [0.0, 0.0, 0.0]
    direction[largest_diagonal] = 1.0
    for _ in range(16):
        projected = [
            sum(covariance[row][column] * direction[column] for column in range(3))
            for row in range(3)
        ]
        length = math.sqrt(sum(value * value for value in projected))
        if length <= 1e-10:
            return None, 0.0
        direction = [value / length for value in projected]
    axis = (direction[0], direction[1], direction[2])
    dominant_variance = _dot(
        axis,
        (
            sum(covariance[0][column] * axis[column] for column in range(3)),
            sum(covariance[1][column] * axis[column] for column in range(3)),
            sum(covariance[2][column] * axis[column] for column in range(3)),
        ),
    )
    return axis, dominant_variance / trace


def _stabilize_body_orientation_to_motion_plane(
    clip: MotionClip,
    *,
    dominant_axis: Point3,
) -> tuple[MotionClip, dict[str, object]]:
    body_frames = [_body_local_frame(frame) for frame in clip.frames]
    available_frames = [frame for frame in body_frames if frame is not None]
    if not available_frames:
        return clip, {"applied": False, "reason": "no_body_local_frames"}

    median_right = _normalize(_median_point([frame.right for frame in available_frames]))
    if median_right is None:
        return clip, {"applied": False, "reason": "unstable_body_lateral_axis"}
    horizontal_motion = _normalize((dominant_axis[0], 0.0, dominant_axis[2]))
    if horizontal_motion is not None:
        target_right = _normalize(_cross((0.0, 1.0, 0.0), horizontal_motion))
    else:
        target_right = _normalize((median_right[0], 0.0, median_right[2]))
    if target_right is None:
        return clip, {"applied": False, "reason": "no_horizontal_lateral_axis"}
    if _dot(target_right, median_right) < 0.0:
        target_right = _scale(target_right, -1.0)

    maximum_angle = math.radians(35.0)
    frames: list[MotionFrame] = []
    corrections_degrees: list[float] = []
    vertical_lifts: list[float] = []
    for frame_index, (frame, body_frame) in enumerate(zip(clip.frames, body_frames)):
        if body_frame is None:
            frames.append(frame)
            continue
        horizontal_right = _normalize(
            (body_frame.right[0], 0.0, body_frame.right[2])
        )
        if horizontal_right is None:
            frames.append(frame)
            continue
        cosine = max(-1.0, min(1.0, _dot(horizontal_right, target_right)))
        signed_sine = _cross(horizontal_right, target_right)[1]
        signed_angle = math.atan2(signed_sine, cosine)
        if abs(signed_angle) <= 1e-8:
            frames.append(frame)
            continue
        angle = math.copysign(min(abs(signed_angle), maximum_angle), signed_angle)
        support_joint_names = _orientation_support_joint_names(
            clip,
            frame_index=frame_index,
        )
        support_points = [
            frame.joints[name]
            for name in support_joint_names
            if name in frame.joints
        ]
        pivot = _average_points(support_points) if support_points else body_frame.origin
        rotated_joints = {
            name: _add(
                pivot,
                _rotate_vector_about_axis(
                    _subtract(point, pivot),
                    axis=(0.0, 1.0, 0.0),
                    angle_radians=angle,
                ),
            )
            for name, point in frame.joints.items()
        }
        vertical_lift = 0.0
        for left_name, right_name in (
            ("left_hip", "right_hip"),
            ("left_shoulder", "right_shoulder"),
        ):
            left = rotated_joints.get(left_name)
            right = rotated_joints.get(right_name)
            if left is None or right is None:
                continue
            shared_y = (left[1] + right[1]) * 0.5
            rotated_joints[left_name] = (
                left[0],
                shared_y,
                left[2],
            )
            rotated_joints[right_name] = (
                right[0],
                shared_y,
                right[2],
            )
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=rotated_joints))
        corrections_degrees.append(abs(math.degrees(angle)))
        vertical_lifts.append(vertical_lift)
    if not corrections_degrees:
        return clip, {"applied": False, "reason": "orientation_already_stable"}
    return replace(clip, frames=frames), {
        "applied": True,
        "strategy": "same_phase_bilateral_body_axis_aligned_to_dominant_motion_plane",
        "targetRightAxis": [target_right[0], target_right[1], target_right[2]],
        "medianCorrectionDegrees": median(corrections_degrees),
        "maxCorrectionDegrees": max(corrections_degrees),
        "maximumAllowedCorrectionDegrees": math.degrees(maximum_angle),
        "maxVerticalNonPenetrationLift": max(vertical_lifts, default=0.0),
    }


def _orientation_support_joint_names(
    clip: MotionClip,
    *,
    frame_index: int,
) -> list[str]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    if not isinstance(cleanup_metadata, dict):
        return []
    contact_states = cleanup_metadata.get("footContacts")
    state = (
        contact_states[frame_index]
        if isinstance(contact_states, list)
        and frame_index < len(contact_states)
        and isinstance(contact_states[frame_index], dict)
        else {}
    )
    if cleanup_metadata.get("supportMode") == "kneeling":
        knee_names = [
            state.get("leftKneeJoint", "left_knee"),
            state.get("rightKneeJoint", "right_knee"),
        ]
        return [name for name in knee_names if isinstance(name, str)]
    contact_joints = state.get("contactJoints")
    if not isinstance(contact_joints, list):
        return []
    return [name for name in contact_joints if isinstance(name, str)]


def _authoritative_support_joint_height(
    clip: MotionClip,
    *,
    joint_name: str,
    fallback: float,
) -> float:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup_metadata = metadata.get("cleanup")
    support_constraint = (
        cleanup_metadata.get("supportSurfaceConstraint")
        if isinstance(cleanup_metadata, dict)
        else None
    )
    knee_lock = (
        support_constraint.get("kneeLock")
        if isinstance(support_constraint, dict)
        else None
    )
    anchors = knee_lock.get("anchors") if isinstance(knee_lock, dict) else None
    anchor = anchors.get(joint_name) if isinstance(anchors, dict) else None
    if (
        isinstance(anchor, list)
        and len(anchor) >= 2
        and isinstance(anchor[1], (int, float))
    ):
        return float(anchor[1])
    return fallback


def _rotate_vector_about_axis(
    vector: Point3,
    *,
    axis: Point3,
    angle_radians: float,
) -> Point3:
    cosine = math.cos(angle_radians)
    sine = math.sin(angle_radians)
    return _add(
        _add(
            _scale(vector, cosine),
            _scale(_cross(axis, vector), sine),
        ),
        _scale(axis, _dot(axis, vector) * (1.0 - cosine)),
    )


def _zero_phase_smooth_points(points: list[Point3], *, radius: int) -> list[Point3]:
    smoothed: list[Point3] = []
    for index in range(len(points)):
        weighted = [0.0, 0.0, 0.0]
        total_weight = 0.0
        for sample_index in range(max(0, index - radius), min(len(points), index + radius + 1)):
            weight = float(radius + 1 - abs(sample_index - index))
            point = points[sample_index]
            for axis_index in range(3):
                weighted[axis_index] += point[axis_index] * weight
            total_weight += weight
        smoothed.append((
            weighted[0] / total_weight,
            weighted[1] / total_weight,
            weighted[2] / total_weight,
        ))
    return smoothed


def _motion_noise_metrics(
    clip: MotionClip,
    *,
    body_height: float,
) -> dict[str, float]:
    residuals: list[float] = []
    for joint_name in clip.joint_names:
        points = [
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ]
        if len(points) != clip.frame_count:
            continue
        smoothed = _zero_phase_smooth_points(points, radius=2)
        residuals.extend(
            _distance(point, target)
            for point, target in zip(points, smoothed)
        )
    if not residuals:
        return {
            "medianResidual": 0.0,
            "p90Residual": 0.0,
            "bodyScale": body_height,
        }
    ordered = sorted(residuals)
    p90_index = min(len(ordered) - 1, int(0.90 * (len(ordered) - 1)))
    return {
        "medianResidual": median(ordered),
        "p90Residual": ordered[p90_index],
        "bodyScale": body_height,
    }


def _point_cloud_extent(points: list[Point3]) -> float:
    if not points:
        return 0.0
    return math.sqrt(sum(
        (max(point[axis] for point in points) - min(point[axis] for point in points)) ** 2
        for axis in range(3)
    ))


def _limit_point_correction(
    source: Point3,
    target: Point3,
    *,
    max_correction: float,
) -> Point3:
    delta = _subtract(target, source)
    distance = _length(delta)
    if distance <= max_correction or distance <= 1e-10:
        return target
    return _add(source, _scale(delta, max_correction / distance))


def _reconstruct_denoised_skeleton(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dynamic_length_child_joints: set[str],
) -> tuple[MotionClip, dict[str, object]]:
    body_scale = max(_median_body_height(reference_clip), 0.5)
    max_length_adjustment = min(0.02, max(0.008, body_scale * 0.01))
    max_joint_correction = min(0.03, max(0.012, body_scale * 0.018))
    reference_lengths = {
        (parent, child): _median_bone_length(reference_clip, parent, child)
        for parent, child in STRUCTURAL_BONES
        if parent in reference_clip.joint_names and child in reference_clip.joint_names
        and child not in dynamic_length_child_joints
    }
    direction_tracks: dict[tuple[str, str], list[Point3]] = {}
    for bone, target_length in reference_lengths.items():
        if target_length <= 1e-8:
            continue
        parent, child = bone
        directions: list[Point3] = []
        for frame in clip.frames:
            direction = _normalize(_subtract(frame.joints[child], frame.joints[parent]))
            directions.append(direction or (0.0, 1.0, 0.0))
        direction_tracks[bone] = [
            _normalize(point) or directions[index]
            for index, point in enumerate(_zero_phase_smooth_points(directions, radius=2))
        ]

    frames: list[MotionFrame] = []
    total_correction = 0.0
    maximum_correction = 0.0
    samples = 0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        for bone, directions in direction_tracks.items():
            parent, child = bone
            if parent not in joints or child not in joints:
                continue
            current_length = _distance(joints[parent], joints[child])
            reference_length = reference_lengths[bone]
            target_length = min(
                current_length + max_length_adjustment,
                max(current_length - max_length_adjustment, reference_length),
            )
            unconstrained_target = _add(
                joints[parent],
                _scale(directions[frame_index], target_length),
            )
            target = _limit_point_correction(
                joints[child],
                unconstrained_target,
                max_correction=max_joint_correction,
            )
            correction = _distance(joints[child], target)
            total_correction += correction
            maximum_correction = max(maximum_correction, correction)
            samples += 1
            joints[child] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": bool(direction_tracks),
        "boneCount": len(direction_tracks),
        "dynamicLengthChildJoints": sorted(dynamic_length_child_joints),
        "maximumLengthAdjustment": max_length_adjustment,
        "maximumJointCorrection": max_joint_correction,
        "averageCorrection": total_correction / samples if samples else 0.0,
        "maxCorrection": maximum_correction,
        "target": "median_bone_lengths_with_zero_phase_smoothed_bone_directions",
    }


def _align_upper_body_to_horizontal_support(
    clip: MotionClip,
    *, level_shoulders: bool = False,
) -> tuple[MotionClip, dict[str, object]]:
    """Flatten a contract-required horizontal torso without moving lower-body contacts."""
    required = {"pelvis", "neck", "left_shoulder", "right_shoulder"}
    if not required.issubset(clip.joint_names) or clip.frame_count < 2:
        return clip, {"applied": False, "reason": "torso_frame_unavailable"}
    upper_body_joints = (
        "spine1", "spine2", "spine3", "neck", "head",
        "left_collar", "right_collar", "left_shoulder", "right_shoulder",
        "left_elbow", "right_elbow", "left_wrist", "right_wrist",
        "left_hand", "right_hand",
    )
    frames: list[MotionFrame] = []
    maximum_correction = 0.0
    pitch_corrections: list[float] = []
    for frame in clip.frames:
        pelvis = frame.joints["pelvis"]
        hip_center = _scale(
            _add(frame.joints["left_hip"], frame.joints["right_hip"]),
            0.5,
        ) if {"left_hip", "right_hip"}.issubset(frame.joints) else pelvis
        shoulder_center = _scale(
            _add(frame.joints["left_shoulder"], frame.joints["right_shoulder"]),
            0.5,
        )
        # Use the visible torso silhouette rather than pelvis-to-neck.  The
        # latter can be horizontal while asymmetric shoulder/hip offsets still
        # leave the rendered trunk visibly pitched against the support plane.
        current_torso_axis = _normalize(_subtract(shoulder_center, hip_center))
        if current_torso_axis is None:
            frames.append(frame)
            continue
        target_torso_axis = _normalize(
            (current_torso_axis[0], 0.0, current_torso_axis[2])
        )
        if target_torso_axis is None:
            frames.append(frame)
            continue
        alignment = max(
            -1.0,
            min(1.0, _dot(current_torso_axis, target_torso_axis)),
        )
        pitch_angle = math.acos(alignment)
        pitch_axis = _normalize(_cross(current_torso_axis, target_torso_axis))
        if pitch_axis is None or pitch_angle <= 1e-8:
            pitch_angle = 0.0
            pitch_axis = (1.0, 0.0, 0.0)
        pitch_corrections.append(math.degrees(pitch_angle))
        joints = dict(frame.joints)
        for joint_name in upper_body_joints:
            point = joints.get(joint_name)
            if point is None:
                continue
            relative = _subtract(point, hip_center)
            rotated = _rotate_vector_about_axis(
                relative,
                axis=pitch_axis,
                angle_radians=pitch_angle,
            )
            target = _add(hip_center, rotated)
            maximum_correction = max(maximum_correction, _distance(point, target))
            joints[joint_name] = target
        if level_shoulders:
            # A supported bilateral press needs a level shoulder line as well
            # as a horizontal torso axis. Pitch-only alignment leaves camera
            # roll in the reconstruction and gives the arms different reaches.
            center = _scale(_add(joints["left_shoulder"], joints["right_shoulder"]), 0.5)
            lateral = _subtract(joints["right_shoulder"], joints["left_shoulder"])
            lateral = _normalize(_subtract(lateral, _scale(target_torso_axis, _dot(lateral, target_torso_axis))))
            target_lateral = _normalize(_cross(target_torso_axis, (0.0, 1.0, 0.0)))
            if lateral is not None and target_lateral is not None:
                if _dot(lateral, target_lateral) < 0:
                    target_lateral = _scale(target_lateral, -1)
                roll = math.atan2(_dot(target_torso_axis, _cross(lateral, target_lateral)),
                                  _dot(lateral, target_lateral))
                for name in upper_body_joints:
                    if name in joints:
                        point = joints[name]
                        joints[name] = _add(center, _rotate_vector_about_axis(
                            _subtract(point, center), axis=target_torso_axis, angle_radians=roll))
                        maximum_correction = max(maximum_correction, _distance(point, joints[name]))
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    refined = replace(clip, frames=frames)
    resulting_axes = [
        _normalize(_subtract(frame.joints["neck"], frame.joints["pelvis"]))
        for frame in refined.frames
    ]
    vertical_components = [abs(axis[1]) for axis in resulting_axes if axis is not None]
    return refined, {
        "applied": maximum_correction > 1e-8,
        "strategy": "contract_required_per_frame_rigid_upper_body_horizontal_alignment",
        "medianPitchCorrectionDegrees": median(pitch_corrections) if pitch_corrections else None,
        "maximumPitchCorrectionDegrees": max(pitch_corrections) if pitch_corrections else None,
        "maximumCorrection": maximum_correction,
        "medianAbsoluteTorsoVerticalComponentAfter": median(vertical_components) if vertical_components else None,
        "lowerBodyContactsPreserved": True,
        "shoulderPlaneLeveled": level_shoulders,
    }


def _preserve_reference_head_pose(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    force_spine_alignment: bool = False,
) -> tuple[MotionClip, dict[str, object]]:
    if "head" not in clip.joint_names or "neck" not in clip.joint_names:
        return clip, {"applied": False, "reason": "missing_head_or_neck"}
    frames: list[MotionFrame] = []
    total_correction = 0.0
    max_correction = 0.0
    samples = 0
    projected_samples = 0
    angular_limited_samples = 0
    previous_target_offset: Point3 | None = None
    previous_time_sec: float | None = None
    for frame, reference_frame in zip(clip.frames, reference_clip.frames):
        head = frame.joints.get("head")
        neck = frame.joints.get("neck")
        reference_head = reference_frame.joints.get("head")
        reference_neck = reference_frame.joints.get("neck")
        if head is None or neck is None or reference_head is None or reference_neck is None:
            frames.append(frame)
            continue
        reference_offset = _subtract(reference_head, reference_neck)
        if force_spine_alignment:
            upper_spine_base = frame.joints.get("spine3") or frame.joints.get("spine2")
            spine_axis = (
                _normalize(_subtract(neck, upper_spine_base))
                if upper_spine_base is not None
                else None
            )
            target_offset = (
                _scale(spine_axis, _length(reference_offset))
                if spine_axis is not None
                else reference_offset
            )
            projected = spine_axis is not None
        else:
            target_offset, projected = _plausible_head_offset(frame, reference_offset)
        if projected:
            projected_samples += 1
        if previous_target_offset is not None and previous_time_sec is not None:
            elapsed_seconds = max(frame.time_sec - previous_time_sec, 1.0 / max(clip.fps, 1.0))
            target_offset, angular_limited = _limit_vector_angular_change(
                previous_target_offset,
                target_offset,
                max_angle_radians=math.radians(180.0) * elapsed_seconds,
            )
            if angular_limited:
                angular_limited_samples += 1
        previous_target_offset = target_offset
        previous_time_sec = frame.time_sec
        target_head = _add(neck, target_offset)
        correction = _distance(head, target_head)
        if correction > 1e-6:
            total_correction += correction
            max_correction = max(max_correction, correction)
            samples += 1
        joints = dict(frame.joints)
        joints["head"] = target_head
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": samples > 0,
        "strategy": "restore_reference_neck_to_head_vector_with_spine_axis_sanity",
        "averageCorrection": total_correction / samples if samples else 0.0,
        "maxCorrection": max_correction,
        "spineAxisProjectedSamples": projected_samples,
        "angularLimitedSamples": angular_limited_samples,
        "maximumAngularSpeedDegreesPerSecond": 180.0,
        "forceSpineAlignment": force_spine_alignment,
    }


def _plausible_head_offset(
    frame: MotionFrame,
    reference_offset: Point3,
) -> tuple[Point3, bool]:
    length = _length(reference_offset)
    if length <= 1e-6:
        return reference_offset, False
    body_frame = _body_local_frame(frame)
    if body_frame is None:
        return reference_offset, False
    neck = frame.joints.get("neck")
    upper_spine_base = frame.joints.get("spine3") or frame.joints.get("spine2")
    upper_spine_axis = (
        _normalize(_subtract(neck, upper_spine_base))
        if neck is not None and upper_spine_base is not None
        else None
    )
    if upper_spine_axis is not None:
        projected_right = _subtract(
            body_frame.right,
            _scale(upper_spine_axis, _dot(body_frame.right, upper_spine_axis)),
        )
        projected_right = _normalize(projected_right)
        if projected_right is not None:
            forward = _normalize(_cross(projected_right, upper_spine_axis))
            if forward is not None:
                body_frame = BodyFrame(
                    origin=body_frame.origin,
                    right=projected_right,
                    up=upper_spine_axis,
                    forward=forward,
                )
    local = (
        _dot(reference_offset, body_frame.right),
        _dot(reference_offset, body_frame.up),
        _dot(reference_offset, body_frame.forward),
    )
    off_axis = math.hypot(local[0], local[2])
    along_spine = local[1]
    minimum_along_spine = length * math.cos(MAX_PLAUSIBLE_HEAD_TO_TORSO_ANGLE_RADIANS)
    maximum_off_axis = length * math.sin(MAX_PLAUSIBLE_HEAD_TO_TORSO_ANGLE_RADIANS)
    if along_spine >= minimum_along_spine and off_axis <= maximum_off_axis:
        return reference_offset, False
    corrected_along_spine = minimum_along_spine
    if off_axis <= 1e-6:
        corrected_local = (0.0, corrected_along_spine, 0.0)
    else:
        off_axis_scale = min(1.0, maximum_off_axis / off_axis)
        corrected_local = (
            local[0] * off_axis_scale,
            corrected_along_spine,
            local[2] * off_axis_scale,
        )
    corrected_world = _add(
        _scale(body_frame.right, corrected_local[0]),
        _add(
            _scale(body_frame.up, corrected_local[1]),
            _scale(body_frame.forward, corrected_local[2]),
        ),
    )
    corrected_direction = _normalize(corrected_world)
    if corrected_direction is None:
        return _scale(body_frame.up, length), True
    return _scale(corrected_direction, length), True


def _limit_vector_angular_change(
    previous: Point3,
    target: Point3,
    *,
    max_angle_radians: float,
) -> tuple[Point3, bool]:
    previous_length = _length(previous)
    target_length = _length(target)
    if previous_length <= 1e-6 or target_length <= 1e-6:
        return target, False
    previous_direction = _scale(previous, 1.0 / previous_length)
    target_direction = _scale(target, 1.0 / target_length)
    cosine = max(-1.0, min(1.0, _dot(previous_direction, target_direction)))
    angle = math.acos(cosine)
    if angle <= max_angle_radians or angle <= 1e-6:
        return target, False
    blend = max_angle_radians / angle
    sin_angle = math.sin(angle)
    if abs(sin_angle) <= 1e-6:
        blended_direction = _normalize(
            _add(
                _scale(previous_direction, 1.0 - blend),
                _scale(target_direction, blend),
            )
        )
    else:
        blended_direction = _add(
            _scale(previous_direction, math.sin((1.0 - blend) * angle) / sin_angle),
            _scale(target_direction, math.sin(blend * angle) / sin_angle),
        )
    if blended_direction is None:
        return target, False
    return _scale(blended_direction, target_length), True










def _dominant_chain_range(
    clip: MotionClip,
    anchors: tuple[str, ...],
    ends: tuple[str, ...],
) -> float:
    samples: list[Point3] = []
    for frame in clip.frames:
        anchor_points = [frame.joints[name] for name in anchors if name in frame.joints]
        end_points = [frame.joints[name] for name in ends if name in frame.joints]
        if not anchor_points or not end_points:
            continue
        samples.append(_subtract(_average_points(end_points), _average_points(anchor_points)))
    if len(samples) < 2:
        return 0.0
    center = _average_points(samples)
    return max(_distance(sample, center) for sample in samples) * 2.0




def _chain_motion_summary(clip: MotionClip) -> dict[str, float]:
    return {
        "torso": _joint_group_motion(clip, [joint for joint in TORSO_STABILITY_JOINTS if joint in clip.joint_names]),
        "leftArm": _joint_group_motion(clip, ["left_elbow", "left_wrist", "left_hand"]),
        "rightArm": _joint_group_motion(clip, ["right_elbow", "right_wrist", "right_hand"]),
        "leftLeg": _joint_group_motion(clip, ["left_knee", "left_ankle", "left_foot"]),
        "rightLeg": _joint_group_motion(clip, ["right_knee", "right_ankle", "right_foot"]),
        "head": _joint_group_motion(clip, ["head", "neck"]),
    }


def _chain_range_summary(clip: MotionClip) -> dict[str, float]:
    return {
        "torso": _joint_group_root_relative_range(
            clip,
            [joint for joint in TORSO_STABILITY_JOINTS if joint in clip.joint_names],
        ),
        "arms": max(
            _dominant_chain_range(clip, ("left_shoulder",), ("left_elbow", "left_wrist", "left_hand")),
            _dominant_chain_range(clip, ("right_shoulder",), ("right_elbow", "right_wrist", "right_hand")),
            _dominant_chain_range(
                clip,
                ("left_shoulder", "right_shoulder"),
                ("left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand"),
            ),
        ),
        "legs": max(
            _dominant_chain_range(clip, ("left_hip",), ("left_knee", "left_ankle", "left_foot")),
            _dominant_chain_range(clip, ("right_hip",), ("right_knee", "right_ankle", "right_foot")),
            _dominant_chain_range(
                clip,
                ("left_hip", "right_hip"),
                ("left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot", "right_foot"),
            ),
        ),
    }


def _preserve_non_torso_dominant_motion(
    clip: MotionClip,
    *,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    return clip, {
        "strategy": "source_preserving_non_torso_motion",
        "applied": False,
        "reason": "canonical_reconstruction_can_distort_source_motion",
        "dominantGroups": list(dominant_profile.get("dominantGroups", [])),
        "maxJointDisplacement": 0.0,
        "steps": [],
    }


def _refine_torso_dominant_motion_conservatively(
    clip: MotionClip,
    *,
    active_threshold: float,
    strongest_chain_motion: float,
    dominant_profile: dict[str, object],
    non_dominant_radius_scale: float,
    source_pose_payload: dict[str, Any] | None,
) -> tuple[MotionClip, dict[str, object]]:
    proposed, jitter_metadata = _suppress_low_magnitude_motion(
        clip,
        active_threshold=active_threshold,
        strongest_chain_motion=strongest_chain_motion,
        dominant_profile=dominant_profile,
    )
    refined, transaction = _accept_source_preserving_refinement_step(
        clip,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="low_magnitude_motion_suppression",
    )
    jitter_metadata["transaction"] = transaction
    before = refined
    proposed, spike_metadata = _suppress_temporal_spikes(refined, active_threshold=active_threshold)
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="isolated_temporal_spike_suppression",
    )
    spike_metadata["transaction"] = transaction
    before = refined
    proposed, target_constraint_metadata = _constrain_to_stabilized_ik_targets(
        refined,
        stabilized_target_clip=clip,
        dominant_profile=dominant_profile,
        non_dominant_radius_scale=non_dominant_radius_scale,
    )
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="stabilized_ik_target_constraint",
    )
    target_constraint_metadata["transaction"] = transaction
    # Hip-relative ankle travel is genuine articulation in squats, split
    # squats, step-ups, and many other planted-foot movements. Without an
    # authoritative support/contact trajectory this signal cannot distinguish
    # sliding from intended motion, so automatic structural cleanup must not
    # rewrite the leg from that heuristic alone.
    distal_leg_metadata: dict[str, object] = {
        "applied": False,
        "reason": "requires_authoritative_support_trajectory",
    }


    before = refined
    proposed, foot_axis_leg_metadata = _align_leg_motion_to_foot_axis(refined, reference_clip=clip)
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="foot_axis_leg_motion_alignment",
    )
    foot_axis_leg_metadata["transaction"] = transaction
    bilateral_modes = _bilateral_modes_from_dominant_profile(dominant_profile)
    before = refined
    proposed, soft_bilateral_metadata = _apply_soft_same_phase_leg_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="soft_same_phase_leg_symmetry",
    )
    soft_bilateral_metadata["transaction"] = transaction
    before = refined
    proposed, soft_arm_metadata = _apply_soft_same_phase_arm_symmetry(
        refined,
        bilateral_modes=bilateral_modes,
    )
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="soft_same_phase_arm_symmetry",
    )
    soft_arm_metadata["transaction"] = transaction
    dynamic_bone_length_joints = _range_dominant_chain_child_joints(dominant_profile)
    before = refined
    proposed, length_metadata = _preserve_reference_bone_lengths(
        refined,
        reference_clip=clip,
        dynamic_length_child_joints=dynamic_bone_length_joints,
    )
    refined, transaction = _accept_source_preserving_refinement_step(
        before,
        proposed,
        source_pose_payload=source_pose_payload,
        step_name="reference_bone_length_projection",
    )
    length_metadata["transaction"] = transaction
    return refined, {
        "strategy": "torso_dominant_conservative_cleanup",
        "bilateralModes": bilateral_modes,
        "lowMagnitudeSuppression": jitter_metadata,
        "temporalSpikes": spike_metadata,
        "stabilizedIkTargetConstraint": target_constraint_metadata,
        "distalLegSlidingStabilization": distal_leg_metadata,
        "footAxisLegAlignment": foot_axis_leg_metadata,
        "softBilateralSymmetry": soft_bilateral_metadata,
        "softArmSymmetry": soft_arm_metadata,
        "boneLengthProjection": length_metadata,
        "steps": [
            "torso_dominant_preserve_body_motion",
            "low_magnitude_motion_suppression",
            "isolated_temporal_spike_suppression",
            "stabilized_ik_target_constraint",
            "foot_axis_leg_motion_alignment",
            "soft_same_phase_leg_symmetry",
            "soft_same_phase_arm_symmetry",
            "reference_bone_length_projection",
        ],
    }


def _restore_rigid_bilateral_support(
    clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
    cleanup = metadata.get("cleanup")
    constraint = cleanup.get("supportSurfaceConstraint") if isinstance(cleanup, dict) else None
    knee_lock = constraint.get("kneeLock") if isinstance(constraint, dict) else None
    if isinstance(knee_lock, dict) and knee_lock.get("strategy") == "planted_support_joint_world_lock":
        anchors = knee_lock.get("anchors")
        distal_support = knee_lock.get("distalSupportVectors")
        distal_sides = (
            distal_support.get("sides")
            if isinstance(distal_support, dict)
            else None
        )
        if not isinstance(anchors, dict):
            return clip, {"applied": False, "reason": "invalid_planted_support_metadata"}
        frames: list[MotionFrame] = []
        maximum_correction = 0.0
        for frame in clip.frames:
            joints = dict(frame.joints)
            for joint_name, raw_anchor in anchors.items():
                if joint_name not in joints or not isinstance(raw_anchor, list) or len(raw_anchor) < 3:
                    continue
                anchor = tuple(float(value) for value in raw_anchor[:3])
                current = joints[joint_name]
                correction = _subtract(anchor, current)
                joints[joint_name] = anchor
                side = joint_name.removesuffix("_knee")
                side_vectors = distal_sides.get(side) if isinstance(distal_sides, dict) else None
                knee_to_ankle = (
                    side_vectors.get("kneeToAnkle")
                    if isinstance(side_vectors, dict)
                    else None
                )
                ankle_to_foot = (
                    side_vectors.get("ankleToFoot")
                    if isinstance(side_vectors, dict)
                    else None
                )
                ankle_name = f"{side}_ankle"
                foot_name = f"{side}_foot"
                if (
                    isinstance(knee_to_ankle, list)
                    and len(knee_to_ankle) >= 3
                    and isinstance(ankle_to_foot, list)
                    and len(ankle_to_foot) >= 3
                    and ankle_name in joints
                    and foot_name in joints
                ):
                    ankle = _add(anchor, tuple(float(value) for value in knee_to_ankle[:3]))
                    joints[ankle_name] = ankle
                    joints[foot_name] = _add(
                        ankle,
                        tuple(float(value) for value in ankle_to_foot[:3]),
                    )
                else:
                    for descendant_name in (ankle_name, foot_name):
                        if descendant_name in joints:
                            joints[descendant_name] = _add(joints[descendant_name], correction)
                maximum_correction = max(maximum_correction, _length(correction))
            frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
        return replace(clip, frames=frames), {
            "applied": True,
            "strategy": "exact_bilateral_support_anchor_restoration",
            "supportJoints": list(anchors),
            "maximumCorrection": maximum_correction,
        }
    if not isinstance(knee_lock, dict) or knee_lock.get("strategy") != "rigid_bilateral_support_midpoint_lock":
        return clip, {"applied": False, "reason": "no_rigid_bilateral_support_lock"}
    support_names = knee_lock.get("supportJoints")
    raw_anchor = knee_lock.get("pairAnchor")
    raw_direction = knee_lock.get("pairDirection")
    if (
        not isinstance(support_names, list)
        or len(support_names) != 2
        or not isinstance(raw_anchor, list)
        or len(raw_anchor) < 3
        or not isinstance(raw_direction, list)
        or len(raw_direction) < 3
    ):
        return clip, {"applied": False, "reason": "invalid_rigid_support_metadata"}
    left_name, right_name = (str(support_names[0]), str(support_names[1]))
    if left_name not in clip.joint_names or right_name not in clip.joint_names:
        return clip, {"applied": False, "reason": "rigid_support_joints_missing"}
    anchor = tuple(float(value) for value in raw_anchor[:3])
    target_direction = _normalize(tuple(float(value) for value in raw_direction[:3]))
    if target_direction is None:
        return clip, {"applied": False, "reason": "invalid_rigid_support_direction"}
    frames: list[MotionFrame] = []
    maximum_rotation_degrees = 0.0
    for frame in clip.frames:
        left = frame.joints[left_name]
        right = frame.joints[right_name]
        midpoint = _average_points([left, right])
        current_direction = _normalize(_subtract(left, right))
        if current_direction is None:
            frames.append(frame)
            continue
        axis = _normalize(_cross(current_direction, target_direction))
        angle = math.acos(max(-1.0, min(1.0, _dot(current_direction, target_direction))))
        maximum_rotation_degrees = max(maximum_rotation_degrees, math.degrees(angle))
        translation = _subtract(anchor, midpoint)
        joints: dict[str, Point3] = {}
        for name, point in frame.joints.items():
            relative = _subtract(point, midpoint)
            rotated = (
                _rotate_vector_about_axis(relative, axis=axis, angle_radians=angle)
                if axis is not None
                else relative
            )
            joints[name] = _add(_add(midpoint, rotated), translation)
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "strategy": "rigid_bilateral_support_pose_restoration",
        "supportJoints": [left_name, right_name],
        "maximumRotationDegrees": maximum_rotation_degrees,
        "preservesAllPairwiseDistances": True,
    }


def _stabilize_torso_dominant_distal_leg_sliding(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    side_configs: list[dict[str, object]] = []
    for side in ("left", "right"):
        hip = f"{side}_hip"
        knee = f"{side}_knee"
        ankle = f"{side}_ankle"
        foot = f"{side}_foot"
        required = (hip, knee, ankle)
        if any(joint not in clip.joint_names or joint not in reference_clip.joint_names for joint in required):
            continue
        knee_range = _joint_root_relative_vertical_range(reference_clip, knee, hip)
        ankle_range = _joint_root_relative_vertical_range(reference_clip, ankle, hip)
        foot_range = _joint_root_relative_vertical_range(reference_clip, foot, hip) if foot in reference_clip.joint_names else 0.0
        if knee_range > 0.08:
            continue
        if max(ankle_range, foot_range) < max(0.12, knee_range * 2.5):
            continue
        side_configs.append({
            "side": side,
            "hip": hip,
            "knee": knee,
            "ankle": ankle,
            "foot": foot if foot in clip.joint_names and foot in reference_clip.joint_names else None,
            "kneeRange": knee_range,
            "ankleRange": ankle_range,
            "footRange": foot_range,
            "hipToAnkle": _median_root_relative_offset(reference_clip, hip, ankle),
            "ankleToFoot": _median_root_relative_offset(reference_clip, ankle, foot) if foot in reference_clip.joint_names else None,
            "upperLen": _median_bone_length(reference_clip, hip, knee),
            "lowerLen": _median_bone_length(reference_clip, knee, ankle),
        })
    if not side_configs:
        return clip, {"applied": False, "reason": "no_distal_leg_sliding_detected"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        body_frame = _body_local_frame(frame)
        fallback_axis = body_frame.forward if body_frame is not None else (0.0, 0.0, 1.0)
        for config in side_configs:
            hip = str(config["hip"])
            knee = str(config["knee"])
            ankle = str(config["ankle"])
            foot = config.get("foot")
            if hip not in joints or knee not in joints or ankle not in joints:
                continue
            target_ankle = _add(joints[hip], config["hipToAnkle"])  # type: ignore[arg-type]
            solved_knee, solved_ankle = _solve_two_bone(
                root=joints[hip],
                current_mid=joints[knee],
                target_end=target_ankle,
                upper_len=float(config["upperLen"]),
                lower_len=float(config["lowerLen"]),
                fallback_axis=fallback_axis,
            )
            for joint_name, target in ((knee, solved_knee), (ankle, solved_ankle)):
                displacement = _distance(joints[joint_name], target)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[joint_name] = target
            if isinstance(foot, str) and foot in joints and config.get("ankleToFoot") is not None:
                target_foot = _add(joints[ankle], config["ankleToFoot"])  # type: ignore[arg-type]
                displacement = _distance(joints[foot], target_foot)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[foot] = target_foot
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "sides": side_configs,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "stable_hip_relative_ankle_foot_offsets_for_sliding_distal_leg",
    }


def _align_leg_motion_to_foot_axis(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
) -> tuple[MotionClip, dict[str, object]]:
    side_configs: list[dict[str, object]] = []
    for side in ("left", "right"):
        hip = f"{side}_hip"
        knee = f"{side}_knee"
        ankle = f"{side}_ankle"
        foot = f"{side}_foot"
        required = (hip, knee, ankle, foot)
        if any(joint not in clip.joint_names or joint not in reference_clip.joint_names for joint in required):
            continue
        leg_horizontal_range = max(
            _joint_root_relative_horizontal_range(reference_clip, knee, hip),
            _joint_root_relative_horizontal_range(reference_clip, ankle, hip),
            _joint_root_relative_horizontal_range(reference_clip, foot, hip),
        )
        if leg_horizontal_range > 0.09:
            continue
        foot_axis = _horizontal_axis(_median_root_relative_offset(reference_clip, ankle, foot))
        if foot_axis is None:
            continue
        side_configs.append({
            "side": side,
            "hip": hip,
            "knee": knee,
            "ankle": ankle,
            "foot": foot,
            "footAxis": foot_axis,
            "legHorizontalRange": leg_horizontal_range,
            "hipToKnee": _median_root_relative_offset(reference_clip, hip, knee),
            "hipToAnkle": _median_root_relative_offset(reference_clip, hip, ankle),
        })
    if not side_configs:
        return clip, {"applied": False, "reason": "no_valid_foot_axes"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        joints = dict(frame.joints)
        for config in side_configs:
            hip = str(config["hip"])
            foot_axis = config["footAxis"]  # type: ignore[assignment]
            if hip not in joints:
                continue
            for joint_name, baseline_key in ((str(config["knee"]), "hipToKnee"), (str(config["ankle"]), "hipToAnkle")):
                if joint_name not in joints:
                    continue
                baseline = config[baseline_key]  # type: ignore[assignment]
                current_offset = _subtract(joints[joint_name], joints[hip])
                residual = _subtract(current_offset, baseline)  # type: ignore[arg-type]
                forward_amount = _dot((residual[0], 0.0, residual[2]), foot_axis)  # type: ignore[arg-type]
                aligned_residual = (
                    foot_axis[0] * forward_amount,  # type: ignore[index]
                    residual[1],
                    foot_axis[2] * forward_amount,  # type: ignore[index]
                )
                target = _add(joints[hip], _add(baseline, aligned_residual))  # type: ignore[arg-type]
                displacement = _distance(joints[joint_name], target)
                if displacement > 1e-6:
                    total_displacement += displacement
                    max_displacement = max(max_displacement, displacement)
                    samples += 1
                joints[joint_name] = target
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": samples > 0,
        "sides": side_configs,
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "target": "knee_ankle_horizontal_motion_projected_onto_foot_forward_axis",
    }


def _horizontal_axis(axis: Point3) -> Point3 | None:
    return _normalize((axis[0], 0.0, axis[2]))


def _joint_root_relative_vertical_range(clip: MotionClip, joint_name: str, root_joint: str) -> float:
    values = [
        frame.joints[joint_name][1] - frame.joints[root_joint][1]
        for frame in clip.frames
        if joint_name in frame.joints and root_joint in frame.joints
    ]
    return max(values) - min(values) if values else 0.0


def _joint_axis_values(clip: MotionClip, joint_name: str, *, axis: int) -> list[float]:
    return [
        frame.joints[joint_name][axis]
        for frame in clip.frames
        if joint_name in frame.joints
    ]




def _joint_root_relative_horizontal_range(clip: MotionClip, joint_name: str, root_joint: str) -> float:
    offsets = [
        _subtract(frame.joints[joint_name], frame.joints[root_joint])
        for frame in clip.frames
        if joint_name in frame.joints and root_joint in frame.joints
    ]
    if not offsets:
        return 0.0
    return max(
        max(offset[0] for offset in offsets) - min(offset[0] for offset in offsets),
        max(offset[2] for offset in offsets) - min(offset[2] for offset in offsets),
    )


def _joint_group_root_relative_range(clip: MotionClip, joint_names: list[str]) -> float:
    root_joint = next((joint for joint in ROOT_VERTICAL_MOTION_JOINTS if joint in clip.joint_names), None)
    if root_joint is None:
        return 0.0
    max_range = 0.0
    for joint_name in joint_names:
        offsets = [
            _subtract(frame.joints[joint_name], frame.joints[root_joint])
            for frame in clip.frames
            if joint_name in frame.joints and root_joint in frame.joints
        ]
        if len(offsets) < 2:
            continue
        ranges = [
            max(offset[axis] for offset in offsets) - min(offset[axis] for offset in offsets)
            for axis in range(3)
        ]
        max_range = max(max_range, math.sqrt(sum(axis_range * axis_range for axis_range in ranges)))
    return max_range


def _median_root_relative_offset(clip: MotionClip, root_joint: str, joint_name: str) -> Point3:
    return _median_point([
        _subtract(frame.joints[joint_name], frame.joints[root_joint])
        for frame in clip.frames
        if root_joint in frame.joints and joint_name in frame.joints
    ])














































def _joint_group_motion(clip: MotionClip, joint_names: list[str]) -> float:
    available = [joint for joint in joint_names if joint in clip.joint_names]
    if not available or clip.frame_count < 2:
        return 0.0
    total = 0.0
    samples = 0
    for frame_index in range(1, clip.frame_count):
        previous = clip.frames[frame_index - 1].joints
        current = clip.frames[frame_index].joints
        for joint in available:
            total += _distance(previous[joint], current[joint])
            samples += 1
    return total / samples if samples else 0.0


def _suppress_low_magnitude_motion(
    clip: MotionClip,
    *,
    active_threshold: float,
    strongest_chain_motion: float,
    dominant_profile: dict[str, object],
) -> tuple[MotionClip, dict[str, object]]:
    joint_motion = {
        joint_name: _joint_group_motion(clip, [joint_name])
        for joint_name in clip.joint_names
    }
    non_dominant_threshold = max(active_threshold, strongest_chain_motion * NON_DOMINANT_CHAIN_RATIO)
    smoothable = {
        joint_name
        for joint_name, motion in joint_motion.items()
        if _should_suppress_joint_motion(
            joint_name,
            motion,
            active_threshold=active_threshold,
            non_dominant_threshold=non_dominant_threshold,
            dominant_profile=dominant_profile,
        )
    }
    smoothable -= _protected_dominant_chain_anchor_joints(dominant_profile)
    smoothable -= _never_suppress_anchor_joints()
    if not smoothable:
        return clip, {"applied": False, "reason": "no_low_magnitude_joints"}

    reference_offsets = _stable_joint_reference_offsets(clip, smoothable)
    reference_positions = _stable_joint_reference_positions(clip, smoothable)
    dominant_groups = set(dominant_profile.get("dominantGroups", []))

    frames: list[MotionFrame] = []
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        for joint_name in smoothable:
            points = [
                clip.frames[index].joints[joint_name]
                for index in range(max(0, frame_index - 2), min(clip.frame_count, frame_index + 3))
            ]
            averaged = _average_points(points)
            blend = _low_motion_suppression_blend(joint_motion[joint_name], active_threshold)
            stabilized = averaged
            joint_group = _joint_motion_group(joint_name)
            if joint_group is not None and joint_group not in dominant_groups and joint_name in reference_positions:
                stabilized = reference_positions[joint_name]
                blend = max(blend, 0.72)
            root_joint = _root_joint_for_stabilization(clip)
            if (
                (joint_group is None or joint_group in dominant_groups)
                and root_joint is not None
                and joint_name in reference_offsets
                and root_joint in frame.joints
            ):
                stabilized = _add(frame.joints[root_joint], reference_offsets[joint_name])
            joints[joint_name] = _limited_lerp_point(
                frame.joints[joint_name],
                stabilized,
                blend,
                MAX_SUPPRESSION_CORRECTION_METERS,
            )
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    refined = replace(clip, frames=frames)
    displacement = _average_joint_displacement(clip, refined, list(smoothable))
    return refined, {
        "applied": True,
        "suppressedJoints": sorted(smoothable),
        "jointMotion": joint_motion,
        "activeThreshold": active_threshold,
        "nonDominantThreshold": non_dominant_threshold,
        "averageDisplacement": displacement["average"],
        "maxDisplacement": displacement["max"],
    }


def _dominant_motion_profile(
    chain_motion: dict[str, float],
    strongest_chain_motion: float,
    *,
    chain_range: dict[str, float],
    body_height: float,
    active_threshold: float,
    dominant_chain_ratio: float,
) -> dict[str, object]:
    if strongest_chain_motion <= 1e-8:
        return {
            "dominantGroups": [],
            "groupMotion": {},
            "groupRange": chain_range,
            "rangeDominantGroups": [],
        }
    group_motion = {
        "torso": max(chain_motion.get("torso", 0.0), chain_motion.get("head", 0.0)),
        "arms": max(chain_motion.get("leftArm", 0.0), chain_motion.get("rightArm", 0.0)),
        "legs": max(chain_motion.get("leftLeg", 0.0), chain_motion.get("rightLeg", 0.0)),
    }
    motion_dominant_groups = {
        group_name
        for group_name, motion in group_motion.items()
        if (
            (motion >= active_threshold or motion >= strongest_chain_motion - 1e-9)
            and motion >= strongest_chain_motion * dominant_chain_ratio
        )
    }
    strongest_chain_range = max(chain_range.values(), default=0.0)
    range_threshold = max(
        DOMINANT_CHAIN_MIN_TOTAL_RANGE_METERS,
        body_height * DOMINANT_CHAIN_MIN_TOTAL_RANGE_BODY_RATIO if body_height > 1e-6 else 0.0,
        strongest_chain_range * DOMINANT_CHAIN_TOTAL_RANGE_RATIO,
    )
    range_dominant_groups = {
        group_name
        for group_name, total_range in chain_range.items()
        if total_range >= range_threshold
    }
    if (
        "arms" in motion_dominant_groups
        and "torso" not in motion_dominant_groups
        and group_motion["torso"] < active_threshold
        and chain_range.get("torso", 0.0) < chain_range.get("arms", 0.0) * 0.75
    ):
        range_dominant_groups.discard("torso")
    dominant_groups = sorted(motion_dominant_groups | range_dominant_groups)
    return {
        "dominantGroups": dominant_groups,
        "groupMotion": group_motion,
        "motionDominantGroups": sorted(motion_dominant_groups),
        "groupRange": chain_range,
        "rangeDominantGroups": sorted(range_dominant_groups),
        "rangeDominanceThreshold": range_threshold,
    }


def _should_suppress_joint_motion(
    joint_name: str,
    joint_motion: float,
    *,
    active_threshold: float,
    non_dominant_threshold: float,
    dominant_profile: dict[str, object],
) -> bool:
    joint_group = _joint_motion_group(joint_name)
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    range_dominant_groups = set(dominant_profile.get("rangeDominantGroups", []))
    if joint_group is not None and joint_group in dominant_groups and joint_group in range_dominant_groups:
        return False
    if joint_motion <= active_threshold:
        return True
    if joint_group is None:
        return False
    if joint_group not in dominant_groups and joint_motion <= non_dominant_threshold:
        return True
    return False


def _joint_motion_group(joint_name: str) -> str | None:
    if joint_name.startswith("left_elbow") or joint_name.startswith("right_elbow"):
        return "arms"
    if joint_name.startswith("left_wrist") or joint_name.startswith("right_wrist"):
        return "arms"
    if joint_name.startswith("left_hand") or joint_name.startswith("right_hand"):
        return "arms"
    if joint_name.startswith("left_knee") or joint_name.startswith("right_knee"):
        return "legs"
    if joint_name.startswith("left_ankle") or joint_name.startswith("right_ankle"):
        return "legs"
    if joint_name.startswith("left_foot") or joint_name.startswith("right_foot"):
        return "legs"
    if joint_name in TORSO_STABILITY_JOINTS or joint_name in ("pelvis", "left_hip", "right_hip"):
        return "torso"
    return None


def _protected_dominant_chain_anchor_joints(dominant_profile: dict[str, object]) -> set[str]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    protected: set[str] = set()
    if "arms" in dominant_groups:
        protected.update((
            "neck",
            "left_collar",
            "right_collar",
            "left_shoulder",
            "right_shoulder",
        ))
    if "legs" in dominant_groups:
        protected.update((
            "pelvis",
            "left_hip",
            "right_hip",
        ))
    return protected


def _range_dominant_chain_child_joints(dominant_profile: dict[str, object]) -> set[str]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    range_dominant_groups = set(dominant_profile.get("rangeDominantGroups", []))
    joints: set[str] = set()
    if "arms" in dominant_groups and "arms" in range_dominant_groups:
        joints.update((
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hand",
            "right_hand",
        ))
    if "legs" in dominant_groups and "legs" in range_dominant_groups:
        joints.update((
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
            "left_foot",
            "right_foot",
        ))
    return joints


def _never_suppress_anchor_joints() -> set[str]:
    return {
        "pelvis",
        "left_hip",
        "right_hip",
        "spine1",
        "spine2",
        "spine3",
    }
















def _stable_joint_reference_offsets(
    clip: MotionClip,
    joint_names: set[str],
) -> dict[str, Point3]:
    root_joint = _root_joint_for_stabilization(clip)
    if root_joint is None:
        return {}
    offsets: dict[str, Point3] = {}
    for joint_name in joint_names:
        if joint_name == root_joint:
            continue
        offsets[joint_name] = _median_point([
            _subtract(frame.joints[joint_name], frame.joints[root_joint])
            for frame in clip.frames
            if joint_name in frame.joints and root_joint in frame.joints
        ])
    return offsets


def _stable_joint_reference_positions(
    clip: MotionClip,
    joint_names: set[str],
) -> dict[str, Point3]:
    return {
        joint_name: _median_point([
            frame.joints[joint_name]
            for frame in clip.frames
            if joint_name in frame.joints
        ])
        for joint_name in joint_names
    }


def _root_joint_for_stabilization(clip: MotionClip) -> str | None:
    for candidate in ("pelvis", "hips", "root"):
        if candidate in clip.joint_names:
            return candidate
    return None


def _low_motion_suppression_blend(joint_motion: float, active_threshold: float) -> float:
    if active_threshold <= 1e-8:
        return 0.0
    ratio = min(max(joint_motion / active_threshold, 0.0), 1.0)
    return 0.85 - ratio * 0.45






def _apply_soft_same_phase_leg_symmetry(
    clip: MotionClip,
    *,
    bilateral_modes: dict[str, dict[str, object]],
) -> tuple[MotionClip, dict[str, object]]:
    return _apply_soft_same_phase_pair_symmetry(
        clip,
        mode=bilateral_modes.get("legs"),
        group_name="legs",
        pairs=(
            ("left_knee", "right_knee"),
            ("left_ankle", "right_ankle"),
            ("left_foot", "right_foot"),
        ),
        anchor_joints=("left_hip", "right_hip"),
        minimum_blend=SOFT_LEG_SYMMETRY_MIN_BLEND,
        maximum_blend=SOFT_LEG_SYMMETRY_MAX_BLEND,
        blend_scale=SOFT_LEG_SYMMETRY_BLEND_SCALE,
        max_correction=SOFT_LEG_SYMMETRY_MAX_CORRECTION_METERS,
    )


def _apply_soft_same_phase_arm_symmetry(
    clip: MotionClip,
    *,
    bilateral_modes: dict[str, dict[str, object]],
) -> tuple[MotionClip, dict[str, object]]:
    return _apply_soft_same_phase_pair_symmetry(
        clip,
        mode=bilateral_modes.get("arms"),
        group_name="arms",
        pairs=(
            ("left_elbow", "right_elbow"),
            ("left_wrist", "right_wrist"),
            ("left_hand", "right_hand"),
        ),
        anchor_joints=("left_shoulder", "right_shoulder"),
        minimum_blend=SOFT_ARM_SYMMETRY_MIN_BLEND,
        maximum_blend=SOFT_ARM_SYMMETRY_MAX_BLEND,
        blend_scale=SOFT_ARM_SYMMETRY_BLEND_SCALE,
        max_correction=SOFT_ARM_SYMMETRY_MAX_CORRECTION_METERS,
    )


def _apply_soft_same_phase_pair_symmetry(
    clip: MotionClip,
    *,
    mode: dict[str, object] | None,
    group_name: str,
    pairs: tuple[tuple[str, str], ...],
    anchor_joints: tuple[str, str],
    minimum_blend: float,
    maximum_blend: float,
    blend_scale: float,
    max_correction: float,
) -> tuple[MotionClip, dict[str, object]]:
    mode_key = f"{group_name}Mode"
    if not isinstance(mode, dict) or mode.get("mode") != "same_phase_symmetric":
        return clip, {
            "applied": False,
            "reason": f"{group_name}_not_same_phase_symmetric",
            mode_key: mode,
        }
    required = (*anchor_joints, *[joint for pair in pairs for joint in pair])
    if any(joint not in clip.joint_names for joint in required):
        return clip, {
            "applied": False,
            "reason": f"missing_{group_name}_joints",
            mode_key: mode,
        }
    mode_strength = _optional_float(mode.get("symmetryStrength"))
    if mode_strength is None:
        mode_strength = 0.50
    blend = min(
        maximum_blend,
        max(minimum_blend, mode_strength * blend_scale),
    )
    motion_driven = mode.get("motionDrivenPoseSymmetryAcceptance")
    exact_motion_evidence = (
        isinstance(motion_driven, dict)
        and motion_driven.get("accepted") is True
    )
    if exact_motion_evidence:
        blend = 1.0
        max_correction = math.inf
    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            frames.append(frame)
            continue
        targets = _symmetric_pair_targets(
            frame,
            body_frame=body_frame,
            pairs=pairs,
        )
        if not targets:
            frames.append(frame)
            continue
        joints = dict(frame.joints)
        for joint_name, target in targets.items():
            current = joints.get(joint_name)
            if current is None:
                continue
            updated = _limited_lerp_point(
                current,
                target,
                blend,
                max_correction,
            )
            displacement = _distance(current, updated)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[joint_name] = updated
        # Mirroring points independently can stretch a chain and trigger the
        # structural rollback, discarding the useful symmetry correction. Walk
        # each side from its fixed anchor and project every corrected segment
        # back to that frame's original length.
        if group_name == "arms":
            parent_pair = anchor_joints
            for child_pair in pairs:
                source_lengths = [
                    _distance(frame.joints[parent_pair[side]], frame.joints[child_pair[side]])
                    for side in range(2)
                ]
                # Coordinate unit directions, not absolute endpoints: differing
                # limb lengths must not reintroduce different joint angles.
                directions = [
                    _normalize(_subtract(frame.joints[child_pair[side]], frame.joints[parent_pair[side]]))
                    for side in range(2)
                ]
                if any(direction is None for direction in directions):
                    parent_pair = child_pair
                    continue
                left, right = directions
                mirrored_right = _subtract(right, _scale(body_frame.right, 2 * _dot(right, body_frame.right)))
                shared_left = _normalize(_add(left, mirrored_right))
                if shared_left is None:
                    parent_pair = child_pair
                    continue
                shared_right = _subtract(shared_left, _scale(body_frame.right, 2 * _dot(shared_left, body_frame.right)))
                for side, shared in enumerate((shared_left, shared_right)):
                    direction = _normalize(_add(_scale(directions[side], 1 - blend), _scale(shared, blend)))
                    if direction is not None:
                        joints[child_pair[side]] = _add(
                            joints[parent_pair[side]], _scale(direction, source_lengths[side]),
                        )
                parent_pair = child_pair
            # The directional chain solve can amplify a distal correction.
            # Retain the original frame when it exceeds the authorized bound.
            if any(_distance(frame.joints[name], joints[name]) > max_correction + 1e-9
                   for pair in pairs for name in pair):
                joints = dict(frame.joints)
        elif group_name == "legs" and exact_motion_evidence:
            parent_pair = anchor_joints
            for child_pair in pairs:
                source_lengths = [
                    _distance(frame.joints[parent_pair[side]], frame.joints[child_pair[side]])
                    for side in range(2)
                ]
                shared_length = sum(source_lengths) * 0.5
                for side in range(2):
                    parent_name = parent_pair[side]
                    child_name = child_pair[side]
                    direction = _normalize(_subtract(joints[child_name], joints[parent_name]))
                    if direction is not None and shared_length > 1e-9:
                        joints[child_name] = _add(
                            joints[parent_name],
                            _scale(direction, shared_length),
                        )
                parent_pair = child_pair
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    if samples == 0:
        return clip, {
            "applied": False,
            "reason": f"no_{group_name}_symmetry_correction_needed",
            mode_key: mode,
            "blend": blend,
        }
    refined = replace(clip, frames=frames)
    displacement = _average_joint_displacement(
        clip,
        refined,
        [joint for pair in pairs for joint in pair],
    )
    return refined, {
        "applied": True,
        "groups": [group_name],
        "target": f"soft_body_local_mirrored_{group_name}_pairs",
        "blend": blend,
        "maxCorrection": "unbounded_by_motion_evidence" if math.isinf(max_correction) else max_correction,
        "exactMotionEvidence": exact_motion_evidence,
        "averageDisplacement": displacement["average"],
        "maxDisplacement": displacement["max"],
        "sampleAverageDisplacement": total_displacement / samples,
        "sampleMaxDisplacement": max_displacement,
        mode_key: mode,
    }


def _average_joint_displacement(
    before: MotionClip,
    after: MotionClip,
    joint_names: list[str],
) -> dict[str, float]:
    total = 0.0
    maximum = 0.0
    count = 0
    for before_frame, after_frame in zip(before.frames, after.frames):
        for joint_name in joint_names:
            if joint_name not in before_frame.joints or joint_name not in after_frame.joints:
                continue
            displacement = _distance(before_frame.joints[joint_name], after_frame.joints[joint_name])
            total += displacement
            maximum = max(maximum, displacement)
            count += 1
    return {
        "average": total / count if count else 0.0,
        "max": maximum,
    }


def _suppress_temporal_spikes(
    clip: MotionClip,
    *,
    active_threshold: float,
) -> tuple[MotionClip, dict[str, object]]:
    if clip.frame_count < 3:
        return clip, {"applied": False, "reason": "too_few_frames"}
    spike_threshold = max(0.055, active_threshold * 3.0)
    frames = [MotionFrame(time_sec=frame.time_sec, joints=dict(frame.joints)) for frame in clip.frames]
    corrections: list[dict[str, object]] = []
    for _ in range(3):
        pass_corrections = 0
        for frame_index in range(1, clip.frame_count - 1):
            previous = frames[frame_index - 1].joints
            current = frames[frame_index].joints
            following = frames[frame_index + 1].joints
            for joint_name in clip.joint_names:
                if joint_name not in previous or joint_name not in current or joint_name not in following:
                    continue
                midpoint = _average_points([previous[joint_name], following[joint_name]])
                deviation = _distance(current[joint_name], midpoint)
                if deviation <= spike_threshold:
                    continue
                current[joint_name] = _lerp_point(current[joint_name], midpoint, 0.86)
                pass_corrections += 1
                corrections.append({
                    "frameIndex": frame_index,
                    "jointName": joint_name,
                    "deviation": deviation,
                })
        if pass_corrections == 0:
            break
    validator_corrections = _suppress_validator_velocity_spikes(frames, clip.joint_names)
    corrections.extend(validator_corrections)
    if not corrections:
        return clip, {
            "applied": False,
            "reason": "no_isolated_spikes",
            "threshold": spike_threshold,
        }
    return replace(clip, frames=frames), {
        "applied": True,
        "threshold": spike_threshold,
        "correctionCount": len(corrections),
        "maxDeviation": max(
            (float(item["deviation"]) for item in corrections if "deviation" in item),
            default=0.0,
        ),
        "correctedJoints": sorted({str(item["jointName"]) for item in corrections}),
        "validatorAlignedCorrectionCount": len(validator_corrections),
    }


def _suppress_validator_velocity_spikes(
    frames: list[MotionFrame],
    joint_names: tuple[str, ...],
) -> list[dict[str, object]]:
    """Repair the same root-relative discontinuities rejected downstream.

    The older midpoint-deviation pass detects isolated positional outliers, but
    the validator measures frame-to-frame distal velocity relative to the root.
    A sustained offset can therefore fail validation without looking like a
    midpoint outlier. Keep this detector aligned with that actual failure
    definition and interpolate only the offending sample.
    """
    root_joint = next(
        (name for name in ("pelvis", "hips", "root") if name in joint_names),
        None,
    )
    if root_joint is None or len(frames) < 3:
        return []
    distal_joints = tuple(
        name
        for name in joint_names
        if any(token in name.lower() for token in ("elbow", "wrist", "hand", "knee", "ankle", "foot"))
    )
    corrections: list[dict[str, object]] = []
    for _ in range(4):
        frame_heights = []
        for frame in frames:
            if frame.joints:
                y_values = [point[1] for point in frame.joints.values()]
                frame_heights.append(max(y_values) - min(y_values))
        body_height = median(frame_heights) if frame_heights else 0.0
        if body_height <= 1e-6:
            break
        pass_corrections = 0
        for joint_name in distal_joints:
            relative_points = []
            if any(joint_name not in frame.joints or root_joint not in frame.joints for frame in frames):
                continue
            for frame in frames:
                relative_points.append(_subtract(frame.joints[joint_name], frame.joints[root_joint]))
            steps = [
                _distance(relative_points[index], relative_points[index - 1])
                for index in range(1, len(relative_points))
            ]
            positive_steps = [step for step in steps if step > 1e-7]
            if len(positive_steps) < 2:
                continue
            median_step = median(positive_steps)
            offending_indices = [
                index
                for index, step in enumerate(steps, start=1)
                if step / max(median_step, 1e-7) >= DISTAL_STEP_SPIKE_RATIO
                and step / body_height >= DISTAL_STEP_BODY_RATIO
            ]
            for frame_index in offending_indices:
                if frame_index >= len(frames) - 1:
                    continue
                previous_relative = relative_points[frame_index - 1]
                following_relative = relative_points[frame_index + 1]
                repaired_relative = _average_points([previous_relative, following_relative])
                root_point = frames[frame_index].joints[root_joint]
                frames[frame_index].joints[joint_name] = _add(root_point, repaired_relative)
                corrections.append(
                    {
                        "frameIndex": frame_index,
                        "jointName": joint_name,
                        "reason": "validator_root_relative_velocity_spike",
                    }
                )
                pass_corrections += 1
        if pass_corrections == 0:
            break
    return corrections


def _constrain_to_stabilized_ik_targets(
    clip: MotionClip,
    *,
    stabilized_target_clip: MotionClip,
    dominant_profile: dict[str, object],
    non_dominant_radius_scale: float,
) -> tuple[MotionClip, dict[str, object]]:
    dominant_groups = set(dominant_profile.get("dominantGroups", []))
    frames: list[MotionFrame] = []
    constrained_joints: set[str] = set()
    total_pullback = 0.0
    max_pullback = 0.0
    samples = 0
    for frame, target_frame in zip(clip.frames, stabilized_target_clip.frames):
        joints = dict(frame.joints)
        for joint_name, point in frame.joints.items():
            target = target_frame.joints.get(joint_name)
            if target is None:
                continue
            max_distance = _original_target_radius(
                joint_name,
                dominant_groups,
                non_dominant_radius_scale=non_dominant_radius_scale,
            )
            delta = _subtract(point, target)
            distance = _length(delta)
            if distance <= max_distance or distance <= 1e-8:
                continue
            constrained = _add(target, _scale(delta, max_distance / distance))
            pullback = _distance(point, constrained)
            joints[joint_name] = constrained
            constrained_joints.add(joint_name)
            total_pullback += pullback
            max_pullback = max(max_pullback, pullback)
            samples += 1
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": bool(constrained_joints),
        "target": "stabilized_ik_target_skeleton",
        "constrainedJoints": sorted(constrained_joints),
        "averagePullback": total_pullback / samples if samples else 0.0,
        "maxPullback": max_pullback,
        "radii": {
            "anchor": 0.018,
            "dominant": 0.055,
            "nonDominant": 0.04,
        },
        "nonDominantRadiusScale": non_dominant_radius_scale,
    }


def _original_target_radius(
    joint_name: str,
    dominant_groups: set[str],
    *,
    non_dominant_radius_scale: float,
) -> float:
    if joint_name in _never_suppress_anchor_joints() or joint_name in TORSO_STABILITY_JOINTS:
        return 0.008 * non_dominant_radius_scale
    joint_group = _joint_motion_group(joint_name)
    if joint_group in dominant_groups:
        return 0.025
    return 0.012 * non_dominant_radius_scale














def _axis_angle_degrees(left: Point3, right: Point3) -> float:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if left_normalized is None or right_normalized is None:
        return 0.0
    alignment = max(-1.0, min(1.0, _dot(left_normalized, right_normalized)))
    angle = math.degrees(math.acos(alignment))
    return min(angle, 180.0 - angle)
















def _dominant_bilateral_motion_modes(reference_clip: MotionClip, dominant_groups: set[str]) -> dict[str, dict[str, object]]:
    modes: dict[str, dict[str, object]] = {}
    if "arms" in dominant_groups:
        modes["arms"] = _bilateral_motion_mode(
            reference_clip,
            group_name="arms",
            left_anchor="left_shoulder",
            right_anchor="right_shoulder",
            left_end="left_wrist",
            right_end="right_wrist",
            left_joints=("left_elbow", "left_wrist", "left_hand"),
            right_joints=("right_elbow", "right_wrist", "right_hand"),
        )
    if "legs" in dominant_groups:
        modes["legs"] = _bilateral_motion_mode(
            reference_clip,
            group_name="legs",
            left_anchor="left_hip",
            right_anchor="right_hip",
            left_end="left_ankle",
            right_end="right_ankle",
            left_joints=("left_knee", "left_ankle", "left_foot"),
            right_joints=("right_knee", "right_ankle", "right_foot"),
        )
    return modes


def _bilateral_modes_from_dominant_profile(dominant_profile: dict[str, object]) -> dict[str, dict[str, object]]:
    modes = dominant_profile.get("bilateralModes")
    if not isinstance(modes, dict):
        return {}
    return {
        str(group_name): dict(mode)
        for group_name, mode in modes.items()
        if isinstance(mode, dict)
    }


def _bilateral_motion_mode(
    clip: MotionClip,
    *,
    group_name: str,
    left_anchor: str,
    right_anchor: str,
    left_end: str,
    right_end: str,
    left_joints: tuple[str, ...],
    right_joints: tuple[str, ...],
) -> dict[str, object]:
    required = (left_anchor, right_anchor, left_end, right_end, *left_joints, *right_joints)
    if any(joint not in clip.joint_names for joint in required):
        return {"group": group_name, "mode": "unavailable", "reason": "missing_joints"}
    left_motion = _joint_group_motion(clip, list(left_joints))
    right_motion = _joint_group_motion(clip, list(right_joints))
    ratio = min(left_motion, right_motion) / max(max(left_motion, right_motion), 1e-8)
    correlation = _mirrored_chain_motion_correlation(clip, left_end=left_end, right_end=right_end)
    pose_symmetry = _mirrored_pose_symmetry(
        clip,
        joint_pairs=tuple(zip(left_joints, right_joints)),
    )
    motion_driven_pose_acceptance = _motion_driven_pose_symmetry_acceptance(
        group_name=group_name,
        motion_ratio=ratio,
        correlation=correlation,
        pose_symmetry=pose_symmetry,
    )
    pose_symmetric = bool(pose_symmetry.get("eligible")) or bool(motion_driven_pose_acceptance.get("accepted"))
    motion_symmetric = ratio >= SYMMETRY_MIN_RATIO and correlation >= max(0.80, SYMMETRY_MIN_CORRELATION)
    same_phase = motion_symmetric and pose_symmetric
    if same_phase:
        mode = "same_phase_symmetric"
    elif ratio >= SYMMETRY_MIN_RATIO:
        mode = "balanced_unsymmetrized"
    else:
        mode = "unilateral_unsymmetrized"
    symmetry_strength = 0.0
    if same_phase:
        asymmetry = max(0.0, 1.0 - ratio)
        strength_floor = 1.0 if group_name == "arms" else 0.48
        strength_base = 1.0 if group_name == "arms" else 0.50
        strength_ceiling = 1.0 if group_name == "arms" else 0.72
        symmetry_strength = min(strength_ceiling, max(strength_floor, strength_base + asymmetry * 1.5))
    return {
        "group": group_name,
        "mode": mode,
        "samePhase": same_phase,
        "leftMotion": left_motion,
        "rightMotion": right_motion,
        "motionRatio": ratio,
        "correlation": correlation,
        "motionSymmetric": motion_symmetric,
        "poseSymmetry": pose_symmetry,
        "motionDrivenPoseSymmetryAcceptance": motion_driven_pose_acceptance,
        "symmetryStrength": symmetry_strength,
    }


def _motion_driven_pose_symmetry_acceptance(
    *,
    group_name: str,
    motion_ratio: float,
    correlation: float,
    pose_symmetry: dict[str, object],
) -> dict[str, object]:
    if motion_ratio < ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO:
        return {
            "accepted": False,
            "reason": f"{group_name}_motion_ratio_too_low",
            "minMotionRatio": ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO,
        }
    if correlation < ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION:
        return {
            "accepted": False,
            "reason": f"{group_name}_motion_correlation_too_low",
            "minCorrelation": ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION,
        }
    median_error = _optional_float(pose_symmetry.get("medianErrorBodyRatio"))
    max_error = _optional_float(pose_symmetry.get("maxErrorBodyRatio"))
    if median_error is None or max_error is None:
        return {"accepted": False, "reason": "missing_pose_error_metrics"}
    accepted = (
        median_error <= ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO
        and max_error <= ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO
    )
    return {
        "accepted": accepted,
        "reason": f"same_phase_{group_name}_motion_overrides_moderate_pose_asymmetry"
        if accepted
        else f"{group_name}_pose_asymmetry_too_large",
        "medianErrorBodyRatio": median_error,
        "maxErrorBodyRatio": max_error,
        "maxMedianErrorBodyRatio": ARM_MOTION_DRIVEN_SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO,
        "maxAllowedErrorBodyRatio": ARM_MOTION_DRIVEN_SYMMETRY_MAX_POSE_ERROR_BODY_RATIO,
        "minMotionRatio": ARM_MOTION_DRIVEN_SYMMETRY_MIN_RATIO,
        "minCorrelation": ARM_MOTION_DRIVEN_SYMMETRY_MIN_CORRELATION,
    }


def _mirrored_pose_symmetry(
    clip: MotionClip,
    *,
    joint_pairs: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    if clip.frame_count == 0:
        return {
            "eligible": False,
            "reason": "empty_clip",
            "sampleCount": 0,
        }
    body_height = _median_body_height(clip)
    if body_height <= 1e-6:
        return {
            "eligible": False,
            "reason": "invalid_body_height",
            "sampleCount": 0,
            "bodyHeight": body_height,
        }
    errors: list[float] = []
    per_pair_errors: dict[str, list[float]] = {
        f"{left}:{right}": []
        for left, right in joint_pairs
    }
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            continue
        for left_joint, right_joint in joint_pairs:
            left_point = frame.joints.get(left_joint)
            right_point = frame.joints.get(right_joint)
            if left_point is None or right_point is None:
                continue
            left_local = _to_local(left_point, body_frame, body_frame.origin)
            right_local = _to_local(right_point, body_frame, body_frame.origin)
            mirrored_left = (-left_local[0], left_local[1], left_local[2])
            error_ratio = _distance(mirrored_left, right_local) / body_height
            errors.append(error_ratio)
            per_pair_errors[f"{left_joint}:{right_joint}"].append(error_ratio)
    if not errors:
        return {
            "eligible": False,
            "reason": "no_pose_samples",
            "sampleCount": 0,
            "bodyHeight": body_height,
        }
    median_error = median(errors)
    max_error = max(errors)
    eligible = (
        median_error <= SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO
        and max_error <= SYMMETRY_MAX_POSE_ERROR_BODY_RATIO
    )
    pair_payload = {
        pair_name: {
            "medianErrorBodyRatio": median(pair_errors),
            "maxErrorBodyRatio": max(pair_errors),
            "sampleCount": len(pair_errors),
        }
        for pair_name, pair_errors in per_pair_errors.items()
        if pair_errors
    }
    return {
        "eligible": eligible,
        "reason": "mirrored_pose_within_threshold" if eligible else "mirrored_pose_error_too_large",
        "bodyHeight": body_height,
        "sampleCount": len(errors),
        "medianErrorBodyRatio": median_error,
        "maxErrorBodyRatio": max_error,
        "maxMedianErrorBodyRatio": SYMMETRY_MAX_MEDIAN_POSE_ERROR_BODY_RATIO,
        "maxAllowedErrorBodyRatio": SYMMETRY_MAX_POSE_ERROR_BODY_RATIO,
        "jointPairs": pair_payload,
    }


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None












def _preserve_reference_bone_lengths(
    clip: MotionClip,
    *,
    reference_clip: MotionClip,
    dynamic_length_child_joints: set[str] | None = None,
    excluded_child_joints: set[str] | None = None,
) -> tuple[MotionClip, dict[str, object]]:
    excluded_joints = set(excluded_child_joints or set())
    reference_lengths = {
        (parent, child): _median_bone_length(reference_clip, parent, child)
        for parent, child in STRUCTURAL_BONES
        if parent in reference_clip.joint_names and child in reference_clip.joint_names
        and child not in excluded_joints
    }
    if not reference_lengths:
        return clip, {"applied": False, "reason": "no_reference_bones"}

    frames: list[MotionFrame] = []
    total_displacement = 0.0
    max_displacement = 0.0
    samples = 0
    dynamic_joints = set(dynamic_length_child_joints or set())
    dynamic_samples = 0
    for frame_index, frame in enumerate(clip.frames):
        joints = dict(frame.joints)
        reference_frame = reference_clip.frames[min(frame_index, reference_clip.frame_count - 1)]
        for (parent, child), target_length in reference_lengths.items():
            if parent not in joints or child not in joints:
                continue
            if (
                child in dynamic_joints
                and parent in reference_frame.joints
                and child in reference_frame.joints
            ):
                target_length = _distance(reference_frame.joints[parent], reference_frame.joints[child])
                dynamic_samples += 1
            direction = _subtract(joints[child], joints[parent])
            current_length = _length(direction)
            if current_length <= 1e-8:
                continue
            projected = _add(joints[parent], _scale(direction, target_length / current_length))
            displacement = _distance(joints[child], projected)
            if displacement > 1e-6:
                total_displacement += displacement
                max_displacement = max(max_displacement, displacement)
                samples += 1
            joints[child] = projected
        frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    return replace(clip, frames=frames), {
        "applied": True,
        "boneCount": len(reference_lengths),
        "averageDisplacement": total_displacement / samples if samples else 0.0,
        "maxDisplacement": max_displacement,
        "dynamicLengthChildJoints": sorted(dynamic_joints),
        "dynamicLengthSampleCount": dynamic_samples,
        "excludedChildJoints": sorted(excluded_joints),
    }








def _mirrored_chain_motion_correlation(clip: MotionClip, *, left_end: str, right_end: str) -> float:
    left_values: list[float] = []
    right_values: list[float] = []
    canonical_left: list[Point3] = []
    canonical_right: list[Point3] = []
    for frame in clip.frames:
        body_frame = _body_local_frame(frame)
        if body_frame is None:
            continue
        origin = body_frame.origin
        left_local = _to_local(frame.joints[left_end], body_frame, origin)
        right_local = _to_local(frame.joints[right_end], body_frame, origin)
        canonical_left.append((-left_local[0], left_local[1], left_local[2]))
        canonical_right.append((right_local[0], right_local[1], right_local[2]))
    if len(canonical_left) < 3:
        return 0.0
    left_center = _median_point(canonical_left)
    right_center = _median_point(canonical_right)
    for left, right in zip(canonical_left, canonical_right):
        left_delta = _subtract(left, left_center)
        right_delta = _subtract(right, right_center)
        left_values.extend((left_delta[1], left_delta[2]))
        right_values.extend((right_delta[1], right_delta[2]))
    return _pearson(left_values, right_values)


def _symmetric_pair_targets(
    frame: MotionFrame,
    *,
    body_frame: "BodyFrame",
    pairs: tuple[tuple[str, str], ...],
) -> dict[str, Point3]:
    targets: dict[str, Point3] = {}
    for left_joint, right_joint in pairs:
        if left_joint not in frame.joints or right_joint not in frame.joints:
            continue
        left_local = _to_local(frame.joints[left_joint], body_frame, body_frame.origin)
        right_local = _to_local(frame.joints[right_joint], body_frame, body_frame.origin)
        half_width = (abs(left_local[0]) + abs(right_local[0])) * 0.5
        shared_y = (left_local[1] + right_local[1]) * 0.5
        shared_z = (left_local[2] + right_local[2]) * 0.5
        targets[left_joint] = _from_local((-half_width, shared_y, shared_z), body_frame, body_frame.origin)
        targets[right_joint] = _from_local((half_width, shared_y, shared_z), body_frame, body_frame.origin)
    return targets


def _stabilize_rigid_paired_hand_spacing(
    clip: MotionClip,
    *, supported_bilateral: bool = False,
) -> tuple[MotionClip, dict[str, object]]:
    """Preserve the fixed endpoint transform implied by a rigid two-hand implement."""
    required = {
        "left_shoulder", "left_elbow", "left_wrist", "left_hand",
        "right_shoulder", "right_elbow", "right_wrist", "right_hand",
    }
    if not required.issubset(clip.joint_names) or clip.frame_count < 3:
        return clip, {"applied": False, "reason": "paired_arm_chain_unavailable"}
    spacing = [
        _distance(frame.joints["left_hand"], frame.joints["right_hand"])
        for frame in clip.frames
    ]
    target_spacing = median(spacing)
    if target_spacing <= 1e-6:
        return clip, {"applied": False, "reason": "paired_hand_spacing_degenerate"}
    hand_axes = [
        _subtract(frame.joints["right_hand"], frame.joints["left_hand"])
        for frame in clip.frames
    ]
    median_axis = _median_point(hand_axes)
    body_frames = [_body_local_frame(frame) for frame in clip.frames]
    local_axes = [(_dot(axis, body.right), _dot(axis, body.up), _dot(axis, body.forward))
                  for axis, body in zip(hand_axes, body_frames) if body is not None]
    local_axis = _normalize(_median_point(local_axes)) if len(local_axes) == len(clip.frames) else None
    # Keep the shared implement orientation in the moving body frame. A fixed
    # world-space axis incorrectly turns a legitimate body turn into arm twist.
    target_axis = _normalize(median_axis)
    if target_axis is None and local_axis is not None:
        target_axis = _normalize(hand_axes[0])
    if target_axis is None:
        return clip, {"applied": False, "reason": "paired_hand_axis_degenerate"}
    spacing_range_before = max(spacing) - min(spacing)
    corrected_frames: list[MotionFrame] = []
    maximum_correction = 0.0
    for frame in clip.frames:
        joints = dict(frame.joints)
        body_frame = _body_local_frame(frame)
        symmetric_elbow_targets = (
            _symmetric_pair_targets(
                frame,
                body_frame=body_frame,
                pairs=(("left_elbow", "right_elbow"),),
            )
            if body_frame is not None
            else {}
        )
        left_hand = joints["left_hand"]
        right_hand = joints["right_hand"]
        midpoint = _scale(_add(left_hand, right_hand), 0.5)
        frame_axis = target_axis
        if local_axis is not None and body_frame is not None:
            frame_axis = _add(_add(_scale(body_frame.right, local_axis[0]),
                                  _scale(body_frame.up, local_axis[1])),
                              _scale(body_frame.forward, local_axis[2]))
        if supported_bilateral:
            shoulder_delta = _subtract(joints["right_shoulder"], joints["left_shoulder"])
            # Use the actual shoulder plane. Flattening this axis to world Y
            # gives unequal reaches when the torso is rolled, and one arm
            # straightens while the other bends despite symmetric targets.
            frame_axis = _normalize(shoulder_delta) or target_axis
            shoulder_center = _scale(_add(joints["left_shoulder"], joints["right_shoulder"]), 0.5)
            lateral_error = _dot(_subtract(midpoint, shoulder_center), frame_axis)
            midpoint = _subtract(midpoint, _scale(frame_axis, lateral_error))
        half_axis = _scale(frame_axis, target_spacing * 0.5)
        # Move the shared implement into the intersection of both arms' reach
        # spheres. Independent reach clamping separates the two hand targets.
        reaches = {}
        for side in ("left", "right"):
            upper = _distance(joints[f"{side}_shoulder"], joints[f"{side}_elbow"])
            lower = _distance(joints[f"{side}_elbow"], joints[f"{side}_hand"])
            reaches[side] = (abs(upper - lower) + 2e-5, upper + lower - 2e-5)
        for _ in range(100):
            maximum_reach_error = 0.0
            for side, sign in (("left", -1), ("right", 1)):
                target = _add(midpoint, _scale(half_axis, sign))
                delta = _subtract(target, joints[f"{side}_shoulder"])
                low, high = reaches[side]
                if supported_bilateral:
                    lateral = _dot(delta, frame_axis)
                    if abs(lateral) >= high:
                        raise ValueError("Rigid hand spacing exceeds supported bilateral arm reach")
                    delta = _subtract(delta, _scale(frame_axis, lateral))
                    low = math.sqrt(max(0.0, low * low - lateral * lateral))
                    high = math.sqrt(high * high - lateral * lateral)
                distance = _length(delta)
                reachable_distance = min(max(distance, low), high)
                error = distance - reachable_distance
                maximum_reach_error = max(maximum_reach_error, abs(error))
                if distance > 1e-9:
                    midpoint = _subtract(midpoint, _scale(delta, error / distance))
            if maximum_reach_error < 1e-8:
                break
        else:
            raise ValueError("Rigid paired hand targets have no common reachable position")
        targets = {
            "left": _subtract(midpoint, half_axis),
            "right": _add(midpoint, half_axis),
        }
        for side in ("left", "right"):
            shoulder_name = f"{side}_shoulder"
            elbow_name = f"{side}_elbow"
            wrist_name = f"{side}_wrist"
            hand_name = f"{side}_hand"
            preferred_elbow = symmetric_elbow_targets.get(elbow_name, joints[elbow_name])
            solved_elbow, solved_hand = _solve_two_bone(
                root=joints[shoulder_name],
                current_mid=joints[elbow_name],
                target_end=targets[side],
                upper_len=_distance(joints[shoulder_name], joints[elbow_name]),
                lower_len=_distance(joints[elbow_name], joints[hand_name]),
                fallback_axis=(0.0, 1.0, 0.0),
                preferred_bend_direction=_subtract(preferred_elbow, joints[shoulder_name]),
            )
            # Rotate the entire forearm/hand triangle rigidly. Keeping the old
            # world-space wrist offset after IK twists the wrist and changes
            # the effective reach differently for the two arms.
            old_axis = _normalize(_subtract(joints[hand_name], joints[elbow_name]))
            new_axis = _normalize(_subtract(solved_hand, solved_elbow))
            wrist_offset = _subtract(joints[wrist_name], joints[elbow_name])
            if old_axis is not None and new_axis is not None:
                turn_axis = _normalize(_cross(old_axis, new_axis))
                cosine = max(-1.0, min(1.0, _dot(old_axis, new_axis)))
                if turn_axis is None and cosine < 0:
                    turn_axis = _normalize(_cross(old_axis, (1.0, 0.0, 0.0))) or _normalize(_cross(old_axis, (0.0, 1.0, 0.0)))
                if turn_axis is not None:
                    wrist_offset = _rotate_vector_about_axis(wrist_offset, axis=turn_axis, angle_radians=math.acos(cosine))
            solved_wrist = _add(solved_elbow, wrist_offset)
            maximum_correction = max(
                maximum_correction,
                _distance(joints[hand_name], solved_hand),
            )
            joints[elbow_name] = solved_elbow
            joints[wrist_name] = solved_wrist
            joints[hand_name] = solved_hand
        corrected_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))
    corrected = replace(clip, frames=corrected_frames)
    corrected_spacing = [
        _distance(frame.joints["left_hand"], frame.joints["right_hand"])
        for frame in corrected.frames
    ]
    return corrected, {
        "applied": maximum_correction > 1e-8,
        "strategy": "rigid_paired_endpoint_transform_with_two_bone_arm_ik",
        "targetSpacing": target_spacing,
        "targetAxis": list(target_axis),
        "axisReference": "moving_body_frame" if local_axis is not None else "world_frame_fallback",
        "spacingRangeBefore": spacing_range_before,
        "spacingRangeAfter": max(corrected_spacing) - min(corrected_spacing),
        "maximumCorrection": maximum_correction,
        "supportedBilateralShoulderReference": supported_bilateral,
    }


def _solve_two_bone(
    *,
    root: Point3,
    current_mid: Point3,
    target_end: Point3,
    upper_len: float,
    lower_len: float,
    fallback_axis: Point3,
    preferred_bend_direction: Point3 | None = None,
) -> tuple[Point3, Point3]:
    root_to_target = _subtract(target_end, root)
    distance = _length(root_to_target)
    if distance <= 1e-6:
        return current_mid, target_end
    max_reach = max(1e-6, upper_len + lower_len - 1e-5)
    min_reach = max(0.0, abs(upper_len - lower_len) + 1e-5)
    clamped_distance = min(max(distance, min_reach), max_reach)
    direction = _scale(root_to_target, 1.0 / distance)
    solved_end = _add(root, _scale(direction, clamped_distance))
    projection_length = (
        (upper_len * upper_len - lower_len * lower_len + clamped_distance * clamped_distance)
        / max(2.0 * clamped_distance, 1e-6)
    )
    bend_height = math.sqrt(max(0.0, upper_len * upper_len - projection_length * projection_length))
    if preferred_bend_direction is not None:
        bend_direction = _subtract(
            preferred_bend_direction,
            _scale(direction, _dot(preferred_bend_direction, direction)),
        )
    else:
        current_root_to_mid = _subtract(current_mid, root)
        projected_mid = _add(root, _scale(direction, _dot(current_root_to_mid, direction)))
        bend_direction = _subtract(current_mid, projected_mid)
    if _length(bend_direction) <= 1e-6:
        bend_direction = _cross(direction, fallback_axis)
    if _length(bend_direction) <= 1e-6:
        basis = min(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                    key=lambda axis: abs(_dot(direction, axis)))
        bend_direction = _cross(direction, basis)
    bend_direction = _normalize(bend_direction)
    solved_mid = _add(
        _add(root, _scale(direction, projection_length)),
        _scale(bend_direction, bend_height),
    )
    return solved_mid, solved_end


class BodyFrame:
    def __init__(self, *, origin: Point3, right: Point3, up: Point3, forward: Point3) -> None:
        self.origin = origin
        self.right = right
        self.up = up
        self.forward = forward


def _body_local_frame(frame: MotionFrame) -> BodyFrame | None:
    joints = frame.joints
    origin = joints.get("pelvis")
    if origin is None:
        return None
    right_axis = None
    if "left_shoulder" in joints and "right_shoulder" in joints:
        right_axis = _normalize(_subtract(joints["right_shoulder"], joints["left_shoulder"]))
    if right_axis is None and "left_hip" in joints and "right_hip" in joints:
        right_axis = _normalize(_subtract(joints["right_hip"], joints["left_hip"]))
    if right_axis is None:
        return None
    spine_top = joints.get("neck") or joints.get("head") or joints.get("spine3")
    if spine_top is None:
        return None
    spine_axis = _normalize(_subtract(spine_top, origin))
    if spine_axis is None:
        return None
    # Match the SMPL/preview directed anatomical basis. Using right x up here
    # produces the same sagittal plane but reverses the meaning of forward,
    # causing source-guided limb travel to be solved on the opposite branch.
    forward_axis = _normalize(_cross(spine_axis, right_axis))
    if forward_axis is None:
        forward_axis = _normalize(_cross((0.0, 1.0, 0.0), right_axis))
    if forward_axis is None:
        return None
    up_axis = _normalize(_cross(right_axis, forward_axis))
    if up_axis is None:
        return None
    return BodyFrame(origin=origin, right=right_axis, up=up_axis, forward=forward_axis)


def _median_bone_length(clip: MotionClip, start_joint: str, end_joint: str) -> float:
    return median([
        _distance(frame.joints[start_joint], frame.joints[end_joint])
        for frame in clip.frames
    ])


def _median_body_height(clip: MotionClip) -> float:
    frame_heights: list[float] = []
    for frame in clip.frames:
        points = list(frame.joints.values())
        if not points:
            continue
        frame_heights.append(max(
            (_distance(left, right) for left in points for right in points),
            default=0.0,
        ))
    return median(frame_heights) if frame_heights else 0.0


def _to_local(point: Point3, frame: BodyFrame, origin: Point3) -> Point3:
    relative = _subtract(point, origin)
    return (_dot(relative, frame.right), _dot(relative, frame.up), _dot(relative, frame.forward))


def _from_local(point: Point3, frame: BodyFrame, origin: Point3) -> Point3:
    return _add(
        origin,
        _add(
            _scale(frame.right, point[0]),
            _add(_scale(frame.up, point[1]), _scale(frame.forward, point[2])),
        ),
    )


def _average_points(points: list[Point3]) -> Point3:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


def _median_point(points: list[Point3]) -> Point3:
    return (
        median(point[0] for point in points),
        median(point[1] for point in points),
        median(point[2] for point in points),
    )




def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((left_value - left_mean) * (right_value - right_mean) for left_value, right_value in zip(left, right))
    left_denominator = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_denominator = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    denominator = left_denominator * right_denominator
    if denominator <= 1e-8:
        return 0.0
    return numerator / denominator


def _distance(left: Point3, right: Point3) -> float:
    return _length(_subtract(left, right))


def _subtract(left: Point3, right: Point3) -> Point3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _add(left: Point3, right: Point3) -> Point3:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _scale(point: Point3, scalar: float) -> Point3:
    return (point[0] * scalar, point[1] * scalar, point[2] * scalar)


def _lerp_point(left: Point3, right: Point3, alpha: float) -> Point3:
    return (
        left[0] * (1.0 - alpha) + right[0] * alpha,
        left[1] * (1.0 - alpha) + right[1] * alpha,
        left[2] * (1.0 - alpha) + right[2] * alpha,
    )


def _limited_lerp_point(left: Point3, right: Point3, alpha: float, max_distance: float) -> Point3:
    target = _lerp_point(left, right, alpha)
    delta = _subtract(target, left)
    distance = _length(delta)
    if distance <= max_distance or distance <= 1e-8:
        return target
    return _add(left, _scale(delta, max_distance / distance))




def _dot(left: Point3, right: Point3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(left: Point3, right: Point3) -> Point3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _length(point: Point3) -> float:
    return math.sqrt(_dot(point, point))


def _normalize(point: Point3) -> Point3 | None:
    length = _length(point)
    if length <= 1e-8:
        return None
    return _scale(point, 1.0 / length)

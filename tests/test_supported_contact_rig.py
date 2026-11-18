import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
from exercise_motion_pkg.supported_contact_rig import (
    canonicalize_after_native_foot_projection,
    mirrored_leg_coupling_authority,
    project_coupled_native_foot_coordinates,
    project_supported_native_foot_coordinates,
)
from exercise_motion_pkg.contact_constraints import (
    observed_full_sole_patch_support_at_time,
)

FIXTURES = Path(__file__).parent / 'fixtures'
OFFSET_LOCAL = np.array([0., 0.5, 0.])


def _rig(frame_count, *, mirrored=False):
    fixture = json.loads(
        (FIXTURES / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    if mirrored:
        pose = motion.canonical_bilateral_reference(
            pose[None], names, {'legs': 'mirrored'})[0]
    return motion.FixedRig(np.tile(pose, (frame_count, 1, 1)), names), names


def _material_frame(ankle, foot, axis):
    bone = foot - ankle
    forward = bone / np.linalg.norm(bone, axis=1)[:, None]
    lateral = axis - forward * np.sum(axis * forward, axis=1, keepdims=True)
    lateral /= np.linalg.norm(lateral, axis=1)[:, None]
    up = np.cross(lateral, forward)
    return np.stack((forward, lateral, up), axis=2)


def _material_point(points, names, axis, local):
    ankle = points[:, names.index('right_ankle')]
    foot = points[:, names.index('right_foot')]
    return ankle + np.einsum('fij,j->fi', _material_frame(ankle, foot, axis), local)


def _scenario(frame_count, *, mirrored=False):
    rig, names = _rig(frame_count, mirrored=mirrored)
    coordinates = rig.initial.copy()
    points = rig.decode(coordinates)
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    source_axis = (rig.global_rotations(rig.material_reference_coordinates)[foot]
                   @ np.array([1., 0., 0.]))
    side_axes = np.broadcast_to(source_axis, (frame_count, 3)).copy()
    bone_length = float(np.linalg.norm(rig.offsets[foot]))
    material = _material_point(points, names, side_axes, OFFSET_LOCAL)
    target = material + np.array([0.0065, 0.002, 0.0])
    episode = {
        'startFrame': 0, 'endFrame': frame_count - 1,
        'anchorId': 'support-anchor', 'mode': 'stationary',
        'materialOffsetLocalMeters': OFFSET_LOCAL.tolist(),
        'referenceLengthMeters': bone_length,
        'targetWorld': target[0].tolist(),
        'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': float(target[0, 1]),
    }
    direction = points[:, foot] - points[:, ankle]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    track = {'version': 2, 'right': {
        'active': [True] * frame_count,
        'directions': direction.tolist(),
        'sideAxes': side_axes.tolist(),
        'anchorIds': ['support-anchor'] * frame_count,
        'episodes': [episode],
    }}
    support = {'version': 1, 'source': 'validated_stationary_body_support', 'joints': {
        'right_knee': {'episodeIds': ['support-anchor'] * frame_count},
    }}
    return rig, names, coordinates, points, track, support, target


def _production_projection_sequence(rig, coordinates, track, support, execution,
                                    source_pinned):
    """The exact post-fit sequence used by controlled_motion."""
    leg_authority = mirrored_leg_coupling_authority(
        rig, coordinates, track, execution, source_pinned)
    projected = project_coupled_native_foot_coordinates(
        rig, coordinates, track, support, execution=execution,
        source_contact_pinned=source_pinned)
    final = canonicalize_after_native_foot_projection(
        rig, projected, execution, leg_authority)
    return final, leg_authority


def test_encoder_corrects_material_target_with_fixed_knee_and_bones():
    rig, names, coordinates, points, track, support, target = _scenario(4)
    original = coordinates.copy()
    q = project_supported_native_foot_coordinates(rig, coordinates, track, support)

    assert q is not coordinates
    assert not np.shares_memory(q, coordinates)
    np.testing.assert_array_equal(coordinates, original)

    corrected = rig.decode(q)
    knee = names.index('right_knee')
    ankle = names.index('right_ankle')
    foot = names.index('right_foot')
    hip = names.index('right_hip')
    np.testing.assert_allclose(corrected[:, knee], points[:, knee], atol=1e-10)
    np.testing.assert_allclose(corrected[:, hip], points[:, hip], atol=1e-10)
    for name in ('left_knee', 'left_ankle', 'left_foot'):
        joint = names.index(name)
        np.testing.assert_allclose(corrected[:, joint], points[:, joint], atol=1e-10)

    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, ankle] - corrected[:, knee], axis=1),
        np.linalg.norm(points[:, ankle] - points[:, knee], axis=1), atol=1e-9)
    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, foot] - corrected[:, ankle], axis=1),
        np.linalg.norm(points[:, foot] - points[:, ankle], axis=1), atol=1e-9)
    assert np.max(np.linalg.norm(corrected[:, ankle] - points[:, ankle], axis=1)) > 1e-4

    axes = _native_side_axes_for_coordinates(
        rig, q, {'_nativeFootMaterialTracks': track})['right']
    material = _material_point(corrected, names, axes, OFFSET_LOCAL)
    np.testing.assert_allclose(material, target, atol=1e-6)


def test_encoder_noop_copy_without_native_track_or_protection():
    rig, names, coordinates, _, track, _, _ = _scenario(3)

    legacy = project_supported_native_foot_coordinates(rig, coordinates, None, {})
    np.testing.assert_array_equal(legacy, coordinates)
    assert legacy is not coordinates

    unprotected = {'version': 1, 'source': 'validated_stationary_body_support', 'joints': {
        'right_knee': {'episodeIds': [None] * 3},
    }}
    np.testing.assert_array_equal(
        project_supported_native_foot_coordinates(rig, coordinates, track, unprotected),
        coordinates)


def test_transient_knee_point_contact_distributes_reach():
    """An unobserved knee must not absorb a large toe correction at the ankle."""
    rig, names, coordinates, points, track, support, _ = _scenario(4)
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    knee = names.index('right_knee')
    axes = _native_side_axes_for_coordinates(
        rig, coordinates, {'_nativeFootMaterialTracks': track})['right']
    material = _material_point(points, names, axes, OFFSET_LOCAL)
    # A 4 cm target offset is well inside the contact projection range but
    # needs a visible foot/ankle rotation when the knee is held fixed.
    track['right']['episodes'][0]['targetWorld'] = (
        material[0] + np.array([0.04, 0.01, 0.])).tolist()

    fixed = project_supported_native_foot_coordinates(
        rig, coordinates, track, support)
    distributed = project_supported_native_foot_coordinates(
        rig, coordinates, track, {}, current_knee_pivot=True)
    fixed_points = rig.decode(fixed)
    distributed_points = rig.decode(distributed)

    for coordinates_out, decoded in (
            (fixed, fixed_points), (distributed, distributed_points)):
        decoded_axes = _native_side_axes_for_coordinates(
            rig, coordinates_out, {'_nativeFootMaterialTracks': track})['right']
        np.testing.assert_allclose(
            _material_point(decoded, names, decoded_axes, OFFSET_LOCAL),
            np.broadcast_to(
                np.asarray(track['right']['episodes'][0]['targetWorld']),
                (len(decoded), 3)),
            atol=1e-6)
        np.testing.assert_allclose(
            np.linalg.norm(decoded[:, foot] - decoded[:, ankle], axis=1),
            np.linalg.norm(points[:, foot] - points[:, ankle], axis=1),
            atol=1e-9)
        np.testing.assert_allclose(
            np.linalg.norm(decoded[:, ankle] - decoded[:, knee], axis=1),
            np.linalg.norm(points[:, ankle] - points[:, knee], axis=1),
            atol=1e-9)

    from exercise_motion_pkg.sequence_stabilization import angles

    source_angle = np.degrees(angles(
        points[:, knee], points[:, ankle], points[:, foot]))
    fixed_angle = np.degrees(angles(
        fixed_points[:, knee], fixed_points[:, ankle], fixed_points[:, foot]))
    distributed_angle = np.degrees(angles(
        distributed_points[:, knee], distributed_points[:, ankle],
        distributed_points[:, foot]))
    fixed_change = float(np.max(np.abs(fixed_angle - source_angle)))
    distributed_change = float(np.max(np.abs(distributed_angle - source_angle)))

    # The distributed path keeps the same contact with a smaller ankle
    # articulation repair by moving the transient knee, not by relaxing it.
    assert distributed_change < fixed_change
    assert np.max(np.linalg.norm(
        distributed_points[:, knee] - points[:, knee], axis=1)) > 1e-4
    np.testing.assert_allclose(
        fixed_points[:, knee], points[:, knee], atol=1e-10)


def test_mirrored_projection_couples_the_unsupported_leg():
    """A one-sided native contact in mirrored legs must rebuild the mirror leg."""
    rig, names, coordinates, points, track, support, target = _scenario(
        4, mirrored=True)
    execution = {'legs': 'mirrored'}
    source_pinned = np.zeros((4, len(names)), dtype=bool)
    source_pinned[:, names.index('right_foot')] = True

    coupled = project_coupled_native_foot_coordinates(
        rig, coordinates, track, support, execution=execution,
        source_contact_pinned=source_pinned)
    decoded = rig.decode(coupled)

    # The observed contact keeps its target.
    axes = _native_side_axes_for_coordinates(
        rig, coupled, {'_nativeFootMaterialTracks': track})['right']
    np.testing.assert_allclose(
        _material_point(decoded, names, axes, OFFSET_LOCAL), target, atol=1e-6)

    # The unowned leg is the exact mirror of the corrected owned leg, not the
    # unchanged input pose.
    reference = motion.canonical_bilateral_reference(decoded, names, execution)
    assert np.max(np.linalg.norm(decoded - reference, axis=-1)) < 1e-9
    left_ankle = names.index('left_ankle')
    right_ankle = names.index('right_ankle')
    left_move = np.linalg.norm(decoded[:, left_ankle] - points[:, left_ankle], axis=1)
    right_move = np.linalg.norm(decoded[:, right_ankle] - points[:, right_ankle], axis=1)
    assert np.max(left_move) > 1e-4
    np.testing.assert_allclose(left_move, right_move, atol=1e-9)

    # Bilateral source pins own both chains: no mirror coupling.
    bilateral = source_pinned.copy()
    bilateral[:, names.index('left_foot')] = True
    uncoupled = project_coupled_native_foot_coordinates(
        rig, coordinates, track, support, execution=execution,
        source_contact_pinned=bilateral)
    np.testing.assert_allclose(
        rig.decode(uncoupled)[:, left_ankle], points[:, left_ankle], atol=1e-9)

    # An unconstrained leg policy keeps the unilateral projection alone.
    unconstrained = project_coupled_native_foot_coordinates(
        rig, coordinates, track, support, execution={'legs': 'unconstrained'},
        source_contact_pinned=source_pinned)
    np.testing.assert_allclose(
        rig.decode(unconstrained)[:, left_ankle], points[:, left_ankle], atol=1e-9)
    np.testing.assert_allclose(
        rig.decode(unconstrained), rig.decode(project_supported_native_foot_coordinates(
            rig, coordinates, track, support)), atol=1e-12)


def test_encoder_unreachable_target_raises_without_mutating_input():
    rig, _, coordinates, _, track, support, target = _scenario(3)
    bad_track = json.loads(json.dumps(track))
    bad_track['right']['episodes'][0]['targetWorld'] = (
        np.asarray(target[0]) + np.array([5., 0., 0.])).tolist()
    original = coordinates.copy()
    with pytest.raises(ValueError):
        project_supported_native_foot_coordinates(rig, coordinates, bad_track, support)
    np.testing.assert_array_equal(coordinates, original)


def test_production_sequence_couples_only_a_verified_one_sided_mirror_pair():
    """Caller-level: unilateral mirror pair is coupled and contact stays exact."""
    rig, names, coordinates, points, track, support, target = _scenario(
        4, mirrored=True)
    execution = {'legs': 'mirrored'}
    source_pinned = np.zeros((4, len(names)), dtype=bool)
    source_pinned[:, names.index('right_foot')] = True

    final, authority = _production_projection_sequence(
        rig, coordinates, track, support, execution, source_pinned)

    assert authority == 'right'
    decoded = rig.decode(final)
    reference = motion.canonical_bilateral_reference(decoded, names, execution)
    assert np.max(np.linalg.norm(decoded - reference, axis=-1)) < 1e-9
    axes = _native_side_axes_for_coordinates(
        rig, final, {'_nativeFootMaterialTracks': track})['right']
    np.testing.assert_allclose(
        _material_point(decoded, names, axes, OFFSET_LOCAL), target, atol=1e-6)


def test_production_sequence_keeps_bilateral_contacts_independent():
    """Caller-level: bilateral pins must not be averaged by canonicalization."""
    rig, names, coordinates, points, track, support, _ = _scenario(
        4, mirrored=True)
    execution = {'legs': 'mirrored'}
    bilateral = np.zeros((4, len(names)), dtype=bool)
    bilateral[:, names.index('right_foot')] = True
    bilateral[:, names.index('left_foot')] = True

    final, authority = _production_projection_sequence(
        rig, coordinates, track, support, execution, bilateral)
    direct = project_supported_native_foot_coordinates(
        rig, coordinates, track, support)

    assert authority is None
    left_ankle = names.index('left_ankle')
    np.testing.assert_allclose(
        rig.decode(final)[:, left_ankle], points[:, left_ankle], atol=1e-9)
    np.testing.assert_allclose(
        rig.decode(final), rig.decode(direct), atol=1e-12)


def test_production_sequence_preserves_partial_opposite_contact_frames():
    """Caller-level: any observed opposite-side frame declines whole-clip coupling."""
    rig, names, coordinates, points, track, support, _ = _scenario(
        4, mirrored=True)
    execution = {'legs': 'mirrored'}
    source_pinned = np.zeros((4, len(names)), dtype=bool)
    source_pinned[:, names.index('right_foot')] = True
    left_track = {
        'active': [False, True, False, False],
        'directions': track['right']['directions'],
        'sideAxes': track['right']['sideAxes'],
        'anchorIds': [None, 'left-observed', None, None],
        'episodes': [{**track['right']['episodes'][0],
                      'startFrame': 1, 'endFrame': 1, 'anchorId': 'left-observed'}],
    }
    partial = {'version': 2, 'left': left_track, 'right': track['right']}

    final, authority = _production_projection_sequence(
        rig, coordinates, partial, support, execution, source_pinned)
    direct = project_supported_native_foot_coordinates(
        rig, coordinates, partial, support)

    assert authority is None
    left_ankle = names.index('left_ankle')
    np.testing.assert_allclose(
        rig.decode(final)[:, left_ankle], points[:, left_ankle], atol=1e-9)
    np.testing.assert_allclose(
        rig.decode(final), rig.decode(direct), atol=1e-12)
    # The observed right contact is still exact after the declared-policy pass.
    axes = _native_side_axes_for_coordinates(
        rig, final, {'_nativeFootMaterialTracks': partial})['right']
    np.testing.assert_allclose(
        _material_point(rig.decode(final), names, axes, OFFSET_LOCAL),
        np.broadcast_to(np.asarray(track['right']['episodes'][0]['targetWorld']),
                        (4, 3)), atol=1e-6)


def test_production_sequence_preserves_anti_phase_mirrored_legs():
    """Caller-level: an out-of-phase pair must not be forced into same-frame symmetry."""
    rig, names, coordinates, points, track, support, _ = _scenario(4)
    # Move the left ankle forward while the right stays: homologous legs now
    # describe alternating phases rather than a same-frame mirror pair.
    execution = {'legs': 'mirrored'}
    left_ankle = names.index('left_ankle')
    swing_points = points.copy()
    swing_points[:, left_ankle, 1] += 0.03
    rig = motion.FixedRig(swing_points, names)
    coordinates = rig.initial
    swing = coordinates
    source_pinned = np.zeros((4, len(names)), dtype=bool)
    source_pinned[:, names.index('right_foot')] = True

    final, authority = _production_projection_sequence(
        rig, swing, track, support, execution, source_pinned)
    direct = project_supported_native_foot_coordinates(
        rig, swing, track, support)

    assert authority is None
    np.testing.assert_allclose(
        rig.decode(final)[:, left_ankle], rig.decode(swing)[:, left_ankle], atol=1e-9)
    np.testing.assert_allclose(
        rig.decode(final), rig.decode(direct), atol=1e-12)


def test_isolated_unknown_frame_inside_toe_run_is_not_full_sole():
    """The retained frame-15 artifact: isolated unknown row inside toe_only run."""
    evidence = {
        'footPatchEvidence': {
            'available': True,
            'sourceTimesSec': [0.0, 1 / 30, 2 / 30, 3 / 30],
            'feet': {'right': {'states': ['toe_only', 'unknown', 'toe_only', 'full_sole']}},
        },
    }
    assert observed_full_sole_patch_support_at_time(evidence, 'right', 1 / 30) == 'toe_only'
    assert observed_full_sole_patch_support_at_time(evidence, 'right', 0.0) == 'toe_only'
    assert observed_full_sole_patch_support_at_time(evidence, 'right', 3 / 30) == 'full_sole'
    assert observed_full_sole_patch_support_at_time(evidence, 'left', 1 / 30) == 'unverified'
    assert observed_full_sole_patch_support_at_time({}, 'right', 1 / 30) == 'unverified'

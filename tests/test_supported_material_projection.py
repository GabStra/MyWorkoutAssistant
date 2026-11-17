import numpy as np
import pytest
import json
from copy import deepcopy
from pathlib import Path

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.contact_interpolation import project_supported_material_contact
from exercise_motion_pkg.contact_interpolation import sample_contact_foot_tracks
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame, validated_native_foot_geometry
from exercise_motion_pkg.support_joint_tracks import validate_support_joint_tracks


def test_supported_material_projection_preserves_links_and_transports_distal_frame():
    support = np.asarray([[0., 0., 0.], [0., 1., 0.]])
    intermediate = np.asarray([[1., 0., 0.], [1.2, 1., 0.]])
    bone_end = intermediate + np.asarray([[0., 0., .15], [0., 0., .2]])
    material = np.asarray([[1.8, .1, 0.], [1.8, 1.1, 0.]])
    target = np.asarray([[1.2, .2, 0.], [1.1, 1.1, 0.]])
    side_axis = np.asarray([[0., 1., 0.], [0., 1., 0.]])

    new_joint, new_end, new_axis, rotations = project_supported_material_contact(
        support, intermediate, bone_end, material, target, side_axis, 'right')

    np.testing.assert_allclose(np.linalg.norm(new_joint - support, axis=1),
                               np.linalg.norm(intermediate - support, axis=1), atol=1e-10)
    np.testing.assert_allclose(np.linalg.norm(target - new_joint, axis=1),
                               np.linalg.norm(material - intermediate, axis=1), atol=1e-10)
    np.testing.assert_allclose(
        new_joint + np.einsum('fij,fj->fi', rotations, material - intermediate),
        target, atol=1e-10)
    np.testing.assert_allclose(np.linalg.norm(new_end - new_joint, axis=1),
                               np.linalg.norm(bone_end - intermediate, axis=1), atol=1e-10)
    np.testing.assert_allclose(np.linalg.norm(new_axis, axis=1), 1., atol=1e-10)
    bone = new_end - new_joint
    np.testing.assert_allclose(np.sum(new_axis * bone, axis=1), 0., atol=1e-10)
    np.testing.assert_allclose(rotations @ np.swapaxes(rotations, 1, 2),
                               np.broadcast_to(np.eye(3), (2, 3, 3)), atol=1e-10)

    with pytest.raises(ValueError, match='unreachable'):
        project_supported_material_contact(
            support[:1], intermediate[:1], bone_end[:1], material[:1],
            np.asarray([[4., 0., 0.]]), side_axis[:1], 'right')


def test_native_sampler_reaches_material_target_without_moving_supported_knee_at_key():
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    rig_model = motion.FixedRig(np.tile(pose, (2, 1, 1)), names)
    coordinates = rig_model.initial
    points = rig_model.decode(coordinates)
    ankle_i, foot_i, knee_i = (names.index(f'right_{part}')
                               for part in ('ankle', 'foot', 'knee'))
    foot_rotation = rig_model.global_rotations(rig_model.material_reference_coordinates)[foot_i]
    axes = foot_rotation[:, :, 0]
    forward = points[:, foot_i] - points[:, ankle_i]
    forward /= np.linalg.norm(forward, axis=1, keepdims=True)
    axes -= forward * np.sum(axes * forward, axis=1, keepdims=True)
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)

    geometry_source = json.loads((Path(__file__).parent / 'fixtures/native_foot_geometry_v1.json').read_text())['reference']
    geometry = validated_native_foot_geometry(geometry_source)
    scale = float(foot_scale_from_pose(points[0], names))
    triangles = shoe_triangles()
    triangle_index = 12
    barycentric = np.asarray([.2, .3, .5])
    shoes = shoe_vertices(points[:, ankle_i], points[:, foot_i], axes, None, scale,
                          native_geometry=geometry['sides']['right'])
    material = np.asarray([barycentric @ shoes[frame, triangles[triangle_index]]
                           for frame in range(2)])
    local_offsets = []
    reference_length = float(np.linalg.norm(rig_model.offsets[foot_i]))
    for frame in range(2):
        fwd, lateral, up, current_length = native_foot_bone_frame(
            points[frame, ankle_i], points[frame, foot_i], axes[frame])
        offset = material[frame] - points[frame, ankle_i]
        local_offsets.append(np.asarray([np.dot(offset, fwd), np.dot(offset, lateral),
                                         np.dot(offset, up)])
                             * (reference_length / current_length[0]))
    target = material[0] + np.asarray([0., .002, 0.])
    episode = {
        'startFrame': 0, 'endFrame': 1, 'anchorId': 'toe-anchor',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:right_ankle->right_foot',
        'triangleIndex': triangle_index, 'barycentric': barycentric.tolist(),
        'materialOffsetLocalMeters': np.mean(local_offsets, axis=0).tolist(),
        'referenceLengthMeters': reference_length, 'targetWorld': target.tolist(),
        'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': float(target[1]),
    }
    directions = (points[:, foot_i] - points[:, ankle_i])
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    contact_tracks = {'version': 2, 'right': {
        'active': [True, True], 'directions': directions.tolist(),
        'sideAxes': axes.tolist(), 'anchorIds': ['toe-anchor', 'toe-anchor'],
        'episodes': [episode],
    }}
    support_tracks = validate_support_joint_tracks({
        'version': 1, 'source': 'validated_stationary_body_support',
        'joints': {'right_knee': {'episodeIds': ['knee-anchor', 'knee-anchor']}},
    }, names, 2)
    rig = {
        'version': 1, 'jointNames': names, 'parents': rig_model.parents,
        'order': rig_model.order, 'offsets': rig_model.offsets.tolist(),
        'coordinates': coordinates.tolist(), 'rotationJointNames': [names[j] for j in rig_model.active],
        'interpolation': motion.INTERPOLATION, 'contactFootTracks': contact_tracks,
        'supportJointTracks': {'version': 1, 'source': 'validated_stationary_body_support',
                               'joints': {'right_knee': {'episodeIds': ['knee-anchor', 'knee-anchor']}}},
        '_supportJointTracksForSampling': support_tracks,
        '_canonicalExecutionForSampling': {'legs': 'mirrored'},
    }
    original_track = deepcopy(contact_tracks)
    sampled, sampled_axes = sample_contact_foot_tracks(
        rig, np.asarray([0., .5]), points[:1].repeat(2, axis=0),
        preserve_keys=True, native_foot_geometry=geometry,
        foot_scale=scale, return_side_axes=True)

    np.testing.assert_allclose(sampled[:, knee_i], np.broadcast_to(points[0, knee_i], (2, 3)),
                               atol=1e-10)
    result_shoes = shoe_vertices(
        sampled[:, ankle_i], sampled[:, foot_i], sampled_axes['right'], None, scale,
        native_geometry=geometry['sides']['right'])
    actual_material = np.asarray([
        barycentric @ result_shoes[frame, triangles[triangle_index]] for frame in range(2)])
    np.testing.assert_allclose(actual_material, np.broadcast_to(target, (2, 3)), atol=1e-6)
    assert contact_tracks == original_track

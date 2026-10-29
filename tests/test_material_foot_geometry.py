import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.foot_geometry import (
    calibrated_foot_rest_pitches, free_foot_floor_translation,
    material_floor_heights, material_foot_points, sample_material_foot_points,
    shoe_vertices, validate_material_shoes,
)


def test_observed_foot_phase_supersedes_only_the_covered_ankle_prior():
    from exercise_motion_pkg.controlled_motion import timed_foot_articulation_residuals
    specs = [('left_knee', (0, 1, 2), 10.), ('left_ankle', (1, 2, 3), 15.)]
    tracks = [(name, joints, np.zeros(3)) for name, joints, _ in specs]
    angles = np.full((3, 2), .1)
    rows = timed_foot_articulation_residuals(
        angles, specs, tracks, 500., {'left_ankle': np.array([0., 1., 0.])})
    np.testing.assert_allclose(rows[:, 0], 0.)
    np.testing.assert_allclose(rows[:, 1], [50., .2, 50.])


def test_calibrated_shoe_is_flat_at_rest_and_pivots_at_the_forefoot():
    ankle, toe, lateral = np.array([-.12, .055, 0.]), np.zeros(3), np.array([0., 0., 1.])
    pitch = np.arctan2(-.055, .12)
    vertices = shoe_vertices(ankle, toe, lateral, pitch, .2)
    assert vertices[:, 1].min() == pytest.approx(0., abs=1e-12)
    heel, anchor = material_foot_points(ankle, toe, lateral, pitch)
    assert heel[1] == pytest.approx(0., abs=1e-12)
    np.testing.assert_array_equal(anchor, toe)
    raised_ankle = Rotation.from_rotvec(lateral * np.deg2rad(-15.)).apply(ankle)
    raised_heel, anchor = material_foot_points(raised_ankle, toe, lateral, pitch)
    assert raised_heel[1] > .03
    np.testing.assert_array_equal(anchor, toe)
    assert shoe_vertices(raised_ankle, toe, lateral, pitch, .2)[:, 1].min() == pytest.approx(0., abs=1e-12)


def test_rest_pitch_uses_anchored_fullsole_track_and_excludes_unknown_patch_samples():
    names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    count = 6
    points = np.zeros((count, len(names), 3), dtype=float)
    left_pitch, right_pitch = np.deg2rad(-12.), np.deg2rad(-24.)
    for frame in range(count):
        points[frame, 1] = [.2*np.cos(left_pitch), .2*np.sin(left_pitch), 0.]
        pitch = right_pitch if frame < 4 else np.deg2rad(40.)
        points[frame, 3] = [.2*np.cos(pitch), .2*np.sin(pitch), 0.]
    contacts = [
        {'jointName': f'{side}_foot', 'contactState': 'full_sole',
         'contactMotion': 'stationary', 'surfaceKind': 'ground',
         'startRatio': 0., 'endRatio': 1.}
        for side in ('left', 'right')
    ]
    evidence = {
        'contacts': contacts,
        'bodySupport': {'required': True, 'status': 'confirmed',
                        'stationaryJoints': ['right_ankle', 'right_foot']},
        'footPatchEvidence': {'available': True, 'feet': {
            'left': {'states': ['full_sole'] * count},
            'right': {'states': ['full_sole'] * 4 + ['airborne', 'unknown']},
        }},
    }

    pitches = calibrated_foot_rest_pitches(points, names, evidence)

    assert pitches['left'] == pytest.approx(left_pitch)
    assert pitches['right'] == pytest.approx(right_pitch)


def test_rest_pitch_maps_cropped_fit_frames_to_native_patch_timestamps():
    names = ['left_ankle', 'left_foot']
    points = np.zeros((4, 2, 3), dtype=float)
    pitch = np.deg2rad(-25.)
    points[:, 1] = [.2*np.cos(pitch), .2*np.sin(pitch), 0.]
    evidence = {
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'surfaceKind': 'ground',
                      'startRatio': 0., 'endRatio': 1.}],
        'footPatchEvidence': {
            'available': True, 'sourceTimeBasis': 'absolute_source_video',
            'sourceStartTimeSec': 0., 'sourceFps': 10.,
            'sourceTimesSec': [index / 10. for index in range(10)],
            'sourceFrameCount': 10,
            'feet': {'left': {'states': ['toe_only'] * 4 + ['full_sole'] * 6}},
        },
    }

    pitches = calibrated_foot_rest_pitches(
        points, names, evidence, frame_times=[.4, .5, .6, .7])

    assert pitches['left'] == pytest.approx(pitch)


def test_rest_pitch_uses_absolute_source_clock_for_nonzero_origin_crop():
    names = ['left_ankle', 'left_foot']
    points = np.zeros((4, 2, 3), dtype=float)
    pitch = np.deg2rad(-19.)
    points[:, 1] = [.2*np.cos(pitch), .2*np.sin(pitch), 0.]
    from exercise_motion_pkg.foot_contact_observation import _patch_source_timing_metadata
    timing = _patch_source_timing_metadata(
        [{'timeSeconds': index / 10.} for index in range(10)], 125.5)
    evidence = {
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'surfaceKind': 'ground',
                      'startRatio': 0., 'endRatio': 1.}],
        'footPatchEvidence': {
            'available': True, **timing, 'sourceFps': 10., 'sourceFrameCount': 10,
            'feet': {'left': {'states': ['toe_only'] * 4 + ['full_sole'] * 6}},
        },
    }

    pitches = calibrated_foot_rest_pitches(
        points, names, evidence, frame_times=[125.9, 126.0, 126.1, 126.2])

    assert timing['sourceStartTimeSec'] == pytest.approx(125.5)
    assert timing['sourceEndTimeSec'] == pytest.approx(126.4)
    assert pitches['left'] == pytest.approx(pitch)


def test_source_clock_fit_view_maps_patch_contacts_without_crop_endpoint_extension():
    from exercise_motion_pkg.contact_constraints import (
        contact_frame_bounds, mapped_foot_patch_state_indices,
        motion_space_support_evidence, motion_support_contacts,
    )

    evidence = {
        'footPatchEvidence': {
            'available': True,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceFps': 4.,
            'sourceTimesSec': [125.5, 125.75, 126.],
            'feet': {
                'left': {'states': ['full_sole', 'airborne', 'full_sole']},
                'right': {'states': ['unknown', 'unknown', 'unknown']},
            },
        },
        'contacts': [{
            'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
            'contactState': 'full_sole', 'contactMotion': 'stationary',
            'startRatio': 0., 'endRatio': 0.,
        }],
    }
    payload = {
        'sourceFootSupportEvidence': evidence,
        'frames': [{'sourceTimeSec': time} for time in
                   (125.5, 125.625, 125.75, 125.875, 126., 126.125)],
    }

    mapped = mapped_foot_patch_state_indices(
        evidence, np.asarray([frame['sourceTimeSec'] for frame in payload['frames']]))
    np.testing.assert_array_equal(mapped, [0, 0, 1, 1, 2, -1])
    contacts = motion_support_contacts(motion_space_support_evidence(payload))
    assert len(contacts) == 1
    # The midpoint between fullsole and airborne is not owned by either
    # endpoint pair; only the exact observed fullsole row remains pinned.
    assert contact_frame_bounds(contacts[0], len(payload['frames'])) == (0, 0)
    assert payload['sourceFootSupportEvidence'] == evidence


def test_rest_pitch_does_not_stretch_source_states_when_timestamps_are_missing():
    names = ['left_ankle', 'left_foot']
    points = np.zeros((4, 2, 3), dtype=float)
    pitch = np.deg2rad(-25.)
    points[:, 1] = [.2*np.cos(pitch), .2*np.sin(pitch), 0.]
    evidence = {
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'surfaceKind': 'ground',
                      'startRatio': 0., 'endRatio': 1.}],
        'footPatchEvidence': {
            'available': True, 'sourceFrameCount': 10,
            'feet': {'left': {'states': ['toe_only'] * 4 + ['full_sole'] * 6}},
        },
    }

    assert calibrated_foot_rest_pitches(points, names, evidence) == {}


def test_legacy_local_patch_clock_is_not_reinterpreted_as_absolute_source_time():
    names = ['left_ankle', 'left_foot']
    points = np.zeros((4, 2, 3), dtype=float)
    pitch = np.deg2rad(-25.)
    points[:, 1] = [.2*np.cos(pitch), .2*np.sin(pitch), 0.]
    evidence = {
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'surfaceKind': 'ground',
                      'startRatio': 0., 'endRatio': 1.}],
        'footPatchEvidence': {
            'available': True, 'policyVersion': 16,
            'sourceStartTimeSec': 0., 'sourceFps': 10., 'sourceFrameCount': 4,
            'feet': {'left': {'states': ['full_sole'] * 4}},
        },
    }

    assert calibrated_foot_rest_pitches(
        points, names, evidence, frame_times=[125.0, 125.1, 125.2, 125.3]) == {}


def test_material_floor_detects_a_penetrating_heel_with_clear_joint_centres():
    names = ['left_ankle', 'left_foot']
    pitch = np.arctan2(-.055, .12)
    ankle = Rotation.from_rotvec([0., 0., np.deg2rad(10.)]).apply([-.12, .055, 0.])
    points = np.array([[ankle + [0., .004, 0.], [0., .004, 0.]]])
    assert points[:, :, 1].min() > 0.
    assert material_floor_heights(
        points, names, {'left': pitch}, .2, {'left': np.array([[0., 0., 1.]])}).min() < -.01


def test_uncalibrated_rendered_shoe_is_still_checked_at_renderer_default_pitch():
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    pose[:, 1] += 1.2
    ankle = names.index('left_ankle')
    toe = names.index('left_foot')
    pose[ankle] = [pose[ankle, 0], .12, pose[ankle, 2]]
    pose[toe] = [pose[ankle, 0] + .021, .001, pose[ankle, 2]]
    points = np.tile(pose, (2, 1, 1))
    floor = 0.
    joints = dict(zip(names, pose.tolist()))
    frames = [{'timeSec': index / 30., 'joints': joints} for index in range(2)]
    payload = {
        'frames': frames, 'jointNames': names, 'renderFloorY': floor,
        'footRestPitchRadians': {}, 'loop': {'enabled': False},
    }

    # The ankle and toe centers are above the floor in this stance fixture,
    # but at renderer-default pitch the mesh outsole intersects the floor.
    assert points[:, :, 1].min() > floor
    from exercise_motion_pkg.foot_geometry import _sample_material_foot_geometry
    geometry = _sample_material_foot_geometry(payload, np.array([0., 1.]), points)
    axes = {side: values['lateral'] for side, values in geometry.items()}
    solver_heights = material_floor_heights(points, names, {}, .2, axes)
    assert solver_heights[:, ankle].min() < floor
    result = validate_material_shoes(
        payload, points, np.array([0., 1.]), floor_limit=.002, contact_limit=.002)

    assert result['required'] is True
    assert result['passed'] is False
    assert result['maximumSurfacePenetrationMeters'] > .002
    assert result['maximumSurfacePenetrationMeters'] == pytest.approx(
        floor - solver_heights[:, ankle].min(), abs=1e-9)


def test_free_foot_floor_translation_clears_material_shoe_without_changing_foot_pose():
    ankle = np.array([-.12, -.01, 0.])
    toe = np.array([0., -.04, 0.])
    side = np.array([0., 0., 1.])
    floor, pitch, scale = 0., -.2, .2

    lift = free_foot_floor_translation(
        ankle, toe, floor_y=floor, rest_pitch_radians=pitch,
        foot_scale=scale, side_axis=side)
    shifted = shoe_vertices(
        ankle + [0., lift, 0.], toe + [0., lift, 0.], side, pitch, scale)

    assert lift > 0.
    assert shifted[:, 1].min() == pytest.approx(floor, abs=1e-12)
    np.testing.assert_array_equal((toe + [0., lift, 0.]) - (ankle + [0., lift, 0.]),
                                  toe - ankle)


def test_free_foot_floor_translation_preserves_clearance_and_rejects_invalid_geometry():
    ankle, toe, side = np.array([-.12, .2, 0.]), np.array([0., .15, 0.]), np.array([0., 0., 1.])
    assert free_foot_floor_translation(
        ankle, toe, floor_y=0., rest_pitch_radians=-.2,
        foot_scale=.2, side_axis=side) == 0.

    with pytest.raises(ValueError, match='finite 3D'):
        free_foot_floor_translation(
            [np.nan, 0., 0.], toe, floor_y=0., rest_pitch_radians=0.,
            foot_scale=.2, side_axis=side)
    with pytest.raises(ValueError, match='foot axes'):
        free_foot_floor_translation(
            ankle, toe, floor_y=0., rest_pitch_radians=0.,
            foot_scale=.2, side_axis=toe - ankle)


def test_material_foot_sampler_interpolates_candidate_keyframes_and_returns_render_axis():
    names = ['left_hip', 'left_knee', 'left_ankle', 'left_foot']
    pose = np.array([[0., 1., 0.], [0., .5, 0.], [-.12, .05, 0.], [0., 0., 0.]])
    shifted = pose + np.array([.1, 0., 0.])
    frames = [
        {'joints': dict(zip(names, row.tolist()))}
        for row in (pose, pose)
    ]
    payload = {'frames': frames, 'jointNames': names, 'footRestPitchRadians': {'left': 0.},
               'loop': {'enabled': False}}
    sampled = sample_material_foot_points(payload, [.5], points=np.stack([pose, shifted]))['left']

    midpoint = pose + np.array([.05, 0., 0.])
    expected_heel, expected_toe = material_foot_points(
        midpoint[names.index('left_ankle')], midpoint[names.index('left_foot')],
        sampled['sideAxis'][0], 0.)
    np.testing.assert_allclose(sampled['heel'][0], expected_heel)
    np.testing.assert_allclose(sampled['toe'][0], expected_toe)
    assert sampled['sideAxis'].shape == (1, 3)


def test_material_foot_axis_transports_through_candidate_keyframes_before_playback_sample():
    from exercise_motion_pkg.foot_geometry import _sample_material_foot_geometry
    from exercise_motion_pkg.temporal_quality import transport_side

    names = ['left_hip', 'left_knee', 'left_ankle', 'left_foot']
    pose = np.array([[0., 1., 0.], [0., .5, 0.], [0., .1, 0.], [.12, .04, 0.]])
    frames = [
        {'joints': dict(zip(names, row.tolist())),
         'boneSides': {'left_ankle->left_foot': [0., 0., 1.]}}
        for row in (pose, pose)
    ]
    payload = {'frames': frames, 'jointNames': names}
    keyframes = np.stack([pose.copy(), pose.copy()])
    keyframes[0, names.index('left_foot')] += [0., .025, 0.]
    cursor = np.array([.5])
    sampled_points = (keyframes[0] + keyframes[1])[None, :, :] * .5

    geometry = _sample_material_foot_geometry(
        payload, cursor, sampled_points, keyframe_points=keyframes)
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    sample_axis = sampled_points[0, toe] - sampled_points[0, ankle]
    sample_axis /= np.linalg.norm(sample_axis)
    endpoint_sides = []
    for frame_index in (0, 1):
        source_axis = pose[toe] - pose[ankle]
        source_axis /= np.linalg.norm(source_axis)
        candidate_axis = keyframes[frame_index, toe] - keyframes[frame_index, ankle]
        candidate_axis /= np.linalg.norm(candidate_axis)
        source_side = np.array([0., 0., 1.])
        candidate_side = transport_side(source_side, source_axis, candidate_axis)
        endpoint_sides.append(transport_side(candidate_side, candidate_axis, sample_axis))
    angle = np.arctan2(
        np.dot(sample_axis, np.cross(*endpoint_sides)),
        np.dot(*endpoint_sides),
    ) * .5
    expected = (endpoint_sides[0] * np.cos(angle)
                + np.cross(sample_axis, endpoint_sides[0]) * np.sin(angle))

    np.testing.assert_allclose(geometry['left']['lateral'][0], expected, atol=1e-12)


def test_contact_shoe_basis_flattens_only_fullsole_and_preserves_free_heel_pitch():
    from exercise_motion_pkg.foot_geometry import shoe_orientation_tracks

    names = ['left_ankle', 'left_foot']
    points = np.array([
        [[0., .1, 0.], [.18, .1, 0.]],
        [[0., .1, 0.], [.18, .12, 0.]],
        [[0., .1, 0.], [.18, .14, 0.]],
    ])
    original = points.copy()
    evidence = {
        'contacts': [{
            'jointName': 'left_foot', 'contactState': 'full_sole',
            'contactMotion': 'stationary', 'surfaceKind': 'ground',
            'startFrame': 0, 'endFrame': 0,
        }],
        'footPatchEvidence': {'available': True, 'feet': {
            'left': {'states': ['full_sole', 'toe_only', 'airborne']},
        }},
        '_fitFrameFootPatchStatesBySide': {
            'left': ['full_sole', 'toe_only', 'airborne'],
        },
    }
    frames = [{
        'timeSec': index / 30.,
        'joints': dict(zip(names, points[index].tolist())),
        'boneSides': {'left_ankle->left_foot': [0., 0., 1.]},
    } for index in range(len(points))]
    payload = {
        'frames': frames, 'jointNames': names,
        'sourceFootSupportEvidence': evidence,
        'renderFloorY': 0., 'groundContactMode': 'continuous',
        'footRestPitchRadians': {'left': 0.},
    }

    tracks = shoe_orientation_tracks(payload, points)

    assert tracks['left']['contactMask'].tolist() == [True, False, False]
    contact_up = np.cross(tracks['left']['side'][0], tracks['left']['forward'][0])
    np.testing.assert_allclose(contact_up, [0., 1., 0.], atol=1e-10)
    # Outside fullsole, the source toe-rise angle remains at the same samples;
    # only the material side is transported to avoid an abrupt roll change.
    free_axis = points[1, 1] - points[1, 0]
    free_axis /= np.linalg.norm(free_axis)
    np.testing.assert_allclose(tracks['left']['forward'][1], free_axis, atol=1e-10)
    assert tracks['left']['forward'][2, 1] > tracks['left']['forward'][1, 1]
    for forward, side_axis in zip(tracks['left']['forward'], tracks['left']['side']):
        assert np.isfinite(forward).all() and np.isfinite(side_axis).all()
        assert np.dot(forward, side_axis) == pytest.approx(0., abs=1e-10)
        assert np.linalg.norm(side_axis) == pytest.approx(1., abs=1e-10)
    assert np.dot(tracks['left']['side'][0], tracks['left']['side'][1]) > .99
    np.testing.assert_array_equal(points, original)


def test_serialized_material_basis_is_authoritative_without_contact_evidence():
    names = ['left_ankle', 'left_foot']
    pose = np.array([[0., .1, 0.], [.18, .1, 0.]])
    forward = np.array([1., .1, .2]); forward /= np.linalg.norm(forward)
    side_axis = np.array([-.1, 0., 1.])
    side_axis -= forward * np.dot(side_axis, forward)
    side_axis /= np.linalg.norm(side_axis)
    frames = [{
        'joints': dict(zip(names, pose.tolist())),
        'boneSides': {'left_ankle->left_foot': [0., 0., 1.]},
        'shoeOrientation': {'left': {
            'forward': forward.tolist(), 'side': side_axis.tolist(),
        }},
    } for _ in range(2)]
    payload = {'frames': frames, 'jointNames': names,
               'footRestPitchRadians': {'left': -.4}}

    sampled = sample_material_foot_points(
        payload, [0., 1.], points=np.repeat(pose[None], 2, axis=0))['left']
    expected_heel = pose[1] - 1.15 * np.linalg.norm(pose[1] - pose[0]) * forward
    np.testing.assert_allclose(sampled['heel'], np.repeat(expected_heel[None], 2, axis=0))
    np.testing.assert_allclose(sampled['forwardAxis'], np.repeat(forward[None], 2, axis=0))
    np.testing.assert_allclose(sampled['sideAxis'], np.repeat(side_axis[None], 2, axis=0))


def test_material_foot_sampler_without_candidate_uses_fixed_rig_playback():
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.rig_playback import sample_rig

    source = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(source['joints'])
    pose = np.asarray([source['joints'][name] for name in names], dtype=float)
    track = np.repeat(pose[None], 2, axis=0)
    rig = FixedRig(track, names)
    fixed_rig = {'version': 1, 'jointNames': names, 'parents': rig.parents, 'order': rig.order,
                 'offsets': rig.offsets.tolist(),
                 'rotationJointNames': [names[joint] for joint in rig.active],
                 'coordinates': rig.initial.tolist()}
    frames = [{'joints': dict(zip(names, row.tolist()))} for row in track]
    payload = {'frames': frames, 'jointNames': names, 'fixedRig': fixed_rig,
               'footRestPitchRadians': {'left': 0.}, 'loop': {'enabled': False}}

    cursor = np.array([.5])
    playback_points = sample_rig(fixed_rig, cursor, wrap=False)
    sampled = sample_material_foot_points(payload, cursor)['left']
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    expected_heel, expected_toe = material_foot_points(
        playback_points[:, ankle], playback_points[:, toe], sampled['sideAxis'], 0.)
    np.testing.assert_allclose(sampled['heel'], expected_heel)
    np.testing.assert_allclose(sampled['toe'], expected_toe)


def test_production_shoe_vertices_match_validation_in_rotated_poses(tmp_path):
    root = Path(__file__).resolve().parents[1]
    three = root / 'build/exercise_motion/web-assets/three.module.0.169.0.js'
    if not shutil.which('node') or not three.is_file():
        pytest.skip('Requires Node and the cached production Three.js module')
    cases = []
    expected = []
    for rotation in [Rotation.identity(), Rotation.from_euler('xyz', [.5, -.7, 1.2])]:
        for lift in [0., -15.]:
            lateral = np.array([0., 0., 1.])
            ankle = Rotation.from_rotvec(lateral * np.deg2rad(lift)).apply([-.12, .055, 0.])
            knee = ankle + [0., .4, 0.]
            ankle, toe, knee, lateral = [rotation.apply(p) for p in (ankle, np.zeros(3), knee, lateral)]
            pitch = float(np.arctan2(-.055, .12))
            orientation_forward = rotation.apply([1., .08, .03])
            orientation_forward /= np.linalg.norm(orientation_forward)
            orientation_side = rotation.apply([-.03, 0., 1.])
            orientation_side -= orientation_forward * np.dot(orientation_side, orientation_forward)
            orientation_side /= np.linalg.norm(orientation_side)
            orientation = {'forward': orientation_forward, 'side': orientation_side}
            expected.append(shoe_vertices(
                ankle, toe, lateral, pitch, .2, orientation=orientation))
            cases.append({'ankle': ankle.tolist(), 'toe': toe.tolist(), 'knee': knee.tolist(),
                          'lateral': lateral.tolist(), 'pitch': pitch,
                          'orientation': {key: value.tolist() for key, value in orientation.items()},
                          'axes': [rotation.apply(v).tolist() for v in np.eye(3)]})
    source = tmp_path / 'cases.json'
    source.write_text(json.dumps(cases))
    script = tmp_path / 'shoes.mjs'
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const code = fs.readFileSync(process.argv[3], 'utf8');
const kernel = code.slice(0, code.indexOf('    function wearColor('));
const build = new Function('THREE', 'scene', kernel + 'return {shoe:wearShoe, mesh:wearMeshData};')(THREE,new THREE.Scene());
const result = JSON.parse(fs.readFileSync(process.argv[4])).map(c => {
  const vec = v => new THREE.Vector3(...v), mesh = build.mesh();
  build.shoe(mesh, vec(c.ankle), vec(c.toe), {side:vec(c.axes[0]),up:vec(c.axes[1]),forward:vec(c.axes[2])},
    .2, 'primary', vec(c.knee), vec(c.lateral), c.pitch,
    {forward:c.orientation.forward,side:c.orientation.side});
  return {vertices:mesh.vertices.map(v => v.toArray()), fills:mesh.faces.map(face => face.fill)};
});
console.log(JSON.stringify(result));
''')
    actual = json.loads(subprocess.check_output(
        ['node', str(script), str(three), str(root / 'exercise_motion_pkg/wear_exact_mesh.js'), str(source)],
        text=True, timeout=30))
    for row, vertices in zip(actual, expected):
        np.testing.assert_allclose(row['vertices'], vertices, atol=1e-12)
    assert set(actual[0]['fills']) == {'primary'}

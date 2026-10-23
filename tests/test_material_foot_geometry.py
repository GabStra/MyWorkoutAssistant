import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.foot_geometry import (
    calibrated_foot_rest_pitches, material_floor_heights, material_foot_points,
    sample_material_foot_points, shoe_vertices,
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
    assert material_floor_heights(points, names, {'left': pitch}, .2).min() < -.01


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
            expected.append(shoe_vertices(ankle, toe, lateral, pitch, .2))
            cases.append({'ankle': ankle.tolist(), 'toe': toe.tolist(), 'knee': knee.tolist(),
                          'lateral': lateral.tolist(), 'pitch': pitch,
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
    .2, 'primary', vec(c.knee), vec(c.lateral), c.pitch);
  return mesh.vertices.map(v => v.toArray());
});
console.log(JSON.stringify(result));
''')
    actual = json.loads(subprocess.check_output(
        ['node', str(script), str(three), str(root / 'exercise_motion_pkg/wear_exact_mesh.js'), str(source)],
        text=True, timeout=30))
    np.testing.assert_allclose(actual, expected, atol=1e-12)

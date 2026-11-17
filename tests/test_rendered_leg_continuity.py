import copy
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from exercise_motion_pkg.temporal_quality import rendered_bone_roll_metrics, rendered_leg_sides
from exercise_motion_pkg import bake_and_rank as bake


def test_fixed_foot_does_not_roll_when_knee_bend_plane_changes():
    frames = [{"joints": {
        "left_hip": [.2 * np.cos(angle), 1., .2 * np.sin(angle)],
        "left_knee": [0., .5, 0.], "left_ankle": [0., 0., 0.],
        "left_foot": [0., -.08, .2],
    }} for angle in np.linspace(0., 1.5, 30)]
    sides = rendered_leg_sides(frames)
    assert np.linalg.norm(np.array(sides[-1]['left_knee->left_ankle'])
                          - sides[0]['left_knee->left_ankle']) > .1
    for frame in sides:
        np.testing.assert_allclose(frame['left_ankle->left_foot'],
                                   sides[0]['left_ankle->left_foot'], atol=1e-10)


def test_timed_ground_patch_owns_roll_without_changing_pitch_or_unknown_contacts():
    from exercise_motion_pkg.temporal_quality import transport_corrected_bone_sides
    frames = [{'joints': {'left_ankle': [0., .1, 0.], 'left_foot': [0., 0., .2]}}
              for _ in range(4)]
    payload = {'jointNames': ['left_ankle', 'left_foot'], 'frames': copy.deepcopy(frames),
               'sourceFootSupportEvidence': {'contacts': [{
                   'jointName': 'left_foot', 'contactState': 'toe_only',
                   'supportKind': 'observed_foot_patch', 'contactMotion': 'stationary',
                   'surfaceKind': 'ground', 'startFrame': 1, 'endFrame': 2,
               }]}}
    evidence = copy.deepcopy(payload['sourceFootSupportEvidence'])
    transport_corrected_bone_sides(frames, payload)
    assert payload['sourceFootSupportEvidence'] == evidence
    assert [f['joints'] for f in payload['frames']] == [f['joints'] for f in frames]
    for index, frame in enumerate(payload['frames']):
        assert ('left_ankle->left_foot' in frame.get('boneSides', {})) == (index in [1, 2])
        if index in [1, 2]:
            np.testing.assert_allclose(frame['boneSides']['left_ankle->left_foot'], [-1., 0., 0.])


@pytest.mark.parametrize("slug", ["dumbbell-thruster", "bulgarian-split-squat"])
def test_retained_leg_tracks_do_not_flip(slug):
    payload = json.loads((Path(__file__).parent / "fixtures" / f"{slug}-renderer.json").read_text())
    metrics = rendered_bone_roll_metrics(payload)
    assert not metrics["severe"], metrics["events"]
    assert metrics["renderedLegFrameCount"] == len(payload["frames"])
    assert metrics["maxStepDegrees"] < 12


def test_production_javascript_matches_validated_leg_orientations(tmp_path):
    root = Path(__file__).resolve().parents[1]
    three = root / "build/exercise_motion/exercise-library/dumbbell-thruster/selected/three.module.0.169.0.js"
    if not shutil.which("node") or not three.is_file():
        pytest.skip("Production JavaScript parity requires Node and the local preview Three.js module")
    fixture = root / "tests/fixtures/dumbbell-thruster-renderer.json"
    payload = json.loads(fixture.read_text())
    first = payload['frames'][0]
    forward = np.asarray(first['joints']['left_foot']) - first['joints']['left_ankle']
    observed = np.cross(forward, [0., 1., 0.])
    first.setdefault('boneSides', {})['left_ankle->left_foot'] = (observed / np.linalg.norm(observed)).tolist()
    fixture = tmp_path / 'observed-sole.json'
    fixture.write_text(json.dumps(payload))
    script = tmp_path / "replay.mjs"
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const code = fs.readFileSync(process.argv[3], 'utf8');
const unit = code.slice(code.indexOf('    function wearUnit('), code.indexOf('    function wearAxes('));
const kernel = code.slice(code.indexOf('    function wearCoordinateLegSides('), code.indexOf('    function wearLimbSides('));
const resolve = new Function('THREE', unit + kernel + '; return wearCoordinateLegSides;')(THREE);
const sole = code.slice(code.indexOf('    function wearApplyExportedSoleSides('), code.indexOf('    function updateWearExactMesh('));
const applySole = new Function('THREE', sole + '; return wearApplyExportedSoleSides;')(THREE);
let previous = new Map();
const result = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')).frames.map(frame => {
    const joints = Object.fromEntries(Object.entries(frame.joints).map(([k,v]) => [k, new THREE.Vector3(...v)]));
    previous = resolve(joints, new Map(), previous);
    applySole(frame, previous);
    return Object.fromEntries([...previous].map(([k,v]) => [k,v.toArray()]));
});
console.log(JSON.stringify(result));
''')
    actual = json.loads(subprocess.check_output(
        ["node", str(script), str(three), str(root / "exercise_motion_pkg/wear_exact_mesh.js"), str(fixture)],
        text=True, timeout=30,
    ))
    expected = rendered_leg_sides(json.loads(fixture.read_text())["frames"])
    for left, right in zip(actual, expected, strict=True):
        assert left.keys() == right.keys()
        for key in left:
            np.testing.assert_allclose(left[key], right[key], atol=1e-10)


def test_production_fixed_rig_interpolation_matches_contact_foot_sampler(tmp_path):
    node = shutil.which('node')
    root = Path(__file__).resolve().parents[1]
    three = root / 'build/exercise_motion/web-assets/three.module.0.169.0.js'
    if not node or not three.is_file():
        pytest.skip('Requires Node and the locally cached preview Three.js module')

    from types import SimpleNamespace

    from exercise_motion_pkg.contact_interpolation import (
        build_contact_foot_tracks, sample_contact_foot_tracks,
    )
    from exercise_motion_pkg.preview import _build_html
    from exercise_motion_pkg.rig_playback import sample_rig

    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    offsets = np.zeros((len(names), 3))
    offsets[names.index('left_hip')] = [0., 1.2, 0.]
    offsets[names.index('left_knee')] = [0., -.65, 0.]
    offsets[names.index('left_ankle')] = [0., -.65, 0.]
    offsets[names.index('left_foot')] = [0., 0., .2]
    coordinates = np.zeros((4, 3 + 3 * len(names)))
    for frame in range(4):
        coordinates[frame, 0] = frame * .01
        coordinates[frame, 3 + 3 * names.index('left_knee')] = .15 + .04 * frame
        coordinates[frame, 3 + 3 * names.index('left_ankle')] = -.1 + .1 * frame
    rig = {
        'version': 1, 'jointNames': names, 'parents': [-1, 0, 1, 2, 3],
        'order': [0, 1, 2, 3, 4], 'offsets': offsets.tolist(),
        'interpolation': 'limited_quaternion_hermite_v2',
        'rotationJointNames': names, 'coordinates': coordinates.tolist(),
    }
    key_points = sample_rig(rig, np.arange(4), wrap=False)
    pinned = np.zeros((4, len(names)), dtype=bool)
    pinned[1:3, names.index('left_ankle')] = True
    pinned[1:3, names.index('left_foot')] = True
    rig['contactFootTracks'] = build_contact_foot_tracks(
        SimpleNamespace(names=names), key_points, pinned)
    queries = np.array([0., .25, .5, .75, 1., 1.25, 1.5, 1.75, 2., 2.25, 2.5, 2.75])
    html = _build_html({'title': 'contact interpolation parity', 'frames': [], 'jointNames': names})
    start = html.index('    function limitedRigTangent(')
    end = html.index('    function getInterpolatedFrame()', start)
    kernel = html[start:end]
    script = tmp_path / 'contact-rig-parity.mjs'
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const playbackState = {loopable:input.wrap};
const interpolate = new Function('THREE', 'playbackState', fs.readFileSync(process.argv[4], 'utf8')
  + '; return interpolateFixedRig;')(THREE, playbackState);
const sampleRig = rig => input.queries.map(cursor => {
  const count = rig.coordinates.length;
  const normalized = input.wrap ? ((cursor % count) + count) % count : Math.max(0, Math.min(count - 1, cursor));
  const first = Math.floor(normalized), last = input.wrap ? (first + 1) % count : Math.min(first + 1, count - 1);
  return interpolate(rig, first, last, normalized - first);
});
const rawRig = {...input.rig};
delete rawRig.contactFootTracks;
console.log(JSON.stringify({base:sampleRig(rawRig), contacted:sampleRig(input.rig)}));
''', encoding='utf-8')
    kernel_path = tmp_path / 'contact-rig-kernel.js'
    kernel_path.write_text(kernel, encoding='utf-8')
    input_path = tmp_path / 'contact-rig-input.json'
    input_path.write_text(json.dumps({'rig': rig, 'queries': queries.tolist(), 'wrap': False}), encoding='utf-8')
    actual_dicts = json.loads(subprocess.check_output(
        [node, str(script), str(three), str(input_path), str(kernel_path)],
        text=True, timeout=30,
    ))
    raw_base = np.asarray([[frame[name] for name in names] for frame in actual_dicts['base']])
    expected = sample_contact_foot_tracks(rig, queries, raw_base, wrap=False)
    actual = np.asarray([[frame[name] for name in names] for frame in actual_dicts['contacted']])
    np.testing.assert_allclose(actual, expected, atol=1e-10, rtol=1e-10)

    loop_rig = {**rig, 'coordinates': np.asarray(coordinates).copy().tolist()}
    for frame, angle in enumerate([3.0, 3.1, -3.1, -3.0]):
        loop_rig['coordinates'][frame][3 + 3 * names.index('left_ankle') + 1] = angle
    loop_key_points = sample_rig(loop_rig, np.arange(4), wrap=False)
    loop_pinned = np.zeros((4, len(names)), dtype=bool)
    loop_pinned[:, names.index('left_foot')] = True
    loop_rig['contactFootTracks'] = build_contact_foot_tracks(
        SimpleNamespace(names=names), loop_key_points, loop_pinned)
    loop_queries = np.array([.25, 3.25, 3.5, 3.75])
    loop_input_path = tmp_path / 'contact-rig-loop-input.json'
    loop_input_path.write_text(json.dumps({
        'rig': loop_rig, 'queries': loop_queries.tolist(), 'wrap': True,
    }), encoding='utf-8')
    loop_actual_dicts = json.loads(subprocess.check_output(
        [node, str(script), str(three), str(loop_input_path), str(kernel_path)],
        text=True, timeout=30,
    ))
    loop_base = np.asarray([[frame[name] for name in names] for frame in loop_actual_dicts['base']])
    loop_expected = sample_contact_foot_tracks(loop_rig, loop_queries, loop_base, wrap=True)
    loop_actual = np.asarray([[frame[name] for name in names] for frame in loop_actual_dicts['contacted']])
    np.testing.assert_allclose(loop_actual, loop_expected, atol=1e-10, rtol=1e-10)


@pytest.mark.parametrize('protected', [False, True])
def test_production_native_v2_contact_frame_blend_matches_sampler(tmp_path, protected):
    """Native v2 contact must blend the correction frame with the projection weight.

    A non-coplanar raw foot heading, sampled material direction and side axis
    make the blend observable: the raw and sampled frames mix, an exact key
    still returns the stored pose when unprotected, and full weight reaches the
    material target. The Python reference uses the production default
    ``preserve_keys=True``, so the preview must apply the same zero-slope
    between-key envelope at quarter and three-quarter samples. The parameterized
    supported knee exercises the protected branch: an exact key may project
    while an unprotected key stays stored.
    """
    node = shutil.which('node')
    root = Path(__file__).resolve().parents[1]
    three = root / 'build/exercise_motion/web-assets/three.module.0.169.0.js'
    if not node or not three.is_file():
        pytest.skip('Requires Node and the locally cached preview Three.js module')

    from exercise_motion_pkg.contact_interpolation import sample_contact_foot_tracks
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
    from exercise_motion_pkg.preview import _build_html

    geometry_fixture = json.loads(
        (Path(__file__).parent / 'fixtures' / 'native_foot_geometry_v1.json').read_text())
    geometry = geometry_fixture['reference']
    side_geometry = geometry['sides']['left']

    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot',
             'right_hip', 'left_shoulder', 'right_shoulder']
    hip = np.array([0., 1.2, 0.])
    toe = np.array([0., 0., .2])
    direction = np.array([0., np.sin(.1), np.cos(.1)])
    ankle = toe - .2 * direction
    reach = ankle - hip
    distance = np.linalg.norm(reach)
    axis = reach / distance
    along = distance / 2.
    bend = np.array([1., 0., 0.]) - axis * axis[0]
    knee = hip + axis * along + bend / np.linalg.norm(bend) * np.sqrt(.65 ** 2 - along ** 2)
    hip_width, shoulder_width = .5, .44
    foot_scale = max(hip_width * .98, shoulder_width * .58)
    offsets = np.zeros((len(names), 3))
    offsets[names.index('left_hip')] = hip
    offsets[names.index('left_knee')] = knee - hip
    offsets[names.index('left_ankle')] = ankle - knee
    offsets[names.index('left_foot')] = toe - ankle
    offsets[names.index('right_hip')] = [hip_width, 1.2, 0.]
    offsets[names.index('left_shoulder')] = [-shoulder_width / 2, 1.65, 0.]
    offsets[names.index('right_shoulder')] = [shoulder_width / 2, 1.65, 0.]

    raw_forward = (toe - ankle) / np.linalg.norm(toe - ankle)
    yaw = np.deg2rad(14.)
    track_direction = np.array([
        np.cos(yaw) * raw_forward[0] + np.sin(yaw) * raw_forward[2],
        raw_forward[1],
        -np.sin(yaw) * raw_forward[0] + np.cos(yaw) * raw_forward[2],
    ])
    track_direction /= np.linalg.norm(track_direction)
    side_axis = np.array([1., .45, 0.])
    side_axis -= track_direction * np.dot(side_axis, track_direction)
    side_axis /= np.linalg.norm(side_axis)
    assert abs(float(np.dot(side_axis, np.cross(raw_forward, track_direction)))) > .05

    triangle_index = 11
    barycentric = np.asarray([.2, .3, .5])
    reference_length = side_geometry['ankleToFootJointLengthMeters']
    material_mesh = shoe_vertices(
        ankle, ankle + track_direction * .2, side_axis, None, foot_scale,
        native_geometry=side_geometry)
    material_point = barycentric @ material_mesh[shoe_triangles()[triangle_index]]
    forward, lateral, up, length = native_foot_bone_frame(
        ankle, ankle + track_direction * .2, side_axis)
    delta = material_point - ankle
    local = np.array([delta @ forward, delta @ lateral, delta @ up])
    local *= reference_length / float(length[0])
    target_world = material_point + np.array([0., .02, .01])
    episode = {
        'startFrame': 1, 'endFrame': 2, 'anchorId': 'left-native-anchor',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:left_ankle->left_foot',
        'triangleIndex': triangle_index, 'barycentric': barycentric.tolist(),
        'materialOffsetLocalMeters': local.tolist(),
        'referenceLengthMeters': reference_length,
        'targetWorld': target_world.tolist(), 'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': float(target_world[1]),
    }
    rig = {
        'version': 1, 'jointNames': names, 'parents': [-1, 0, 1, 2, 3, 0, 0, 0],
        'order': [0, 1, 2, 3, 4, 5, 6, 7], 'offsets': offsets.tolist(),
        'interpolation': 'limited_quaternion_hermite_v2',
        'rotationJointNames': ['left_hip', 'left_knee', 'left_ankle', 'left_foot'],
        'coordinates': [[0., 0., 0.] + [0.] * 12 for _ in range(3)],
        'contactFootTracks': {'version': 2, 'left': {
            'active': [False, True, True],
            'directions': [track_direction.tolist()] * 3,
            'sideAxes': [side_axis.tolist()] * 3,
            'anchorIds': [None, 'left-native-anchor', 'left-native-anchor'],
            'episodes': [episode],
        }},
    }
    support_tracks = None
    if protected:
        support_tracks = {
            'version': 1, 'source': 'validated_stationary_body_support',
            'joints': {'left_knee': {'episodeIds': [None, 'left-support', 'left-support']}},
        }
        rig['supportJointTracks'] = support_tracks
    frames = [{'joints': {
        'left_hip': hip.tolist(), 'right_hip': (hip + [hip_width, 0., 0.]).tolist(),
        'left_shoulder': [-shoulder_width / 2, 1.65, 0.],
        'right_shoulder': [shoulder_width / 2, 1.65, 0.],
    }} for _ in range(3)]

    html = _build_html({'title': 'native v2 contact parity', 'frames': [], 'jointNames': names})
    kernel_start = html.index('    function limitedRigTangent(')
    kernel_end = html.index('    function getInterpolatedFrame()', kernel_start)
    wear_start = html.index('    let wearStableBodyProportions = null;')
    wear_end = html.index('    const perspectiveCamera = new THREE.PerspectiveCamera(')
    validate_start = html.index('    function wearValidateNativeFootGeometry(')
    validate_end = html.index('    let activeNativeFootGeometry =', validate_start)
    kernel = (
        html[validate_start:validate_end]
        + '    let activeNativeFootGeometry = wearValidateNativeFootGeometry(input.nativeFootGeometry);\n'
        + html[wear_start:wear_end] + html[kernel_start:kernel_end]
    )
    kernel_path = tmp_path / 'native-v2-kernel.js'
    kernel_path.write_text(kernel, encoding='utf-8')
    script = tmp_path / 'native-v2-parity.mjs'
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const playbackState = {loopable:input.wrap, frames:input.frames};
const api = new Function('THREE', 'playbackState', 'input', fs.readFileSync(process.argv[4], 'utf8')
  + '; return {interpolateFixedRig};')(THREE, playbackState, input);
const sampleRig = rig => input.queries.map(cursor => {
  const count = rig.coordinates.length;
  const normalized = input.wrap ? ((cursor % count) + count) % count : Math.max(0, Math.min(count - 1, cursor));
  const first = Math.floor(normalized), last = input.wrap ? (first + 1) % count : Math.min(first + 1, count - 1);
  const pose = api.interpolateFixedRig(rig, first, last, normalized - first);
  return {joints:pose, sideAxes:pose.contactSideAxes ?? {}};
});
const rawRig = {...input.rig};
delete rawRig.contactFootTracks;
console.log(JSON.stringify({base:sampleRig(rawRig), contacted:sampleRig(input.rig)}));
''', encoding='utf-8')
    payload = tmp_path / 'native-v2-input.json'
    cursors = [.25, .5, .75, 1., 1.25, 1.5]
    key_index = cursors.index(1.)
    payload.write_text(json.dumps({
        'rig': rig, 'queries': cursors, 'wrap': False, 'frames': frames,
        'nativeFootGeometry': geometry,
    }), encoding='utf-8')
    actual = json.loads(subprocess.check_output(
        [node, str(script), str(three), str(payload), str(kernel_path)],
        text=True, timeout=60,
    ))
    base = np.asarray([[frame['joints'][name] for name in names] for frame in actual['base']])
    contacted = np.asarray([[frame['joints'][name] for name in names]
                            for frame in actual['contacted']])

    sampling_rig = {**rig, '_supportJointTracksForSampling': support_tracks} \
        if support_tracks is not None else rig
    expected, expected_axes = sample_contact_foot_tracks(
        sampling_rig, np.asarray(cursors), base, wrap=False,
        native_foot_geometry=geometry, foot_scale=foot_scale,
        return_side_axes=True)
    np.testing.assert_allclose(contacted, expected, atol=1e-10, rtol=1e-10)

    # An unprotected exact key keeps the stored pose; a protected key owns it.
    if protected:
        assert not np.allclose(contacted[key_index], base[key_index], atol=1e-10)
    else:
        np.testing.assert_array_equal(contacted[key_index], base[key_index])
    # Off-key corrections keep the bone length.
    off_key = np.arange(len(cursors)) != key_index
    np.testing.assert_allclose(
        np.linalg.norm(contacted[off_key, 4] - contacted[off_key, 3], axis=1), .2, atol=1e-10)
    for index, expected_axis in enumerate(expected_axes['left']):
        np.testing.assert_allclose(
            actual['contacted'][index]['sideAxes']['left_ankle->left_foot'],
            expected_axis, atol=1e-10)

    if protected:
        # The protected projection fixes the knee and moves the distal pose.
        assert not np.allclose(contacted[-1], base[-1], atol=1e-10)
        np.testing.assert_allclose(contacted[-1, 2], base[-1, 2], atol=1e-10)
    else:
        # Full weight reaches the bound material target through the blended frame.
        full_ankle = np.asarray(actual['contacted'][-1]['joints']['left_ankle'])
        material = full_ankle + (track_direction * local[0] + side_axis * local[1]
                                 + np.cross(side_axis, track_direction) * local[2]) * (
            .2 / reference_length)
        np.testing.assert_allclose(material, target_world, atol=1e-10)


def test_observed_anchor_identity_survives_normalization_and_correction():
    frames = [{"joints": {"pelvis": [0, 1, 0], "head": [0, 2, 0],
                          "left_foot": [i * .01, 0, .1]}} for i in range(30)]
    contacts = [{"jointName": "left_foot", "startFrame": start, "endFrame": end,
                 "anchorGroupId": "left-observed-toe", "supportKind": "observed_foot_patch",
                 "contactState": "full_sole", "contactMotion": "stationary"}
                for start, end in [(0, 9), (20, 29)]]
    payload = {"fps": 30, "frames": frames}
    evidence = {"contacts": contacts}
    corrected, details = bake.apply_source_contact_sequence_correction(payload, evidence)
    anchors = [interval["anchor"] for interval in details["contactIntervals"]]
    assert anchors[0] == anchors[1]
    assert bake.source_confirmed_support_stationarity_metrics(corrected, evidence)["passed"]
    moved = copy.deepcopy(corrected)
    for frame in moved["frames"][20:]:
        frame["joints"]["left_foot"][0] += .25
    metrics = bake.source_confirmed_support_stationarity_metrics(moved, evidence)
    assert "left_source_confirmed_anchor_relocated" in metrics["rejectionReasons"]
    # A new observed support location must not be forced to the old anchor.
    evidence["contacts"][1]["anchorGroupId"] = "new-location"
    _, details = bake.apply_source_contact_sequence_correction(payload, evidence)
    assert details["contactIntervals"][0]["anchor"] != details["contactIntervals"][1]["anchor"]

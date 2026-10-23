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

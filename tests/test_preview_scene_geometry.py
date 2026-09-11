"""Exercise the production JS frame transport and floor anchor with Node."""
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_inferred_arm_frame_closes_without_a_restart_snap(tmp_path):
    node = shutil.which('node')
    asset = ROOT / 'build/exercise_motion/web-assets/three.module.0.169.0.js'
    if not node or not asset.exists():
        pytest.skip('Requires Node and the locally cached Three.js asset')
    shutil.copyfile(asset, tmp_path / 'three.mjs')
    source = (ROOT / 'exercise_motion_pkg/wear_exact_mesh.js').read_text()
    script = tmp_path / 'orientations.mjs'
    script.write_text('''
import * as THREE from './three.mjs';
import {readFileSync} from 'node:fs';
const scene = new THREE.Scene();
let activeRenderFrame = null, fixedRoot = false;
const getFrameTranslation = () => null;
const toWorldPoint = point => new THREE.Vector3(...point);
let playbackState = {frames: JSON.parse(readFileSync(0, 'utf8')), loopable: false};
''' + source + '''
const run = loopable => {
  playbackState.loopable = loopable;
  return wearBuildStableSidesByFrame().map(s => s.get('left_shoulder->left_elbow').toArray());
};
console.log(JSON.stringify({open:run(false), closed:run(true)}));
''', encoding='utf-8')
    template = json.loads((ROOT / 'tests/fixtures/sequence_stabilization_stance.json').read_text())['joints']
    directions = []
    frames = []
    for phase in np.linspace(0, 2*np.pi, 120, endpoint=False):
        direction = np.array([.5*np.cos(phase), np.sqrt(.75), .5*np.sin(phase)])
        directions.append(direction)
        joints = dict(template)
        joints['left_elbow'] = (np.array(joints['left_shoulder']) + .3*direction).tolist()
        frames.append({'joints': joints})
    result = json.loads(subprocess.run([node, str(script)], input=json.dumps(frames),
                                      capture_output=True, text=True, timeout=30, check=True).stdout)
    from exercise_motion_pkg.temporal_quality import transport_side

    def steps(sides):
        values = []
        for index, side in enumerate(sides):
            axis = directions[index]
            previous = transport_side(np.array(sides[index-1]), directions[index-1], axis)
            values.append(np.rad2deg(np.arctan2(axis @ np.cross(previous, side), previous @ side)))
        return np.abs(values)

    assert steps(result['open'])[0] > 10  # The unclosed transport exhibits the original failure.
    assert steps(result['closed']).max() < 2
    np.testing.assert_allclose(np.linalg.norm(result['closed'], axis=1), 1, atol=1e-12)
    np.testing.assert_allclose(np.sum(np.array(result['closed'])*directions, axis=1), 0, atol=1e-12)


def test_floor_center_uses_body_position_not_reaching_limbs(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Requires Node')
    source = (ROOT / 'exercise_motion_pkg/preview.py').read_text(encoding='utf-8')
    kernel = source[source.index('    function bakedWearFloorCenter()'):source.index('    function refreshGroundPlacement()')]
    script = tmp_path / 'floor.js'
    script.write_text('''
const playbackState = {frames: [
 {joints:{pelvis:[1,2,3],hand:[100,2,100]}},
 {joints:{pelvis:[3,2,5],hand:[-100,2,-100]}}
]};
const getFrameRootPoint = frame => ({x:frame.joints.pelvis[0],z:frame.joints.pelvis[2]});
''' + kernel.replace('{{', '{').replace('}}', '}') + '\nconsole.log(JSON.stringify(bakedWearFloorCenter()));', encoding='utf-8')
    value = json.loads(subprocess.check_output([node, str(script)], text=True, timeout=15))
    assert value == {'x': 2, 'z': 4}

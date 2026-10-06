import copy
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from exercise_motion_pkg.temporal_quality import rendered_bone_roll_metrics, rendered_leg_sides
from exercise_motion_pkg import bake_and_rank as bake


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
    script = tmp_path / "replay.mjs"
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const code = fs.readFileSync(process.argv[3], 'utf8');
const unit = code.slice(code.indexOf('    function wearUnit('), code.indexOf('    function wearAxes('));
const kernel = code.slice(code.indexOf('    function wearCoordinateLegSides('), code.indexOf('    function wearLimbSides('));
const resolve = new Function('THREE', unit + kernel + '; return wearCoordinateLegSides;')(THREE);
let previous = new Map();
const result = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')).frames.map(frame => {
    const joints = Object.fromEntries(Object.entries(frame.joints).map(([k,v]) => [k, new THREE.Vector3(...v)]));
    previous = resolve(joints, new Map(), previous);
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

import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_solid_torso_shares_shoulder_rim_and_overlaps_caps_in_every_frame(tmp_path):
    root = Path(__file__).resolve().parents[1]
    three = root / "build/exercise_motion/exercise-library/dumbbell-thruster/selected/three.module.0.169.0.js"
    if not shutil.which("node") or not three.is_file():
        pytest.skip("Requires Node and the local preview Three.js module")
    script = tmp_path / "shoulders.mjs"
    script.write_text(r'''import fs from "node:fs";
import assert from "node:assert/strict";
const THREE = await import("data:text/javascript;base64," + fs.readFileSync(process.argv[2]).toString("base64"));
const source = fs.readFileSync(process.argv[3], "utf8");
const kernel = source.slice(0, source.indexOf("    function wearColor(")).replace(
  "const headHeightAtJoint =", "mesh.headStart = mesh.vertices.length; const headHeightAtJoint ="
);
const build = new Function("THREE", "scene", kernel + `
    const originalSegment = wearSegment, originalSphere = wearSphere;
    let segments, spheres;
    wearSegment = (...args) => {
      const first = args[0].vertices.length;
      originalSegment(...args);
      segments.push({start: args[1].clone(), end: args[2].clone(),
        vertices: args[0].vertices.slice(first)});
    };
    wearSphere = (...args) => {
      spheres.push({center: args[1].clone(), radius: args[3]});
      originalSphere(...args);
    };
    return joints => {
      segments = []; spheres = [];
      const mesh = wearBuildHumanoid(joints);
      return {mesh, segments, spheres};
    };
`)(THREE, new THREE.Scene());
const frames = JSON.parse(fs.readFileSync(process.argv[4], "utf8")).frames;
let checked = 0;
for (const frame of frames) {
  const joints = Object.fromEntries(Object.entries(frame.joints).map(([k,v]) => [k,new THREE.Vector3(...v)]));
  const {mesh, segments, spheres} = build(joints);
  assert.equal(spheres[2].radius, spheres[3].radius);
  const torsoFrontRight = mesh.vertices[13], torsoFrontLeft = mesh.vertices[14];
  const torsoBackLeft = mesh.vertices[17];
  const across = torsoFrontRight.clone().sub(torsoFrontLeft);
  const depth = torsoBackLeft.clone().sub(torsoFrontLeft);
  const pairCenter = joints.left_shoulder.clone().lerp(joints.right_shoulder, .5);
  const shoulderAxis = joints.right_shoulder.clone().sub(joints.left_shoulder).normalize();
  assert.ok(Math.abs(across.clone().normalize().dot(shoulderAxis)) > 1 - 1e-10,
    "Upper chest must follow the shoulder line without adding a tilt");
  const torsoCenter = torsoFrontLeft.clone().addScaledVector(across, .5).addScaledVector(depth, .5);
  assert.ok(Math.abs(pairCenter.clone().sub(torsoCenter).dot(across.clone().normalize())) < 1e-6,
    "Upper chest must be centered laterally on the shoulder pair");
  // Waist, chest, upper back, shoulder rim and collar form one tube with shared edges.
  const torsoFaces = mesh.faces.filter(face => face.indices.every(index => index < 40));
  assert.equal(torsoFaces.length, 40);
  const edgeUses = new Map();
  for (const face of torsoFaces) {
    for (let i=0; i<face.indices.length; i++) {
      const a=face.indices[i], b=face.indices[(i+1)%face.indices.length];
      const key=[a,b].sort((a,b)=>a-b).join(",");
      edgeUses.set(key,(edgeUses.get(key) ?? 0)+1);
    }
  }
  for (let i=0; i<8; i++) {
    const key=[12+i,12+(i+1)%8].sort((a,b)=>a-b).join(",");
    assert.equal(edgeUses.get(key),2,"Shoulder rim must be shared by chest and traps");
  }
  for(let i=0;i<8;i++) {
    const lower=mesh.vertices[12+i],upper=mesh.vertices[20+i];
    assert.ok(Math.abs(lower.distanceTo(upper)/spheres[2].radius-1.10)<1e-8,
      "Shoulder connection needs a full-height socket instead of a single edge");
    const key=[20+i,20+(i+1)%8].sort((a,b)=>a-b).join(",");
    assert.equal(edgeUses.get(key),2,"Socket upper rim must join the traps");
  }
  assert.equal(segments.length,10,"Only limbs and hands use separate segments");
  for (const [i,side] of ["left","right"].entries()) {
    const cap = spheres[2+i];
    assert.ok(cap.center.distanceTo(joints[side+"_shoulder"]) < 1e-10);
    const corners = side === "left" ? [15,16] : [12,19];
    const wallStart=mesh.vertices[corners[0]],wallEnd=mesh.vertices[corners[1]];
    const wallVector=wallEnd.clone().sub(wallStart);
    const t=cap.center.clone().sub(wallStart).dot(wallVector)/wallVector.lengthSq();
    assert.ok(t>0 && t<1);
    const sideWallPoint=wallStart.clone().lerp(wallEnd,t);
    assert.ok(sideWallPoint.distanceTo(cap.center) < cap.radius * .80,
      "Torso side wall must overlap the shoulder cap");
    const upperArm = segments[side === "left" ? 4 : 6];
    const armRoot = upperArm.vertices.slice(0,4).reduce((sum,v) => sum.add(v), new THREE.Vector3()).multiplyScalar(.25);
    assert.ok(armRoot.distanceTo(cap.center) < cap.radius * .80,
      "Upper arm must overlap its shoulder cap");
    checked++;
  }
  for(const [start,progress,front,back] of [[4,.45,.18,.24]]) {
    const frontCenter=mesh.vertices[start+1].clone().lerp(mesh.vertices[start+2],.5);
    const backCenter=mesh.vertices[start+5].clone().lerp(mesh.vertices[start+6],.5);
    const center=frontCenter.lerp(backCenter,front/(front+back));
    assert.ok(center.distanceTo(joints.spine1.clone().lerp(joints.neck,progress))<1e-10,
      "Torso rings must follow the original spine rather than an offset shoulder midpoint");
  }
  const headVertices = mesh.vertices.slice(mesh.headStart, mesh.headStart + 12);
  const headUp=joints.head.clone().sub(joints.neck).normalize();
  const headSide=shoulderAxis.clone().addScaledVector(headUp,-shoulderAxis.dot(headUp)).normalize();
  assert.equal(headVertices.length,12);
  for(let r=0;r<3;r++) {
    const ring=headVertices.slice(r*4,r*4+4);
    const center=ring.reduce((sum,v)=>sum.add(v),new THREE.Vector3()).multiplyScalar(.25);
    const neckToCenter=center.clone().sub(joints.neck);
    assert.ok(neckToCenter.clone().cross(headUp).length()<1e-10,
      "Head must remain on the original neck-head axis without a lateral correction");
    for(const [a,b] of [[0,1],[3,2]]) {
      const mirrored=ring[a].clone().addScaledVector(headSide,
        -2*ring[a].clone().sub(center).dot(headSide));
      assert.ok(mirrored.distanceTo(ring[b])<1e-10,"Original box head must remain symmetric");
    }
  }
  const socketUp=mesh.vertices[20].clone().sub(mesh.vertices[12]).normalize();
  const socketForward=shoulderAxis.clone().cross(socketUp).normalize();
  for(let i=0;i<8;i++) {
    const lower=mesh.vertices[4+i], middle=mesh.vertices[28+i], upper=mesh.vertices[12+i];
    for(const axis of [shoulderAxis,socketForward]) {
      const a=lower.dot(axis),b=upper.dot(axis),value=middle.dot(axis);
      assert.ok(value>=Math.min(a,b)-1e-10 && value<=Math.max(a,b)+1e-10,
        "Chest/back transition must not protrude beyond its endpoints");
    }
    const lastSegment=upper.clone().sub(middle);
    assert.ok(lastSegment.dot(socketUp)/lastSegment.length()>.20,
      "Transition into the shoulder socket must not form a horizontal shelf");
  }
  assert.ok(mesh.vertices.every(v => v.toArray().every(Number.isFinite)));
}
console.log(JSON.stringify({checked}));
''')
    result = subprocess.check_output([
        "node", str(script), str(three), str(root / "exercise_motion_pkg/wear_exact_mesh.js"),
        str(root / "tests/fixtures/dumbbell-thruster-renderer.json"),
    ], text=True, timeout=30)
    assert json.loads(result)["checked"] > 200

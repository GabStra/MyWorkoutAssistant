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
  const torsoFrontRight = mesh.vertices[17], torsoFrontLeft = mesh.vertices[18];
  const torsoBackLeft = mesh.vertices[21];
  const across = torsoFrontRight.clone().sub(torsoFrontLeft);
  const depth = torsoBackLeft.clone().sub(torsoFrontLeft);
  const pairCenter = joints.left_shoulder.clone().lerp(joints.right_shoulder, .5);
  const shoulderAxis = joints.right_shoulder.clone().sub(joints.left_shoulder).normalize();
  assert.ok(Math.abs(across.clone().normalize().dot(shoulderAxis)) > 1 - 1e-10,
    "Upper chest must follow the shoulder line without adding a tilt");
  // The back corners flare wider than the front (lat mass), so the ring
  // centroid — not a rectangle midpoint — must sit on the shoulder axis.
  const torsoBackRight = mesh.vertices[22];
  const torsoCenter = [torsoFrontRight, torsoFrontLeft, torsoBackLeft, torsoBackRight]
    .reduce((sum, v) => sum.add(v), new THREE.Vector3()).multiplyScalar(.25);
  assert.ok(Math.abs(pairCenter.clone().sub(torsoCenter).dot(across.clone().normalize())) < 1e-6,
    "Upper chest must be centered laterally on the shoulder pair");
  // Waist, chest, upper back, shoulder rim and collar form one tube with shared edges.
  const torsoFaces = mesh.faces.filter(face => face.indices.every(index => index < 48));
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
    const key=[16+i,16+(i+1)%8].sort((a,b)=>a-b).join(",");
    assert.equal(edgeUses.get(key),2,"Shoulder rim must be shared by chest and traps");
  }
  for(let i=0;i<8;i++) {
    const lower=mesh.vertices[16+i],upper=mesh.vertices[24+i];
    assert.ok(lower.distanceTo(upper)/spheres[2].radius>1.0 && lower.distanceTo(upper)/spheres[2].radius<2.2,
      "Shoulder connection needs a full-height socket instead of a single edge");
    const key=[24+i,24+(i+1)%8].sort((a,b)=>a-b).join(",");
    assert.equal(edgeUses.get(key),2,"Socket upper rim must join the traps");
  }
  assert.equal(segments.length,10,"Only limbs and hands use separate segments");
  for (const [i,side] of ["left","right"].entries()) {
    const cap = spheres[2+i];
    assert.ok(cap.center.distanceTo(joints[side+"_shoulder"]) < 1e-10);
    const corners = side === "left" ? [19,20] : [16,23];
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
  const stableShoulderWidth = new THREE.Vector3(...frames[0].joints.right_shoulder)
    .distanceTo(new THREE.Vector3(...frames[0].joints.left_shoulder));
  for(const [start,progress,front,back] of [[8,.45,.24,.28]]) {
    const frontCenter=mesh.vertices[start+1].clone().lerp(mesh.vertices[start+2],.5);
    const backCenter=mesh.vertices[start+5].clone().lerp(mesh.vertices[start+6],.5);
    const center=frontCenter.lerp(backCenter,front/(front+back));
    // The chest ring intentionally rides .02*shoulderWidth forward of the
    // spine point so the profile carries a pec shelf instead of a plank.
    const depthAxis=frontCenter.clone().sub(backCenter).normalize();
    const expected=joints.spine1.clone().lerp(joints.neck,progress)
      .addScaledVector(depthAxis, stableShoulderWidth*.02);
    assert.ok(center.distanceTo(expected)<1e-10,
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
  const ringExtent=(start,count,axis)=>{
    let min=Infinity,max=-Infinity;
    for(let i=0;i<count;i++){
      const value=mesh.vertices[start+i].dot(axis);
      min=Math.min(min,value); max=Math.max(max,value);
    }
    return [min,max];
  };
  // Torso-frame forward axis, upright relative to the chest ring itself.
  const chestFrontMid=mesh.vertices[9].clone().lerp(mesh.vertices[10],.5);
  const chestBackMid=mesh.vertices[13].clone().lerp(mesh.vertices[14],.5);
  const bodyForward=chestFrontMid.clone().sub(chestBackMid).normalize();
  for(const axis of [shoulderAxis, bodyForward]) {
    const lower=ringExtent(8,8,axis), upper=ringExtent(16,8,axis), middle=ringExtent(32,8,axis);
    assert.ok(middle[0]>=Math.min(lower[0],upper[0])-1e-10 && middle[1]<=Math.max(lower[1],upper[1])+1e-10,
      "Chest/back transition must not protrude beyond its endpoints");
  }
  // Torso back-depth invariant, per ring in its OWN frame (a single global
  // forward axis aliases ring yaw on twisted poses): the lumbar waist is the
  // forward-most point of the lower back, the chest ring is the ribcage peak,
  // and the shoulder line tapers forward into the traps.
  {
    const ringBack=(start)=>{
      const front=mesh.vertices[start+1].clone().lerp(mesh.vertices[start+2],.5);
      const back=mesh.vertices[start+5].clone().lerp(mesh.vertices[start+6],.5);
      const fwd=front.clone().sub(back).normalize();
      const spine=start===0?joints.spine1
        :start===8?joints.spine1.clone().lerp(joints.neck,.45)
        :start===16?joints.left_shoulder.clone().lerp(joints.right_shoulder,.5)
        :joints.left_hip.clone().lerp(joints.right_hip,.5).lerp(joints.spine1,.76);
      return back.clone().sub(spine).dot(fwd);
    };
    const waist=ringBack(0), chest=ringBack(8), upperChest=ringBack(16), junction=ringBack(72);
    assert.ok(waist>junction+1e-6,
      "Lumbar waist must ride forward of the pelvis junction (no backward arch)");
    assert.ok(chest<waist&&chest<upperChest,
      "Chest ring must be the ribcage peak of the back profile");
    assert.ok(upperChest>chest+1e-6,
      "Shoulder line must taper forward of the scapular peak");
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

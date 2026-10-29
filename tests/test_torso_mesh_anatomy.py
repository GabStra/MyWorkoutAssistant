"""Torso front/back and ribcage shape follow anatomical landmarks, in any view."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_torso_neck_and_shoulder_caps_survive_model_rotation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    three = root / "build/exercise_motion/web-assets/three.module.0.169.0.js"
    if not shutil.which("node") or not three.is_file():
        pytest.skip("Requires Node and the cached preview Three.js module")
    script = tmp_path / "torso.mjs"
    script.write_text(r'''
import fs from "node:fs";
import assert from "node:assert/strict";
const THREE = await import("data:text/javascript;base64," + fs.readFileSync(process.argv[2]).toString("base64"));
const source = fs.readFileSync(process.argv[3], "utf8");
const kernel = source.slice(0, source.indexOf("    function wearColor("));
const colorSource = source.slice(source.indexOf("    function wearColor("),
  source.indexOf("    function wearApplyExportedSoleSides("));
const shade = new Function("THREE", colorSource + "return wearColor;")(THREE);
const authored = new THREE.Color().setRGB(128/255, 128/255, 128/255, THREE.SRGBColorSpace);
assert.ok(Math.abs(shade("#808080", .5).r - authored.r * .5) < 1e-12,
  "Lighting must scale linear color to match the app shader instead of darkening sRGB first");
const correctHead = new Function("THREE", "scene", kernel + "return wearNeutralHeadPitchJoint;")(THREE,new THREE.Scene());
for (const angles of [[0,0,0],[.6,1.3,-.4],[-1.1,-.7,.8]]) {
  const orientation = new THREE.Quaternion().setFromEuler(new THREE.Euler(...angles));
  const side = new THREE.Vector3(1,0,0).applyQuaternion(orientation);
  const neck = new THREE.Vector3(0,1,0).applyQuaternion(orientation);
  const spine = new THREE.Vector3(0,.8,0).applyQuaternion(orientation);
  for (const nod of [-.3,0,.3]) {
    const measuredDelta = new THREE.Vector3(.02,.1,0)
      .applyAxisAngle(new THREE.Vector3(1,0,0), Math.PI/6 + nod).applyQuaternion(orientation);
    const expectedDelta = new THREE.Vector3(.02,.1,0)
      .applyAxisAngle(new THREE.Vector3(1,0,0), nod).applyQuaternion(orientation);
    const result = correctHead(neck,neck.clone().add(measuredDelta),spine,side);
    assert.ok(result.clone().sub(neck).distanceTo(expectedDelta) < 1e-10,
      "Remove only the fixed rest pitch, preserving signed nods, lateral motion, and whole-body rotation");
    assert.ok(Math.abs(result.distanceTo(neck) - measuredDelta.length()) < 1e-10,
      "Head pitch correction must preserve the neck-to-head length");
  }
}
const build = new Function("THREE", "scene", kernel + `
  const originalRing = wearDirectionalRing;
  const originalSphere = wearSphere, originalSegment = wearSegment;
  const originalShoe = wearShoe;
  const originalTube = wearSmoothTorsoTube;
  let rings, spheres, segments, shoes, tubeFaces;
  wearShoe = (...args) => {
    const first = args[0].faces.length;
    const firstVertex = args[0].vertices.length;
    const firstRing = rings.length;
    const result = originalShoe(...args);
    shoes.push({rings: rings.slice(firstRing), faces: args[0].faces.slice(first), vertices: args[0].vertices.slice(firstVertex), ankle: args[1].clone(), foot: args[2].clone()});
    return result;
  };
  wearSmoothTorsoTube = (mesh, rings, fill, jointStart) => {
    const first = mesh.faces.length;
    originalTube(mesh, rings, fill, jointStart);
    tubeFaces = mesh.faces.slice(first);
  };
  wearSphere = (...args) => {
    const first = args[0].faces.length;
    originalSphere(...args);
    spheres.push({center: args[1].clone(), radius: args[3], faces: args[0].faces.slice(first)});
  };
  wearSegment = (...args) => {
    const first = args[0].vertices.length;
    const firstFace = args[0].faces.length;
    const firstRing = rings.length;
    originalSegment(...args);
    segments.push({start: args[1].clone(), end: args[2].clone(), endWidth: args[5], endInset: args[9], vertices: args[0].vertices.slice(first), rootRing: rings[firstRing], faces: args[0].faces.slice(firstFace), tipIndex: args[0].vertices.length - 1});
  };
  wearDirectionalRing = (mesh, center, side, depth, ...args) => {
    const indices = originalRing(mesh, center, side, depth, ...args);
    rings.push({center: center.clone(), depth: depth.clone(), indices});
    return indices;
  };
  return joints => {
    rings = []; spheres = []; segments = []; shoes = [];
    const mesh = wearBuildHumanoid(joints);
    return {mesh, rings, spheres, segments, shoes, tubeFaces};
  };
`)(THREE, new THREE.Scene());
const fixture = JSON.parse(fs.readFileSync(process.argv[4], "utf8")).joints;
for (const shoulderDepthOffset of [0,.07]) for (const angles of [[0,0,0], [.6,1.3,-.4], [-1.1,-.7,.8]]) {
  const rotation = new THREE.Quaternion().setFromEuler(new THREE.Euler(...angles));
  const posedFixture = Object.fromEntries(Object.entries(fixture).map(([name, xyz]) => {
    const point = [...xyz];
    if (["left_shoulder","left_elbow","left_wrist","left_hand"].includes(name)) point[2] += shoulderDepthOffset;
    return [name,point];
  }));
  const joints = Object.fromEntries(Object.entries(posedFixture).map(([name, xyz]) =>
    [name, new THREE.Vector3(...xyz).applyQuaternion(rotation)]));
  const sourceSnapshot = JSON.stringify(joints);
  const {mesh, rings, spheres, segments, shoes, tubeFaces} = build(joints);
  assert.equal(JSON.stringify(joints), sourceSnapshot, "Widening must not mutate saved joint positions");
  const footForward = joints.left_foot.clone().sub(joints.left_ankle)
    .add(joints.right_foot.clone().sub(joints.right_ankle)).normalize();
  assert.ok(rings[0].depth.dot(footForward) > .8,
    "The torso front must face the toes, not the heels, in the standing fixture");
  assert.ok(rings[2].depth.dot(footForward) > .8,
    "The upper torso must keep the same anatomical front");
  const extent = (ring, sign) => Math.max(...ring.indices.map(index =>
    mesh.vertices[index].clone().sub(ring.center).dot(ring.depth) * sign));
  const lowerRibs = rings[1], shoulders = rings[2], upperBack = rings[3];
  assert.ok(extent(upperBack, -1) > extent(lowerRibs, -1),
    "Posterior fullness belongs at the upper back rather than the lower ribs");
  assert.ok(extent(upperBack, -1) > extent(shoulders, -1),
    "The shoulder line must taper from the scapular region");
  assert.ok(extent(upperBack, 1) > extent(lowerRibs, 1),
    "The chest must widen from the lower rib margin rather than inflate the abdomen");
  const neckDepth = joints.neck.clone().sub(shoulders.center).dot(shoulders.depth);
  assert.ok(Math.abs(neckDepth - (extent(shoulders, 1) - extent(shoulders, -1)) * .5) < 1e-10,
    "The neck must lie at the front-to-back center of the upper torso envelope");
  for (const side of ["left", "right"]) {
    const cap = spheres[side === "left" ? 2 : 3];
    const center = cap.center;
    const sourceShoulder = joints[side + "_shoulder"];
    const outward = sourceShoulder.clone().sub(joints[side === "left" ? "right_shoulder" : "left_shoulder"]).normalize();
    assert.ok(center.clone().sub(sourceShoulder).dot(outward) > .02,
      "Widened torso must carry its shoulder attachments and arms outward");
    for (const corner of side === "left" ? [0,7] : [3,4]) {
      assert.ok(mesh.vertices[shoulders.indices[corner]].distanceTo(cap.center) < cap.radius * .75,
        "Both front and back socket edges must remain embedded in their actual shoulder cap");
    }
    const arm = segments.find(s => s.start.distanceTo(center) < 1e-10);
    assert.ok(arm.end.clone().sub(arm.start).distanceTo(joints[side + "_elbow"].clone().sub(sourceShoulder)) < 1e-10,
      "Widening translates the arm without stretching or rotating its upper-arm bone");
    const root = arm.rootRing.indices.map(index => mesh.vertices[index]);
    assert.equal(root.length, 8, "Limb sections must be beveled octagons rather than boxes");
    const depthAxis = arm.rootRing.depth;
    const sideAxis = depthAxis.clone().cross(arm.end.clone().sub(arm.start).normalize()).normalize();
    const span = axis => {
      const values = root.map(v => v.dot(axis));
      return Math.max(...values) - Math.min(...values);
    };
    const smallerHalfExtent = Math.min(span(sideAxis), span(depthAxis)) / 2;
    assert.ok(cap.radius < smallerHalfExtent && cap.radius > smallerHalfExtent * .8,
      "Shoulder cap must be slightly smaller than both upper-arm cross-section dimensions");
    const armRoot = root.reduce((sum,v) => sum.add(v), new THREE.Vector3()).multiplyScalar(1/root.length);
    assert.ok(armRoot.distanceTo(center) < cap.radius,
      "The arm must start inside its shoulder cap instead of leaving a gap");
    const socketAxis = center.clone().sub(joints[side === "left" ? "right_shoulder" : "left_shoulder"]).normalize();
    const overlap = Math.min(...shoulders.indices.map(index =>
      center.clone().sub(mesh.vertices[index]).dot(socketAxis)));
    assert.ok(overlap > 0 && overlap < cap.radius,
      "The torso socket must end inside the shoulder cap instead of flaring beyond the shoulder into the arm");
    const capPlanes = cap.faces.map(face => {
      const [a,b,c] = face.indices.map(index => mesh.vertices[index]);
      const n = b.clone().sub(a).cross(c.clone().sub(a)).normalize();
      if (n.dot(cap.center.clone().sub(a)) > 0) n.negate();
      return {n,a};
    });
    const socketMargin = Math.min(...tubeFaces.flatMap(face =>
      face.indices.slice(1,-1).map((_,i) => {
        const triangle = new THREE.Triangle(...[face.indices[0],face.indices[i+1],face.indices[i+2]]
          .map(index => mesh.vertices[index]));
        const point = triangle.closestPointToPoint(cap.center, new THREE.Vector3());
        return Math.max(...capPlanes.map(({n,a}) => n.dot(point.clone().sub(a))));
      })));
    assert.ok(socketMargin < 0,
      "The final smoothed torso surface must intersect the shoulder cap, not only its unused control ring");
  }
  const collar = rings[4], neckMid = rings[5], neckUpper = rings[6];
  const neckFaces = tubeFaces.filter(face => face.fill === "joint");
  assert.ok(neckFaces.length > 0, "The neck retains its distinct joint color");
  const tubeEdges = new Map();
  for (const face of tubeFaces) {
    for (let i=0; i<face.indices.length; i++) {
      const key = [face.indices[i], face.indices[(i+1)%face.indices.length]].sort((a,b)=>a-b).join(',');
      if (!tubeEdges.has(key)) tubeEdges.set(key, []);
      tubeEdges.get(key).push(face);
    }
  }
  const colorSeam = [...tubeEdges.values()].filter(faces => faces.length === 2 && faces[0].fill !== faces[1].fill);
  assert.equal(colorSeam.length, 8, "Torso and neck share one continuous eight-edge color seam");
  const normal = face => {
    const [a,b,c] = face.indices.map(index => mesh.vertices[index]);
    return b.clone().sub(a).cross(c.clone().sub(a)).normalize();
  };
  assert.ok(colorSeam.every(([body, neck]) => normal(body).dot(normal(neck)) > .85),
    "The neck color seam must follow a smooth surface rather than form a flat ledge");
  const neckDirection = joints.neck.clone().sub(collar.center).normalize();
  const upperSpineDirection = joints.neck.clone().sub(joints.spine3);
  const shoulderSide = joints.left_shoulder.clone().sub(joints.right_shoulder).normalize();
  upperSpineDirection.addScaledVector(shoulderSide, -upperSpineDirection.dot(shoulderSide)).normalize();
  assert.ok(neckDirection.dot(upperSpineDirection) > 1 - 1e-10,
    "The neck must follow the upper spine rather than the offset shoulder-to-neck line");
  assert.ok(collar.center.distanceTo(joints.neck) > shoulders.center.distanceTo(joints.neck) * .2,
    "The gray neck must have visible length rather than a compressed sliver");
  for (const ring of [collar, neckMid, neckUpper]) {
    assert.equal(ring.indices.length, 8, "Neck cross sections must be rounded octagons rather than four-corner boxes");
    assert.ok(Math.abs(extent(ring, 1) - extent(ring, -1)) < 1e-10,
      "Neck thickness must be balanced around its centerline rather than sheared to one side");
  }
  for (let i=0; i<neckUpper.indices.length; i++) {
    const a = neckUpper.indices[i], b = neckUpper.indices[(i+1)%neckUpper.indices.length];
    const shared = mesh.faces.filter(face => face.indices.some((v,k) =>
      (v === a && face.indices[(k+1)%face.indices.length] === b) ||
      (v === b && face.indices[(k+1)%face.indices.length] === a)));
    assert.equal(shared.length, 2, "Neck and head share a watertight boundary");
    assert.deepEqual(new Set(shared.map(face => face.fill)), new Set(["joint", "primary"]));
    const headFace = shared.find(face => face.fill === "primary");
    const headCenter = headFace.indices.reduce((sum,index) => sum.add(mesh.vertices[index]), new THREE.Vector3())
      .multiplyScalar(1/headFace.indices.length);
    assert.ok(headCenter.distanceTo(joints.neck) > .01,
      "Head must join the neck directly, without an extra paper-thin base strip");
  }
  const displayHead = correctHead(joints.neck,joints.head,joints.spine3,
    joints.left_shoulder.clone().sub(joints.right_shoulder));
  const headAxis = displayHead.clone().sub(joints.neck).normalize();
  const headRings = rings.filter(ring => {
    const delta = ring.center.clone().sub(joints.neck);
    return delta.dot(headAxis) > .001 && delta.clone().cross(headAxis).length() < 1e-9;
  });
  assert.equal(headRings.length, 4, "Head needs a jaw, broad skull, upper skull and tapered crown");
  const headWidth = ring => {
    const lateral = ring.depth.clone().cross(headAxis).normalize();
    const values = ring.indices.map(index => mesh.vertices[index].clone().sub(ring.center).dot(lateral));
    assert.ok(Math.abs(Math.max(...values) + Math.min(...values)) < 1e-10, "Head stays laterally symmetric");
    return Math.max(...values) - Math.min(...values);
  };
  assert.ok(headRings.every(ring => ring.indices.length === 8), "Head corners must be beveled rather than square");
  assert.ok(headWidth(headRings[0]) < headWidth(headRings[1]), "Jaw must narrow below the skull");
  assert.ok(headWidth(headRings[2]) < headWidth(headRings[1]), "Upper skull must round toward its crown");
  assert.ok(headWidth(headRings[3]) < headWidth(headRings[1]) * .6, "Crown must not end as a broad box lid");
  const triangleCount = mesh.faces.reduce((sum,face) => sum + face.indices.length - 2, 0);
  assert.ok(segments.every(segment => segment.rootRing.indices.length === 8),
    "Hands and limbs must use the same beveled sections");
  assert.ok(rings.slice(-6).every(ring => ring.indices.length === 8),
    "Both feet must use three beveled sections rather than box sections");
  for (const hand of segments.slice(-2)) {
    assert.ok(hand.vertices.at(-1).clone().sub(hand.end).dot(hand.end.clone().sub(hand.start).normalize()) > 0,
      "Fingertip cap must have depth beyond the palm instead of ending flat");
    const tipFaces = hand.faces.filter(face => face.indices.includes(hand.tipIndex));
    assert.equal(tipFaces.length, 8);
    assert.ok(tipFaces.every(face => face.indices.length === 3), "Fingertip cap must be faceted and convex");
  }
  for (const shoe of shoes) {
    const forward = shoe.foot.clone().sub(shoe.ankle).normalize();
    const length = shoe.foot.distanceTo(shoe.ankle);
    const positions = shoe.vertices.map(v => v.clone().sub(shoe.ankle).dot(forward));
    assert.ok(Math.min(...positions) > -length * .20,
      "The heel must stay close to the ankle instead of extending far behind the leg");
    assert.ok(Math.max(...positions) > length * .90,
      "Most of the shoe length must extend forward toward the toes");
    for (const ring of [shoe.rings[0], shoe.rings.at(-1)]) {
      const capFaces = shoe.faces.filter(face => face.indices.filter(index => ring.indices.includes(index)).length === 2);
      assert.equal(capFaces.filter(face => face.indices.length === 3).length, 8,
        "Heel and toe caps must be convex fans rather than broad flat polygons");
    }
  }
  for (const side of ["left", "right"]) {
    const ankle = joints[side + "_ankle"];
    const shin = segments.find(segment =>
      segment.start.distanceTo(joints[side + "_knee"]) < 1e-10 &&
      segment.end.distanceTo(ankle) < 1e-10);
    const ankleCap = spheres.find(sphere => sphere.center.distanceTo(ankle) < 1e-10);
    assert.ok(shin && ankleCap, "Each ankle must have a lower-leg mesh and its joint cap");
    const appliedInset = Math.min(shin.endInset, shin.start.distanceTo(shin.end) * .15);
    assert.ok(appliedInset >= ankleCap.radius * .80 && appliedInset <= ankleCap.radius,
      "The calf endpoint must overlap the ankle cap slightly, without leaving a visible gap");
  }
  const torsoSide = joints.left_shoulder.clone().sub(joints.right_shoulder).normalize();
  const waistWidth = (() => {
    const values = rings[0].indices.map(index => mesh.vertices[index].dot(torsoSide));
    return Math.max(...values) - Math.min(...values);
  })();
  const shoulderSpan = spheres[2].center.distanceTo(spheres[3].center);
  assert.ok(waistWidth > shoulderSpan * .55 && waistWidth < shoulderSpan * .75,
    "The waist must balance the widened shoulders instead of retaining the old pinched proportions");
  for (const pelvisRing of rings.slice(7,10)) {
    const values = pelvisRing.indices.map(index => mesh.vertices[index].dot(torsoSide));
    const width = Math.max(...values) - Math.min(...values);
    const hipEnvelope = spheres[0].center.distanceTo(spheres[1].center) +
      2 * Math.max(spheres[0].radius, spheres[1].radius);
    assert.ok(width < Math.max(waistWidth * 1.12, hipEnvelope),
      "Pelvis width must balance the waist while leaving enough room for the hip caps");
  }
  const hipCenter = joints.left_hip.clone().lerp(joints.right_hip, .5);
  for (let side = 0; side < 2; side++) {
    const hip = spheres[side];
    const leg = side === 0 ? "left" : "right";
    const thighHalfDepth = joints[leg + "_hip"].distanceTo(joints[leg + "_knee"]) * .27 * .46;
    assert.ok(hip.radius < thighHalfDepth,
      "The hip cap must fit inside the thigh's smaller cross section");
    assert.ok(hip.faces.every(face => face.fill === "joint"),
      "Hip caps must use the same simple joint treatment as the other limbs");
  }
  const pelvisUp = joints.spine1.clone().sub(hipCenter).normalize();
  const bottomHeights = rings[7].indices.map(index =>
    mesh.vertices[index].clone().sub(hipCenter).dot(pelvisUp));
  assert.ok(Math.min(...bottomHeights) < -spheres[0].radius * .45,
    "The pelvis rim must extend below the hip centers");
  const undersideFaces = mesh.faces.filter(face =>
    face.indices.filter(index => rings[7].indices.includes(index)).length === 2);
  assert.equal(undersideFaces.filter(face => face.indices.length === 3).length, 8,
    "The pelvis underside must be a closed convex fan");
  const undersideIndex = undersideFaces[0].indices.find(index => !rings[7].indices.includes(index));
  const undersideHeight = mesh.vertices[undersideIndex].clone().sub(hipCenter).dot(pelvisUp);
  assert.ok(undersideHeight < Math.min(...bottomHeights) - spheres[0].radius * .2,
    "The underside must round below its rim instead of forming an inverted crotch notch");
  const ringWidth = ring => {
    const values = ring.indices.map(index => mesh.vertices[index].dot(torsoSide));
    return Math.max(...values) - Math.min(...values);
  };
    const centerTipWidth = mesh.vertices[rings[7].indices[1]].distanceTo(mesh.vertices[rings[7].indices[2]]);
  assert.ok(centerTipWidth < ringWidth(rings[8]) * .5,
    "The pelvis center must taper into an inverted triangle between the hip sockets");
  for (const corner of [0,3,4,7]) {
    const point = mesh.vertices[rings[7].indices[corner]].clone().sub(hipCenter);
    assert.ok(point.dot(pelvisUp) >= spheres[0].radius * .2,
      "The pelvis outer rim must reach over the hip centers without separate domes");
  }
    const taper = ringWidth(upperBack) / waistWidth;
  assert.ok(taper > 1.35 && taper < 1.6,
    "The muscular ribcage must taper gradually into the waist without a sharp pinch");
  const frontFaceWidth = mesh.vertices[upperBack.indices[1]].distanceTo(mesh.vertices[upperBack.indices[2]]);
  assert.ok(frontFaceWidth < ringWidth(upperBack) * .2,
    "The rounded torso must replace its broad flat front with angled elliptical facets");
    const chestDepthRatio = extent(upperBack, 1) / extent(rings[0], 1);
  assert.ok(chestDepthRatio > 1.2 && chestDepthRatio < 1.6,
    "Chest depth must taper moderately into the abdomen instead of creating a deep hollow");
  const fairWaist = joints.spine1.clone().multiplyScalar(.5)
    .addScaledVector(hipCenter, .25).addScaledVector(joints.spine2, .25);
  const fairChest = joints.spine2.clone().multiplyScalar(.5)
    .addScaledVector(joints.spine1, .25).addScaledVector(joints.spine3, .25);
  const fairUpper = joints.spine3.clone().multiplyScalar(.5)
    .addScaledVector(joints.spine2, .25).addScaledVector(joints.neck, .25);
  assert.ok(upperBack.center.distanceTo(fairUpper) < 1e-10,
    "The upper torso surface must follow the faired centerline, not the raw spine kink");
  const curvature = points => points.slice(1,-1).reduce((sum,p,i) =>
    sum + p.clone().multiplyScalar(2).sub(points[i]).sub(points[i+2]).lengthSq(), 0);
  assert.ok(curvature([hipCenter,fairWaist,fairChest,fairUpper,joints.neck]) <=
    curvature([hipCenter,joints.spine1,joints.spine2,joints.spine3,joints.neck]) + 1e-12,
    "Surface fairing must reduce zigzag curvature while retaining its endpoints");
  const socketWidth = spheres[0].center.distanceTo(spheres[1].center) + spheres[0].radius * 1.7;
  const socketPoints = rings[8].indices.map(index => mesh.vertices[index].dot(torsoSide));
  assert.ok(Math.max(...socketPoints) - Math.min(...socketPoints) >= socketWidth,
    "The socket volume must enclose both hip caps");
  assert.ok(triangleCount <= 1194, "The complete mesh, including preserved shoulder sockets, must stay within the reduced triangle budget");
}
''', encoding="utf-8")
    subprocess.run(
        ["node", str(script), str(three),
         str(root / "exercise_motion_pkg/wear_exact_mesh.js"),
         str(root / "tests/fixtures/sequence_stabilization_stance.json")],
        check=True, capture_output=True, text=True,
    )

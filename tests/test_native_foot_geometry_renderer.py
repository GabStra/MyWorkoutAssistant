import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from exercise_motion_pkg.native_foot_geometry import native_foot_marker_world
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.preview import _build_wear_transformed_frames, _preview_native_foot_geometry, _subtract_scene_origin_from_frames
from exercise_motion_pkg.models import MotionFrame
from exercise_motion_pkg.rig_playback import decode_rig


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "native_foot_geometry_v1.json"
V2_FIXTURE = ROOT / "motion-renderer" / "src" / "test" / "resources" / "native_material_contact_tracks_v2.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _v2_fixture():
    return json.loads(V2_FIXTURE.read_text(encoding="utf-8"))


def test_preview_serializes_only_qualified_native_prior_or_validated_baked_tag():
    fixture = _fixture()
    raw = SimpleNamespace(metadata={"reconstruction": {"footMarkerPrior": fixture["sourcePrior"]}})
    promoted = _preview_native_foot_geometry(raw, None)
    assert promoted["version"] == fixture["reference"]["version"]
    assert promoted["modelSha256"] == fixture["reference"]["modelSha256"]
    for side in ("left", "right"):
        assert promoted["sides"][side]["ankleToFootJointLengthMeters"] == pytest.approx(
            fixture["reference"]["sides"][side]["ankleToFootJointLengthMeters"])
        np.testing.assert_allclose(
            promoted["sides"][side]["heelFromAnkleLocalMeters"],
            fixture["reference"]["sides"][side]["heelFromAnkleLocalMeters"], atol=1e-15)
        np.testing.assert_allclose(
            promoted["sides"][side]["toeFromAnkleLocalMeters"],
            fixture["reference"]["sides"][side]["toeFromAnkleLocalMeters"], atol=1e-15)

    legacy = SimpleNamespace(metadata={})
    assert _preview_native_foot_geometry(legacy, None) is None
    assert _preview_native_foot_geometry(legacy, {"frames": [{}]}) is None

    with pytest.raises(ValueError, match="present but invalid"):
        _preview_native_foot_geometry(
            legacy, {"nativeFootGeometry": {"version": 9}, "frames": [{}]})


def test_wear_export_transports_carried_bone_side_axes_as_vectors():
    frames = [MotionFrame(
        time_sec=0.0,
        joints={"pelvis": (1.0, 2.0, 3.0), "left_ankle": (1.0, 0.0, 0.0), "left_foot": (2.0, 0.0, 0.0)},
        bone_sides={"left_ankle->left_foot": (0.0, 1.0, 0.0)},
        bone_side_provenance={"left_ankle->left_foot": "observed"},
    )]
    rotated = _build_wear_transformed_frames(
        active_frames=frames,
        root_joint="pelvis",
        active_root_anchor=None,
        auto_alignment=[((1.0, 0.0, 0.0), np.pi / 2)],
        lock_y_drift=False,
        lock_root_translation=False,
    )
    assert rotated[0]["boneSides"]["left_ankle->left_foot"] == pytest.approx([0.0, 0.0, 1.0])
    centered = _subtract_scene_origin_from_frames(rotated, (4.0, -2.0, 8.0))
    assert centered[0]["boneSides"]["left_ankle->left_foot"] == pytest.approx(
        rotated[0]["boneSides"]["left_ankle->left_foot"])


def _expected_vertices(case, side_geometry, foot_scale):
    ankle, foot = np.asarray(case["ankle"]), np.asarray(case["foot"])
    forward = foot - ankle
    length = np.linalg.norm(forward)
    forward /= length
    side = np.asarray(case["sideAxis"])
    side -= forward * np.dot(side, forward)
    side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    factor = length / side_geometry["ankleToFootJointLengthMeters"]
    heel = np.asarray(side_geometry["heelFromAnkleLocalMeters"]) * factor
    toe = np.asarray(side_geometry["toeFromAnkleLocalMeters"]) * factor
    half_width = max(length * .26, foot_scale * .15)
    height = max(length * .28, foot_scale * .15)
    profile = [(0., -.05, .78, .55), (.36, .12, 1., .72), (1., -.25, .76, .35)]
    rings = []
    for fraction, up_scale, width_scale, height_scale in profile:
        local = heel * (1 - fraction) + toe * fraction
        center = ankle + forward * local[0] + side * local[1] + up * (local[2] + height * (up_scale + .60))
        width = side * (half_width * width_scale)
        depth = up * (height * height_scale)
        top_width = width * .88
        corners = [center + top_width + depth, center - top_width + depth,
                   center - width - depth, center + width - depth]
        ring = []
        for i, corner in enumerate(corners):
            ring.extend([corner * .70 + corners[(i - 1) % 4] * .30,
                         corner * .70 + corners[(i + 1) % 4] * .30])
        rings.append(ring)
    rear_tip = (rings[0][0] + rings[0][4]) * .5
    toe_tip = (rings[2][0] + rings[2][4]) * .5
    return np.asarray(rings[0] + rings[1] + rings[2] + [rear_tip, toe_tip])


def test_v2_fixture_triangle_cache_matches_canonical_native_mesh_and_scale():
    fixture = _v2_fixture()
    sample = fixture["sample"]
    geometry = fixture["nativeFootGeometry"]
    episode = fixture["track"]["left"]["episodes"][0]
    rig = json.loads((ROOT / "motion-renderer/src/test/resources/fixed-rig-parity.json").read_text())["rig"]
    points = decode_rig(rig, np.asarray(rig["coordinates"], dtype=float))
    scale = foot_scale_from_pose(points[0], rig["jointNames"])
    assert sample["footScaleMeters"] == pytest.approx(scale, abs=1e-12)
    assert fixture["canonicalFootScaleMeters"] == pytest.approx(scale, abs=1e-12)

    ankle = np.asarray(sample["ankle"], dtype=float)
    foot = np.asarray(sample["foot"], dtype=float)
    side = np.asarray(sample["sideAxis"], dtype=float)
    vertices = shoe_vertices(ankle, foot, side, None, scale, native_geometry=geometry["sides"]["left"])
    triangles = shoe_triangles()
    triangle = triangles[episode["triangleIndex"]]
    assert triangle.tolist() == [5, 14, 6]
    np.testing.assert_allclose(vertices[triangle], sample["triangleVertices"], atol=1e-12)
    material = np.asarray(sample["barycentric"]) @ vertices[triangle]
    np.testing.assert_allclose(material, sample["materialPointWorld"], atol=1e-12)

    direction = (foot - ankle) / np.linalg.norm(foot - ankle)
    lateral = side - direction * np.dot(side, direction)
    lateral /= np.linalg.norm(lateral)
    up = np.cross(lateral, direction)
    local = np.array([np.dot(material - ankle, axis) for axis in (direction, lateral, up)])
    np.testing.assert_allclose(local, episode["materialOffsetLocalMeters"], atol=1e-12)
    assert episode["referenceLengthMeters"] == pytest.approx(np.linalg.norm(foot - ankle), abs=1e-12)
    assert np.min(vertices[:, 1]) == pytest.approx(sample["nativeShoeMinY"], abs=1e-12)
    assert np.max(vertices[:, 1]) == pytest.approx(sample["nativeShoeMaxY"], abs=1e-12)


def test_js_v2_fixture_binding_uses_actual_native_shoe_triangle(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Requires Node.js for renderer parity")
    fixture = _v2_fixture()
    sample = fixture["sample"]
    case_path = tmp_path / "native-material-binding.json"
    case_path.write_text(json.dumps({"fixture": fixture}), encoding="utf-8")
    script = tmp_path / "native-material-binding.mjs"
    script.write_text('''
import fs from 'node:fs';
class Vector3 {
  constructor(x=0,y=0,z=0) { this.x=x; this.y=y; this.z=z; }
  clone() { return new Vector3(this.x,this.y,this.z); }
  add(v) { this.x+=v.x; this.y+=v.y; this.z+=v.z; return this; }
  sub(v) { this.x-=v.x; this.y-=v.y; this.z-=v.z; return this; }
  addScaledVector(v,s) { this.x+=v.x*s; this.y+=v.y*s; this.z+=v.z*s; return this; }
  multiplyScalar(s) { this.x*=s; this.y*=s; this.z*=s; return this; }
  dot(v) { return this.x*v.x+this.y*v.y+this.z*v.z; }
  cross(v) { const x=this.y*v.z-this.z*v.y,y=this.z*v.x-this.x*v.z,z=this.x*v.y-this.y*v.x; this.x=x; this.y=y; this.z=z; return this; }
  lengthSq() { return this.dot(this); }
  length() { return Math.sqrt(this.lengthSq()); }
  normalize() { const n=this.length(); if(n) this.multiplyScalar(1/n); return this; }
  lerp(v,t) { this.x+=(v.x-this.x)*t; this.y+=(v.y-this.y)*t; this.z+=(v.z-this.z)*t; return this; }
  toArray() { return [this.x,this.y,this.z]; }
}
const THREE={Vector3,BufferGeometry:class{},Mesh:class{constructor(g,m){this.geometry=g;}},
  MeshBasicMaterial:class{},FrontSide:0};
const source = fs.readFileSync(process.argv[2], 'utf8');
const kernel = source.slice(0, source.indexOf('    function wearColor('));
const api = new Function('THREE', 'scene', kernel + 'return {shoe:wearShoe, mesh:wearMeshData};')(THREE, {add(){}});
const fixture = JSON.parse(fs.readFileSync(process.argv[3], 'utf8')).fixture;
const s = fixture.sample, e = fixture.track.left.episodes[0];
const mesh = api.mesh(), v = x => new Vector3(...x);
const forward = v(s.direction), side = v(s.sideAxis), up = side.clone().cross(forward).normalize();
api.shoe(mesh, v(s.ankle), v(s.foot), {forward, side, up}, fixture.canonicalFootScaleMeters,
  'primary', null, side, null, {forward:s.direction, side:s.sideAxis}, fixture.nativeFootGeometry.sides.left);
console.log(JSON.stringify({vertices:mesh.vertices.map(p=>p.toArray()),faces:mesh.faces.map(f=>f.indices)}));
''', encoding="utf-8")
    rendered = json.loads(subprocess.check_output(
        ["node", str(script), str(ROOT / "exercise_motion_pkg/wear_exact_mesh.js"), str(case_path)],
        text=True, timeout=30))
    vertices = np.asarray(rendered["vertices"])
    episode = fixture["track"]["left"]["episodes"][0]
    triangle = shoe_triangles()[episode["triangleIndex"]]
    rendered_triangles = []
    for face in rendered["faces"]:
        if len(face) == 3:
            rendered_triangles.append(face)
        elif len(face) == 4:
            rendered_triangles.extend(([face[0], face[1], face[2]], [face[0], face[2], face[3]]))
    rendered_keys = {tuple(sorted(face)) for face in rendered_triangles}
    assert tuple(sorted(triangle.tolist())) in rendered_keys
    material = np.asarray(episode["barycentric"]) @ vertices[triangle]
    np.testing.assert_allclose(material, fixture["sample"]["materialPointWorld"], atol=1e-12)
    np.testing.assert_allclose(np.min(vertices[:, 1]), fixture["sample"]["nativeShoeMinY"], atol=1e-12)
    np.testing.assert_allclose(np.max(vertices[:, 1]), fixture["sample"]["nativeShoeMaxY"], atol=1e-12)


def test_js_native_mesh_matches_v1_marker_frame_and_keeps_caps_inside_extrema(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Requires Node.js for renderer parity")
    three = ROOT / "build/exercise_motion/web-assets/three.module.0.169.0.js"
    if not three.is_file():
        pytest.skip("Requires the cached production Three.js module")

    fixture = _fixture()
    native = fixture["reference"]
    neutral = fixture["neutralCase"]
    cases = [{"ankle": neutral["ankle"], "foot": neutral["footJoint"],
              "sideAxis": neutral["sideAxis"], "scale": 1.0}]
    for value in fixture["rigidCases"]:
        matrix = np.asarray(value["rotationMatrix"], dtype=float)
        translation = np.asarray(value["translation"], dtype=float)
        scale = float(value["scale"])
        side_axis = matrix @ np.asarray(neutral["sideAxis"])
        if np.linalg.det(matrix) < 0:
            side_axis = -side_axis
        cases.append({
            "ankle": (matrix @ np.asarray(neutral["ankle"]) * scale + translation).tolist(),
            "foot": (matrix @ np.asarray(neutral["footJoint"]) * scale + translation).tolist(),
            "sideAxis": side_axis.tolist(),
            "scale": scale,
        })
    twisted = fixture["twistedRetargetCase"]
    cases.append({
        "ankle": twisted["ankle"],
        "foot": twisted["footJoint"],
        "sideAxis": twisted["sideAxis"],
        "scale": twisted["scale"],
        "geometry": fixture["twistedRetargetGeometry"],
    })

    input_path = tmp_path / "native-foot-cases.json"
    input_path.write_text(json.dumps({"cases": cases, "geometry": native}), encoding="utf-8")
    script = tmp_path / "native-foot-check.mjs"
    script.write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const source = fs.readFileSync(process.argv[3], 'utf8');
const kernel = source.slice(0, source.indexOf('    function wearColor('));
const api = new Function('THREE', 'scene', kernel + 'return {shoe:wearShoe, mesh:wearMeshData};')(THREE, new THREE.Scene());
const input = JSON.parse(fs.readFileSync(process.argv[4]));
const output = input.cases.map(c => {
  const vec = v => new THREE.Vector3(...v), mesh = api.mesh();
  const geometry = c.geometry ?? input.geometry;
  api.shoe(mesh, vec(c.ankle), vec(c.foot), {side:vec([0,0,1]),up:vec([0,1,0]),forward:vec([1,0,0])},
    .2*c.scale, 'primary', null, vec(c.sideAxis), 1.1, {forward:[0,0,1],side:c.sideAxis}, geometry.sides.left);
  return mesh.vertices.map(v => v.toArray());
});
console.log(JSON.stringify(output));
''', encoding="utf-8")
    actual = json.loads(subprocess.check_output(
        ["node", str(script), str(three), str(ROOT / "exercise_motion_pkg/wear_exact_mesh.js"), str(input_path)],
        text=True, timeout=30))

    for case, vertices in zip(cases, actual):
        geometry = case.get("geometry", native)
        side_geometry = geometry["sides"]["left"]
        expected = _expected_vertices(case, side_geometry, .2 * case["scale"])
        np.testing.assert_allclose(vertices, expected, atol=1e-12)
        helper_mesh = shoe_vertices(
            np.asarray(case["ankle"]), np.asarray(case["foot"]), np.asarray(case["sideAxis"]),
            None, .2 * case["scale"], native_geometry=side_geometry)
        np.testing.assert_allclose(vertices, helper_mesh, atol=1e-12)
        assert len(vertices) == 26
        ankle, foot = np.asarray(case["ankle"]), np.asarray(case["foot"])
        forward = (foot - ankle) / np.linalg.norm(foot - ankle)
        projected = (np.asarray(vertices) - ankle) @ forward
        heel = np.asarray(side_geometry["heelFromAnkleLocalMeters"])
        toe = np.asarray(side_geometry["toeFromAnkleLocalMeters"])
        factor = np.linalg.norm(foot - ankle) / side_geometry["ankleToFootJointLengthMeters"]
        assert projected.min() >= heel[0] * factor - 1e-12
        assert projected.max() <= toe[0] * factor + 1e-12

    twisted = fixture["twistedRetargetCase"]
    geometry = fixture["twistedRetargetGeometry"]["sides"]["left"]
    heel, toe = native_foot_marker_world(
        twisted["ankle"], twisted["footJoint"], twisted["sideAxis"], geometry)
    np.testing.assert_allclose(heel, twisted["expected"]["heel"], atol=1e-12)
    np.testing.assert_allclose(toe, twisted["expected"]["toe"], atol=1e-12)
    assert min(np.asarray(actual[-1])[:, 1]) == pytest.approx(twisted["expected"]["meshMinY"], abs=1e-12)

import numpy as np
import json
from pathlib import Path

from exercise_motion_pkg.body_surface_geometry import (
    body_surface_primitive_meshes,
    evaluate_contact_patch,
)


def _poses():
    names = ["pelvis", "neck", "spine1", "spine2", "spine3", "head",
             "left_hip", "right_hip", "left_shoulder", "right_shoulder",
             "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
             "left_knee", "right_knee", "left_ankle", "right_ankle",
             "left_foot", "right_foot"]
    base = {
        "pelvis": [0, 1, 0], "neck": [0, 1.6, 0], "spine1": [0, 1.2, 0],
        "spine2": [0, 1.35, 0], "spine3": [0, 1.5, 0], "head": [0, 1.85, 0],
        "left_hip": [-.12, 1, 0], "right_hip": [.12, 1, 0],
        "left_shoulder": [-.25, 1.55, 0], "right_shoulder": [.25, 1.55, 0],
        "left_elbow": [-.4, 1.3, 0], "right_elbow": [.4, 1.3, 0],
        "left_wrist": [-.45, 1.05, 0], "right_wrist": [.45, 1.05, 0],
        "left_hand": [-.50, 1.00, 0], "right_hand": [.50, 1.00, 0],
        "left_knee": [-.12, .55, 0], "right_knee": [.12, .55, 0],
        "left_ankle": [-.12, .1, 0], "right_ankle": [.12, .1, 0],
        "left_foot": [-.12, 0, .18], "right_foot": [.12, 0, .18],
    }
    second = {key: list(value) for key, value in base.items()}
    second["left_knee"] = [-.2, .5, .1]
    second["left_ankle"] = [-.12, .08, .2]
    second["pelvis"] = [.18, 1, .05]
    for name in ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                 "left_wrist", "right_wrist", "spine1", "spine2", "spine3", "neck"):
        second[name][0] += .12
        second[name][2] += .04
    return names, np.asarray([[base[n] for n in names], [second[n] for n in names]], dtype=float)


def test_native_shin_mesh_tracks_articulated_knee_and_samples_exact_triangle_patch():
    names, points = _poses()
    identity_axes = np.broadcast_to(np.eye(3), (2, 3, 3))
    meshes = body_surface_primitive_meshes(points, names, binding={
        "bodyAxes": identity_axes,
        "limbSides": {"left_knee->left_ankle": [-1., 0., 0.]},
    })
    mesh = meshes["wearSegment:left_knee->left_ankle"]
    assert mesh["vertices"].shape == (2, 24, 3)  # native two-ring plus bulge ring
    assert mesh["triangles"].shape == (44, 3)
    # Native wearDirectionalRing(.30) fixture: beveled lower ring, then upper,
    # then the bulge ring. The emitted wall order is lower→bulge→upper.
    np.testing.assert_allclose(mesh["vertices"][0, 0], [-.170625, .5419, .01782], atol=1e-12)
    np.testing.assert_array_equal(mesh["triangles"][:2], [[0, 16, 17], [0, 17, 1]])
    np.testing.assert_array_equal(mesh["triangles"][-6:], [
        [15, 14, 13], [15, 13, 12], [15, 12, 11],
        [15, 11, 10], [15, 10, 9], [15, 9, 8],
    ])
    assert not np.allclose(mesh["vertices"][0], mesh["vertices"][1])
    binding = {"primitiveId": "wearSegment:left_knee->left_ankle",
               "points": [{"triangleIndex": 0, "barycentric": [1 / 3, 1 / 3, 1 / 3]}]}
    sampled = evaluate_contact_patch(meshes, binding)
    np.testing.assert_allclose(sampled[:, 0], mesh["vertices"][:, mesh["triangles"][0]].mean(axis=1))


def test_native_shoulder_cap_is_renderer_surface_while_pelvis_moves():
    names, points = _poses()
    identity_axes = np.broadcast_to(np.eye(3), (2, 3, 3))
    meshes = body_surface_primitive_meshes(points, names, binding={"bodyAxes": identity_axes})
    cap = meshes["wearSphere:left_shoulder"]
    assert cap["vertices"].shape == (2, 18, 3)
    assert cap["triangles"].shape == (32, 3)
    np.testing.assert_array_equal(cap["triangles"][-8:], [
        [1, 17, 16], [1, 16, 15], [1, 15, 14], [1, 14, 13],
        [1, 13, 12], [1, 12, 11], [1, 11, 10], [1, 10, 17],
    ])
    # Native shoulder spheres start at center - up*radius; renderer offsets
    # both shoulder chains by 7.5% of the clip-bound shoulder width.
    shoulder_width = np.linalg.norm(points[0, names.index("left_shoulder")] -
                                    points[0, names.index("right_shoulder")])
    direction = points[0, names.index("left_shoulder")] - points[0, names.index("right_shoulder")]
    center = points[0, names.index("left_shoulder")] + direction / np.linalg.norm(direction) * shoulder_width * .075
    np.testing.assert_allclose(cap["vertices"][0, 0], center * 2 - cap["vertices"][0, 1], atol=1e-12)
    assert not np.allclose(cap["vertices"][0], cap["vertices"][1])


def test_patch_sampler_rejects_unknown_mesh_and_invalid_coordinates():
    names, points = _poses()
    meshes = body_surface_primitive_meshes(points, names)
    with np.testing.assert_raises(ValueError):
        evaluate_contact_patch(meshes, {"primitiveId": "capsule:shin", "points": []})
    binding = {"primitiveId": "wearSphere:left_shoulder",
               "points": [{"triangleIndex": 0, "barycentric": [1., 1., 0.]}]}
    with np.testing.assert_raises(ValueError):
        evaluate_contact_patch(meshes, binding)


def test_every_native_limb_segment_and_joint_cap_has_an_explicit_mesh_id():
    names, points = _poses()
    meshes = body_surface_primitive_meshes(points, names)
    limb_ids = [key for key in meshes if key.startswith("wearSegment:")]
    cap_ids = [key for key in meshes if key.startswith("wearSphere:")]
    assert len(limb_ids) == 10
    assert len(cap_ids) == 12
    assert "wearSegment:left_knee->left_ankle" in limb_ids
    assert "wearSegment:left_wrist->left_hand" in limb_ids
    assert "wearSphere:left_shoulder" in cap_ids


def test_head_mesh_uses_native_render_geometry_fixture_and_strip_topology():
    fixture = json.loads((Path(__file__).parent / "fixtures/native_head_material_regions.json").read_text())
    points = np.asarray(fixture["points"])
    names = fixture.get("names", fixture.get("jointNames"))
    assert names is not None
    meshes = body_surface_primitive_meshes(points, names)
    head = meshes["wearHeadMaterial:head"]
    np.testing.assert_allclose(head["vertices"], fixture["nativeVertices"], atol=1e-6, rtol=0.)
    assert head["vertices"].shape[1:] == (32, 3)
    assert head["triangles"].shape == (54, 3)


def test_hand_segment_and_shoe_meshes_match_native_family_dimensions_and_topology():
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles

    names, points = _poses()
    identity_axes = np.broadcast_to(np.eye(3), (2, 3, 3))
    side = np.asarray([0., 0., 1.])
    meshes = body_surface_primitive_meshes(points, names, binding={
        "bodyAxes": identity_axes,
        "limbSides": {"left_ankle->left_foot": side},
        "footScale": .2,
        "footRestPitchRadians": {"left": 0.},
    })
    hand = meshes["wearSegment:left_wrist->left_hand"]
    assert hand["vertices"].shape == (2, 25, 3)
    assert hand["triangles"].shape == (46, 3)
    shoe = meshes["wearShoe:left_ankle->left_foot"]
    expected = shoe_vertices(points[:, names.index("left_ankle")], points[:, names.index("left_foot")],
                             side, 0., .2)
    np.testing.assert_allclose(shoe["vertices"], expected, atol=1e-12, rtol=0.)
    np.testing.assert_array_equal(shoe["triangles"], shoe_triangles())
    assert shoe["vertices"].shape == (2, 26, 3)


def test_whole_native_torso_shell_transforms_and_preserves_upper_back_fixture_parity():
    from scipy.spatial.transform import Rotation

    fixture = json.loads((Path(__file__).parent / "fixtures/native_upper_back_region.json").read_text())
    points = np.asarray(fixture["points"])
    axes = np.asarray(fixture["bodyAxes"])
    names = fixture["names"]
    meshes = body_surface_primitive_meshes(points, names, binding={
        "bodyAxes": axes, "torsoMaterial": fixture["binding"],
    })
    shell = meshes["wearTorsoShell:body"]
    assert shell["vertices"].shape == (len(points), 105, 3)
    assert shell["triangles"].shape == (200, 3)
    assert shell["ringNames"] == ["pelvisJunction", "pelvisMid", "pelvisBottom", "waist",
        "chest", "upperBack", "upperChest", "trapezius", "upperTransition", "neckMid", "neckUpper"]
    np.testing.assert_allclose(shell["upperBackQuads"], fixture["expectedQuads"], atol=3e-14, rtol=0.)

    rotation = Rotation.from_euler("xyz", [23., -41., 17.], degrees=True).as_matrix()
    translation = np.asarray([.3, -.2, .5])
    transformed = body_surface_primitive_meshes(points @ rotation.T + translation, names, binding={
        "bodyAxes": axes @ rotation.T, "torsoMaterial": fixture["binding"],
    })["wearTorsoShell:body"]
    np.testing.assert_allclose(transformed["vertices"], shell["vertices"] @ rotation.T + translation,
                               atol=4e-14, rtol=0.)


def test_native_torso_shell_rejects_missing_body_geometry():
    names, points = _poses()
    keep = [i for i, name in enumerate(names) if name != "right_shoulder"]
    broken_names = [names[i] for i in keep]
    with np.testing.assert_raises(ValueError):
        body_surface_primitive_meshes(points[:, keep], broken_names)

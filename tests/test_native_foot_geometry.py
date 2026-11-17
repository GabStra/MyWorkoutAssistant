import copy
import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.native_foot_geometry import (
    is_qualified_named_foot_marker_prior,
    native_foot_geometry_from_prior,
    native_foot_geometry_identity,
    native_foot_marker_world,
    promote_native_foot_geometry,
    validated_native_foot_geometry,
)

FIXTURE = Path(__file__).parent / "fixtures" / "native_foot_geometry_v1.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _assert_geometry_close(actual, expected, path="root"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), path
        for key in expected:
            _assert_geometry_close(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            _assert_geometry_close(actual[index], value, f"{path}[{index}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert actual == pytest.approx(expected, abs=1e-12), path
    else:
        assert actual == expected, path


def test_prior_normalizes_with_added_heel_offset_and_exact_span():
    fixture = _fixture()
    prior = fixture["sourcePrior"]
    assert is_qualified_named_foot_marker_prior(prior)
    block = native_foot_geometry_from_prior(prior)
    _assert_geometry_close(block, fixture["reference"])
    left = block["sides"]["left"]
    np.testing.assert_allclose(
        left["heelFromAnkleLocalMeters"],
        np.asarray(left["toeFromAnkleLocalMeters"])
        + np.asarray(prior["sides"]["left"]["heelToToeLocalMeters"]))
    assert np.linalg.norm(
        np.asarray(left["heelFromAnkleLocalMeters"])
        - np.asarray(left["toeFromAnkleLocalMeters"])) == pytest.approx(.219483, abs=1e-12)


def test_neutral_provider_frame_reconstructs_named_markers_and_ball_joint():
    fixture = _fixture()
    case = fixture["neutralCase"]
    block = fixture["reference"]
    heel, toe = native_foot_marker_world(
        case["ankle"], case["footJoint"], case["sideAxis"], block["sides"]["left"])
    np.testing.assert_allclose(heel, case["expected"]["heel"], atol=1e-12)
    np.testing.assert_allclose(toe, case["expected"]["toe"], atol=1e-12)
    np.testing.assert_allclose(case["footJoint"], case["expected"]["ballJoint"], atol=1e-12)
    assert np.linalg.norm(toe - heel) == pytest.approx(
        case["expected"]["heelToToeSpanMeters"], abs=1e-12)


@pytest.mark.parametrize("case_index", [0, 1, 2])
def test_rigid_embedding_under_rotation_reflection_subframe_and_scale(case_index):
    fixture = _fixture()
    case = fixture["rigidCases"][case_index]
    block = fixture["reference"]
    rotation = np.asarray(case["rotationMatrix"], dtype=float)
    translation = np.asarray(case["translation"], dtype=float)
    scale = float(case["scale"])
    neutral = fixture["neutralCase"]
    ankle = scale * rotation @ np.asarray(neutral["ankle"]) + translation
    foot = scale * rotation @ np.asarray(neutral["footJoint"]) + translation
    side_axis = rotation @ np.asarray(neutral["sideAxis"])
    if np.linalg.det(rotation) < 0.:
        # Bone side axes are pseudo-vectors under an improper mirror.
        side_axis = -side_axis
    heel, toe = native_foot_marker_world(ankle, foot, side_axis, block["sides"]["left"])
    expected_heel = scale * rotation @ np.asarray(neutral["expected"]["heel"]) + translation
    expected_toe = scale * rotation @ np.asarray(neutral["expected"]["toe"]) + translation
    np.testing.assert_allclose(heel, expected_heel, atol=1e-9)
    np.testing.assert_allclose(toe, expected_toe, atol=1e-9)
    # The rig's forefoot joint remains the rigid bone endpoint.
    np.testing.assert_allclose(
        ankle + (foot - ankle) / np.linalg.norm(foot - ankle)
        * np.linalg.norm(foot - ankle), foot, atol=1e-12)
    # All three local components scale uniformly: marker vector scales with bone.
    assert np.linalg.norm(toe - heel) == pytest.approx(
        scale * neutral["expected"]["heelToToeSpanMeters"], abs=1e-9)


def test_all_local_components_scale_uniformly_under_proper_rotation():
    block = _fixture()["reference"]
    side = copy.deepcopy(block["sides"]["left"])
    side["toeFromAnkleLocalMeters"] = [.181410, .032, -.018]
    side["heelFromAnkleLocalMeters"] = [-.038073, .040, -.029]
    rotation = np.asarray([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    side_axis = rotation @ np.asarray([0., 0., 1.])
    ankle, foot = np.asarray([.3, .4, .5]), np.asarray([.3, .4, .5]) + .134302 * rotation @ np.asarray([1., 0., 0.])
    heel, toe = native_foot_marker_world(ankle, foot, side_axis, side)
    reference_ankle = np.zeros(3)
    reference_foot = np.asarray([.134302, 0., 0.])
    reference_heel, reference_toe = native_foot_marker_world(
        reference_ankle, reference_foot, np.asarray([0., 0., 1.]), side)
    np.testing.assert_allclose(heel, ankle + rotation @ reference_heel, atol=1e-12)
    np.testing.assert_allclose(toe, ankle + rotation @ reference_toe, atol=1e-12)


def test_legacy_path_is_unchanged_and_identity_only_when_present():
    from exercise_motion_pkg.foot_geometry import (
        _sample_material_foot_geometry, material_foot_points, shoe_vertices)
    from exercise_motion_pkg.artifact_state import baked_payload_identity

    names = ["left_ankle", "left_foot", "right_ankle", "right_foot"]
    pose = np.asarray([[0., .1, 0.], [.18, .02, 0.], [.1, .1, 0.], [.28, .02, 0.]])
    frame = {"joints": dict(zip(names, pose.tolist())),
             "boneSides": {"left_ankle->left_foot": [0., 0., 1.],
                           "right_ankle->right_foot": [0., 0., 1.]}}
    payload = {"frames": [frame], "jointNames": names,
               "footRestPitchRadians": {"left": 0., "right": 0.},
               "loop": {"enabled": False}}
    points = pose[None]
    geometry = _sample_material_foot_geometry(payload, [0.], points)
    assert geometry["left"]["nativeGeometry"] is None
    heel, toe = material_foot_points(
        points[0, 0], points[0, 1], geometry["left"]["lateral"], 0.)
    np.testing.assert_allclose(geometry["left"]["heel"][0], np.reshape(heel, 3))
    np.testing.assert_allclose(geometry["left"]["toe"][0], np.reshape(toe, 3))
    legacy_vertices = shoe_vertices(
        points[0, 0], points[0, 1], geometry["left"]["lateral"], 0., .2)
    np.testing.assert_allclose(
        shoe_vertices(points[0, 0], points[0, 1], geometry["left"]["lateral"],
                      0., .2, native_geometry=None), legacy_vertices)

    framed = {"frames": [{"joints": frame["joints"]}], "fps": 30., "frameCount": 1}
    assert "nativeFootGeometry" not in baked_payload_identity(framed)
    without_key = copy.deepcopy(framed)
    assert baked_payload_identity(framed) == baked_payload_identity(without_key)
    with_native = copy.deepcopy(framed)
    with_native["nativeFootGeometry"] = _fixture()["reference"]
    assert baked_payload_identity(with_native)["contentSha256"] != baked_payload_identity(framed)["contentSha256"]
    assert native_foot_geometry_identity(framed) is None
    assert native_foot_geometry_identity(with_native) is not None


def test_native_contact_track_geometry_is_in_artifact_and_fit_identity():
    from exercise_motion_pkg.artifact_state import baked_payload_identity
    from exercise_motion_pkg.fit_runtime import fit_input_key

    names = ["left_ankle", "left_foot", "right_ankle", "right_foot"]
    frame = {
        "joints": dict(zip(names, [[0., .1, 0.], [.18, .02, 0.],
                                   [.1, .1, 0.], [.28, .02, 0.]])),
        "boneSides": {"left_ankle->left_foot": [0., 0., 1.],
                      "right_ankle->right_foot": [0., 0., 1.]},
        "boneSideProvenance": {
            "left_ankle->left_foot": "gvhmr_ankle_global_smpl_rotation",
            "right_ankle->right_foot": "gvhmr_ankle_global_smpl_rotation",
        },
    }
    tracks = {
        "version": 2,
        "left": {
            "active": [True],
            "directions": [[1., 0., 0.]],
            "sideAxes": [[0., 0., 1.]],
            "anchorIds": ["left-contact"],
            "episodes": [{"materialOffsetLocalMeters": [0., .03, -.04],
                          "referenceLengthMeters": .18}],
        },
    }
    payload = {
        "frames": [frame],
        "fps": 30.,
        "frameCount": 1,
        "nativeFootGeometry": _fixture()["reference"],
        "fixedRig": {"contactFootTracks": tracks},
    }
    identity = baked_payload_identity(payload)
    assert baked_payload_identity(copy.deepcopy(payload)) == identity

    frame_mutation = copy.deepcopy(payload)
    frame_mutation["frames"][0]["boneSides"]["left_ankle->left_foot"] = [0., 1., 0.]
    assert baked_payload_identity(frame_mutation)["contentSha256"] != identity["contentSha256"]

    track_mutation = copy.deepcopy(payload)
    track_mutation["fixedRig"]["contactFootTracks"]["left"]["sideAxes"] = [[0., 1., 0.]]
    assert baked_payload_identity(track_mutation)["contentSha256"] != identity["contentSha256"]
    assert fit_input_key(track_mutation) != fit_input_key(payload)

    legacy = {
        "frames": [frame],
        "fps": 30.,
        "frameCount": 1,
        "fixedRig": {"contactFootTracks": {"version": 1, "left": tracks["left"]}},
    }
    legacy_without_tracks = copy.deepcopy(legacy)
    legacy_without_tracks["fixedRig"] = {}
    assert baked_payload_identity(legacy) == baked_payload_identity(legacy_without_tracks)

    malformed = copy.deepcopy(_fixture()["reference"])
    malformed["sides"]["left"]["toeFromAnkleLocalMeters"] = [0., 0., 0.]
    assert validated_native_foot_geometry(malformed) is None
    assert promote_native_foot_geometry({"nativeFootGeometry": malformed}) is None


def test_python_consumers_share_the_same_native_shoe_vertices():
    from exercise_motion_pkg.foot_geometry import (
        _sample_material_foot_geometry, foot_scale_from_pose,
        material_floor_heights, shoe_vertices)
    from exercise_motion_pkg.body_surface_geometry import body_surface_primitive_meshes

    fixture = _fixture()
    names = ["pelvis", "neck", "left_shoulder", "right_shoulder",
             "left_elbow", "right_elbow",
             "left_hip", "right_hip", "left_knee", "right_knee",
             "left_ankle", "right_ankle", "left_foot", "right_foot"]
    pose = np.asarray([[0., 1., 0.], [0., 1.6, 0.], [-.25, 1.55, 0.], [.25, 1.55, 0.],
                       [-.4, 1.3, 0.], [.4, 1.3, 0.],
                       [-.12, .9, 0.], [.12, .9, 0.],
                       [-.12, .55, 0.], [.12, .55, 0.],
                       [-.12, .1, 0.], [.12, .1, 0.],
                       [-.12, .02, .18], [.12, .02, .18]])
    frame = {"joints": dict(zip(names, pose.tolist())),
             "boneSides": {"left_ankle->left_foot": [0., 0., 1.],
                           "right_ankle->right_foot": [0., 0., 1.]}}
    payload = {"frames": [frame], "jointNames": names,
               "footRestPitchRadians": {"left": 0., "right": 0.},
               "loop": {"enabled": False},
               "nativeFootGeometry": fixture["reference"]}
    points = pose[None]
    scale = foot_scale_from_pose(pose, names)
    geometry = _sample_material_foot_geometry(payload, [0.], points)
    binding = {"footScale": scale, "footRestPitchRadians": {},
               "nativeFootGeometry": fixture["reference"],
               "limbSides": {f"{side}_ankle->{side}_foot": geometry[side]["lateral"]
                             for side in ("left", "right")}}
    meshes = body_surface_primitive_meshes(points, names, binding=binding)
    for side in ("left", "right"):
        ankle = names.index(f"{side}_ankle")
        toe = names.index(f"{side}_foot")
        expected = shoe_vertices(
            points[:, ankle], points[:, toe], geometry[side]["lateral"], 0., scale,
            native_geometry=geometry[side]["nativeGeometry"])
        np.testing.assert_allclose(
            meshes[f"wearShoe:{side}_ankle->{side}_foot"]["vertices"], expected,
            atol=1e-12)
        # Native caps are inside the physical longitudinal extrema.
        heel, material_toe = native_foot_marker_world(
            points[0, ankle], points[0, toe], geometry[side]["lateral"],
            geometry[side]["nativeGeometry"])
        forward = (points[0, toe] - points[0, ankle])
        forward /= np.linalg.norm(forward)
        vertices = expected[0]
        longitudinal = (vertices - points[0, ankle]) @ forward
        assert longitudinal.max() <= np.dot(material_toe - points[0, ankle], forward) + 1e-12
        assert longitudinal.min() >= np.dot(heel - points[0, ankle], forward) - 1e-12
        heights = material_floor_heights(
            points, names, {"left": 0., "right": 0.}, scale,
            {other: {"lateral": geometry[other]["lateral"],
                     "orientation": geometry[other]["orientation"],
                     "nativeGeometry": geometry[other]["nativeGeometry"]}
             for other in ("left", "right")})
        assert heights[0, ankle] == pytest.approx(
            min(points[0, ankle, 1], expected[:, :, 1].min()), abs=1e-12)


def test_fit_source_evidence_includes_geometry_only_when_present():
    from exercise_motion_pkg.controlled_motion import controlled_motion_fit_source_evidence

    fixture = _fixture()
    legacy = {"frames": [], "nativeFootGeometry": None}
    legacy.pop("nativeFootGeometry")
    assert "nativeFootGeometry" not in controlled_motion_fit_source_evidence(legacy)
    native = {"frames": [], "nativeFootGeometry": fixture["reference"]}
    assert controlled_motion_fit_source_evidence(native)["nativeFootGeometry"] == fixture["reference"]


def test_invalid_prior_and_recognized_tag_are_rejected_without_repair():
    fixture = _fixture()
    prior = copy.deepcopy(fixture["sourcePrior"])
    prior["sides"]["left"]["modelFootFrame"] = [[1., 0., 0.], [0., 2., 0.], [0., 0., 1.]]
    assert not is_qualified_named_foot_marker_prior(prior)
    assert native_foot_geometry_from_prior(prior) is None

    block = copy.deepcopy(fixture["reference"])
    block["version"] = 2
    assert validated_native_foot_geometry(block) is None
    block = copy.deepcopy(fixture["reference"])
    block["sides"]["left"]["toeFromAnkleLocalMeters"] = [float("nan"), 0., 0.]
    assert validated_native_foot_geometry(block) is None
    block = copy.deepcopy(fixture["reference"])
    block["modelSha256"] = "abc"
    assert validated_native_foot_geometry(block) is None

    # A recognized invalid tag is never repaired from a valid prior.
    payload = {"sourceFootMarkerPrior": fixture["sourcePrior"],
               "nativeFootGeometry": {"version": 9}}
    assert promote_native_foot_geometry(payload) is None
    _assert_geometry_close(
        promote_native_foot_geometry({"sourceFootMarkerPrior": fixture["sourcePrior"]}),
        fixture["reference"])


def test_immutable_validation_rejects_changed_native_geometry(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    fixture = _fixture()
    original = fixture["reference"]
    changed = copy.deepcopy(original)
    changed["sides"]["left"]["toeFromAnkleLocalMeters"] = [.19, 0., 0.]
    payload = {"nativeFootGeometry": original}
    candidate = {"nativeFootGeometry": changed}
    monkeypatch.setattr(
        motion, "fit_controlled_motion",
        lambda *args, **kwargs: (payload, {"applied": True, "validationOnly": True}))
    result, report = motion.validate_controlled_motion_candidate(payload, candidate)
    assert result is payload
    assert report["applied"] is False
    assert report["reason"] == "native_foot_geometry_changed"

"""Candidate repair must read back its own scene-placed native v2 foot tracks."""
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_interpolation import _native_material_point
from exercise_motion_pkg.controlled_motion import _unplaced_contact_foot_tracks
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose
from exercise_motion_pkg.native_foot_geometry import validated_native_foot_geometry

FIXTURES = Path(__file__).parent / "fixtures"


def _unit(values):
    values = np.asarray(values, dtype=float)
    return (values / np.linalg.norm(values)).tolist()


def _placement():
    return {
        "version": 1,
        "orientationReason": "test_retained_placement",
        "referenceFrames": 0,
        "rotationVector": [0.11, -0.07, 0.05],
        "originAfterRotation": [0.0123, -0.777, 0.0456],
        "floorInferred": False,
    }


def _local_native_tracks():
    """Native v2 tracks deliberately omit ``toes`` and carry world episodes."""
    tracks = {"version": 2}
    for side, lateral in (("left", 0.02), ("right", -0.02)):
        anchor = f"{side}:reviewed-stance:toe"
        tracks[side] = {
            "active": [True, True],
            "directions": [_unit([0.6, -0.2, 0.77]), _unit([0.61, -0.19, 0.76])],
            "sideAxes": [_unit([0.7, 0.0, -0.6]), _unit([0.68, 0.01, -0.62])],
            "anchorIds": [anchor, anchor],
            "episodes": [{
                "startFrame": 0,
                "endFrame": 1,
                "anchorId": anchor,
                "regionRole": "full_sole",
                "mode": "stationary",
                "primitiveId": f"wearShoe:{side}_ankle->{side}_foot",
                "triangleIndex": 26,
                "barycentric": [0.0, 0.0, 1.0],
                "materialOffsetLocalMeters": [0.181, lateral, 0.013],
                "referenceLengthMeters": 0.1345,
                "targetWorld": ([0.09, 0.0, -0.22] if side == "left"
                                else [0.13, 0.0, 0.27]),
                "surfaceNormal": [0.0, 1.0, 0.0],
                "planeOffsetMeters": 0.0,
                "soleNormalLocalMeters": [-0.305, 0.0, 0.952],
            }],
        }
    return tracks


def _forward_place(tracks, placement):
    """Reference producer transform: world = rotation * local - origin."""
    placed = deepcopy(tracks)
    rotation = Rotation.from_rotvec(
        np.asarray(placement["rotationVector"], dtype=float))
    origin = np.asarray(placement["originAfterRotation"], dtype=float)
    version = placed.get("version", 1)
    for side in ("left", "right"):
        track = placed.get(side)
        if not isinstance(track, dict):
            continue
        if version == 1:
            track["toes"] = (
                rotation.apply(np.asarray(track["toes"], dtype=float)) - origin
            ).tolist()
            track["directions"] = rotation.apply(
                np.asarray(track["directions"], dtype=float)).tolist()
            continue
        track["directions"] = rotation.apply(
            np.asarray(track["directions"], dtype=float)).tolist()
        track["sideAxes"] = rotation.apply(
            np.asarray(track["sideAxes"], dtype=float)).tolist()
        for episode in track["episodes"]:
            if "targetWorld" in episode:
                episode["targetWorld"] = (
                    rotation.apply(np.asarray(episode["targetWorld"], dtype=float))
                    - origin
                ).tolist()
            if "surfaceNormal" in episode:
                normal = rotation.apply(
                    np.asarray(episode["surfaceNormal"], dtype=float))
                episode["surfaceNormal"] = normal.tolist()
                if "planeOffsetMeters" in episode:
                    episode["planeOffsetMeters"] = (
                        float(episode["planeOffsetMeters"])
                        - float(np.dot(normal, origin)))
    return placed


def _fixture_points():
    fixture = json.loads(
        (FIXTURES / "sequence_stabilization_stance.json").read_text(encoding="utf-8"))
    names = list(fixture["joints"])
    return names, np.asarray([fixture["joints"][name] for name in names], dtype=float)


def _assert_values_close(actual, expected, atol=1e-12):
    if isinstance(expected, dict):
        assert set(actual) == set(expected)
        for key in expected:
            _assert_values_close(actual[key], expected[key], atol=atol)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for left, right in zip(actual, expected):
            _assert_values_close(left, right, atol=atol)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert abs(float(actual) - float(expected)) <= atol
    else:
        assert actual == expected


def test_candidate_repair_reads_back_native_v2_scene_placement():
    placement = _placement()
    local = _local_native_tracks()
    world = _forward_place(local, placement)
    snapshot = json.dumps(world, sort_keys=True, separators=(",", ":"))

    unplaced = _unplaced_contact_foot_tracks(world, placement)

    # The serialized candidate input must not be mutated by the reader.
    assert json.dumps(world, sort_keys=True, separators=(",", ":")) == snapshot
    # All world-space fields must invert together, including episode planes.
    roundtrip = _forward_place(unplaced, placement)
    _assert_values_close(roundtrip, world)
    for side in ("left", "right"):
        for key in ("materialOffsetLocalMeters", "soleNormalLocalMeters",
                    "barycentric", "triangleIndex", "referenceLengthMeters",
                    "primitiveId", "anchorId"):
            assert unplaced[side]["episodes"][0][key] == world[side]["episodes"][0][key]
        assert unplaced[side]["active"] == local[side]["active"]
        assert unplaced[side]["anchorIds"] == local[side]["anchorIds"]
        np.testing.assert_allclose(
            unplaced[side]["episodes"][0]["targetWorld"],
            local[side]["episodes"][0]["targetWorld"],
            atol=1e-12, rtol=0.)
        np.testing.assert_allclose(
            unplaced[side]["episodes"][0]["surfaceNormal"],
            local[side]["episodes"][0]["surfaceNormal"],
            atol=1e-12, rtol=0.)
        np.testing.assert_allclose(
            unplaced[side]["episodes"][0]["planeOffsetMeters"],
            local[side]["episodes"][0]["planeOffsetMeters"], atol=1e-12, rtol=0.)

    # Measured material contact is rigidly equivalent in both gauges.
    names, local_points = _fixture_points()
    rotation = Rotation.from_rotvec(
        np.asarray(placement["rotationVector"], dtype=float))
    origin = np.asarray(placement["originAfterRotation"], dtype=float)
    world_points = rotation.apply(local_points) - origin
    geometry = validated_native_foot_geometry(json.loads(
        (FIXTURES / "native_foot_geometry_v1.json").read_text(encoding="utf-8"))["reference"])
    scale = float(foot_scale_from_pose(local_points, names))
    for side in ("left", "right"):
        ankle, foot = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
        material_local = _native_material_point(
            local_points[ankle], local_points[foot], unplaced[side]["sideAxes"][0],
            unplaced[side]["episodes"][0], geometry["sides"][side], scale)
        material_world = _native_material_point(
            world_points[ankle], world_points[foot], world[side]["sideAxes"][0],
            world[side]["episodes"][0], geometry["sides"][side], scale)
        np.testing.assert_allclose(
            material_world, rotation.apply(material_local) - origin,
            atol=1e-12, rtol=0.)

    # Legacy version-1 tracks keep their toe/direction inverse unchanged.
    legacy = {"version": 1}
    for side in ("left", "right"):
        legacy[side] = {
            "active": [True, True],
            "toes": [[0.1, 0.0, 0.2], [0.11, 0.01, 0.21]],
            "directions": [_unit([0.5, -0.1, 0.8]), _unit([0.5, -0.1, 0.8])],
            "anchorIds": [f"{side}:toe", f"{side}:toe"],
        }
    legacy_world = _forward_place(legacy, placement)
    legacy_unplaced = _unplaced_contact_foot_tracks(legacy_world, placement)
    for side in ("left", "right"):
        np.testing.assert_allclose(
            legacy_unplaced[side]["toes"], legacy[side]["toes"],
            atol=1e-12, rtol=0.)
        np.testing.assert_allclose(
            legacy_unplaced[side]["directions"], legacy[side]["directions"],
            atol=1e-12, rtol=0.)
    # A candidate without a retained placement keeps its serialized gauge.
    assert _unplaced_contact_foot_tracks(legacy, {}) == legacy

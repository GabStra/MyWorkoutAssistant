import copy
import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.foot_geometry import (
    foot_scale_from_pose, material_foot_points, shoe_vertices,
)
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.native_foot_geometry import (
    native_foot_bone_frame, validated_native_foot_geometry,
)
from exercise_motion_pkg.rig_playback import canonical_execution_policy_evidence
from exercise_motion_pkg.support_geometry import _NATIVE_SHOE_SOLE_RING_VERTICES


def _payload_with_native_stance(frame_count=3):
    fixture_dir = Path(__file__).parent / "fixtures"
    stance = json.loads((fixture_dir / "sequence_stabilization_stance.json").read_text())
    geometry_fixture = json.loads((fixture_dir / "native_foot_geometry_v1.json").read_text())
    native = validated_native_foot_geometry(geometry_fixture["reference"])
    names = list(stance["joints"])
    base = np.asarray([stance["joints"][name] for name in names], dtype=float)
    points = np.repeat(base[None, :, :], frame_count, axis=0)
    body_scale = foot_scale_from_pose(base, names)
    anchors = {}

    # Keep the actual rendered forefoot sole patch on one world point while
    # pitching the shoe up at the heel. Skin/toe pivots remain above the floor.
    pitch_degrees = np.linspace(-2.54, -8.0, frame_count)
    side_axes = {side: np.asarray([0., 0., 1.]) for side in ("left", "right")}
    for side in ("left", "right"):
        ankle_i, foot_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
        side_geometry = native["sides"][side]
        length = side_geometry["ankleToFootJointLengthMeters"]
        anchor = np.asarray([base[foot_i, 0], 0., base[foot_i, 2]])
        anchors[side] = anchor
        for frame, angle in enumerate(np.deg2rad(pitch_degrees)):
            sign = 1. if base[foot_i, 0] >= base[ankle_i, 0] else -1.
            forward = np.asarray([sign * np.cos(angle), np.sin(angle), 0.])
            local_mesh = shoe_vertices(
                np.zeros(3), length * forward, side_axes[side], None, body_scale,
                native_geometry=side_geometry)
            local_pivot = np.mean(
                local_mesh[list(_NATIVE_SHOE_SOLE_RING_VERTICES[-2:])], axis=0)
            ankle = anchor - local_pivot
            foot = ankle + length * forward
            points[frame, ankle_i] = ankle
            points[frame, foot_i] = foot

    rig = FixedRig(points, names)
    fixed_rig = {
        "version": 1,
        "jointNames": list(names),
        "parents": rig.parents,
        "order": rig.order,
        "offsets": rig.offsets.tolist(),
        "rotationJointNames": [names[index] for index in rig.active],
        "coordinates": rig.initial.tolist(),
    }
    scale = foot_scale_from_pose(points[0], names)
    tracks = {"version": 2}
    for side in ("left", "right"):
        ankle_i, foot_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
        directions = points[:, foot_i] - points[:, ankle_i]
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)
        active = side == "left"
        anchor_id = f"{side}-forefoot" if active else None
        episode = {
            "startFrame": 0, "endFrame": frame_count - 1,
            "anchorId": anchor_id, "mode": "stationary", "regionRole": "forefoot",
            "primitiveId": f"wearShoe:{side}_ankle->{side}_foot",
            "triangleIndex": 26, "barycentric": [0., .5, .5],
            "materialOffsetLocalMeters": [0., 0., 0.],
            "referenceLengthMeters": native["sides"][side]["ankleToFootJointLengthMeters"],
            "targetWorld": anchors[side].tolist(),
            "surfaceNormal": [0., 1., 0.], "planeOffsetMeters": 0.,
        }
        if active:
            ankle_i, foot_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
            forward, lateral, up, current_length = native_foot_bone_frame(
                points[0, ankle_i], points[0, foot_i], side_axes[side])
            mesh = shoe_vertices(
                points[0, ankle_i], points[0, foot_i], side_axes[side], None, scale,
                native_geometry=native["sides"][side])
            bound = np.asarray(episode["barycentric"]) @ mesh[
                shoe_triangles()[episode["triangleIndex"]]]
            delta = bound - points[0, ankle_i]
            episode["materialOffsetLocalMeters"] = [
                float(np.dot(delta, axis) * episode["referenceLengthMeters"] / current_length[0])
                for axis in (forward, lateral, up)
            ]
        episodes = [episode] if active else []
        tracks[side] = {
            "active": [active] * frame_count,
            "directions": directions.tolist(),
            "sideAxes": [side_axes[side].tolist()] * frame_count,
            "anchorIds": [anchor_id] * frame_count,
            "episodes": episodes,
        }
    fixed_rig["contactFootTracks"] = tracks
    payload = {
        "fps": 30.,
        "jointNames": names,
        "fixedRig": fixed_rig,
        "nativeFootGeometry": native,
        "canonicalExecution": {"stance": "stationary_bilateral"},
        "loop": {"enabled": False},
        "renderFloorY": 0.,
        "groundContactMode": "continuous",
        "frames": [
            {"timeSec": frame / 30., "joints": dict(zip(names, sample.tolist()))}
            for frame, sample in enumerate(points)
        ],
    }
    return names, points, payload, native, side_axes


def _sole_pivots(names, points, native, side_axes, scale):
    result = {}
    for side in ("left", "right"):
        ankle_i, foot_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
        vertices = shoe_vertices(
            points[:, ankle_i], points[:, foot_i], side_axes[side], None, scale,
            native_geometry=native["sides"][side])
        result[side] = {
            "forefoot": np.mean(
                vertices[:, list(_NATIVE_SHOE_SOLE_RING_VERTICES[-2:])], axis=1),
            "heel": np.mean(vertices[:, list(_NATIVE_SHOE_SOLE_RING_VERTICES[:2])], axis=1),
            "minimumMeshY": vertices[:, :, 1].min(axis=1),
        }
    return result


def test_stationary_bilateral_uses_native_forefoot_pivots_and_allows_heel_rise():
    names, points, payload, native, side_axes = _payload_with_native_stance()
    pivots = _sole_pivots(
        names, points, native, side_axes, foot_scale_from_pose(points[0], names))
    skin_markers = {}
    for side in ("left", "right"):
        ankle_i = names.index(f"{side}_ankle")
        foot_i = names.index(f"{side}_foot")
        _, skin_markers[side] = material_foot_points(
            points[:, ankle_i], points[:, foot_i], side_axes[side], None,
            native_geometry=native["sides"][side])
    report = canonical_execution_policy_evidence(payload, points)

    stance = report["stationaryBilateralStance"]
    assert report["passed"] is True, report
    for side, authority in (("left", "source_native_contact_track"),
                            ("right", "canonical_inferred_native_geometry")):
        row = stance["toePivots"][side]
        expected_pivot = ("qualified_episode_material_point" if side == "left"
                          else "native_forefoot_sole_patch")
        assert row["pivotKind"] == expected_pivot
        assert row["geometryAuthority"] == authority
        assert row["maximumDriftMeters"] <= .0005
        assert row["maximumToeFloorErrorMeters"] <= .0005
    assert stance["toePivots"]["left"]["observedTrackFrameCount"] == len(points)
    assert stance["toePivots"]["right"]["observedTrackFrameCount"] == 0
    assert max(np.max(np.abs(pivots[side]["forefoot"][:, 1])) for side in pivots) <= 1e-10
    # The toe joint is above the floor in this heel-raised stance and the full
    # rendered shoe mesh does not penetrate it. This fixture's qualified native
    # model places its skin marker exactly at the forefoot sole-patch mean.
    assert min(np.min(points[:, names.index(f"{side}_foot"), 1]) for side in pivots) > .0005
    assert min(np.min(skin_markers[side][:, 1]) for side in pivots) >= -.0005
    assert min(np.min(pivots[side]["minimumMeshY"]) for side in pivots) >= -.0005
    for side in pivots:
        np.testing.assert_allclose(
            skin_markers[side][:, 1], pivots[side]["forefoot"][:, 1], atol=1e-10)
    assert np.ptp(pivots["left"]["heel"][:, 1]) > .005


def test_native_material_pivot_drift_and_floor_gap_fail_but_legacy_uses_toe_joint():
    names, points, payload, native, side_axes = _payload_with_native_stance()

    drifted = points.copy()
    for name in ("left_ankle", "left_foot"):
        drifted[-1, names.index(name), 0] += .002
    drift_report = canonical_execution_policy_evidence(payload, drifted)
    assert drift_report["passed"] is False
    assert drift_report["stationaryBilateralStance"]["toePivots"]["left"][
        "maximumDriftMeters"] > .0005

    lifted = points.copy()
    lifted[:, :, 1] += .001
    floor_report = canonical_execution_policy_evidence(payload, lifted)
    assert floor_report["passed"] is False
    assert floor_report["stationaryBilateralStance"]["toePivots"]["left"][
        "maximumToeFloorErrorMeters"] > .0005

    legacy = copy.deepcopy(payload)
    legacy.pop("nativeFootGeometry")
    legacy["fixedRig"].pop("contactFootTracks")
    legacy_report = canonical_execution_policy_evidence(legacy, points)
    legacy_left = legacy_report["stationaryBilateralStance"]["toePivots"]["left"]
    assert legacy_left["pivotKind"] == "legacy_toe_joint"
    assert legacy_left["maximumToeFloorErrorMeters"] > .0005
    assert legacy_report["passed"] is False

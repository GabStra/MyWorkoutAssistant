import copy
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import (
    FixedRig,
    active_native_stationary_material_episode,
)
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
from exercise_motion_pkg.joint_plant_initialization import (
    initialize_joint_plant_coordinates,
)
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.native_foot_geometry import validated_native_foot_geometry


def _material_episode(points, names, rig, side, native, scale, triangle_index,
                      barycentric):
    """Built from playback's stored direction/side-axis material formula."""
    ankle_i, toe_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
    reference_world = rig.global_rotations(rig.material_reference_coordinates)
    reference_axis = reference_world[toe_i] @ np.asarray([1., 0., 0.])
    side_axes = rig.material_side_axes(
        rig.initial, np.broadcast_to(reference_axis, (len(points), 3)), side)
    direction = points[:, toe_i] - points[:, ankle_i]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    up = np.cross(side_axes, direction)
    first_mesh = shoe_vertices(
        points[0, ankle_i], points[0, toe_i], side_axes[0], None, scale,
        native_geometry=native["sides"][side])
    target = barycentric @ first_mesh[shoe_triangles()[triangle_index]]
    delta = target - points[0, ankle_i]
    local_offset = np.asarray([
        np.dot(direction[0], delta),
        np.dot(side_axes[0], delta),
        np.dot(up[0], delta),
    ])
    length = float(np.linalg.norm(rig.offsets[toe_i]))
    return {
        "track": {
            "active": [True] * len(points),
            "directions": direction.tolist(),
            "sideAxes": side_axes.tolist(),
            "anchorIds": [f"{side}-forefoot"] * len(points),
            "episodes": [{
                "startFrame": 0, "endFrame": len(points) - 1,
                "anchorId": f"{side}-forefoot", "mode": "stationary",
                "regionRole": "forefoot",
                "primitiveId": f"wearShoe:{side}_ankle->{side}_foot",
                "triangleIndex": triangle_index,
                "barycentric": barycentric.tolist(),
                "materialOffsetLocalMeters": local_offset.tolist(),
                "referenceLengthMeters": length,
                "targetWorld": target.tolist(),
                "surfaceNormal": [0., 1., 0.],
                "planeOffsetMeters": float(target[1]),
            }],
        },
        "target": target,
        "direction": direction,
        "sideAxes": side_axes,
        "localOffset": local_offset,
        "length": length,
    }


def _case(left_mode, *, bent_knees=False):
    fixture_dir = Path(__file__).parent / "fixtures"
    stance = json.loads((fixture_dir / "sequence_stabilization_stance.json").read_text())
    geometry_fixture = json.loads((fixture_dir / "native_foot_geometry_v1.json").read_text())
    names = list(stance["joints"])
    frame_count = 5
    source_points = np.repeat(
        np.asarray([stance["joints"][name] for name in names], dtype=float)[None],
        frame_count, axis=0)
    if bent_knees:
        for side in ('left', 'right'):
            source_points[:, names.index(f'{side}_knee'), 2] += .08
    rig = FixedRig(source_points, names)
    coordinates = rig.initial.copy()
    coordinates[:, 0] += np.linspace(0., .004, frame_count)
    # Vary only the left foot pitch so the derived seed must preserve it.
    foot_index = names.index("left_foot")
    parent_index = rig.parents[foot_index]
    foot_slot = rig.slots[foot_index]
    world = rig.global_rotations(coordinates)
    source_world = rig.global_rotations(rig.material_reference_coordinates)[foot_index]
    source_axis = source_world @ np.asarray([1., 0., 0.])
    parent_world = rig.global_rotations(coordinates)[parent_index]
    angles = np.deg2rad(np.linspace(6., 13., frame_count))
    for frame, angle in enumerate(angles):
        delta = Rotation.from_rotvec(source_axis[frame] * angle).as_matrix()
        desired = delta @ world[foot_index][frame]
        local = parent_world[frame].T @ desired
        coordinates[frame, foot_slot:foot_slot + 3] = Rotation.from_matrix(local).as_rotvec()
    points = rig.decode(coordinates)
    native = validated_native_foot_geometry(geometry_fixture["reference"])
    scale = foot_scale_from_pose(points[0], names)
    barycentric = np.asarray([.2, .4, .4])
    left = _material_episode(points, names, rig, "left", native, scale, 10, barycentric)
    right = _material_episode(points, names, rig, "right", native, scale, 10, barycentric)
    if left_mode == "verticalOnly":
        episode = left["track"]["episodes"][0]
        episode.pop("targetWorld")
        episode["mode"] = "verticalOnly"
    tracks = {"version": 2, "left": left["track"], "right": right["track"]}
    pinned = np.zeros(points.shape[:2], dtype=bool)
    return (names, rig, coordinates, points, points.copy(), pinned, tracks, native,
            scale, left, right)


def test_height_only_native_projection_keeps_source_hinge_and_plane_consistent():
    from exercise_motion_pkg.physical_validation import hinge_direction_events
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
    from exercise_motion_pkg.supported_contact_rig import _episode_targets, _material_points

    (names, rig, coordinates, points, targets, pinned, tracks, native, scale,
     left, _) = _case('verticalOnly', bent_knees=True)
    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets, articulation_reference=points,
        fps=30., cyclic=False, deadline=monotonic() + 20.,
        native_foot_geometry=native, native_foot_tracks=tracks)
    assert initialized is not None, report
    actual = rig.decode(initialized)
    assert not hinge_direction_events(actual, names, points, fps=30.)
    axes = _native_side_axes_for_coordinates(
        rig, initialized, {'_nativeFootMaterialTracks': tracks})
    episode = left['track']['episodes'][0]
    material = _material_points(actual[:, names.index('left_ankle')],
        actual[:, names.index('left_foot')], axes['left'], episode)
    assert np.max(np.linalg.norm(_episode_targets(episode, material) - material, axis=1)) < 1e-5
    assert not pinned.any()


@pytest.mark.parametrize("left_mode, left_owned", [
    ("stationary", True),
    ("verticalOnly", False),
])
def test_native_forefoot_seed_preserves_pitch_and_leaves_height_only_free(
        left_mode, left_owned):
    (names, rig, coordinates, points, targets, pinned, tracks, native, scale,
     left, right) = _case(left_mode)
    assert active_native_stationary_material_episode(tracks, names, len(points))
    # A vertical-only plane never becomes a fully anchored XYZ contact.
    only_height = {"version": 2, "right": copy.deepcopy(tracks["right"])}
    right_episode = only_height["right"]["episodes"][0]
    right_episode.pop("targetWorld")
    right_episode["mode"] = "verticalOnly"
    assert not active_native_stationary_material_episode(only_height, names, len(points))

    captured = {}
    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets, articulation_reference=points,
        fps=30., cyclic=False, deadline=monotonic() + 20.,
        native_foot_geometry=native, native_foot_tracks=tracks,
        native_fullsole_constraint_capture=lambda constraints: captured.update(
            constraints))
    assert initialized is not None, report
    material = (report.get("nativeFullsole") or {}).get("material") or {}
    assert material.get("available") is True
    assert material.get("derivedSource") == "stored_playback_direction_and_side_axis"
    assert material.get("seedOnly") is True
    assert material.get("fitAuthority") == "calibrated_material_point_residual"
    # The closed-chain seed must not hand the stored inferred direction to the
    # fit as full-XYZ ankle/toe pins; the fit keeps the calibrated material
    # point residual instead.
    assert captured, report.get("nativeFullsole")
    assert captured["materialSeedPinnedFrameCount"] > 0
    assert not captured["pinned"].any()
    assert "right" in (material.get("sides") or {})
    if left_owned:
        assert "left" in (material.get("sides") or {})
        assert (report.get("nativeFullsole") or {}).get(
            "materialPostcheck", {}).get("passed") is True
    else:
        assert "left" not in (material.get("sides") or {})

    actual = rig.decode(initialized)

    def _material_target_error(side, entry):
        """Playback's stored direction/side-axis material reconstruction error."""
        ankle_i = names.index(f"{side}_ankle")
        direction = np.asarray(entry["track"]["directions"], dtype=float)
        lateral = np.asarray(entry["track"]["sideAxes"], dtype=float)
        up = np.cross(lateral, direction)
        scale_ratio = entry["length"] / entry["track"]["episodes"][0][
            "referenceLengthMeters"]
        local = entry["localOffset"]
        offset = ((direction * local[0] + lateral * local[1] + up * local[2])
                  * scale_ratio)
        return np.max(np.linalg.norm(
            actual[:, ankle_i] + offset - entry["target"], axis=1))

    def _pitch_spread(side, entry):
        ankle_i, toe_i = names.index(f"{side}_ankle"), names.index(f"{side}_foot")
        direction = actual[:, toe_i] - actual[:, ankle_i]
        direction /= np.linalg.norm(direction, axis=1)[:, None]
        source_direction = np.asarray(entry["track"]["directions"], dtype=float)
        spread = np.degrees(np.arccos(np.clip(
            source_direction[0] @ source_direction[-1], -1., 1.)))
        return direction, source_direction, spread

    for side, entry in (("left", left), ("right", right)):
        if side == "left" and not left_owned:
            continue
        assert _material_target_error(side, entry) <= 1e-5, side
        actual_direction, source_direction, spread = _pitch_spread(side, entry)
        if side == "left":
            # The left foot's source pitch varies; owned material pins preserve
            # that frame-varying toe/ankle pitch instead of freezing it flat.
            assert spread > 2., (side, spread)
        alignment = np.degrees(np.arccos(np.clip(
            np.sum(actual_direction * source_direction, axis=1), -1., 1.)))
        assert np.max(alignment) <= .1, (side, np.max(alignment))

    if not left_owned:
        # A vertical-only row is not a fully anchored material point: playback's
        # reconstructed target is deliberately not locked, so the unowned side
        # must miss the target while still keeping its varying pitch (no freeze).
        assert _material_target_error("left", left) > 1e-4
        _, _, spread = _pitch_spread("left", left)
        assert spread > 2., spread

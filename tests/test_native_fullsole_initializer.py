import copy
import json
from pathlib import Path
from time import monotonic

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.joint_plant_initialization import initialize_joint_plant_coordinates
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg.native_foot_geometry import validated_native_foot_geometry
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
from exercise_motion_pkg.support_geometry import _native_foot_material_contact_residuals


def _case(frame_count=4):
    fixture_dir = Path(__file__).parent / "fixtures"
    stance = json.loads((fixture_dir / "sequence_stabilization_stance.json").read_text())
    geometry_fixture = json.loads((fixture_dir / "native_foot_geometry_v1.json").read_text())
    names = list(stance["joints"])
    source_points = np.repeat(
        np.asarray([stance["joints"][name] for name in names], dtype=float)[None],
        frame_count, axis=0)
    rig = FixedRig(source_points, names)
    coordinates = rig.initial.copy()
    foot_index = names.index("left_foot")
    ankle_index = names.index("left_ankle")
    parent_index = rig.parents[foot_index]
    foot_slot = rig.slots[foot_index]

    # Give each frame a slightly different source pose and lift the left heel
    # by pitching the complete foot frame around its carried lateral axis.
    q = coordinates.copy()
    q[:, 0] += np.linspace(0., .004, frame_count)
    world = rig.global_rotations(q)
    source_world = rig.global_rotations(rig.material_reference_coordinates)[foot_index]
    source_axes = source_world @ np.asarray([1., 0., 0.])
    angles = np.deg2rad(np.linspace(6., 10., frame_count))
    parent_world = rig.global_rotations(q)[parent_index]
    for frame, angle in enumerate(angles):
        delta = Rotation.from_rotvec(source_axes[frame] * angle).as_matrix()
        desired_world = delta @ world[foot_index][frame]
        local = parent_world[frame].T @ desired_world
        q[frame, foot_slot:foot_slot + 3] = Rotation.from_matrix(local).as_rotvec()

    points = rig.decode(q)
    native = validated_native_foot_geometry(geometry_fixture["reference"])
    scale = foot_scale_from_pose(points[0], names)
    side_axes = rig.material_side_axes(q, np.broadcast_to(source_axes, (frame_count, 3)), "left")
    source_world_by_joint = rig.global_rotations(rig.material_reference_coordinates)
    axes_by_side = []
    for side in ("left", "right"):
        side_foot = names.index(f"{side}_foot")
        reference_axis = source_world_by_joint[side_foot] @ np.asarray([1., 0., 0.])
        axes_by_side.append(rig.material_side_axes(
            q, reference_axis, side))
    side_axis_by_side = np.stack(axes_by_side, axis=1)
    triangle_index = 10
    barycentric = np.asarray([.2, .4, .4])
    triangle = shoe_triangles()[triangle_index]
    first_mesh = shoe_vertices(
        points[0, ankle_index], points[0, foot_index], side_axes[0], None, scale,
        native_geometry=native["sides"]["left"])
    target = barycentric @ first_mesh[triangle]
    bone_length = float(np.linalg.norm(points[0, foot_index] - points[0, ankle_index]))
    local_frame = np.stack((
        (points[:, foot_index] - points[:, ankle_index]) /
        np.linalg.norm(points[:, foot_index] - points[:, ankle_index], axis=1)[:, None],
        side_axes,
        np.cross(side_axes, (points[:, foot_index] - points[:, ankle_index]) /
                 np.linalg.norm(points[:, foot_index] - points[:, ankle_index], axis=1)[:, None]),
    ), axis=2)
    material_offset = local_frame[0].T @ (target - points[0, ankle_index])
    material_offset *= bone_length / bone_length

    track = {"version": 2, "left": {
        "active": [True] * frame_count,
        "directions": ((points[:, foot_index] - points[:, ankle_index]) /
                       np.linalg.norm(points[:, foot_index] - points[:, ankle_index], axis=1)[:, None]).tolist(),
        "sideAxes": side_axes.tolist(),
        "anchorIds": ["left-fullsole"] * frame_count,
        "episodes": [{
            "startFrame": 0, "endFrame": frame_count - 1,
            "anchorId": "left-fullsole", "mode": "stationary",
            "regionRole": "full_sole", "primitiveId": "wearShoe:left_ankle->left_foot",
            "triangleIndex": triangle_index, "barycentric": barycentric.tolist(),
            "materialOffsetLocalMeters": material_offset.tolist(),
            "referenceLengthMeters": bone_length,
            "targetWorld": target.tolist(),
            "surfaceNormal": [0., 1., 0.], "planeOffsetMeters": float(target[1]),
        }],
    }}
    pinned = np.zeros(points.shape[:2], dtype=bool)
    right_foot = names.index("right_foot")
    pinned[:, right_foot] = True
    targets = points.copy()
    targets[:, right_foot, 0] += .006
    return (names, rig, q, points, targets, pinned, track, native, scale,
            side_axis_by_side, target)


def test_joint_plant_flattens_native_fullsole_and_preserves_opposite_joint_pin():
    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case()
    pins_before = pinned.copy()
    coordinates_before = coordinates.copy()
    right_foot = names.index("right_foot")
    left_knee = names.index("left_knee")
    left_ankle = names.index("left_ankle")
    left_foot = names.index("left_foot")

    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
    )

    assert initialized is not None, report
    result = rig.decode(initialized)
    assert report["feasible"] is True
    assert report["root"]["maxMagnitudeMeters"] > 1e-5
    assert report["nativeFullsole"]["postcheck"][
        "maximumSoleMaterialStationarityMeters"] <= 1e-5
    np.testing.assert_allclose(result[:, right_foot], targets[:, right_foot], atol=1e-5)
    np.testing.assert_array_equal(pinned, pins_before)
    np.testing.assert_array_equal(coordinates, coordinates_before)
    assert np.ptp(result[:, left_knee, 0]) > 1e-4  # No temporal knee freeze.

    child_ids = np.flatnonzero(np.asarray(rig.parents) >= 0)
    parent_ids = np.asarray(rig.parents)[child_ids]
    np.testing.assert_allclose(
        np.linalg.norm(result[:, child_ids] - result[:, parent_ids], axis=-1),
        np.linalg.norm(source_points[:, child_ids] - source_points[:, parent_ids], axis=-1),
        atol=1e-8)
    assert not np.any(pinned[:, left_knee])
    assert np.ptp(result[:, left_knee, 0]) > 1e-4

    reference_axis = (rig.global_rotations(rig.material_reference_coordinates)[left_foot]
                      @ np.asarray([1., 0., 0.]))
    projected_axes = rig.material_side_axes(
        initialized, np.broadcast_to(reference_axis, (len(result), 3)), "left")
    from exercise_motion_pkg.support_geometry import _NATIVE_SHOE_SOLE_RING_VERTICES
    left_sole = shoe_vertices(
        result[:, left_ankle], result[:, left_foot], projected_axes, None, scale,
        native_geometry=native["sides"]["left"]
    )[:, _NATIVE_SHOE_SOLE_RING_VERTICES]
    assert np.max(np.linalg.norm(left_sole - left_sole[:1], axis=-1)) <= 1e-5
    residuals, errors = _native_foot_material_contact_residuals(
        result, names, {
            "_nativeFootMaterialTracks": tracks,
            "nativeFootGeometry": native,
            "_nativeFootScale": scale,
        }, side_axes_override={"left": projected_axes})
    assert errors == []
    assert residuals.shape == (len(result), 10)  # anchor, penetration, six sole vertices
    assert np.max(np.abs(residuals)) <= 1e-5

    from exercise_motion_pkg.controlled_motion import _refresh_native_foot_contact_tracks
    original_tracks = copy.deepcopy(tracks)
    serialized_tracks = _refresh_native_foot_contact_tracks(
        rig, initialized, tracks, {"_nativeFootMaterialTracks": tracks})
    assert tracks == original_tracks  # Immutable validation must not rebind its input.
    serialized_evidence = {
        "_nativeFootMaterialTracks": serialized_tracks,
        "nativeFootGeometry": native,
        "_nativeFootScale": scale,
    }
    serialized_residuals, serialized_errors = _native_foot_material_contact_residuals(
        result, names, serialized_evidence)
    assert serialized_errors == []
    assert np.max(np.abs(serialized_residuals)) <= 1e-5


    from exercise_motion_pkg.support_geometry import _validate_skeletal_support_geometry
    count = len(result)
    stationary_evidence = {
        "required": True,
        "status": "confirmed",
        "stationaryJoints": ["left_ankle", "left_foot"],
        "contacts": [{
            "jointName": "left_foot", "contactState": "full_sole",
            "contactMotion": "stationary", "verticalOnly": False,
            "sourceFrameCount": count, "sourceFrameBounds": [0, count - 1],
            "startRatio": 0., "endRatio": 1.,
            "_fitFrameRuns": [[0, count - 1]], "_fitFrameCount": count,
        }],
        "soleContacts": [{
            "joints": ["left_knee", "left_ankle", "left_foot"],
            "normal": [0., 1., 0.],
        }],
        "coplanarGroups": [],
        "nonPenetrationChains": [],
        "_nativeFootMaterialTracks": serialized_tracks,
        "_nativeFootScale": scale,
        "nativeFootGeometry": native,
        "materialFootRestPitchRadians": {},
    }
    validation_payload = {
        "jointNames": names,
        "frames": [{
            "sourceTimeSec": frame / 30.,
            "joints": dict(zip(names, row.tolist())),
        } for frame, row in enumerate(result)],
        "fixedRig": {
            "jointNames": names,
            "coordinates": initialized.tolist(),
            "contactFootTracks": serialized_tracks,
        },
        "nativeFootGeometry": native,
        "sourceFootSupportEvidence": {"bodySupport": stationary_evidence},
        "renderFloorY": float(target[1]),
        "loop": {"enabled": False},
    }
    support_geometry = _validate_skeletal_support_geometry(
        validation_payload, result, names, evidence_override=stationary_evidence)
    assert support_geometry["maximumStationaryJointRangeMeters"] <= 1e-5
    assert "supported_body_moves" not in support_geometry["rejectionReasons"]

    # An unreachable world anchor fails closed without mutating the source q.
    unreachable = copy.deepcopy(tracks)
    unreachable["left"]["episodes"][0]["targetWorld"] = (
        np.asarray(target) + np.asarray([4., 0., 0.])).tolist()
    initializer_failures = []
    rejected, reject_report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=unreachable,
        failure_capture=lambda stage, q, details: initializer_failures.append(
            (stage, q.copy(), copy.deepcopy(details))),
    )
    assert rejected is None, reject_report
    assert reject_report.get("feasible") is False
    assert len(initializer_failures) == 1
    assert initializer_failures[0][1].shape == coordinates.shape
    assert initializer_failures[0][0]
    np.testing.assert_array_equal(coordinates, coordinates_before)


def test_rejected_fit_capture_does_not_enable_intermediate_stage_diagnostics():
    from exercise_motion_pkg.controlled_motion import (
        _joint_plant_stage_capture_callback,
        _joint_plant_stage_diagnostics_enabled,
        capture_joint_plant_stage_diagnostics,
        capture_rejected_fit_candidate,
    )

    assert not _joint_plant_stage_diagnostics_enabled()
    observer = lambda *_: None
    with capture_rejected_fit_candidate(lambda *_: None):
        assert not _joint_plant_stage_diagnostics_enabled()
        assert _joint_plant_stage_capture_callback(observer) is None
    with capture_joint_plant_stage_diagnostics():
        assert _joint_plant_stage_diagnostics_enabled()
        assert _joint_plant_stage_capture_callback(observer) is observer
        with capture_rejected_fit_candidate(lambda *_: None):
            assert _joint_plant_stage_diagnostics_enabled()
    assert not _joint_plant_stage_diagnostics_enabled()


def test_joint_plant_opt_in_stage_capture_tracks_native_fullsole_encode_boundary():
    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case(frame_count=4)
    captured = []

    def capture(stage, stage_coordinates, postcheck):
        captured.append((stage, stage_coordinates.copy(), copy.deepcopy(postcheck)))

    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
        diagnostic_stage_capture=capture,
    )

    assert initialized is not None, report
    assert [stage for stage, _, _ in captured] == [
        "before_root_adjusted_pose_encode",
        "after_root_adjusted_pose_encode",
        "after_native_track_projection",
        "after_native_fullsole_material_twist_encode",
    ]
    for _, stage_coordinates, postcheck in captured:
        assert stage_coordinates.shape == coordinates.shape
        assert set(postcheck["bySide"]) == {"left"}
        assert "maximumSoleMaterialStationarityMeters" in postcheck
    assert captured[-1][2] == report["nativeFullsole"]["postcheck"]
    before_twist = rig.decode(captured[-2][1])
    after_twist = rig.decode(captured[-1][1])
    for side in ("left", "right"):
        for joint in (f"{side}_ankle", f"{side}_foot"):
            joint_index = names.index(joint)
            np.testing.assert_allclose(
                after_twist[:, joint_index], before_twist[:, joint_index],
                rtol=0., atol=1e-12)


def test_native_fullsole_calibrates_varying_source_local_material_axes_per_frame():
    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case(frame_count=5)
    tracks = copy.deepcopy(tracks)
    side_axes = np.asarray(tracks["left"]["sideAxes"], dtype=float)
    ankle_i, foot_i = names.index("left_ankle"), names.index("left_foot")
    forward = source_points[:, foot_i] - source_points[:, ankle_i]
    forward /= np.linalg.norm(forward, axis=1, keepdims=True)
    local_axis_roll = np.deg2rad(np.linspace(0., 8., len(side_axes)))
    tracks["left"]["sideAxes"] = np.asarray([
        Rotation.from_rotvec(axis * angle).apply(seed_axis)
        for axis, angle, seed_axis in zip(forward, local_axis_roll, side_axes)
    ]).tolist()
    reference_foot_rotations = rig.global_rotations(
        rig.material_reference_coordinates)[foot_i]
    source_local_axes = np.einsum(
        "fji,fj->fi", reference_foot_rotations,
        np.asarray(tracks["left"]["sideAxes"], dtype=float))
    local_axis_degrees = np.rad2deg(np.arccos(np.clip(
        np.sum(source_local_axes * source_local_axes[:1], axis=1), -1., 1.)))
    assert np.max(local_axis_degrees) >= 7.9

    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
    )

    assert initialized is not None, report
    postcheck = report["nativeFullsole"]["postcheck"]
    assert postcheck["passed"] is True
    assert postcheck["maximumSoleMaterialStationarityMeters"] <= 1e-5
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
    output_points = rig.decode(initialized)
    output_axes = _native_side_axes_for_coordinates(
        rig, initialized, {"_nativeFootMaterialTracks": tracks})["left"]
    output_mesh = shoe_vertices(
        output_points[:, ankle_i], output_points[:, foot_i], output_axes, None, scale,
        native_geometry=native["sides"]["left"])
    from exercise_motion_pkg.support_geometry import _NATIVE_SHOE_SOLE_RING_VERTICES
    output_sole = output_mesh[:, _NATIVE_SHOE_SOLE_RING_VERTICES]
    assert np.max(np.linalg.norm(output_sole - output_sole[:1], axis=-1)) <= 1e-5

    # The calibration is episode-owned: forefoot sliding and release frames
    # keep their own tracked local axes.
    scoped_tracks = copy.deepcopy(tracks)
    scoped_tracks["left"]["active"] = [True, True, True, True, False]
    scoped_tracks["left"]["anchorIds"] = ["left-fullsole"] * 3 + ["left-slide", None]
    fullsole_episode = copy.deepcopy(scoped_tracks["left"]["episodes"][0])
    fullsole_episode["endFrame"] = 2
    sliding_episode = {
        **fullsole_episode,
        "startFrame": 3,
        "endFrame": 3,
        "anchorId": "left-slide",
        "regionRole": "forefoot",
        "mode": "sliding",
    }
    scoped_tracks["left"]["episodes"] = [fullsole_episode, sliding_episode]
    scoped_world = rig.global_rotations(coordinates)[foot_i]
    scoped_axes = _native_side_axes_for_coordinates(
        rig, coordinates, {"_nativeFootMaterialTracks": scoped_tracks})["left"]
    scoped_local = np.einsum("fji,fj->fi", scoped_world, scoped_axes)
    uncalibrated_local = np.einsum(
        "fji,fj->fi", reference_foot_rotations,
        np.asarray(scoped_tracks["left"]["sideAxes"], dtype=float))
    np.testing.assert_allclose(
        scoped_local[:3], np.broadcast_to(scoped_local[:1], (3, 3)),
        rtol=0., atol=1e-12)
    np.testing.assert_allclose(scoped_local[3:], uncalibrated_local[3:], rtol=0., atol=1e-12)
    assert np.linalg.norm(scoped_local[3] - scoped_local[2]) > 1e-3


def test_initializer_rejects_distant_camera_yaw_outside_source_articulation_envelope():
    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case()
    ankle, foot = names.index("left_ankle"), names.index("left_foot")
    projection_constraint = {
        "available": True,
        "projection": np.asarray([[1., 0., 0.], [0., 0., 1.]]),
        "sourceFootRaySideMapping": {"left": "left"},
        "sourceFootRayObservations": [{
            "sourceSide": "left", "motionSide": "left",
            "leftFrame": 0, "rightFrame": 0, "alpha": 0.,
            "ankleJointIndex": ankle, "footJointIndex": foot,
            "targetRay": np.asarray([1., 0.]), "headingOffsetRadians": 0.,
        }],
    }

    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
        source_projection_constraint=projection_constraint,
    )

    assert initialized is not None, report
    assert report["feasible"] is True
    rejected_yaw = report["nativeFullsole"].get("sourceCameraYawRejected")
    assert rejected_yaw is not None, report["nativeFullsole"]
    assert rejected_yaw["side"] == "left"
    assert abs(np.rad2deg(rejected_yaw["proposedYawRadians"])) > 15.
    assert rejected_yaw["proposedPreflight"]["p95SourceHeadingDeltaDegrees"] > 15.
    assert report["nativeFullsole"]["postcheck"]["passed"] is True


def test_root_track_exact_frame_state_cache_preserves_solution_and_reduces_calls(
        monkeypatch):
    import exercise_motion_pkg.joint_plant_initialization as initialization

    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, _) = _case(frame_count=4)
    points = rig.decode(coordinates)
    side_axes = {side: side_axis_by_side[:, index, :]
                 for index, side in enumerate(("left", "right"))}
    fullsole = initialization._native_fullsole_solver_constraints(
        rig, points, coordinates, pinned, targets,
        native_foot_tracks=tracks, native_foot_geometry=native,
        side_axis_by_side=side_axes, foot_scale=scale)
    specs, preflight = initialization._make_specs(
        names, points, fullsole["pins"], fullsole["targets"], source_points,
        cyclic=True, floor_y=float(fullsole["coverage"]["left"][0]["targets"][0, 1]),
        rest_pitch_radians={}, foot_scale=scale,
        side_axis_by_side=side_axis_by_side, fps=30.)
    assert specs and preflight["feasible"] is True

    original_frame_state = initialization._frame_state
    counts = {}

    def run(cache_enabled):
        count = 0

        def counted(*args, **kwargs):
            nonlocal count
            count += 1
            return original_frame_state(*args, **kwargs)

        monkeypatch.setattr(initialization, "_frame_state", counted)
        try:
            result = initialization._root_track(
                specs, len(points), monotonic() + 20., True, 30.,
                _cache_frame_state=cache_enabled)
        finally:
            monkeypatch.setattr(initialization, "_frame_state", original_frame_state)
        counts[cache_enabled] = count
        return result

    uncached_offsets, uncached_report = run(False)
    cached_offsets, cached_report = run(True)

    assert uncached_offsets is not None and cached_offsets is not None
    np.testing.assert_allclose(cached_offsets, uncached_offsets, rtol=0., atol=1e-12)
    assert cached_report["feasible"] == uncached_report["feasible"] is True
    for key in ("maxMagnitudeMeters", "maxStepMeters", "maxSecondDifferenceMeters"):
        assert np.isclose(cached_report[key], uncached_report[key], rtol=0., atol=1e-12)
    assert counts[True] < counts[False]


def test_joint_plant_mirrors_only_inferred_opposite_toe_target():
    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case()
    tracks = copy.deepcopy(tracks)
    right_foot = names.index("right_foot")
    right_ankle = names.index("right_ankle")
    right_direction = source_points[:, right_foot] - source_points[:, right_ankle]
    right_direction /= np.linalg.norm(right_direction, axis=1, keepdims=True)
    # The inactive opposite track supplies its physical frame for the
    # validator, but does not claim native contact ownership.
    tracks["right"] = {
        "active": [False] * len(source_points),
        "directions": right_direction.tolist(),
        "sideAxes": side_axis_by_side[:, 1, :].tolist(),
        "anchorIds": [None] * len(source_points),
        "episodes": [],
    }
    tracks_before = copy.deepcopy(tracks)
    pins_before = pinned.copy()
    coordinates_before = coordinates.copy()
    from exercise_motion_pkg.support_geometry import TOLERANCE_METERS
    baseline_residuals, baseline_errors = _native_foot_material_contact_residuals(
        source_points, names, {
            "_nativeFootMaterialTracks": tracks,
            "_nativeFootMirrorRequired": True,
            "nativeFootGeometry": native,
            "_nativeFootScale": scale,
        }, side_axes_override={
            "left": side_axis_by_side[:, 0, :],
            "right": side_axis_by_side[:, 1, :],
        })
    assert baseline_errors == []
    assert np.max(np.abs(baseline_residuals[:, 10:])) > TOLERANCE_METERS

    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
        native_foot_mirror_required=True,
    )

    assert initialized is not None, report
    result = rig.decode(initialized)
    assert report["feasible"] is True
    np.testing.assert_allclose(result[:, right_foot], targets[:, right_foot], atol=1e-5)
    np.testing.assert_allclose(
        np.linalg.norm(result[:, right_foot] - result[:, right_ankle], axis=1),
        np.linalg.norm(source_points[:, right_foot] - source_points[:, right_ankle], axis=1),
        atol=1e-8)
    assert not np.any(pinned[:, right_ankle])
    np.testing.assert_array_equal(pinned, pins_before)
    np.testing.assert_array_equal(coordinates, coordinates_before)
    assert tracks == tracks_before

    reference_world = rig.global_rotations(rig.material_reference_coordinates)
    side_axes = {}
    for side in ("left", "right"):
        foot = names.index(f"{side}_foot")
        reference_axis = reference_world[foot] @ np.asarray([1., 0., 0.])
        side_axes[side] = rig.material_side_axes(
            initialized, reference_axis, side)
    residuals, errors = _native_foot_material_contact_residuals(
        result, names, {
            "_nativeFootMaterialTracks": tracks,
            "_nativeFootMirrorRequired": True,
            "nativeFootGeometry": native,
            "_nativeFootScale": scale,
        }, side_axes_override=side_axes)
    assert errors == []
    # Ten rows are the anchored full-sole point/penetration/samples; the final
    # six are physical bilateral forward/lateral displacement residuals.
    assert residuals.shape == (len(result), 16)
    assert np.max(np.abs(residuals[:, :10])) <= 1e-5
    mirror_rows = residuals[:, 10:]
    worst_frame, worst_component = np.unravel_index(
        int(np.argmax(np.abs(mirror_rows))), mirror_rows.shape)
    assert np.max(np.abs(mirror_rows)) <= TOLERANCE_METERS, (
        f"mirror residual={np.max(np.abs(mirror_rows)):.9g}m at frame {worst_frame}; "
        f"forward={mirror_rows[worst_frame, :3].tolist()}, "
        f"lateral={mirror_rows[worst_frame, 3:].tolist()}, "
        f"dominantComponent={worst_component}, "
        f"leftForward={(result[worst_frame, names.index('left_foot')] - result[worst_frame, names.index('left_ankle')]).tolist()}, "
        f"rightForward={(result[worst_frame, right_foot] - result[worst_frame, right_ankle]).tolist()}")


def test_joint_plant_couples_overlapping_observed_mirrored_fullsole_episodes():
    from exercise_motion_pkg.support_geometry import (
        TOLERANCE_METERS, _native_foot_material_contact_residuals,
    )
    from exercise_motion_pkg.rig_playback import PLAYBACK_CONTACT_LIMIT_METERS

    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, _) = _case(frame_count=4)
    tracks = copy.deepcopy(tracks)
    # Production stores the v2 schema version on the track bundle, not on
    # each side record. Exercise that exact normalizer/initializer handoff.
    tracks['version'] = 2
    triangle_index = 10
    barycentric = np.asarray([.2, .4, .4])
    triangle = shoe_triangles()[triangle_index]
    episodes = {}
    for side_index, side in enumerate(('left', 'right')):
        ankle_i, toe_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axis = side_axis_by_side[:, side_index, :]
        shoes = shoe_vertices(
            source_points[:, ankle_i], source_points[:, toe_i], axis, None, scale,
            native_geometry=native['sides'][side])
        anchor = barycentric @ shoes[0, triangle]
        episodes[side] = {
            'startFrame': 0, 'endFrame': len(source_points) - 1,
            'anchorId': f'{side}-fullsole', 'mode': 'stationary',
            'regionRole': 'full_sole',
            'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
            'triangleIndex': triangle_index,
            'barycentric': barycentric.tolist(),
            'targetWorld': anchor.tolist(),
            'surfaceNormal': [0., 1., 0.],
            'planeOffsetMeters': float(anchor[1]),
        }
        tracks[side] = {
            'active': [True] * len(source_points),
            'directions': (
                (source_points[:, toe_i] - source_points[:, ankle_i]) /
                np.linalg.norm(source_points[:, toe_i] - source_points[:, ankle_i],
                               axis=1, keepdims=True)).tolist(),
            'sideAxes': axis.tolist(),
            'anchorIds': [f'{side}-fullsole'] * len(source_points),
            'episodes': [episodes[side]],
        }
    # This fixture has a single common horizontal support plane, matching the
    # explicit mirrored full-sole contract.
    right_anchor = np.asarray(episodes['right']['targetWorld'], dtype=float)
    right_anchor[1] = float(episodes['left']['planeOffsetMeters'])
    episodes['right']['targetWorld'] = right_anchor.tolist()
    episodes['right']['planeOffsetMeters'] = float(right_anchor[1])
    tracks['right']['episodes'] = [episodes['right']]

    pinned[:] = False
    targets = source_points.copy()
    projection = np.asarray([[1., 0., 0.], [0., 0., 1.]])
    ray_rows = []
    for side in ('left', 'right'):
        ankle_i, toe_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        for frame in range(len(source_points)):
            ray = projection @ (source_points[frame, toe_i] - source_points[frame, ankle_i])
            ray_rows.append({
                'sourceSide': side, 'motionSide': side,
                'leftFrame': frame, 'rightFrame': frame, 'alpha': 0.,
                'ankleJointIndex': ankle_i, 'footJointIndex': toe_i,
                'targetRay': ray.tolist(), 'headingOffsetRadians': 0.,
            })
    projection_constraint = {
        'available': True, 'projection': projection.tolist(),
        'sourceFootRaySideMapping': {'left': 'left', 'right': 'right'},
        'sourceFootRayObservations': ray_rows,
    }
    canonical_execution = {
        'stance': 'stationary_bilateral', 'legs': 'mirrored', 'torso': 'sagittal',
    }

    captured = {}
    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 20., floor_y=float(episodes['left']['planeOffsetMeters']),
        rest_pitch_radians={}, foot_scale=scale,
        side_axis_by_side=side_axis_by_side, native_foot_geometry=native,
        native_foot_tracks=tracks, native_foot_mirror_required=True,
        source_projection_constraint=projection_constraint,
        canonical_execution=canonical_execution,
        native_fullsole_constraint_capture=captured.update,
    )

    assert initialized is not None, json.dumps({
        'reason': report.get('reason'),
        'postcheck': (report.get('nativeFullsole') or {}).get('postcheck'),
        'coupling': (report.get('nativeFullsole') or {}).get('mirroredPairCoupling'),
    }, sort_keys=True)
    assert report['feasible'] is True
    assert report['nativeFullsole']['postcheck']['passed'] is True
    assert report['nativeFullsole']['mirroredPairCoupling']['frameCount'] == len(source_points)
    assert report['nativeFullsole']['mirroredPairCoupling']['targetAnchorsPreserved'] is True
    assert (report['nativeFullsole']['canonicalStanceHeadingSeed']['headingReference']
            == 'qualified_native_bilateral_fullsole_anchor_pair')
    left_anchor = np.asarray(episodes['left']['targetWorld'], dtype=float)
    right_anchor = np.asarray(episodes['right']['targetWorld'], dtype=float)
    np.testing.assert_allclose(left_anchor[1], right_anchor[1], atol=1e-12)
    mirror_normal = right_anchor - left_anchor
    mirror_normal[1] = 0.
    mirror_normal /= np.linalg.norm(mirror_normal)
    mirror_offset = float(np.dot(mirror_normal, .5 * (left_anchor + right_anchor)))
    derived_targets = np.asarray(captured['targets'], dtype=float)
    for left_name, right_name in (('left_ankle', 'right_ankle'),
                                  ('left_foot', 'right_foot')):
        left_target = derived_targets[:, names.index(left_name)]
        right_target = derived_targets[:, names.index(right_name)]
        pair_delta = left_target - right_target
        pair_midpoint = .5 * (left_target + right_target)
        direction_error = np.linalg.norm(
            pair_delta - np.outer(pair_delta @ mirror_normal, mirror_normal), axis=1)
        midpoint_error = np.abs(pair_midpoint @ mirror_normal - mirror_offset)
        assert np.max(direction_error) <= PLAYBACK_CONTACT_LIMIT_METERS
        assert np.max(midpoint_error) <= PLAYBACK_CONTACT_LIMIT_METERS
    for side in ('left', 'right'):
        np.testing.assert_allclose(
            np.asarray(tracks[side]['episodes'][0]['targetWorld'], dtype=float),
            np.asarray(episodes[side]['targetWorld'], dtype=float), atol=1e-12,
        )
    ray_fit = report['nativeFullsole']['sourceCameraYaw']['sourceRayFitAfterMirroredPair']
    assert ray_fit['passed'] is True, ray_fit
    assert all(
        side['absoluteAngularResidualP95Degrees'] <= side['headingToleranceDegrees']
        for side in ray_fit['bySide'].values() if side['available'])

    initialized_points = rig.decode(initialized)
    axes = {}
    reference_world = rig.global_rotations(rig.material_reference_coordinates)
    for side in ('left', 'right'):
        foot = names.index(f'{side}_foot')
        reference_axis = reference_world[foot] @ np.asarray([1., 0., 0.])
        axes[side] = rig.material_side_axes(initialized, reference_axis, side)
    residuals, errors = _native_foot_material_contact_residuals(
        initialized_points, names, {
            '_nativeFootMaterialTracks': tracks,
            '_nativeFootMirrorRequired': True,
            'nativeFootGeometry': native,
            '_nativeFootScale': scale,
        }, side_axes_override=axes)
    assert errors == []
    assert residuals.shape == (len(source_points), 26)
    assert np.max(np.abs(residuals[:, :20])) <= 1e-5
    assert np.max(np.abs(residuals[:, 20:])) <= TOLERANCE_METERS

    right_hip = names.index('right_hip')
    tilted_hips = initialized_points.copy()
    tilted_hips[:, right_hip, 1] += .00687227
    tilted_residuals, tilted_errors = _native_foot_material_contact_residuals(
        tilted_hips, names, {
            '_nativeFootMaterialTracks': tracks,
            '_nativeFootMirrorRequired': True,
            'nativeFootGeometry': native,
            '_nativeFootScale': scale,
        }, side_axes_override=axes)
    assert tilted_errors == []
    np.testing.assert_allclose(tilted_residuals, residuals, atol=1e-12)

    skewed_hips = initialized_points.copy()
    skewed_hips[:, right_hip, 0] += .01
    skewed_residuals, skewed_errors = _native_foot_material_contact_residuals(
        skewed_hips, names, {
            '_nativeFootMaterialTracks': tracks,
            '_nativeFootMirrorRequired': True,
            'nativeFootGeometry': native,
            '_nativeFootScale': scale,
        }, side_axes_override=axes)
    assert skewed_errors == []
    assert np.max(np.abs(skewed_residuals[:, 20:])) > TOLERANCE_METERS


def test_joint_plant_canonical_stance_seed_encodes_rigid_heading_only():
    from exercise_motion_pkg.joint_plant_initialization import (
        _canonical_stance_heading_seed,
    )
    from exercise_motion_pkg.controlled_motion import canonical_stance_heading_target

    names, rig, coordinates, points, _, _, _, _, _, _, _ = _case(frame_count=5)
    coordinates = coordinates.copy()
    root_world = rig.global_rotations(coordinates)[rig.root]
    root_slot = rig.slots[rig.root]
    for frame, yaw in enumerate(np.linspace(-.05, .05, len(coordinates))):
        turn = Rotation.from_euler('y', yaw).as_matrix()
        coordinates[frame, root_slot:root_slot + 3] = Rotation.from_matrix(
            turn @ root_world[frame]).as_rotvec()
    points = rig.decode(coordinates)

    contact_targets = points.copy()
    for side in ('left', 'right'):
        toe = names.index(f'{side}_foot')
        contact_targets[:, toe] = contact_targets[0, toe]
    execution = {
        'stance': 'stationary_bilateral', 'legs': 'mirrored', 'torso': 'sagittal',
    }
    expected, expected_report = canonical_stance_heading_target(
        points, names, execution, contact_targets)
    seeded, report = _canonical_stance_heading_seed(
        rig, coordinates, contact_targets, execution)

    assert expected_report['applied'] is True
    assert seeded is not None, report
    assert report['seedEncodingApplied'] is True
    actual = rig.decode(seeded)
    np.testing.assert_allclose(actual, expected, atol=1e-10)
    pelvis = names.index('pelvis')
    np.testing.assert_allclose(actual[:, pelvis, 1], points[:, pelvis, 1], atol=1e-12)
    np.testing.assert_allclose(
        np.linalg.norm(actual[:, :, None] - actual[:, None, :], axis=-1),
        np.linalg.norm(points[:, :, None] - points[:, None, :], axis=-1), atol=1e-10)
    left_hip, right_hip = names.index('left_hip'), names.index('right_hip')
    hip_axis = actual[:, right_hip] - actual[:, left_hip]
    hip_axis[:, 1] = 0.
    hip_axis /= np.linalg.norm(hip_axis, axis=1, keepdims=True)
    stance_axis = contact_targets[0, names.index('right_foot')] - contact_targets[0, names.index('left_foot')]
    stance_axis[1] = 0.
    stance_axis /= np.linalg.norm(stance_axis)
    np.testing.assert_allclose(hip_axis, np.broadcast_to(stance_axis, hip_axis.shape), atol=1e-10)


def test_joint_plant_returns_separate_fullsole_fit_constraints_and_axis_rows():
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates

    (names, rig, coordinates, source_points, targets, pinned, tracks,
     native, scale, side_axis_by_side, target) = _case(frame_count=4)
    observed_pins = pinned.copy()
    captured = {}
    initialized, report = initialize_joint_plant_coordinates(
        rig, coordinates, pinned, targets,
        articulation_reference=source_points, fps=30., cyclic=False,
        deadline=monotonic() + 10., floor_y=float(target[1]),
        rest_pitch_radians={}, foot_scale=scale, side_axis_by_side=side_axis_by_side,
        native_foot_geometry=native, native_foot_tracks=tracks,
        native_fullsole_constraint_capture=captured.update,
    )

    assert initialized is not None, report
    np.testing.assert_array_equal(pinned, observed_pins)
    derived = captured["pinned"]
    assert np.all(derived[:, names.index("left_ankle")])
    assert np.all(derived[:, names.index("left_foot")])
    assert not np.any(derived & observed_pins)
    np.testing.assert_allclose(
        rig.decode(initialized)[derived], captured["targets"][derived], atol=1e-5)
    from exercise_motion_pkg.controlled_motion import project_contact_plant_coordinates
    from exercise_motion_pkg.rig_playback import PLAYBACK_CONTACT_LIMIT_METERS

    fit_pins = observed_pins | derived
    fit_targets = targets.copy()
    fit_targets[derived] = captured["targets"][derived]
    perturbed = initialized.copy()
    perturbed[:, :3] += np.asarray([.002, 0., 0.])
    projected = project_contact_plant_coordinates(
        perturbed, rig, fit_pins, fit_targets, max_nfev=20,
    )
    projected_error = np.max(np.linalg.norm(
        (rig.decode(projected) - fit_targets)[fit_pins], axis=-1), initial=0.)
    assert projected_error <= PLAYBACK_CONTACT_LIMIT_METERS

    orientation = captured["orientationTargets"]["left"]
    active = np.zeros(len(source_points), dtype=bool)
    active[orientation["frames"]] = True
    evidence = {
        "_nativeFootMaterialTracks": tracks,
        "_nativeFootScale": scale,
        "nativeFootGeometry": native,
        "_nativeFullsoleFitConstraints": {
            "orientationTargets": {
                "left": {"active": active,
                         "sideAxes": np.zeros((len(active), 3), dtype=float)},
            },
        },
    }
    evidence["_nativeFullsoleFitConstraints"]["orientationTargets"]["left"][
        "sideAxes"][orientation["frames"]] = orientation["sideAxes"]
    current_axes = _native_side_axes_for_coordinates(
        rig, initialized, {"_nativeFootMaterialTracks": tracks})["left"]
    baseline_rows, _ = _native_foot_material_contact_residuals(
        rig.decode(initialized), names, evidence,
        side_axes_override={"left": current_axes},
    )
    np.testing.assert_allclose(baseline_rows[:, -3:], 0., atol=1e-8)

    points = rig.decode(initialized)
    ankle, toe = names.index("left_ankle"), names.index("left_foot")
    forward = points[:, toe] - points[:, ankle]
    forward /= np.linalg.norm(forward, axis=1, keepdims=True)
    drifted_axes = Rotation.from_rotvec(forward * np.deg2rad(3.)).apply(current_axes)
    drift_rows, _ = _native_foot_material_contact_residuals(
        points, names, evidence, side_axes_override={"left": drifted_axes},
    )
    assert np.max(np.abs(drift_rows[:, -3:])) > .001

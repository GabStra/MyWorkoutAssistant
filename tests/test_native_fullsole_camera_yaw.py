import copy

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import controlled_motion as motion


def _case():
    names = ["right_knee", "right_ankle", "right_foot"]
    points = np.asarray([[
        [0., 0., 0.],
        [0., 1., 0.],
        [0., 1., .12],
    ]])
    ankle = names.index("right_ankle")
    foot = names.index("right_foot")
    anchor = np.asarray([0., 1., .06])
    normal = np.asarray([0., 1., 0.])
    tracks = {"version": 2, "right": {
        "active": [True],
        "directions": [[0., 0., 1.]],
        "sideAxes": [[1., 0., 0.]],
        "anchorIds": ["right-fullsole"],
        "episodes": [{
            "startFrame": 0, "endFrame": 0,
            "anchorId": "right-fullsole", "mode": "stationary",
            "regionRole": "full_sole", "primitiveId": "wearShoe:right_ankle->right_foot",
            "triangleIndex": 10, "barycentric": [.2, .4, .4],
            "materialOffsetLocalMeters": [.06, 0., 0.],
            "referenceLengthMeters": .12,
            "targetWorld": anchor.tolist(),
            "surfaceNormal": normal.tolist(), "planeOffsetMeters": 1.,
        }],
    }}
    projection = np.asarray([[1., 0., 0.], [0., 0., 1.]])
    # This is the retained 2D camera observation; it is not manufactured by
    # rotating the 3D foot pose by a preferred angle.
    target_ray = np.asarray([1., 0.])
    constraint = {
        "available": True,
        "projection": projection,
        "sourceFootRaySideMapping": {"right": "right"},
        "sourceFootRayObservations": [{
            "sourceSide": "right", "leftFrame": 0, "rightFrame": 0,
            "alpha": 0., "ankleJointIndex": ankle, "footJointIndex": foot,
            "targetRay": target_ray, "headingOffsetRadians": 0.,
        }],
    }
    return names, points, tracks, constraint, anchor, normal


def test_fullsole_camera_yaw_improves_qualified_ray_without_moving_anchor_or_plane():
    (names, points, tracks, constraint, anchor, normal) = _case()
    points_before = points.copy()
    tracks_before = copy.deepcopy(tracks)
    constraint_before = copy.deepcopy(constraint)

    yaw_by_side, report = motion._native_fullsole_camera_yaw_by_side(
        points, names, tracks, constraint)

    assert "right" in yaw_by_side, report
    yaw = float(yaw_by_side["right"])
    assert np.isfinite(yaw) and abs(yaw) > 1e-4
    ankle, foot = names.index("right_ankle"), names.index("right_foot")
    before_fit = motion._source_foot_ray_fit_evidence(points, constraint)

    # Apply the proposed common yaw about the episode's support-plane normal,
    # rotating the anchor-to-ankle and ankle-to-toe vectors together.
    rotation = Rotation.from_rotvec(normal * yaw)
    candidate = points.copy()
    anchor_to_ankle = anchor - points[0, ankle]
    candidate[0, ankle] = anchor - rotation.apply(anchor_to_ankle)
    candidate[0, foot] = candidate[0, ankle] + rotation.apply(
        points[0, foot] - points[0, ankle])

    after_fit = motion._source_foot_ray_fit_evidence(candidate, constraint)
    after_anchor = candidate[0, ankle] + rotation.apply(anchor_to_ankle)
    assert after_fit["available"] is True
    assert after_fit["absoluteAngularResidualP95Degrees"] < before_fit[
        "absoluteAngularResidualP95Degrees"]
    np.testing.assert_allclose(after_anchor, anchor, atol=1e-12)
    np.testing.assert_allclose(after_anchor @ normal, anchor @ normal, atol=1e-12)
    np.testing.assert_array_equal(points, points_before)
    assert tracks == tracks_before
    for key in ("available", "sourceFootRaySideMapping"):
        assert constraint[key] == constraint_before[key]
    assert report


def test_fullsole_camera_yaw_does_not_infer_when_rays_are_missing_or_unmapped():
    names, points, tracks, constraint, _, _ = _case()
    points_before = points.copy()
    tracks_before = copy.deepcopy(tracks)
    missing = {"available": True, "sourceFootRayObservations": []}
    unqualified = copy.deepcopy(constraint)
    unqualified["sourceFootRaySideMapping"] = {"left": "left"}
    unqualified["sourceFootRayObservations"][0]["sourceSide"] = "left"
    inactive_tracks = copy.deepcopy(tracks)
    inactive_tracks["right"]["active"][0] = False
    wrong_anchor_tracks = copy.deepcopy(tracks)
    wrong_anchor_tracks["right"]["anchorIds"][0] = "different-anchor"

    missing_yaw, missing_report = motion._native_fullsole_camera_yaw_by_side(
        points, names, tracks, missing)
    unqualified_yaw, unqualified_report = motion._native_fullsole_camera_yaw_by_side(
        points, names, tracks, unqualified)
    inactive_yaw, inactive_report = motion._native_fullsole_camera_yaw_by_side(
        points, names, inactive_tracks, constraint)
    wrong_anchor_yaw, wrong_anchor_report = motion._native_fullsole_camera_yaw_by_side(
        points, names, wrong_anchor_tracks, constraint)

    assert missing_yaw == {}
    assert unqualified_yaw == {}
    assert inactive_yaw == {}
    assert wrong_anchor_yaw == {}
    assert missing_report and unqualified_report and inactive_report and wrong_anchor_report
    np.testing.assert_array_equal(points, points_before)
    assert tracks == tracks_before

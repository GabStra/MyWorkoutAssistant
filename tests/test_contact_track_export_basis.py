import copy

import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import refresh_contact_foot_tracks


def _native_track(count=2):
    return {
        "version": 2,
        "left": {
            "active": [True] * count,
            "directions": [[0.0, 0.0, 1.0]] * count,
            "sideAxes": [[1.0, 0.0, 0.0]] * count,
            "anchorIds": ["source-forefoot"] * count,
            "episodes": [{
                "startFrame": 0,
                "endFrame": count - 1,
                "anchorId": "source-forefoot",
                "regionRole": "forefoot",
                "mode": "stationary",
                "primitiveId": "wearShoe:left_ankle->left_foot",
                "triangleIndex": 11,
                "barycentric": [0.2, 0.3, 0.5],
                "materialOffsetLocalMeters": [0.04, -0.01, 0.02],
                "referenceLengthMeters": 0.2,
                "targetWorld": [0.0, 0.0, 0.0],
                "surfaceNormal": [0.0, 1.0, 0.0],
                "planeOffsetMeters": 0.0,
            }],
        },
    }


def test_native_track_refresh_exports_same_frame_orthonormal_basis_and_preserves_binding():
    names = ["left_ankle", "left_foot"]
    points = np.asarray([
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.2]],
        [[0.0, 0.0, 0.0], [0.04, 0.0, np.sqrt(0.2**2 - 0.04**2)]],
    ])
    rig = {"jointNames": names}
    tracks = _native_track()
    original = copy.deepcopy(tracks)
    axes_from_current_fk = np.tile([1.0, 0.0, 0.0], (len(points), 1))

    refreshed = refresh_contact_foot_tracks(
        rig, points, tracks, side_axes={"left": axes_from_current_fk})

    directions = points[:, 1] - points[:, 0]
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    axes = np.asarray(refreshed["left"]["sideAxes"])
    np.testing.assert_allclose(refreshed["left"]["directions"], directions)
    np.testing.assert_allclose(np.linalg.norm(axes, axis=1), 1.0, atol=1e-12)
    np.testing.assert_allclose(np.sum(axes * directions, axis=1), 0.0, atol=1e-12)
    assert refreshed["left"]["active"] == original["left"]["active"]
    assert refreshed["left"]["anchorIds"] == original["left"]["anchorIds"]
    assert refreshed["left"]["episodes"] == original["left"]["episodes"]
    assert tracks == original


def test_native_track_refresh_fails_closed_for_collinear_current_side_axis():
    points = np.asarray([[[0.0, 0.0, 0.0], [0.0, 0.0, 0.2]]] * 2)
    with pytest.raises(ValueError, match="collinear with foot direction"):
        refresh_contact_foot_tracks(
            {"jointNames": ["left_ankle", "left_foot"]},
            points,
            _native_track(),
            side_axes={"left": np.tile([0.0, 0.0, 1.0], (2, 1))},
        )

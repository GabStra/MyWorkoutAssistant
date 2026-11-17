import copy
import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import apply_canonical_stance_targets
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices


def _case():
    names = [
        "left_hip", "left_knee", "left_ankle", "left_foot",
        "right_hip", "right_knee", "right_ankle", "right_foot",
        "left_shoulder", "right_shoulder",
    ]
    row = np.asarray([
        [-0.2, 1.0, 0.0], [-0.2, 0.55, 0.0], [-0.2, 0.12, 0.0],
        [-0.02, 0.08, 0.0], [0.2, 1.0, 0.0], [0.2, 0.55, 0.0],
        [0.2, 0.12, 0.0], [0.38, 0.08, 0.0], [-0.25, 1.4, 0.0],
        [0.25, 1.4, 0.0],
    ])
    targets = np.repeat(row[None, :, :], 3, axis=0)
    frames = [{
        "sourceTimeSec": float(index) / 30.,
        "joints": dict(zip(names, targets[index].tolist())),
        "boneSides": {
            "left_ankle->left_foot": [0., 0., 1.],
            "right_ankle->right_foot": [0., 0., -1.],
        },
    } for index in range(len(targets))]
    geometry_fixture = json.loads((
        Path(__file__).parent / "fixtures/native_foot_geometry_v1.json"
    ).read_text(encoding="utf-8"))
    payload = {
        "jointNames": names,
        "frames": frames,
        "canonicalExecution": {"stance": "stationary_bilateral"},
        "renderFloorY": 0.0,
        "nativeFootGeometry": geometry_fixture["reference"],
        "sourceFootSupportEvidence": {
            "contacts": [{"jointName": "left_foot", "contactState": "toe_only"}],
            "supportContacts": [],
        },
    }
    return names, targets, payload


def test_inferred_toe_anchor_places_native_shoe_on_floor_and_respects_owned_targets():
    names, targets, payload = _case()
    original_targets = targets.copy()
    original_contacts = copy.deepcopy(payload["sourceFootSupportEvidence"])
    active_right_track = {"episodes": [{"kind": "native_material"}],
                          "active": np.ones(len(targets), dtype=bool)}
    original_track = copy.deepcopy(active_right_track)
    pinned = np.zeros(targets.shape[:2], dtype=bool)
    left_toe = names.index("left_foot")
    pinned[:, left_toe] = True  # Canonical toe-only target; ankle remains free.

    result = apply_canonical_stance_targets(
        payload, targets, names, pinned,
        native_foot_tracks={"right": active_right_track},
    )

    right_toe = names.index("right_foot")
    left_ankle = names.index("left_ankle")
    np.testing.assert_array_equal(targets, original_targets)
    np.testing.assert_allclose(result[:, left_toe, (0, 2)],
                               original_targets[:, left_toe, (0, 2)])
    assert np.all(result[:, left_toe, 1] > 0.)  # Toe joint is above the floor.
    np.testing.assert_allclose(
        result[:, left_toe] - result[:, left_ankle],
        original_targets[:, left_toe] - original_targets[:, left_ankle],
        atol=1e-12,
    )
    np.testing.assert_array_equal(result[:, right_toe], original_targets[:, right_toe])

    from exercise_motion_pkg.heel_contacts import resolved_foot_side_axes

    axes = resolved_foot_side_axes(result, names, payload["frames"])
    scale = foot_scale_from_pose(result[0], names)
    native = payload["nativeFootGeometry"]["sides"]["left"]
    for frame in range(len(result)):
        vertices = shoe_vertices(
            result[frame, left_ankle], result[frame, left_toe],
            axes["left"][frame], None, scale, native_geometry=native)
        assert float(vertices[:, 1].min()) == pytest.approx(0., abs=1e-9)

    # A full-sole evidence state also owns the target pair, even without a
    # native material track.
    payload["sourceFootSupportEvidence"]["_fitFrameFootPatchStatesBySide"] = {
        "left": ["full_sole"] * len(targets),
        "right": ["unknown"] * len(targets),
    }
    full_sole_contacts = copy.deepcopy(payload["sourceFootSupportEvidence"])
    full_sole_result = apply_canonical_stance_targets(
        payload, targets, names, pinned,
        native_foot_tracks={"right": active_right_track},
    )
    np.testing.assert_array_equal(full_sole_result, original_targets)

    # An explicit ankle+toe pair owns its original non-floor target in full.
    explicit_pair = np.zeros_like(pinned)
    explicit_pair[:, names.index("left_ankle")] = True
    explicit_pair[:, left_toe] = True
    explicit_result = apply_canonical_stance_targets(
        payload, targets, names, explicit_pair,
        native_foot_tracks={"right": active_right_track},
    )
    np.testing.assert_array_equal(explicit_result, original_targets)
    assert payload["sourceFootSupportEvidence"] == full_sole_contacts
    assert original_contacts["contacts"] == payload["sourceFootSupportEvidence"]["contacts"]
    assert np.array_equal(active_right_track["active"], original_track["active"])
    assert active_right_track["episodes"] == original_track["episodes"]

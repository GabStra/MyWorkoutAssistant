import numpy as np


def test_canonical_mirrored_targets_follow_source_authority_per_frame():
    from exercise_motion_pkg.controlled_motion import (
        _propagate_inferred_mirrored_contact_targets,
        canonical_bilateral_reference,
    )

    names = [
        "left_hip", "right_hip",
        "left_knee", "right_knee",
        "left_ankle", "right_ankle",
        "left_foot", "right_foot",
    ]
    source_points = np.array([
        [[-.10, .50, .00], [.10, .50, .00],
         [-.16, .28, .04], [.29, .31, -.11],
         [-.19, .07, .09], [.31, .10, -.16],
         [-.22, .01, .12], [.34, .02, -.21]],
        [[-.10, .50, .00], [.10, .50, .00],
         [-.17, .27, .06], [.28, .29, -.08],
         [-.21, .06, .12], [.33, .09, -.12],
         [-.24, .01, .14], [.36, .02, -.18]],
        [[-.10, .50, .00], [.10, .50, .00],
         [-.15, .29, .03], [.30, .32, -.13],
         [-.18, .08, .08], [.30, .11, -.18],
         [-.21, .01, .11], [.33, .02, -.23]],
    ], dtype=float)
    source_points_before = source_points.copy()
    projected_points = canonical_bilateral_reference(
        source_points,
        names,
        {"legs": "mirrored"},
        {"legs": "left"},
    )

    # The projection is independently derived from the left-owned source pose;
    # it preserves that pose and changes the modeled right leg.
    left_indexes = [names.index(f"left_{part}") for part in ("hip", "knee", "ankle", "foot")]
    right_ankle, right_foot = names.index("right_ankle"), names.index("right_foot")
    assert np.allclose(projected_points[:, left_indexes], source_points[:, left_indexes],
                       rtol=0., atol=1e-14)
    assert not np.allclose(projected_points[:, [right_ankle, right_foot]],
                           source_points[:, [right_ankle, right_foot]])

    targets = source_points + np.array([.013, -.007, .021])
    targets_before = targets.copy()
    pinned = np.ones(targets.shape[:2], dtype=bool)
    source_contact_pinned = np.zeros_like(pinned)
    left_ankle, left_foot = names.index("left_ankle"), names.index("left_foot")
    source_contact_pinned[:, [left_ankle, left_foot]] = True
    # This frame has an independently observed right-foot pin; preserve the
    # literal right target there, even though the canonical projection differs.
    source_contact_pinned[1, [right_ankle, right_foot]] = True
    pinned_before = pinned.copy()
    source_contact_pinned_before = source_contact_pinned.copy()

    result, updated, report = _propagate_inferred_mirrored_contact_targets(
        targets,
        projected_points,
        names,
        pinned,
        source_contact_pinned,
        mirrored=True,
        native_foot_mirror_required=True,
    )

    expected = targets_before.copy()
    expected[[0, 2], right_ankle] = projected_points[[0, 2], right_ankle]
    expected[[0, 2], right_foot] = projected_points[[0, 2], right_foot]
    expected_mask = np.zeros_like(pinned)
    expected_mask[[0, 2], [right_ankle, right_ankle]] = True
    expected_mask[[0, 2], [right_foot, right_foot]] = True
    assert np.array_equal(result, expected)
    assert np.array_equal(updated, expected_mask)
    assert np.array_equal(result[1, [right_ankle, right_foot]],
                          targets_before[1, [right_ankle, right_foot]])
    assert np.array_equal(result[:, [left_ankle, left_foot]],
                          targets_before[:, [left_ankle, left_foot]])
    assert np.array_equal(result[:, [names.index("left_knee"), names.index("right_knee")]],
                          targets_before[:, [names.index("left_knee"), names.index("right_knee")]])
    assert report["applied"] is True
    assert report["provenance"] == "canonical_mirror_projection"
    assert report["sourceAuthoritySide"] == "per_frame"
    assert report["inferredSide"] == "opposite_per_frame"
    assert report["updatedJointFrames"] == 4

    # Only the approved canonical mirrored-stationary mode enables propagation.
    for mirrored, native_foot_mirror_required in ((False, True), (True, False)):
        disabled, disabled_mask, _ = _propagate_inferred_mirrored_contact_targets(
            targets,
            projected_points,
            names,
            pinned,
            source_contact_pinned,
            mirrored=mirrored,
            native_foot_mirror_required=native_foot_mirror_required,
        )
        assert np.array_equal(disabled, targets_before)
        assert not np.any(disabled_mask)

    # All caller-owned evidence and inputs remain immutable.
    assert np.array_equal(source_points, source_points_before)
    assert np.array_equal(targets, targets_before)
    assert np.array_equal(projected_points, canonical_bilateral_reference(
        source_points_before, names, {"legs": "mirrored"}, {"legs": "left"}))
    assert np.array_equal(pinned, pinned_before)
    assert np.array_equal(source_contact_pinned, source_contact_pinned_before)

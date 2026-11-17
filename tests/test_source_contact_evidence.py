"""Focused coverage for source contact evidence after physical pin suppression."""

import numpy as np

from exercise_motion_pkg.controlled_motion import trajectory_fit_evidence


def _trajectory_inputs(*, review_only=False):
    names = ["pelvis", "left_foot", "right_foot", "right_hand", "left_hand"]
    frames = 8
    target = np.zeros((frames, len(names), 3), dtype=float)
    target[:, names.index("pelvis"), 1] = 1.0
    target[:, names.index("left_foot"), 0] = -0.1
    target[:, names.index("right_foot"), 0] = 0.1
    candidate = target.copy()
    candidate += np.array([0.04, 0.0, 0.0])
    candidate[:, names.index("right_hand"), 1] += 0.15
    physical_pinned = np.zeros(target.shape[:2], dtype=bool)
    source_contact_mask = np.zeros_like(physical_pinned)
    source_contact_mask[:, names.index("left_foot")] = True
    contact = {
        "jointName": "left_foot",
        "supportKind": "observed_foot_patch",
        "contactState": "full_sole",
        "contactMotion": "stationary",
        "surfaceKind": "ground",
        "startFrame": 0,
        "endFrame": frames - 1,
    }
    if review_only:
        contact["reviewOnly"] = True
    support = {"contacts": [contact]}
    constraint = {
        "available": True,
        "cameraAuthority": "retained_source_correction_camera",
        "sourceFootRaySideMapping": {"left": "left", "right": "right"},
    }
    camera = {"bilateralAssignment": "identity"}
    return names, target, candidate, physical_pinned, source_contact_mask, support, constraint, camera


def _evidence(values, *, source_mask=None):
    names, target, candidate, physical_pinned, source_mask_default, support, constraint, camera = values
    return trajectory_fit_evidence(
        candidate,
        target,
        names,
        1.0,
        root_index=names.index("pelvis"),
        pinned=physical_pinned,
        support_evidence=support,
        source_projection_constraint=constraint,
        source_camera=camera,
        source_contact_mask=source_mask,
    )


def test_source_contact_evidence_survives_pin_suppression_without_changing_free_coverage():
    inputs = _trajectory_inputs()
    *_, source_mask, support, constraint, camera = inputs
    legacy = _evidence(inputs)
    source_owned = trajectory_fit_evidence(
        inputs[2], inputs[1], inputs[0], 1.0,
        root_index=inputs[0].index("pelvis"),
        pinned=inputs[3], support_evidence=support,
        source_projection_constraint=constraint, source_camera=camera,
        source_contact_mask=source_mask,
    )

    assert not legacy["eligible"]
    assert legacy["observedSupportAnchorSampleCount"] == 0
    assert source_owned["eligible"]
    assert source_owned["observedSupportAnchorSampleCount"] == 8
    assert source_owned["finalSourceCameraPoseFidelityRequired"] is True
    assert source_owned["passed"] is False
    assert source_owned["freeJointCoverage"] == legacy["freeJointCoverage"]
    assert source_owned["freeJointCoverage"]["freeSampleCount"] == 8 * (len(inputs[0]) - 1)


def test_review_only_or_unobserved_source_mask_cannot_qualify_contact_evidence():
    review_inputs = _trajectory_inputs(review_only=True)
    review_result = _evidence(review_inputs, source_mask=review_inputs[4])
    assert not review_result["eligible"]
    assert review_result["observedSupportAnchorSampleCount"] == 0
    assert review_result["finalSourceCameraPoseFidelityRequired"] is False

    observed_inputs = _trajectory_inputs()
    no_source_observations = np.zeros_like(observed_inputs[4])
    unobserved_result = _evidence(observed_inputs, source_mask=no_source_observations)
    assert not unobserved_result["eligible"]
    assert unobserved_result["observedSupportAnchorSampleCount"] == 0

import copy

import numpy as np
import pytest

from exercise_motion_pkg.native_foot_geometry import (
    ANATOMY_CALIBRATION_METHOD,
    calibrate_avatar_foot_geometry,
    native_foot_marker_world,
    validated_native_foot_geometry,
)

MODEL_SHA256 = "a" * 64
MIRROR_LATERAL = np.diag([1.0, -1.0, 1.0])


def _uncalibrated_geometry():
    return {
        "version": 1,
        "source": "named_smpl_rest_heel_and_toe_vertices",
        "modelSha256": MODEL_SHA256,
        "sides": {
            "left": {
                "ankleToFootJointLengthMeters": 0.181,
                "heelFromAnkleLocalMeters": [0.020, 0.010, -0.010],
                "toeFromAnkleLocalMeters": [0.180, 0.020, 0.010],
            },
            "right": {
                "ankleToFootJointLengthMeters": 0.193,
                "heelFromAnkleLocalMeters": [0.015, -0.024, -0.014],
                "toeFromAnkleLocalMeters": [0.170, 0.032, 0.016],
            },
        },
    }


def _assert_side(actual, expected):
    assert actual["ankleToFootJointLengthMeters"] == pytest.approx(
        expected["ankleToFootJointLengthMeters"], abs=1e-15)
    np.testing.assert_allclose(
        actual["heelFromAnkleLocalMeters"],
        expected["heelFromAnkleLocalMeters"], atol=1e-15)
    np.testing.assert_allclose(
        actual["toeFromAnkleLocalMeters"],
        expected["toeFromAnkleLocalMeters"], atol=1e-15)


def test_calibration_mirrors_world_markers_and_retains_source_provenance():
    original = _uncalibrated_geometry()
    snapshot = copy.deepcopy(original)
    calibrated = calibrate_avatar_foot_geometry(original)

    assert calibrated is not None
    assert original == snapshot
    provenance = calibrated["anatomyCalibration"]
    assert provenance == {
        "method": ANATOMY_CALIBRATION_METHOD,
        "sourceGeometry": snapshot,
    }
    assert calibrated["modelSha256"] == snapshot["modelSha256"]
    assert (calibrated["sides"]["left"]["ankleToFootJointLengthMeters"]
            == calibrated["sides"]["right"]["ankleToFootJointLengthMeters"])
    np.testing.assert_allclose(
        MIRROR_LATERAL @ np.asarray(
            calibrated["sides"]["right"]["heelFromAnkleLocalMeters"]),
        calibrated["sides"]["left"]["heelFromAnkleLocalMeters"], atol=1e-15)
    np.testing.assert_allclose(
        MIRROR_LATERAL @ np.asarray(
            calibrated["sides"]["right"]["toeFromAnkleLocalMeters"]),
        calibrated["sides"]["left"]["toeFromAnkleLocalMeters"], atol=1e-15)

    left_ankle = np.asarray([0.10, 0.12, 0.08])
    left_foot = left_ankle + np.asarray([0.18, 0.01, -0.02])
    left_side_axis = np.asarray([0.0, 0.0, 1.0])
    right_ankle = MIRROR_LATERAL @ left_ankle
    right_foot = MIRROR_LATERAL @ left_foot
    right_side_axis = -MIRROR_LATERAL @ left_side_axis

    left_heel, left_toe = native_foot_marker_world(
        left_ankle, left_foot, left_side_axis, calibrated["sides"]["left"])
    right_heel, right_toe = native_foot_marker_world(
        right_ankle, right_foot, right_side_axis, calibrated["sides"]["right"])
    np.testing.assert_allclose(right_heel, MIRROR_LATERAL @ left_heel, atol=1e-12)
    np.testing.assert_allclose(right_toe, MIRROR_LATERAL @ left_toe, atol=1e-12)


def test_calibration_is_idempotent_and_legacy_input_is_unchanged():
    original = _uncalibrated_geometry()
    calibrated = calibrate_avatar_foot_geometry(original)

    assert validated_native_foot_geometry(original) == original
    assert calibrate_avatar_foot_geometry(copy.deepcopy(calibrated)) == calibrated
    assert validated_native_foot_geometry(copy.deepcopy(calibrated)) == calibrated
    _assert_side(
        calibrate_avatar_foot_geometry(calibrated)["sides"]["right"],
        calibrated["sides"]["right"])


def test_tampered_calibration_source_or_identity_is_rejected():
    calibrated = calibrate_avatar_foot_geometry(_uncalibrated_geometry())

    tampered_sides = copy.deepcopy(calibrated)
    tampered_sides["sides"]["right"]["toeFromAnkleLocalMeters"][0] += 1e-6
    assert validated_native_foot_geometry(tampered_sides) is None
    assert calibrate_avatar_foot_geometry(tampered_sides) is None

    tampered_source = copy.deepcopy(calibrated)
    tampered_source["anatomyCalibration"]["sourceGeometry"]["sides"]["left"][
        "toeFromAnkleLocalMeters"][0] += 1e-6
    assert validated_native_foot_geometry(tampered_source) is None

    changed_outer_identity = copy.deepcopy(calibrated)
    changed_outer_identity["modelSha256"] = "b" * 64
    assert validated_native_foot_geometry(changed_outer_identity) is None

    changed_source_identity = copy.deepcopy(calibrated)
    changed_source_identity["anatomyCalibration"]["sourceGeometry"][
        "modelSha256"] = "b" * 64
    assert validated_native_foot_geometry(changed_source_identity) is None

    nested_calibration = copy.deepcopy(calibrated)
    nested_calibration["anatomyCalibration"]["sourceGeometry"][
        "anatomyCalibration"] = copy.deepcopy(
            calibrated["anatomyCalibration"])
    assert validated_native_foot_geometry(nested_calibration) is None

    malformed_method = copy.deepcopy(calibrated)
    malformed_method["anatomyCalibration"]["method"] = "unknown"
    assert calibrate_avatar_foot_geometry(malformed_method) is None

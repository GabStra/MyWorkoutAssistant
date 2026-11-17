"""Shared native foot geometry v1: qualified prior, retarget math and identity.

The producer serializes only local ankle-to-forefoot coordinates. Every
physical consumer derives heel/toe material points from the current playback
ankle/foot bone, so no per-frame world arrays can detach from FK/SLERP.

This module owns the measured trust boundary for the named SMPL heel/toe
prior and the single retarget implementation reused by foot_geometry,
shoe_floor, material_region_support, body_surface_geometry and the mutable
controlled-motion promotion boundary.
"""

from __future__ import annotations

import json
import math
import re

import numpy as np

NATIVE_FOOT_GEOMETRY_VERSION = 1
NATIVE_FOOT_GEOMETRY_SOURCE = "named_smpl_rest_heel_and_toe_vertices"
ANATOMY_CALIBRATION_METHOD = "bilateral_normalized_mean_v1"
_SIDES = ("left", "right")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MIRROR_LATERAL = np.diag([1.0, -1.0, 1.0])


def _is_hex64(value) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _finite_vector(value, length=3):
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return None
    if vector.shape != (length,) or not np.isfinite(vector).all():
        return None
    return vector


def _orthonormal_frame(value) -> bool:
    try:
        frame = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(frame.shape == (3, 3) and np.isfinite(frame).all()
                and np.allclose(frame.T @ frame, np.eye(3), atol=1e-6))


def _side_prior_is_valid(side_value) -> bool:
    if not isinstance(side_value, dict):
        return False
    try:
        length = float(side_value["ankleToFootJointLengthMeters"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    toe = _finite_vector(side_value.get("toeFromAnkleLocalMeters"))
    heel_to_toe = _finite_vector(side_value.get("heelToToeLocalMeters"))
    return (math.isfinite(length) and length > 0.0 and toe is not None
            and heel_to_toe is not None
            and np.linalg.norm(toe) > 1e-9
            and np.linalg.norm(heel_to_toe) > 1e-9
            and _orthonormal_frame(side_value.get("modelFootFrame")))


def is_qualified_named_foot_marker_prior(prior) -> bool:
    """Structural trust boundary for an existing named-SMPL heel/toe prior.

    Callers with stronger source-video identity requirements (for example
    anatomical pixel calibration) add those checks; this function owns only
    the shared source/model/geometry shape so the trust boundary is not
    duplicated.
    """
    if not isinstance(prior, dict):
        return False
    if (prior.get("source") != NATIVE_FOOT_GEOMETRY_SOURCE
            or prior.get("modelType") != "smpl"
            or type(prior.get("modelVertexCount")) is not int
            or prior.get("modelVertexCount") != 6890
            or not _is_hex64(prior.get("modelSha256"))
            or not _is_hex64(prior.get("reconstructionSha256"))):
        return False
    sides = prior.get("sides")
    return (isinstance(sides, dict)
            and all(side in sides and _side_prior_is_valid(sides[side])
                    for side in _SIDES))


def native_foot_geometry_from_prior(prior):
    """Normalize a qualified prior to the exact minimal nativeFootGeometry v1.

    Returns ``None`` when the prior is absent or not qualified. The heel offset
    is ``toeFromAnkle + heelToToeLocalMeters``: the stored heelToToe vector is
    ``heel - toe`` and is therefore added, never subtracted.
    """
    if not is_qualified_named_foot_marker_prior(prior):
        return None
    sides = {}
    for side in _SIDES:
        source = prior["sides"][side]
        toe = np.asarray(source["toeFromAnkleLocalMeters"], dtype=float)
        heel_to_toe = np.asarray(source["heelToToeLocalMeters"], dtype=float)
        heel = toe + heel_to_toe
        sides[side] = {
            "ankleToFootJointLengthMeters": float(
                source["ankleToFootJointLengthMeters"]),
            "heelFromAnkleLocalMeters": heel.tolist(),
            "toeFromAnkleLocalMeters": toe.tolist(),
        }
    return {
        "version": NATIVE_FOOT_GEOMETRY_VERSION,
        "source": NATIVE_FOOT_GEOMETRY_SOURCE,
        "modelSha256": prior["modelSha256"],
        "sides": sides,
    }


def _normalized_side(value):
    if not isinstance(value, dict):
        return None
    try:
        length = float(value["ankleToFootJointLengthMeters"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    heel = _finite_vector(value.get("heelFromAnkleLocalMeters"))
    toe = _finite_vector(value.get("toeFromAnkleLocalMeters"))
    if (heel is None or toe is None or not math.isfinite(length)
            or length <= 0.0 or toe[0] <= 0.0
            or np.linalg.norm(toe) <= 1e-9
            or np.linalg.norm(toe - heel) <= 1e-9):
        return None
    return {
        "ankleToFootJointLengthMeters": length,
        "heelFromAnkleLocalMeters": heel.tolist(),
        "toeFromAnkleLocalMeters": toe.tolist(),
    }


def _calibrated_sides(sides):
    """Infer a shared bilateral avatar anatomy from normalized local offsets."""
    try:
        left_length = float(sides["left"]["ankleToFootJointLengthMeters"])
        right_length = float(sides["right"]["ankleToFootJointLengthMeters"])
        left_heel = np.asarray(
            sides["left"]["heelFromAnkleLocalMeters"], dtype=float)
        left_toe = np.asarray(
            sides["left"]["toeFromAnkleLocalMeters"], dtype=float)
        right_heel = np.asarray(
            sides["right"]["heelFromAnkleLocalMeters"], dtype=float)
        right_toe = np.asarray(
            sides["right"]["toeFromAnkleLocalMeters"], dtype=float)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (not math.isfinite(left_length) or not math.isfinite(right_length)
            or left_length <= 0.0 or right_length <= 0.0):
        return None
    common_length = (left_length + right_length) / 2.0
    right_normalized_heel = (
        right_heel / right_length
        + _MIRROR_LATERAL @ (left_heel / left_length)) / 2.0
    right_normalized_toe = (
        right_toe / right_length
        + _MIRROR_LATERAL @ (left_toe / left_length)) / 2.0
    right_from_ankle_heel = right_normalized_heel * common_length
    right_from_ankle_toe = right_normalized_toe * common_length
    sides = {
        "left": {
            "ankleToFootJointLengthMeters": common_length,
            "heelFromAnkleLocalMeters": (
                _MIRROR_LATERAL @ right_from_ankle_heel).tolist(),
            "toeFromAnkleLocalMeters": (
                _MIRROR_LATERAL @ right_from_ankle_toe).tolist(),
        },
        "right": {
            "ankleToFootJointLengthMeters": common_length,
            "heelFromAnkleLocalMeters": right_from_ankle_heel.tolist(),
            "toeFromAnkleLocalMeters": right_from_ankle_toe.tolist(),
        },
    }
    normalized = {side: _normalized_side(value) for side, value in sides.items()}
    return None if any(value is None for value in normalized.values()) else normalized


def _validated_geometry_base(payload):
    """Validate the uncalibrated v1 shape without retaining any metadata."""
    if not isinstance(payload, dict):
        return None
    if (type(payload.get("version")) is not int
            or payload.get("version") != NATIVE_FOOT_GEOMETRY_VERSION
            or payload.get("source") != NATIVE_FOOT_GEOMETRY_SOURCE
            or not _is_hex64(payload.get("modelSha256"))):
        return None
    sides = payload.get("sides")
    if not isinstance(sides, dict) or set(sides) != set(_SIDES):
        return None
    normalized = {side: _normalized_side(sides[side]) for side in _SIDES}
    if any(value is None for value in normalized.values()):
        return None
    return {
        "version": NATIVE_FOOT_GEOMETRY_VERSION,
        "source": NATIVE_FOOT_GEOMETRY_SOURCE,
        "modelSha256": payload["modelSha256"],
        "sides": normalized,
    }


def _same_side_values(actual, expected) -> bool:
    return bool(
        actual["ankleToFootJointLengthMeters"]
        == expected["ankleToFootJointLengthMeters"]
        and np.array_equal(
            np.asarray(actual["heelFromAnkleLocalMeters"]),
            np.asarray(expected["heelFromAnkleLocalMeters"]))
        and np.array_equal(
            np.asarray(actual["toeFromAnkleLocalMeters"]),
            np.asarray(expected["toeFromAnkleLocalMeters"])))


def validated_native_foot_geometry(payload):
    """Validate an existing serialized block without promotion or repair."""
    base = _validated_geometry_base(payload)
    if base is None:
        return None
    if "anatomyCalibration" not in payload:
        return base
    calibration = payload.get("anatomyCalibration")
    if (not isinstance(calibration, dict)
            or set(calibration) != {"method", "sourceGeometry"}
            or calibration.get("method") != ANATOMY_CALIBRATION_METHOD):
        return None
    source_payload = calibration.get("sourceGeometry")
    if (not isinstance(source_payload, dict)
            or "anatomyCalibration" in source_payload):
        return None
    source = _validated_geometry_base(source_payload)
    if source is None or source["modelSha256"] != base["modelSha256"]:
        return None
    recomputed = _calibrated_sides(source["sides"])
    if (recomputed is None
            or any(not _same_side_values(base["sides"][side], recomputed[side])
                   for side in _SIDES)):
        return None
    return {
        **base,
        "anatomyCalibration": {
            "method": ANATOMY_CALIBRATION_METHOD,
            "sourceGeometry": source,
        },
    }


def calibrate_avatar_foot_geometry(geometry):
    """Infer and attach a bilateral avatar anatomy calibration, or return None.

    The input must be a valid nativeFootGeometry v1 block. Calibration changes
    only the local avatar anatomy offsets; the original block is retained under
    ``anatomyCalibration.sourceGeometry`` as provenance and is never mutated.
    Valid calibrated input is returned normalized and unchanged, so repeated
    calls never re-average the inferred anatomy.
    """
    validated = validated_native_foot_geometry(geometry)
    if validated is None:
        return None
    if "anatomyCalibration" in validated:
        return validated
    calibrated = _calibrated_sides(validated["sides"])
    if calibrated is None:
        return None
    return {
        "version": NATIVE_FOOT_GEOMETRY_VERSION,
        "source": NATIVE_FOOT_GEOMETRY_SOURCE,
        "modelSha256": validated["modelSha256"],
        "sides": calibrated,
        "anatomyCalibration": {
            "method": ANATOMY_CALIBRATION_METHOD,
            "sourceGeometry": validated,
        },
    }


def promote_native_foot_geometry(payload):
    """Mutable generation boundary: promote a qualified prior, never repair.

    If the payload already carries a ``nativeFootGeometry`` key it is validated
    exactly as submitted. An invalid recognized block returns ``None`` and the
    caller must reject rather than fall back to the prior.
    """
    if not isinstance(payload, dict):
        return None
    if "nativeFootGeometry" in payload:
        return validated_native_foot_geometry(payload.get("nativeFootGeometry"))
    return native_foot_geometry_from_prior(payload.get("sourceFootMarkerPrior"))


def native_foot_bone_frame(ankle, foot_joint, side_axis):
    """Fixed producer convention with a pose-aware side axis (no model up)."""
    ankle = np.asarray(ankle, dtype=float)
    foot_joint = np.asarray(foot_joint, dtype=float)
    side_axis = np.asarray(side_axis, dtype=float)
    vector = foot_joint - ankle
    length = np.linalg.norm(vector, axis=-1, keepdims=True)
    if np.any(length <= 1e-12):
        raise ValueError("native foot geometry requires a nonzero ankle-foot bone")
    forward = vector / length
    lateral = side_axis - forward * np.sum(side_axis * forward, axis=-1, keepdims=True)
    lateral_length = np.linalg.norm(lateral, axis=-1, keepdims=True)
    if np.any(lateral_length <= 1e-9):
        raise ValueError("native foot geometry requires a non-collinear side axis")
    lateral = lateral / lateral_length
    up = np.cross(lateral, forward)
    return forward, lateral, up, length


def native_foot_marker_world(ankle, foot_joint, side_axis, side_geometry):
    """Return world heel/toe material markers from current bone plus local offsets."""
    if not isinstance(side_geometry, dict):
        raise ValueError("native foot geometry side is unavailable")
    reference_length = float(side_geometry["ankleToFootJointLengthMeters"])
    if not math.isfinite(reference_length) or reference_length <= 0.0:
        raise ValueError("native foot geometry reference length is invalid")
    heel_local = _finite_vector(side_geometry.get("heelFromAnkleLocalMeters"))
    toe_local = _finite_vector(side_geometry.get("toeFromAnkleLocalMeters"))
    if heel_local is None or toe_local is None:
        raise ValueError("native foot geometry local offsets are invalid")
    ankle = np.asarray(ankle, dtype=float)
    forward, lateral, up, length = native_foot_bone_frame(
        ankle, foot_joint, side_axis)
    factor = length / reference_length
    heel_local = heel_local * factor
    toe_local = toe_local * factor

    def offset(local):
        return (forward * local[..., 0:1] + lateral * local[..., 1:2]
                + up * local[..., 2:3])

    return ankle + offset(heel_local), ankle + offset(toe_local)


def native_foot_geometry_identity(payload):
    """Canonical geometry identity only when a valid block is present."""
    value = payload.get("nativeFootGeometry") if isinstance(payload, dict) else None
    validated = validated_native_foot_geometry(value)
    if validated is None:
        return None
    return json.dumps(validated, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ANATOMY_CALIBRATION_METHOD",
    "NATIVE_FOOT_GEOMETRY_SOURCE",
    "NATIVE_FOOT_GEOMETRY_VERSION",
    "calibrate_avatar_foot_geometry",
    "is_qualified_named_foot_marker_prior",
    "native_foot_bone_frame",
    "native_foot_geometry_from_prior",
    "native_foot_geometry_identity",
    "native_foot_marker_world",
    "promote_native_foot_geometry",
    "validated_native_foot_geometry",
]

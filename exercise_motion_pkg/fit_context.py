"""JSON-safe snapshot of the constraints that produced a rejected fit candidate.

The snapshot is evidence about one concrete candidate: its pose identity, frame
clock and the actual derived contact/temporal constraints used by the fit. It
is intentionally a plain data builder, not a solver or a repair framework.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

import numpy as np

from .sequence_stabilization import pose_digest


SCHEMA_VERSION = 1
KIND = "controlled_motion_fit_context"
CONTEXT_ORIGINS = ("actual_fit", "reconstructed_normal_context")


def _finite_value(value):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _numeric_array(value):
    """Return a JSON list copy; non-finite entries become None, never defaults."""
    if value is None:
        return None
    array = np.asarray(value, dtype=float)
    if np.isfinite(array).all():
        return array.tolist()
    finite = np.asarray(array, dtype=object)
    finite[~np.isfinite(array)] = None
    return finite.tolist()


def _jsonable(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, np.ndarray):
        if value.dtype.kind == "b":
            return value.astype(bool).tolist()
        if value.dtype.kind in "iuf":
            return _numeric_array(value)
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return deepcopy(value)


def _frame_times(candidate):
    times = []
    for frame in candidate.get("frames") or []:
        times.append(_finite_value((frame or {}).get("timeSec")))
    return times


def _safe_pose_digest(candidate):
    try:
        return pose_digest(candidate)
    except Exception:
        return None


def _context_digest(context):
    contents = {
        key: value for key, value in context.items() if key != "contextDigest"
    }
    encoded = json.dumps(
        contents, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_fit_context(
    candidate,
    *,
    fit_contact_pinned,
    fit_contact_targets,
    temporal_reference,
    jerk_limit,
    contact_limit,
    contact_anchor_ids=None,
    model_intent_contact_mask=None,
    native_foot_tracks=None,
    native_foot_geometry=None,
    joint_contact_pinned=None,
    joint_contact_targets=None,
    height_contact_pinned=None,
    height_contact_targets=None,
    height_contact_limit=None,
    origin="actual_fit",
    stage="candidate_validation",
):
    """Return a JSON-safe copy of one candidate's actual fit constraint context.

    Required values that are unavailable are retained as ``None`` and reported
    through ``complete``/``unavailableReasons``. They are never replaced by
    permissive defaults.

    ``joint_contact_pinned``/``joint_contact_targets`` describe the hard
    keyframe-contact gate inputs (the validator's own pin mask and targets).
    They stay distinct from the fitting/repair targets above, which may include
    derived native-fullsole endpoints and therefore are not a hard gate.
    Omitting them means "unavailable"; they are never inferred from the fit
    mask.

    ``height_contact_pinned``/``height_contact_targets`` describe the hard
    height-only gate's own ``(frames, joints)`` mask and scalar vertical
    targets (the production gate compares each pinned joint's Y coordinate).
    ``height_contact_limit`` is that gate's actual production tolerance. They
    stay separate from the XYZ pins, are copied verbatim, and are omitted as
    ``None`` when unavailable rather than being replaced by XYZ pins or zeros.
    """
    if not isinstance(candidate, dict):
        raise TypeError("candidate must be a mapping")
    if origin not in CONTEXT_ORIGINS:
        raise ValueError(f"unsupported context origin: {origin!r}")

    joint_names = list(candidate.get("jointNames") or [])
    frame_times = _frame_times(candidate)
    reasons = []

    def required_array(name, value, shape):
        try:
            converted = _numeric_array(value)
        except (TypeError, ValueError):
            reasons.append(f"{name}_invalid")
            return None
        if converted is None:
            reasons.append(f"{name}_unavailable")
            return None
        try:
            actual = np.asarray(value)
        except (TypeError, ValueError):
            reasons.append(f"{name}_invalid")
            return converted
        if actual.shape != shape:
            reasons.append(f"{name}_shape_mismatch")
            return converted
        return converted

    shape2 = (len(frame_times), len(joint_names))
    shape3 = (len(frame_times), len(joint_names), 3)
    pinned_values = _jsonable(fit_contact_pinned)
    targets_values = required_array("fitContactTargets", fit_contact_targets, shape3)
    temporal_values = required_array(
        "temporalReferenceJoints", temporal_reference, shape3
    )
    try:
        pinned_array = (None if fit_contact_pinned is None
                        else np.asarray(fit_contact_pinned))
    except (TypeError, ValueError):
        pinned_array = None
    if pinned_array is None:
        reasons.append("fitContactPinned_unavailable")
    elif pinned_array.shape != shape2:
        reasons.append("fitContactPinned_shape_mismatch")
    elif pinned_array.dtype.kind != "b":
        reasons.append("fitContactPinned_not_boolean")

    joint_pinned_values = _jsonable(joint_contact_pinned)
    if joint_contact_pinned is not None:
        try:
            joint_pinned_array = np.asarray(joint_contact_pinned)
        except (TypeError, ValueError):
            joint_pinned_array = None
            reasons.append("jointContactPinned_invalid")
        if joint_pinned_array is not None:
            if joint_pinned_array.shape != shape2:
                reasons.append("jointContactPinned_shape_mismatch")
            elif joint_pinned_array.dtype.kind != "b":
                reasons.append("jointContactPinned_not_boolean")
    joint_targets_values = None
    if joint_contact_targets is not None:
        joint_targets_values = required_array(
            "jointContactTargets", joint_contact_targets, shape3
        )

    height_pinned_values = _jsonable(height_contact_pinned)
    if height_contact_pinned is not None:
        try:
            height_pinned_array = np.asarray(height_contact_pinned)
        except (TypeError, ValueError):
            height_pinned_array = None
            reasons.append("heightContactPinned_invalid")
        if height_pinned_array is not None:
            if height_pinned_array.shape != shape2:
                reasons.append("heightContactPinned_shape_mismatch")
            elif height_pinned_array.dtype.kind != "b":
                reasons.append("heightContactPinned_not_boolean")
    height_targets_values = None
    if height_contact_targets is not None:
        height_targets_values = required_array(
            "heightContactTargets", height_contact_targets, shape2
        )
    height_limit_value = None
    if height_contact_limit is not None:
        height_limit_value = _finite_value(height_contact_limit)
        if height_limit_value is None or height_limit_value <= 0.0:
            reasons.append("heightContactLimitMeters_invalid")
    if (height_contact_pinned is None) != (height_contact_targets is None):
        reasons.append("heightContactFields_incomplete")
    if height_contact_pinned is not None and height_limit_value is None:
        reasons.append("heightContactLimitMeters_unavailable")

    model_mask_values = _jsonable(model_intent_contact_mask)
    if model_intent_contact_mask is not None:
        mask_array = np.asarray(model_intent_contact_mask)
        if mask_array.shape != shape2:
            reasons.append("modelIntentContactMask_shape_mismatch")
        elif mask_array.dtype.kind != "b":
            reasons.append("modelIntentContactMask_not_boolean")

    anchor_values = _jsonable(contact_anchor_ids)
    if contact_anchor_ids is not None:
        try:
            anchor_shape = np.asarray(contact_anchor_ids, dtype=object).shape
        except (TypeError, ValueError):
            anchor_shape = None
        if anchor_shape != shape2:
            reasons.append("contactAnchorIds_shape_mismatch")

    jerk_value = _finite_value(jerk_limit)
    if jerk_value is None:
        reasons.append("jerkLimit_unavailable")
    elif jerk_value <= 0.0:
        reasons.append("jerkLimit_not_positive")
    contact_value = _finite_value(contact_limit)
    if contact_value is None:
        reasons.append("contactLimitMeters_unavailable")
    elif contact_value <= 0.0:
        reasons.append("contactLimitMeters_not_positive")

    fps_value = _finite_value(candidate.get("fps"))
    if fps_value is None or fps_value <= 0.0:
        reasons.append("fps_unavailable")
        fps_value = fps_value if fps_value is not None else None
    if not frame_times:
        reasons.append("frameCount_unavailable")
    elif any(time is None for time in frame_times):
        reasons.append("frameTimesSec_incomplete")
    if not joint_names:
        reasons.append("jointNames_unavailable")

    context = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "contextOrigin": origin,
        "stage": str(stage),
        "candidatePoseDigest": _safe_pose_digest(candidate),
        "frameCount": len(frame_times),
        "jointNames": joint_names,
        "fps": fps_value,
        "frameTimesSec": frame_times,
        "fitContactPinned": pinned_values,
        "fitContactTargets": targets_values,
        "jointContactPinned": joint_pinned_values,
        "jointContactTargets": joint_targets_values,
        "heightContactPinned": height_pinned_values,
        "heightContactTargets": height_targets_values,
        "heightContactLimitMeters": height_limit_value,
        "temporalReferenceJoints": temporal_values,
        "jerkLimit": jerk_value,
        "contactLimitMeters": contact_value,
        "contactAnchorIds": anchor_values,
        "modelIntentContactMask": model_mask_values,
        "nativeFootMaterialTracks": _jsonable(native_foot_tracks),
        "nativeFootGeometry": _jsonable(native_foot_geometry),
        "complete": not reasons,
        "unavailableReasons": sorted(set(reasons)),
    }
    if context["candidatePoseDigest"] is None:
        context["complete"] = False
        context["unavailableReasons"] = sorted(
            set(context["unavailableReasons"]) | {"candidatePoseDigest_unavailable"}
        )
    context["contextDigest"] = _context_digest(context)
    return context


def unavailable_fit_context(
    candidate,
    *,
    error=None,
    reason=None,
    stage="candidate_validation",
    origin="actual_fit",
):
    """Return an explicit incomplete context for a candidate that was retained."""
    if origin not in CONTEXT_ORIGINS:
        origin = "actual_fit"
    candidate = candidate if isinstance(candidate, dict) else {}
    joint_names = list(candidate.get("jointNames") or [])
    frame_times = _frame_times(candidate)
    reasons = []
    if reason:
        reasons.append(str(reason))
    if error is not None:
        reasons.append(f"fit_context_error:{type(error).__name__}:{error}")
    if not reasons:
        reasons.append("fit_context_unavailable")
    context = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "contextOrigin": origin,
        "stage": str(stage),
        "candidatePoseDigest": _safe_pose_digest(candidate),
        "frameCount": len(frame_times),
        "jointNames": joint_names,
        "fps": _finite_value(candidate.get("fps")),
        "frameTimesSec": frame_times,
        "fitContactPinned": None,
        "fitContactTargets": None,
        "jointContactPinned": None,
        "jointContactTargets": None,
        "heightContactPinned": None,
        "heightContactTargets": None,
        "heightContactLimitMeters": None,
        "temporalReferenceJoints": None,
        "jerkLimit": None,
        "contactLimitMeters": None,
        "contactAnchorIds": None,
        "modelIntentContactMask": None,
        "nativeFootMaterialTracks": None,
        "nativeFootGeometry": None,
        "complete": False,
        "available": False,
        "unavailableReasons": reasons,
    }
    if error is not None:
        context["error"] = f"{type(error).__name__}: {error}"
    context["contextDigest"] = _context_digest(context)
    return context


def _shape_matches(value, shape):
    if value is None:
        return False
    try:
        return np.asarray(value, dtype=float).shape == shape
    except (TypeError, ValueError):
        return False


def _finite_shape(value, shape):
    if not _shape_matches(value, shape):
        return False
    try:
        return bool(np.isfinite(np.asarray(value, dtype=float)).all())
    except (TypeError, ValueError):
        return False


def validate_fit_context(candidate, context):
    """Validate identity association and shape/finiteness of one context snapshot."""
    if not isinstance(context, dict):
        return {"passed": False, "reasons": ["context_not_a_mapping"]}
    reasons = []
    if context.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append("unsupported_schema_version")
    if context.get("kind") != KIND:
        reasons.append("wrong_context_kind")
    if context.get("contextOrigin") not in CONTEXT_ORIGINS:
        reasons.append("unsupported_context_origin")
    if context.get("complete") is not True:
        reasons.append("context_incomplete")
        reasons.extend(str(item) for item in context.get("unavailableReasons") or [])
    if context.get("available") is False:
        reasons.append("context_unavailable")

    candidate = candidate if isinstance(candidate, dict) else {}
    frames = candidate.get("frames") or []
    joint_names = list(candidate.get("jointNames") or [])
    expected_count = len(frames)
    if context.get("frameCount") != expected_count:
        reasons.append("frame_count_mismatch")
    if list(context.get("jointNames") or []) != joint_names:
        reasons.append("joint_names_mismatch")
    candidate_fps = _finite_value(candidate.get("fps"))
    context_fps = _finite_value(context.get("fps"))
    if candidate_fps is None or context_fps is None:
        if candidate_fps != context_fps:
            reasons.append("fps_mismatch")
    elif not math.isclose(candidate_fps, context_fps, rel_tol=1e-9, abs_tol=1e-12):
        reasons.append("fps_mismatch")

    candidate_times = _frame_times(candidate)
    context_times = context.get("frameTimesSec")
    if not isinstance(context_times, list) or len(context_times) != len(candidate_times):
        reasons.append("frame_clock_mismatch")
    else:
        for expected, actual in zip(candidate_times, context_times):
            if expected is None or actual is None:
                if expected != actual:
                    reasons.append("frame_clock_mismatch")
                    break
            elif not math.isclose(float(expected), float(actual),
                                  rel_tol=1e-9, abs_tol=1e-12):
                reasons.append("frame_clock_mismatch")
                break

    actual_digest = _safe_pose_digest(candidate)
    if actual_digest is None:
        reasons.append("candidate_pose_digest_unavailable")
    elif context.get("candidatePoseDigest") != actual_digest:
        reasons.append("candidate_pose_digest_mismatch")

    stored_digest = context.get("contextDigest")
    try:
        rebuilt_digest = _context_digest(context)
    except (TypeError, ValueError):
        rebuilt_digest = None
    if stored_digest is None or rebuilt_digest != stored_digest:
        reasons.append("context_digest_mismatch")

    shape2 = (expected_count, len(joint_names))
    shape3 = (expected_count, len(joint_names), 3)
    pinned = context.get("fitContactPinned")
    if not _shape_matches(pinned, shape2):
        reasons.append("fit_contact_pinned_shape_mismatch")
    else:
        pinned_array = np.asarray(pinned)
        if pinned_array.dtype.kind != "b":
            reasons.append("fit_contact_pinned_not_boolean")
    if not _finite_shape(context.get("fitContactTargets"), shape3):
        reasons.append("fit_contact_targets_invalid")
    joint_pinned = context.get("jointContactPinned")
    if joint_pinned is not None:
        if not _shape_matches(joint_pinned, shape2):
            reasons.append("joint_contact_pinned_shape_mismatch")
        elif np.asarray(joint_pinned).dtype.kind != "b":
            reasons.append("joint_contact_pinned_not_boolean")
    joint_targets = context.get("jointContactTargets")
    if joint_targets is not None and not _finite_shape(joint_targets, shape3):
        reasons.append("joint_contact_targets_invalid")

    height_pinned = context.get("heightContactPinned")
    height_targets = context.get("heightContactTargets")
    height_limit = context.get("heightContactLimitMeters")
    if (height_pinned is not None or height_targets is not None
            or height_limit is not None):
        if height_pinned is None or height_targets is None:
            reasons.append("height_contact_fields_incomplete")
        if height_pinned is not None:
            if not _shape_matches(height_pinned, shape2):
                reasons.append("height_contact_pinned_shape_mismatch")
            elif np.asarray(height_pinned).dtype.kind != "b":
                reasons.append("height_contact_pinned_not_boolean")
        if height_targets is not None and not _finite_shape(height_targets, shape2):
            reasons.append("height_contact_targets_invalid")
        limit = _finite_value(height_limit)
        if limit is None or limit <= 0.0:
            reasons.append("height_contact_limit_invalid")

    if not _finite_shape(context.get("temporalReferenceJoints"), shape3):
        reasons.append("temporal_reference_invalid")

    jerk = _finite_value(context.get("jerkLimit"))
    if jerk is None or jerk <= 0.0:
        reasons.append("jerk_limit_invalid")
    contact = _finite_value(context.get("contactLimitMeters"))
    if contact is None or contact <= 0.0:
        reasons.append("contact_limit_invalid")

    anchor_ids = context.get("contactAnchorIds")
    if anchor_ids is not None:
        try:
            if np.asarray(anchor_ids, dtype=object).shape != shape2:
                reasons.append("contact_anchor_ids_shape_mismatch")
        except (TypeError, ValueError):
            reasons.append("contact_anchor_ids_invalid")
    model_mask = context.get("modelIntentContactMask")
    if model_mask is not None:
        if not _shape_matches(model_mask, shape2):
            reasons.append("model_intent_contact_mask_shape_mismatch")
        elif np.asarray(model_mask).dtype.kind != "b":
            reasons.append("model_intent_contact_mask_not_boolean")

    unique = sorted(set(reasons))
    return {"passed": not unique, "reasons": unique}

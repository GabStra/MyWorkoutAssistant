"""Normalize version-1 body-surface contact records.

This module owns only the shared JSON shape and strict type/finite-value
checks at the record boundary. It validates neither source-evidence
authenticity nor calibrated placement: the source verifier owns proof against
reopened video/pose/clock receipts, and calibration owns geometry inference.
In particular, ``geometryProvenance.kind == "observed"`` is rejected because
schema validation must never certify a surface as an observation.

Unknown anatomical region names are valid. Primitive availability is resolved
by actual geometry, never by a closed body-part whitelist here.
"""

from copy import deepcopy
import math
import re

SCHEMA_VERSION = 1
CONTACT_MODES = ("stationary", "sliding", "rolling")
REGION_SIDES = ("left", "right", "center")
CONTACT_STATES = ("direct_contact", "no_contact", "unknown")
GEOMETRY_PROVENANCE_KINDS = ("inferred", "calibrated")
INFERRED_ACTIVATION_KINDS = ("stationary_source_track_between_direct_contacts",)

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_BARYCENTRIC_SUM_TOLERANCE = 1e-6
_NORMAL_UNIT_TOLERANCE = 1e-6
_POLYGON_OFFSET_TOLERANCE = 1e-4

_TOP_LEVEL_REQUIRED = (
    "schemaVersion",
    "contactId",
    "bodyRegion",
    "contactMode",
    "sourceEvidence",
    "patchBinding",
    "surfaceEstimate",
    "geometryProvenance",
)
_TOP_LEVEL_OPTIONAL = ("uncertainty", "visibilityAdjudication")


def _fail(where, message):
    raise ValueError(f"{where}: {message}")


def _mapping(value, where):
    if not isinstance(value, dict):
        _fail(where, "must be an object")
    for key in value:
        if not isinstance(key, str):
            _fail(where, "object keys must be strings")
    return value


def _require_keys(value, where, required, optional=()):
    missing = [key for key in required if key not in value]
    if missing:
        _fail(where, f"missing required field(s): {', '.join(sorted(missing))}")
    allowed = set(required) | set(optional)
    unexpected = [key for key in value if key not in allowed]
    if unexpected:
        _fail(where, f"unknown field(s): {', '.join(sorted(unexpected))}")


def _nonempty_string(value, where):
    if not isinstance(value, str):
        _fail(where, "must be a string")
    if not value.strip():
        _fail(where, "must be a non-empty string")
    return value


def _finite_number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(where, "must be a finite number")
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        _fail(where, "must be finite")
    return value


def _nonnegative_number(value, where):
    _finite_number(value, where)
    if value < 0:
        _fail(where, "must be non-negative")
    return value


def _nonnegative_integer(value, where):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(where, "must be a non-negative integer")
    if value < 0:
        _fail(where, "must be non-negative")
    return value


def _number_list(value, length, where):
    if not isinstance(value, list) or len(value) != length:
        _fail(where, f"must be a list of {length} numbers")
    for index, component in enumerate(value):
        _finite_number(component, f"{where}[{index}]")
    return value


def _unit_vector3(value, where):
    _number_list(value, 3, where)
    length = math.sqrt(sum(float(component) ** 2 for component in value))
    if abs(length - 1.0) > _NORMAL_UNIT_TOLERANCE:
        _fail(where, "must be a unit vector")
    return value


def _sha256(value, where):
    _nonempty_string(value, where)
    if not _SHA256_PATTERN.match(value):
        _fail(where, "must be a 64-character SHA256 hex digest")
    return value


def _json_value(value, where):
    """Copy an unconstrained provenance value while enforcing JSON finiteness."""
    if value is None or isinstance(value, (str, bool, int)):
        return deepcopy(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(where, "must be finite")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        _mapping(value, where)
        return {
            key: _json_value(item, f"{where}.{key}") for key, item in value.items()
        }
    _fail(where, "must be a JSON value")


def _normalize_body_region(value, where):
    value = _mapping(value, where)
    _require_keys(value, where, ("name", "side"))
    name = _nonempty_string(value["name"], f"{where}.name")
    side = _nonempty_string(value["side"], f"{where}.side")
    if side not in REGION_SIDES:
        _fail(f"{where}.side", f"must be one of {', '.join(REGION_SIDES)}")
    return {"name": name, "side": side}


def _normalize_observation(value, where):
    value = _mapping(value, where)
    _require_keys(
        value,
        where,
        (
            "sampleId",
            "sourceTimeSec",
            "sourcePoseFrameIndex",
            "sourceFrameIndex",
            "sourceFps",
            "contactState",
            "visible",
            "surfaceId",
        ),
    )
    sample_id = _nonempty_string(value["sampleId"], f"{where}.sampleId")
    source_time = _finite_number(value["sourceTimeSec"], f"{where}.sourceTimeSec")
    pose_frame = _nonnegative_integer(
        value["sourcePoseFrameIndex"], f"{where}.sourcePoseFrameIndex"
    )
    frame = _nonnegative_integer(value["sourceFrameIndex"], f"{where}.sourceFrameIndex")
    source_fps = _finite_number(value["sourceFps"], f"{where}.sourceFps")
    if source_fps <= 0:
        _fail(f"{where}.sourceFps", "must be positive")
    contact_state = _nonempty_string(value["contactState"], f"{where}.contactState")
    if contact_state not in CONTACT_STATES:
        _fail(
            f"{where}.contactState",
            f"must be one of {', '.join(CONTACT_STATES)}",
        )
    visible = value["visible"]
    if not isinstance(visible, bool):
        _fail(f"{where}.visible", "must be a boolean")
    surface_id = _nonempty_string(value["surfaceId"], f"{where}.surfaceId")
    return {
        "sampleId": sample_id,
        "sourceTimeSec": source_time,
        "sourcePoseFrameIndex": pose_frame,
        "sourceFrameIndex": frame,
        "sourceFps": source_fps,
        "contactState": contact_state,
        "visible": visible,
        "surfaceId": surface_id,
    }


def _normalize_inferred_activation(value, where, normalized_source_evidence):
    """Validate the explicit, bounded interval inferred between direct contacts."""
    value = _mapping(value, where)
    _require_keys(value, where, (
        "kind", "jointName", "startSourcePoseFrameIndex", "endSourcePoseFrameIndex",
        "sourceSampleIds", "trackProofSha256"))
    kind = _nonempty_string(value["kind"], f"{where}.kind")
    if kind not in INFERRED_ACTIVATION_KINDS:
        _fail(f"{where}.kind", f"must be one of {', '.join(INFERRED_ACTIVATION_KINDS)}")
    joint_name = _nonempty_string(value["jointName"], f"{where}.jointName")
    start = _nonnegative_integer(value["startSourcePoseFrameIndex"],
                                 f"{where}.startSourcePoseFrameIndex")
    end = _nonnegative_integer(value["endSourcePoseFrameIndex"],
                               f"{where}.endSourcePoseFrameIndex")
    if end <= start:
        _fail(f"{where}.endSourcePoseFrameIndex", "must be greater than the start frame")
    sample_ids = value["sourceSampleIds"]
    if not isinstance(sample_ids, list) or len(sample_ids) != 2:
        _fail(f"{where}.sourceSampleIds", "must list exactly the two direct-contact sampleIds")
    sample_ids = [_nonempty_string(sample_id, f"{where}.sourceSampleIds[{index}]")
                  for index, sample_id in enumerate(sample_ids)]
    if len(set(sample_ids)) != 2:
        _fail(f"{where}.sourceSampleIds", "must be unique")
    observations = {row["sampleId"]: row
                    for row in normalized_source_evidence["observations"]}
    direct_ids = {row["sampleId"] for row in observations.values()
                  if row["contactState"] == "direct_contact" and row["visible"]}
    if set(sample_ids) != direct_ids:
        _fail(f"{where}.sourceSampleIds", "must identify the direct-contact observations")
    referenced = [observations[sample_id] for sample_id in sample_ids]
    if sorted(row["sourcePoseFrameIndex"] for row in referenced) != [start, end]:
        _fail(f"{where}", "start/end source pose bounds must match both direct observations")
    if len({row["surfaceId"] for row in referenced}) != 1:
        _fail(f"{where}.sourceSampleIds", "direct observations must share one surfaceId")
    return {"kind": kind, "jointName": joint_name, "startSourcePoseFrameIndex": start,
            "endSourcePoseFrameIndex": end, "sourceSampleIds": sample_ids,
            "trackProofSha256": _sha256(
                value["trackProofSha256"], f"{where}.trackProofSha256")}


def _normalize_source_evidence(value, where):
    value = _mapping(value, where)
    _require_keys(
        value,
        where,
        (
            "sourceVideoSha256",
            "sourcePosePayloadSha256",
            "sourceFrameClockReceiptSha256",
            "observations",
        ),
        ("inferredActivation",),
    )
    video_sha = _sha256(value["sourceVideoSha256"], f"{where}.sourceVideoSha256")
    pose_sha = _sha256(value["sourcePosePayloadSha256"], f"{where}.sourcePosePayloadSha256")
    clock_sha = _sha256(
        value["sourceFrameClockReceiptSha256"],
        f"{where}.sourceFrameClockReceiptSha256",
    )
    observations = value["observations"]
    if not isinstance(observations, list):
        _fail(f"{where}.observations", "must be a list")
    if not observations:
        _fail(f"{where}.observations", "must contain at least one observation")
    seen_sample_ids = set()
    normalized = []
    for index, observation in enumerate(observations):
        item_where = f"{where}.observations[{index}]"
        item = _normalize_observation(observation, item_where)
        if item["sampleId"] in seen_sample_ids:
            _fail(f"{item_where}.sampleId", "must be unique")
        seen_sample_ids.add(item["sampleId"])
        normalized.append(item)
    normalized = {
        "sourceVideoSha256": video_sha,
        "sourcePosePayloadSha256": pose_sha,
        "sourceFrameClockReceiptSha256": clock_sha,
        "observations": normalized,
    }
    if "inferredActivation" in value:
        normalized["inferredActivation"] = _normalize_inferred_activation(
            value["inferredActivation"], f"{where}.inferredActivation", normalized
        )
    return normalized


def _normalize_patch_binding(value, where):
    value = _mapping(value, where)
    _require_keys(value, where, ("primitiveId", "points"))
    primitive_id = _nonempty_string(value["primitiveId"], f"{where}.primitiveId")
    points = value["points"]
    if not isinstance(points, list):
        _fail(f"{where}.points", "must be a list")
    if not points:
        _fail(f"{where}.points", "must contain at least one point")
    normalized_points = []
    for index, point in enumerate(points):
        point_where = f"{where}.points[{index}]"
        point = _mapping(point, point_where)
        _require_keys(point, point_where, ("triangleIndex", "barycentric"))
        triangle_index = _nonnegative_integer(
            point["triangleIndex"], f"{point_where}.triangleIndex"
        )
        barycentric = _number_list(
            point["barycentric"], 3, f"{point_where}.barycentric"
        )
        for weight_index, weight in enumerate(barycentric):
            _nonnegative_number(
                weight, f"{point_where}.barycentric[{weight_index}]"
            )
        if abs(sum(float(weight) for weight in barycentric) - 1.0) > _BARYCENTRIC_SUM_TOLERANCE:
            _fail(f"{point_where}.barycentric", "must sum to 1")
        normalized_points.append(
            {"triangleIndex": triangle_index, "barycentric": barycentric}
        )
    return {"primitiveId": primitive_id, "points": normalized_points}


def _normalize_surface_estimate(value, where):
    value = _mapping(value, where)
    _require_keys(value, where, ("normal", "offsetMeters"), ("polygonWorld",))
    normal = _unit_vector3(value["normal"], f"{where}.normal")
    offset = _finite_number(value["offsetMeters"], f"{where}.offsetMeters")
    normalized = {"normal": normal, "offsetMeters": offset}
    if "polygonWorld" not in value:
        return normalized
    polygon = value["polygonWorld"]
    if not isinstance(polygon, list) or len(polygon) < 3:
        _fail(f"{where}.polygonWorld", "must be a list of at least 3 vertices")
    tolerance = _POLYGON_OFFSET_TOLERANCE * max(1.0, abs(float(offset)))
    for index, vertex in enumerate(polygon):
        vertex_where = f"{where}.polygonWorld[{index}]"
        _number_list(vertex, 3, vertex_where)
        plane_value = sum(float(n) * float(p) for n, p in zip(normal, vertex))
        if abs(plane_value - float(offset)) > tolerance:
            _fail(vertex_where, "must lie on the plane defined by normal and offsetMeters")
    normalized["polygonWorld"] = polygon
    return normalized


def _normalize_geometry_provenance(value, where):
    value = _mapping(value, where)
    if "kind" not in value:
        _fail(where, "missing required field: kind")
    kind = _nonempty_string(value["kind"], f"{where}.kind")
    if kind not in GEOMETRY_PROVENANCE_KINDS:
        _fail(
            f"{where}.kind",
            "must be inferred or calibrated; schema validation never certifies observed placement",
        )
    normalized = {"kind": kind}
    for key, item in value.items():
        if key != "kind":
            normalized[key] = _json_value(item, f"{where}.{key}")
    return normalized


def _normalize_uncertainty(value, where):
    value = _mapping(value, where)
    _require_keys(value, where, ("positionMeters", "normalRadians"))
    position = _nonnegative_number(value["positionMeters"], f"{where}.positionMeters")
    normal = _nonnegative_number(value["normalRadians"], f"{where}.normalRadians")
    return {"positionMeters": position, "normalRadians": normal}


def _normalize_visibility_adjudication(value, where):
    value = _mapping(value, where)
    _require_keys(value, where, ("receiptPath", "receiptSha256"))
    path = _nonempty_string(value["receiptPath"], f"{where}.receiptPath")
    digest = _sha256(value["receiptSha256"], f"{where}.receiptSha256")
    return {"receiptPath": path, "receiptSha256": digest}


def normalize_body_surface_contact(record):
    """Return a validated, JSON-owned version-1 contact dict or raise ValueError.

    The input is never mutated or aliased. Exact code-owned identifiers and
    source references are preserved verbatim; this function only checks shape,
    types, finiteness and internal numerical consistency. It does not claim
    that the described source evidence or geometry has been observed.
    """
    record = _mapping(record, "record")
    _require_keys(record, "record", _TOP_LEVEL_REQUIRED, _TOP_LEVEL_OPTIONAL)
    try:
        record = deepcopy(record)
    except Exception as exc:  # non-JSON values cannot be owned by the record
        raise ValueError("record: must be a JSON-compatible object") from exc

    schema_version = record["schemaVersion"]
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        _fail("record.schemaVersion", f"must be the integer {SCHEMA_VERSION}")

    contact_id = _nonempty_string(record["contactId"], "record.contactId")
    body_region = _normalize_body_region(record["bodyRegion"], "record.bodyRegion")
    contact_mode = _nonempty_string(record["contactMode"], "record.contactMode")
    if contact_mode not in CONTACT_MODES:
        _fail(
            "record.contactMode",
            f"must be one of {', '.join(CONTACT_MODES)}",
        )
    source_evidence = _normalize_source_evidence(
        record["sourceEvidence"], "record.sourceEvidence"
    )

    patch_binding = record["patchBinding"]
    if patch_binding is not None:
        patch_binding = _normalize_patch_binding(
            patch_binding, "record.patchBinding"
        )
    surface_estimate = record["surfaceEstimate"]
    if surface_estimate is not None:
        surface_estimate = _normalize_surface_estimate(
            surface_estimate, "record.surfaceEstimate"
        )
    geometry_provenance = record["geometryProvenance"]
    if geometry_provenance is not None:
        geometry_provenance = _normalize_geometry_provenance(
            geometry_provenance, "record.geometryProvenance"
        )
    if (
        patch_binding is not None or surface_estimate is not None
    ) and geometry_provenance is None:
        _fail(
            "record.geometryProvenance",
            "must be explicit when patchBinding or surfaceEstimate is present",
        )

    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "contactId": contact_id,
        "bodyRegion": body_region,
        "contactMode": contact_mode,
        "sourceEvidence": source_evidence,
        "patchBinding": patch_binding,
        "surfaceEstimate": surface_estimate,
        "geometryProvenance": geometry_provenance,
    }
    if "uncertainty" in record:
        normalized["uncertainty"] = _normalize_uncertainty(
            record["uncertainty"], "record.uncertainty"
        )
    if "visibilityAdjudication" in record:
        normalized["visibilityAdjudication"] = _normalize_visibility_adjudication(
            record["visibilityAdjudication"], "record.visibilityAdjudication"
        )
    return normalized


__all__ = [
    "CONTACT_MODES",
    "CONTACT_STATES",
    "GEOMETRY_PROVENANCE_KINDS",
    "INFERRED_ACTIVATION_KINDS",
    "REGION_SIDES",
    "SCHEMA_VERSION",
    "normalize_body_surface_contact",
]

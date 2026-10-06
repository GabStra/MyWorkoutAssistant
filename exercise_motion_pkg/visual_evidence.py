"""Localize visual claims on the delivered motion, without approving uncertainty."""
from __future__ import annotations

import math
import re
from typing import Any


DEFECT_TYPES = frozenset({"torso_twist", "limb_geometry", "tracking_discontinuity",
                         "wrong_action", "support_contradiction", "grip_contradiction",
                         "render_corruption", "unreadable"})
BODY_REGIONS = frozenset({"torso", "left_arm", "right_arm", "both_arms", "left_leg",
                         "right_leg", "both_legs", "hands", "feet", "whole_body"})


def parse_visual_observations(payload: Any, sampled_indices: list[int]) -> dict[str, Any]:
    """Optional findings have no acceptance fields, even if a model invents them."""
    result = {"advisoryOnly": True, "status": "unavailable", "findings": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        return {**result, "reason": "invalid_observation_schema"}
    allowed = set(sampled_indices)
    findings = []
    for row in payload["findings"]:
        if not isinstance(row, dict):
            continue
        indices = row.get("frameIndices")
        if (not isinstance(row.get("kind"), str)
                or row["kind"] not in {"readability", "mesh", "recognizability", "uncertain"}
                or not isinstance(row.get("observation"), str) or not row["observation"].strip()
                or not isinstance(indices, list) or not indices
                or any(type(i) is not int or i not in allowed for i in indices)):
            continue
        findings.append({"kind": row["kind"], "frameIndices": sorted(set(indices)),
                         "observation": row["observation"].strip()})
    return {**result, "status": "observed", "findings": findings,
            "discardedFindingCount": len(payload["findings"]) - len(findings),
            "note": payload.get("note") if isinstance(payload.get("note"), str) else ""}


BODY_RELATIONS = frozenset({"above", "below", "in_front_of", "behind", "near", "far_from",
                           "moving_toward", "moving_away", "moving_together", "moving_alternately",
                           "rotated_relative_to", "crossing"})
BODY_PARTS = frozenset({"head", "torso", "pelvis", "hands", "feet", "shoulders", "hips"} | {
    f"{side}_{part}" for side in ("left", "right") for part in
    ("shoulder", "elbow", "wrist", "hand", "hip", "knee", "ankle", "foot")})
MECHANICS_TAGS = frozenset({"wrong_exercise", "wrong_variant", "support_mode_mismatch",
                          "equipment_holding_pose_invalid", "gross_pose_reconstruction_error"})
# Prose is only a secondary contamination guard. The closed body-part/relation
# schema below is the primary boundary; arbitrary object names cannot enter it.
_OBJECT_WORDS = r"(?:equipment|implements?|accessor(?:y|ies)|props?|barbells?|dumbbells?|kettlebells?|bars?|bench(?:es)?|rings?|cables?|machines?|racks?|weights|loads?|resistance|straps?|handles?|plates?)"
_OBJECT_ASSERTION = re.compile(
    rf"\b{_OBJECT_WORDS}\b|\b(?:body[- ]?weight|unweighted|unloaded|weighted|loaded)\b|"
    rf"\b\d+(?:\.\d+)?\s*(?:kg|kilograms?|lb|lbs|pounds?)\b", re.IGNORECASE)



def body_only_contract() -> dict[str, Any]:
    return {"policy": "body_only", "equipmentIdentityOwner": "source_video_validation",
            "excludedFromFinalVerdict": ["equipment_presence", "equipment_type", "load_magnitude"],
            "requirementOwner": "source_confirmed_mechanics_and_deterministic_source_fidelity",
            "bodyParts": sorted(BODY_PARTS), "bodyRelations": sorted(BODY_RELATIONS)}


def body_evidence_exclusion(row: dict[str, Any]) -> str | None:
    """A model-provided basis label cannot authorize object-based judgments."""
    observation = row.get("observation")
    if (not isinstance(row.get("tag"), str) or row.get("basis") != "body_motion"
            or not isinstance(observation, str) or not observation.strip()):
        return "body_motion_evidence_unavailable"
    if _OBJECT_ASSERTION.search(observation):
        # Mixed claims must be restated independently. Do not salvage an implied
        # body requirement from a sentence whose premise is omitted equipment.
        return "equipment_assertion_outside_final_review_scope"
    if row.get("tag") in MECHANICS_TAGS:
        relation = row.get("bodyRelation")
        if (not isinstance(relation, dict)
                or set(relation) != {"subject", "reference", "relation"}
                or any(not isinstance(relation.get(key), str) for key in ("subject", "reference", "relation"))
                or relation.get("subject") not in BODY_PARTS
                or relation.get("reference") not in BODY_PARTS
                or relation.get("subject") == relation.get("reference")
                or relation.get("relation") not in BODY_RELATIONS):
            return "observable_body_relationship_missing"
    return None


def localized_claims(review: dict[str, Any]) -> list[dict[str, Any]]:
    """Only the artifact-aware interpreter can establish valid sample references."""
    return [claim for claim in review.get("localizedClaims", [])
            if isinstance(claim, dict) and claim.get("status") == "observed"]


def claims_agree(first: dict[str, Any], second: dict[str, Any], tag: str) -> bool:
    return any(a["tag"] == b["tag"] == tag
               and a["defectType"] == b["defectType"] and a["bodyRegion"] == b["bodyRegion"]
               and a.get("bodyRelation") == b.get("bodyRelation")
               and set(a["frameIndices"]) & set(b["frameIndices"])
               for a in localized_claims(first) for b in localized_claims(second))


def _axis_misalignment(frame: dict[str, Any]) -> float | None:
    joints = frame.get("joints", {})
    try:
        axes = [[joints[f"right_{part}"][i] - joints[f"left_{part}"][i]
                 for i in range(3)] for part in ("shoulder", "hip")]
        lengths = [math.sqrt(sum(v*v for v in axis)) for axis in axes]
        if min(lengths) <= 1e-8:
            return None
        cosine = sum(a*b for a, b in zip(*axes)) / math.prod(lengths)
        return math.degrees(math.acos(max(-1., min(1., cosine))))
    except (KeyError, TypeError, IndexError, ValueError):
        return None


def localize_review_evidence(
    review: dict[str, Any], export: dict[str, Any], sampled_indices: list[int],
) -> dict[str, Any]:
    """Check references and contradict a narrow skeletal claim when measurable.

    Small shoulder/hip misalignment contradicts *gross axial torso twisting*;
    it says nothing about mesh deformation or overall movement correctness.
    Large angles are not, by themselves, evidence of anatomically invalid motion.
    """
    rows = (review.get("modelPayload") or {}).get("rejectionEvidence") or []
    frames = export.get("frames") or []
    allowed = set(sampled_indices)
    claims = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if body_evidence_exclusion(row) is not None:
            continue
        indices = row.get("frameIndices")
        if (row.get("basis") != "body_motion" or row.get("defectType") not in DEFECT_TYPES
                or row.get("bodyRegion") not in BODY_REGIONS
                or not isinstance(row.get("observation"), str) or not row["observation"].strip()
                or not isinstance(indices, list) or not indices
                or any(type(i) is not int or i not in allowed or not 0 <= i < len(frames) for i in indices)):
            continue
        claim = {**row, "frameIndices": sorted(set(indices)), "status": "observed"}
        if row["defectType"] == "torso_twist":
            angles = [_axis_misalignment(frames[i]) for i in indices]
            if any(angle is None or not math.isfinite(angle) for angle in angles):
                claim["status"] = "unavailable"
            elif max(angles) < 15.:
                claim.update(status="contradicted", maximumAxisMisalignmentDegrees=max(angles))
        claims.append(claim)
    result = {**review, "localizedClaims": claims}
    observed = [claim for claim in claims if claim["status"] == "observed"]
    if observed and all(claim["defectType"] in {"render_corruption", "unreadable"} for claim in observed):
        result.update(failureOwner="rendering", underlyingMotionRejected=False)
    return result


def diagnostic_frame_indices(review: dict[str, Any], frame_count: int, *, limit: int = 16) -> list[int]:
    """Bound dense evidence around supplied events; preserve claimed samples first."""
    anchors = sorted({i for claim in review.get("localizedClaims", []) for i in claim["frameIndices"]})
    anchor_limit = max(1, limit // 4)
    if len(anchors) > anchor_limit:
        anchors = [anchors[round(i * (len(anchors)-1) / max(1, anchor_limit-1))] for i in range(anchor_limit)]
    selected = set(anchors)
    for offset in (-1, 1, -2, 2):
        for index in anchors:
            if len(selected) < limit and 0 <= index + offset < frame_count:
                selected.add(index + offset)
    return sorted(selected)

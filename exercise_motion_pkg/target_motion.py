from __future__ import annotations

import re
from typing import Any


TARGET_MOTION_PREFILTER_BLOCKING_ISSUE = "low_target_motion_observability"
TARGET_MOTION_MATERIALIZED_REJECTION_REASON = "materialized_low_target_motion_observability"
HINGED_UPPER_LIMB_PULL_PROFILE_KEY = "hinged_upper_limb_pull"
SUPPORTED_TARGET_MOTION_PROFILE_KEYS = {
    "distal_leg_vertical_raise",
    HINGED_UPPER_LIMB_PULL_PROFILE_KEY,
}
DISTAL_LEG_VERTICAL_RAISE_PROFILE_KEY = "distal_leg_vertical_raise"
OBSERVABLE_MOTION_PATTERN_VALUES = {
    "joint_travel",
    "body_toward_anchor",
    "body_away_from_anchor",
    "limb_toward_body",
    "limb_away_from_body",
    "distal_limb_vertical",
    "joint_flex_extend",
    "other",
}
OBSERVABLE_MOTION_AXIS_VALUES = {"vertical", "horizontal", "depth", "any"}
OBSERVABLE_MOTION_REGION_ALIASES = {
    "arm": "upper_limb",
    "arms": "upper_limb",
    "upper arm": "upper_limb",
    "upper arms": "upper_limb",
    "upper limb": "upper_limb",
    "upper limbs": "upper_limb",
    "hand": "hands",
    "hands": "hands",
    "wrist": "hands",
    "wrists": "hands",
    "elbow": "elbows",
    "elbows": "elbows",
    "shoulder": "shoulders",
    "shoulders": "shoulders",
    "torso": "torso",
    "chest": "torso",
    "rib": "torso",
    "ribs": "torso",
    "abdomen": "torso",
    "trunk": "torso",
    "body": "torso",
    "head": "head",
    "neck": "head",
    "hip": "hips",
    "hips": "hips",
    "pelvis": "hips",
    "leg": "lower_limb",
    "legs": "lower_limb",
    "lower limb": "lower_limb",
    "lower limbs": "lower_limb",
    "knee": "knees",
    "knees": "knees",
    "ankle": "feet",
    "ankles": "feet",
    "foot": "feet",
    "feet": "feet",
    "heel": "feet",
    "heels": "feet",
    "toe": "feet",
    "toes": "feet",
    "bar": "hands",
    "barbell": "hands",
    "dumbbell": "hands",
    "dumbbells": "hands",
    "kettlebell": "hands",
    "kettlebells": "hands",
    "handle": "hands",
    "handles": "hands",
    "pull up bar": "hands",
    "pull-up bar": "hands",
    "floor": "feet",
    "ground": "feet",
}


def normalize_target_motion_profile_key(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if not text or text == "none":
        return None
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if key in SUPPORTED_TARGET_MOTION_PROFILE_KEYS:
        return key
    return None


def normalize_observable_motion_spec(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    primary_regions = normalize_observable_motion_regions(value.get("primaryMovingRegions"), limit=8)
    reference_regions = normalize_observable_motion_regions(value.get("referenceRegions"), limit=8)
    visible_regions = normalize_observable_motion_regions(value.get("mustBeVisibleRegions"), limit=8)
    axis = normalize_observable_motion_axis(value.get("primaryAxis"))
    pattern = normalize_observable_motion_pattern(value.get("motionPattern"))
    pattern = normalize_joint_center_motion_pattern(
        pattern,
        primary_regions=primary_regions,
    )
    requires_return = parse_contract_bool(value.get("requiresReturnToStart"))
    one_way_invalid = parse_contract_bool(value.get("oneWayPartialIsInvalid"))
    must_show_full_cycle = parse_contract_bool(value.get("mustShowFullCycle"))
    if not primary_regions and not reference_regions and axis == "any" and pattern == "other":
        return None
    return {
        "schemaVersion": 1,
        "primaryMovingRegions": primary_regions,
        "referenceRegions": reference_regions,
        "primaryAxis": axis,
        "motionPattern": pattern,
        "requiresReturnToStart": requires_return if requires_return is not None else True,
        "oneWayPartialIsInvalid": one_way_invalid if one_way_invalid is not None else True,
        "mustShowFullCycle": must_show_full_cycle if must_show_full_cycle is not None else True,
        "mustBeVisibleRegions": visible_regions,
    }


def normalize_joint_center_motion_pattern(
    pattern: str,
    *,
    primary_regions: list[str] | tuple[str, ...],
) -> str:
    """Use joint angle for hinge-joint targets whose centers should stay anchored.

    Small generated contracts sometimes describe an elbow or knee action as
    ``joint_travel``. That is the wrong observable for extensions/curls: the
    joint center can remain nearly stationary while the distal limb rotates.
    A contract that names only hinge joints therefore owns flexion/extension
    evidence regardless of that model wording error.
    """

    primary = {str(region) for region in primary_regions if str(region)}
    if pattern == "joint_travel" and primary and primary.issubset({"elbows", "knees"}):
        return "joint_flex_extend"
    return pattern


def observable_motion_spec_for_contract(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(contract, dict):
        return None
    spec = normalize_observable_motion_spec(contract.get("observableMotionSpec"))
    if spec is not None:
        return spec
    explicit_requires_return = parse_contract_bool(contract.get("requiresReturnToStart"))
    explicit_one_way_invalid = parse_contract_bool(contract.get("oneWayPartialIsInvalid"))
    explicit_must_show_full_cycle = parse_contract_bool(contract.get("mustShowFullCycle"))
    if explicit_requires_return is not None:
        if explicit_one_way_invalid is None:
            explicit_one_way_invalid = explicit_requires_return
        if explicit_must_show_full_cycle is None:
            explicit_must_show_full_cycle = explicit_requires_return
    spec_payload = {
        "primaryMovingRegions": contract.get("primaryMovingRegions") or contract.get("primaryMotionRegions"),
        "referenceRegions": contract.get("referenceRegions"),
        "primaryAxis": contract.get("primaryAxis"),
        "motionPattern": contract.get("motionPattern"),
        "requiresReturnToStart": explicit_requires_return,
        "oneWayPartialIsInvalid": explicit_one_way_invalid,
        "mustShowFullCycle": explicit_must_show_full_cycle,
        "mustBeVisibleRegions": contract.get("mustBeVisibleRegions") or contract.get("mustBeVisible"),
    }
    return normalize_observable_motion_spec(spec_payload)


def observable_target_motion_range(
    *,
    primary_motion_range: float,
    relative_motion_range: float,
    flexion_range: float = 0.0,
    reference_regions: list[str] | tuple[str, ...] | None,
    motion_pattern: str,
) -> float:
    """Select motion that proves the contract relationship, not incidental travel.

    When a contract names a reference region, absolute movement can come from
    camera/root translation and is not sufficient evidence of the exercise.
    Flexion remains valid for a flex/extend contract because it is inherently
    body-relative. Without a reference, absolute joint travel is the available
    observable signal.
    """
    flexion_evidence = flexion_range if motion_pattern == "joint_flex_extend" else 0.0
    if reference_regions:
        return max(relative_motion_range, flexion_evidence)
    return max(primary_motion_range, flexion_evidence)


def contract_plain_text_for_return_detection(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return ""

    parts: list[str] = []

    def add_text(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                parts.append(text)
            return
        if isinstance(value, list):
            for item in value:
                add_text(item)
            return
        if isinstance(value, dict):
            for nested_key in (
                "advisoryText",
                "guidance",
                "text",
                "contract",
                "plainText",
                "movementType",
                "requiresReturnToStart",
                "validStartState",
                "validEndState",
                "boundaryRule",
                "allowedExerciseTransitions",
                "excludedSetupOrCleanup",
                "Source",
                "Complete",
                "Boundary",
                "Reject",
                "Notes",
                "source",
                "complete",
                "boundary",
                "reject",
                "notes",
                "requiredPhases",
                "reviewNotes",
            ):
                add_text(value.get(nested_key))

    for key in (
        "advisoryText",
        "guidance",
        "text",
        "contract",
        "plainText",
        "movementType",
        "requiresReturnToStart",
        "validStartState",
        "validEndState",
        "boundaryRule",
        "allowedExerciseTransitions",
        "excludedSetupOrCleanup",
        "Source",
        "Complete",
        "Boundary",
        "Reject",
        "Notes",
        "source",
        "complete",
        "boundary",
        "reject",
        "notes",
        "requiredPhases",
        "reviewNotes",
    ):
        add_text(contract.get(key))

    return "\n".join(parts)


def plain_text_contract_requires_return(contract: dict[str, Any] | None) -> bool:
    text = contract_plain_text_for_return_detection(contract)
    if not text:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    if not normalized:
        return False
    return any(
        re.search(pattern, normalized) is not None
        for pattern in (
            r"\breturn(?:s|ed|ing)?(?:\s+back)?\s+to\s+(?:the\s+)?(?:start|starting|initial|original)\b",
            r"\bback\s+to\s+(?:the\s+)?(?:start|starting|initial|original)\b",
            r"\bfinish(?:es|ed|ing)?\s+(?:back\s+)?(?:at|in)\s+(?:the\s+)?(?:start|starting|initial|original)\b",
            r"\bfull\s+cycle\b",
            r"\bcomplete\s+cycle\b",
            r"\bforward\s+and\s+backward\b",
            r"\bbackward\s+and\s+forward\b",
            r"\bback\s+and\s+forth\b",
            r"\bforth\s+and\s+back\b",
            r"\baway\s+from\s+(?:the\s+)?body\s+and\s+(?:back|toward)\b",
            r"\btoward\s+(?:the\s+)?body\s+and\s+away\b",
            r"\bone\s+way\s+(?:partial|fragment|movement|only)\b",
            r"\bonly\s+(?:the\s+)?(?:forward|backward|return|lowering|raising|descent|ascent|pull|push|roll)\b",
        )
    )


def observable_motion_spec_requires_return(contract: dict[str, Any] | None) -> bool:
    if isinstance(contract, dict):
        explicit_requires_return = parse_contract_bool(contract.get("requiresReturnToStart"))
        if explicit_requires_return is not None:
            return explicit_requires_return
        movement_type = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(contract.get("movementType") or "").strip().casefold(),
        ).strip("_")
        if movement_type in {"hold", "carry", "transition_sequence"}:
            return False
        if movement_type in {"repetition", "cyclic"}:
            return True
    spec = observable_motion_spec_for_contract(contract)
    if spec is not None and (
        bool(spec.get("requiresReturnToStart"))
        or bool(spec.get("oneWayPartialIsInvalid"))
    ):
        return True
    return plain_text_contract_requires_return(contract)



def observable_motion_spec_mentions_lower_body(contract: dict[str, Any] | None) -> bool:
    spec = observable_motion_spec_for_contract(contract)
    if spec is None:
        return False
    lower_body_regions = {"lower_limb", "hips", "knees", "feet"}
    regions = {
        str(region)
        for key in ("primaryMovingRegions", "referenceRegions", "mustBeVisibleRegions")
        for region in spec.get(key, [])
    }
    return bool(regions.intersection(lower_body_regions))


def normalize_observable_motion_regions(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    regions: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        region = normalize_observable_motion_region(item)
        if region is None or region in seen:
            continue
        regions.append(region)
        seen.add(region)
        if len(regions) >= limit:
            break
    return regions


def normalize_observable_motion_region(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().casefold()).strip()
    if not text:
        return None
    if text in OBSERVABLE_MOTION_REGION_ALIASES:
        return OBSERVABLE_MOTION_REGION_ALIASES[text]
    tokens = set(text.split())
    if tokens.intersection({"wrist", "wrists", "hand", "hands", "bar", "barbell", "handle", "handles"}):
        return "hands"
    if tokens.intersection({"elbow", "elbows"}):
        return "elbows"
    if tokens.intersection({"shoulder", "shoulders"}):
        return "shoulders"
    if tokens.intersection({"torso", "trunk", "chest", "rib", "ribs", "abdomen", "body"}):
        return "torso"
    if tokens.intersection({"hip", "hips", "pelvis"}):
        return "hips"
    if tokens.intersection({"knee", "knees"}):
        return "knees"
    if tokens.intersection({"ankle", "ankles", "foot", "feet", "heel", "heels", "toe", "toes"}):
        return "feet"
    if tokens.intersection({"leg", "legs"}):
        return "lower_limb"
    if tokens.intersection({"arm", "arms"}):
        return "upper_limb"
    if tokens.intersection({"head", "neck"}):
        return "head"
    return None


def normalize_observable_motion_axis(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "up": "vertical",
        "down": "vertical",
        "up_down": "vertical",
        "vertical_motion": "vertical",
        "side": "horizontal",
        "side_to_side": "horizontal",
        "left_right": "horizontal",
        "forward_backward": "depth",
        "front_back": "depth",
        "toward_away": "depth",
    }
    key = aliases.get(key, key)
    return key if key in OBSERVABLE_MOTION_AXIS_VALUES else "any"


def normalize_observable_motion_pattern(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "toward_anchor": "body_toward_anchor",
        "away_from_anchor": "body_away_from_anchor",
        "limb_to_body": "limb_toward_body",
        "limb_from_body": "limb_away_from_body",
        "distal_vertical": "distal_limb_vertical",
        "flexion_extension": "joint_flex_extend",
        "flex_extend": "joint_flex_extend",
        "joint_flexion": "joint_flex_extend",
    }
    key = aliases.get(key, key)
    return key if key in OBSERVABLE_MOTION_PATTERN_VALUES else "other"


def parse_contract_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().casefold()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def target_motion_profile_for_exercise(
    exercise_name: str | None,
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del exercise_name
    contract_profile = (
        normalize_target_motion_profile_key(contract.get("targetMotionProfile"))
        if isinstance(contract, dict)
        else None
    )
    if contract_profile == DISTAL_LEG_VERTICAL_RAISE_PROFILE_KEY:
        return distal_leg_vertical_raise_profile()
    if (
        contract_profile == HINGED_UPPER_LIMB_PULL_PROFILE_KEY
        and contract_text_implies_hinged_upper_limb_pull(contract)
    ):
        return hinged_upper_limb_pull_profile()
    if contract is not None and contract_text_implies_distal_leg_vertical_raise(contract):
        return distal_leg_vertical_raise_profile()
    if contract is not None and contract_text_implies_hinged_upper_limb_pull(contract):
        return hinged_upper_limb_pull_profile()
    return None


def distal_leg_vertical_raise_profile() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "profile": "distal_leg_vertical_raise",
        "target": "distal_leg_vertical_raise",
        "description": "Requires visible vertical travel of the foot, heel, or ankle relative to the lower leg.",
        "requiredPoseJoints": [
            "left_hip",
            "right_hip",
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
        ],
        "requiredSkeletonJoints": [
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
            "left_foot",
            "right_foot",
        ],
        "minPoseRequiredJointVisibility": 0.68,
        "minPoseDistalVerticalRangeRatio": 0.035,
        "minPoseDistalRelativeVerticalRangeRatio": 0.025,
        "minSkeletonDistalVerticalRangeRatio": 0.035,
        "minSkeletonDistalArticulationRangeRatio": 0.025,
        "targetMotionDominanceMetricKeys": [
            "distalVerticalRangeRatio",
            "distalArticulationRangeRatio",
            "lowerBodyDistalRootRelativeRangeRatio",
        ],
        "nonTargetMotionDominanceRules": [
            {
                "metricKey": "upperBodyRootRelativeRangeRatio",
                "failureReason": "non_target_motion_dominates_target_motion",
                "minRangeRatio": 0.18,
                "maxRatioToTargetMotion": 1.75,
            }
        ],
    }


def hinged_upper_limb_pull_profile() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "profile": HINGED_UPPER_LIMB_PULL_PROFILE_KEY,
        "target": HINGED_UPPER_LIMB_PULL_PROFILE_KEY,
        "description": "Requires a visibly hinged torso and upper-limb pull toward the torso.",
        "requiredSkeletonJoints": [
            "pelvis",
            "neck",
            "left_shoulder",
            "right_shoulder",
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hand",
            "right_hand",
        ],
        "minSkeletonTorsoLeanDegrees": 20.0,
        "minSkeletonHandTorsoDistanceRangeRatio": 0.04,
        "minSkeletonElbowFlexionRangeRatio": 0.08,
        "targetMotionDominanceMetricKeys": [
            "handTorsoDistanceRangeRatio",
            "elbowFlexionRangeRatio",
        ],
    }


def target_motion_profile_text(
    exercise_name: str | None,
    *,
    contract: dict[str, Any] | None = None,
    keys: tuple[str, ...] | None = None,
) -> str:
    del exercise_name
    parts: list[str] = []
    if isinstance(contract, dict):
        for key in keys or (
            "requiredStartPosture",
            "requiredEndPosture",
            "requiredPhases",
            "primaryMotionRegions",
            "mustBeVisible",
            "reviewNotes",
        ):
            value = contract.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value)
    return " ".join(parts).casefold()


def contract_text_implies_distal_leg_vertical_raise(contract: dict[str, Any]) -> bool:
    distal_lower_leg_terms = {
        "ankle",
        "ankles",
        "foot",
        "feet",
        "heel",
        "heels",
        "toe",
        "toes",
    }
    vertical_raise_terms = {
        "elevate",
        "elevates",
        "elevated",
        "lift",
        "lifts",
        "lifted",
        "raise",
        "raises",
        "raised",
        "rise",
        "rises",
        "rising",
        "up",
        "upward",
        "vertical",
    }
    primary_text = target_motion_profile_text(
        None,
        contract=contract,
        keys=("primaryMotionRegions",),
    )
    motion_text = target_motion_profile_text(
        None,
        contract=contract,
        keys=("requiredPhases", "reviewNotes"),
    )
    primary_tokens = set(re.findall(r"[a-z0-9]+", primary_text))
    motion_tokens = set(re.findall(r"[a-z0-9]+", motion_text))
    motion_has_distal_raise = bool(motion_tokens.intersection(distal_lower_leg_terms)) and bool(
        motion_tokens.intersection(vertical_raise_terms)
    )
    primary_names_distal_target = bool(primary_tokens.intersection(distal_lower_leg_terms)) and bool(
        motion_tokens.intersection(vertical_raise_terms)
    )
    return motion_has_distal_raise or primary_names_distal_target


def contract_text_implies_hinged_upper_limb_pull(contract: dict[str, Any]) -> bool:
    text = target_motion_profile_text(None, contract=contract)
    motion_text = target_motion_profile_text(
        None,
        contract=contract,
        keys=("requiredPhases", "mustBeVisible", "reviewNotes"),
    )
    tokens = set(re.findall(r"[a-z0-9]+", text))
    motion_tokens = set(re.findall(r"[a-z0-9]+", motion_text))
    hinged = bool(
        re.search(
            r"\b(hinge|hinged|bent\s+over|forward\s+at\s+the\s+hips|torso\s+(?:forward|leaned|inclined))\b",
            text,
        )
    )
    upper_limb_terms = {
        "arm",
        "arms",
        "elbow",
        "elbows",
        "wrist",
        "wrists",
        "hand",
        "hands",
        "barbell",
        "dumbbell",
        "handle",
        "handles",
    }
    pull_terms = {
        "pull",
        "pulls",
        "pulled",
        "pulling",
        "draw",
        "draws",
        "drawn",
        "rowing",
        "toward",
        "towards",
    }
    torso_target_terms = {
        "torso",
        "rib",
        "ribs",
        "chest",
        "abdomen",
        "abdominal",
        "midsection",
        "waist",
    }
    return (
        hinged
        and bool(tokens.intersection(upper_limb_terms))
        and bool(motion_tokens.intersection(pull_terms))
        and bool(motion_tokens.intersection(torso_target_terms))
    )

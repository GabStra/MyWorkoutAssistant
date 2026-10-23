"""Advisory LLM critic for generated exercise-motion contracts.

The critic records semantic suggestions for diagnostics. Its output is not
source evidence and cannot establish new movement requirements or trigger
repairs of a usable contract. Parsing constrains suggestions to the existing
field vocabulary; deterministic validation remains the repair authority.
"""
from __future__ import annotations

import json
from typing import Any, Callable


CONTRACT_CRITIC_PROMPT_MARKER = "semantic consistency review"
MAX_CONTRACT_CRITIC_ISSUES = 3
CONTRACT_CRITIC_MAX_TOKENS = 1536

TEXT_FIELD_MIN_CHARS = 12
TEXT_FIELD_MAX_CHARS = 280

POSE_CONSTRAINT_ENUMS: dict[str, tuple[str, ...]] = {
    "supportMode": ("standing", "seated", "lying", "kneeling", "hanging", "any"),
    "handHeight": ("above_head", "shoulder_chest", "hip", "below_hips", "any"),
    "torsoOrientation": ("upright", "hinged", "horizontal", "any"),
    "kneeState": ("extended", "flexed", "deep_flexion", "any"),
    "stance": ("narrow", "shoulder_width", "wide", "split", "any"),
}

# Replace-only patch surface. ``None`` marks bounded free-text posture
# sentences; every other field only accepts values from its closed enum.
PATCHABLE_CONTRACT_FIELDS: dict[str, tuple[str, ...] | None] = {
    "movementType": ("repetition", "cyclic", "hold", "carry", "transition_sequence", "unknown"),
    "completionMode": (
        "return_to_start",
        "distinct_end_state",
        "stable_hold",
        "active_travel",
        "representative_cycle",
        "alternating_pair",
    ),
    "requiresReturnToStart": ("true", "false"),
    "groundContactMode": ("continuous", "intermittent", "none"),
    "implementSupportMode": ("hands_only", "body_supported", "mixed", "external", "none"),
    "handRelationship": ("rigid_pair", "independent", "single", "none", "unknown"),
    "validStartState": None,
    "validEndState": None,
    "requiredPhases": None,
    **{f"startPoseConstraints.{key}": values for key, values in POSE_CONSTRAINT_ENUMS.items()},
    **{f"endPoseConstraints.{key}": values for key, values in POSE_CONSTRAINT_ENUMS.items()},
}


def contract_critic_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """The critic only needs the fields it can reason about and patch."""
    if contract.get("contractScope") == "definition_only":
        keys = (
            "movementType",
            "completionMode",
            "requiresReturnToStart",
            "groundContactMode",
            "implementSupportMode",
            "handRelationship",
            "definingAction",
            "variantQualifiers",
            "motionContext",
            "primaryMovingRegions",
            "referenceRegions",
        )
    else:
        keys = (
            "movementType",
            "completionMode",
            "requiresReturnToStart",
            "groundContactMode",
            "implementSupportMode",
            "handRelationship",
            "validStartState",
            "validEndState",
            "startPoseConstraints",
            "endPoseConstraints",
            "requiredPhases",
            "singleExecutionDurationSeconds",
            "motionContext",
            "primaryMovingRegions",
            "referenceRegions",
        )
    projection: dict[str, Any] = {}
    for key in keys:
        value = contract.get(key)
        if value is not None:
            projection[key] = value
    return projection


def build_contract_critic_prompt(
    *,
    exercise_name: str,
    equipment: str | None,
    contract: dict[str, Any],
) -> str:
    if contract.get("contractScope") == "definition_only":
        fields = (
            "movementType", "completionMode", "requiresReturnToStart",
            "groundContactMode", "implementSupportMode", "handRelationship",
        )
        allowed = "; ".join(
            f"{field}: {', '.join(PATCHABLE_CONTRACT_FIELDS[field] or ())}"
            for field in fields if field in contract
        )
        return (
            f"{CONTRACT_CRITIC_PROMPT_MARKER}: check definition-level exercise requirements.\n"
            f"Exercise request: {exercise_name}"
            + (f" (equipment: {equipment})" if equipment else "")
            + "\nContract: "
            + json.dumps(contract_critic_projection(contract), ensure_ascii=False)
            + "\nCheck only concrete contradictions between the exercise definition, equipment, "
            "movement type, completion boundary, broad body action, and implement relationship. "
            "No source video has been seen; do not invent posture, contacts, or phase detail. "
            "Return minified JSON only: "
            '{"issues":[{"field":"<field>","value":"<corrected value>",'
            '"evidence":"<short reason>"}]}. '
            f"At most {MAX_CONTRACT_CRITIC_ISSUES} issues. Allowed fields and values: {allowed}. "
            'Return {"issues":[]} when consistent.\n'
        )
    allowed = "; ".join(
        f"{field}: {', '.join(values)}" if values else (
            f"{field}: array of corrected short phase sentences" if field == "requiredPhases"
            else f"{field}: corrected short posture sentence")
        for field, values in PATCHABLE_CONTRACT_FIELDS.items()
    )
    return (
        f"{CONTRACT_CRITIC_PROMPT_MARKER}: validate this structured exercise movement contract.\n"
        f"Exercise request: {exercise_name}"
        + (f" (equipment: {equipment})" if equipment else "")
        + "\nContract:\n"
        + json.dumps(contract_critic_projection(contract), ensure_ascii=False)
        + "\nThe original exercise name and supplied equipment/accessories are the immutable target definition. "
        "Do not replace a supplied variant with a more common version or infer accessory contacts from its name. "
        "Review only concrete contradictions between the structured fields, defining action and that target. "
        "Do not treat internally consistent states and phases as authority to redefine the requested exercise.\n"
        "A required accessory does not establish which body part contacts it. Lying means pelvis and upper back "
        "resting on a surface, not just a horizontal torso. Hands-and-feet support with a suspended torso uses "
        "supportMode any; torsoOrientation describes its pose. Prioritize false supportMode and torsoOrientation "
        "requirements over wording corrections.\n"
        "Check that the structured fields agree with the movement the required phases and states actually describe:\n"
        "Report semantic errors, not stylistic shortening or values already correct. Prioritize incorrect actions, "
        "equipment relationships and contacts over wording corrections.\n"
        "- rigid_pair means both hands on the same rigid implement, not two separate implements. "
        "implementSupportMode describes one rigid two-hand implement; separate implements or single-hand use "
        "use none. Do not infer a rigid pair from bilateral movement.\n"
        "- If the phases travel or advance to a new position (stepping or walking forward, a carry distance, "
        "moving between positions), completionMode must not be return_to_start unless a phase explicitly "
        "returns to the exact starting position; prefer distinct_end_state or active_travel.\n"
        "- A hold uses stable_hold; a carry uses active_travel; a transition sequence ends in a distinct state.\n"
        "- requiresReturnToStart is true only for return_to_start.\n"
        "- The end state must describe where the phases actually finish and must differ from the start state "
        "when completionMode is distinct_end_state.\n"
        "- Start and end pose constraints must match the described postures.\n"
        "- requiredPhases must describe exactly one execution, not multiple repetitions. Do not make optional "
        "pauses, coaching cues, or setup into required action phases. To correct phases, return their complete "
        "replacement array of short strings, not a placeholder or a sentence saying they need correction.\n"
        "A correction must identify a concrete contradiction or missing defining action, not a preference for conventional technique. "
        "Only report clear semantic contradictions with the described movement; do not invent requirements "
        "and do not judge exercise quality or difficulty.\n"
        "Return minified JSON only with this schema: "
        '{"issues": [{"field": "<field>", "value": "<corrected value>", '
        '"evidence": "<short reason>"}]}\n'
        "Do not echo the old value or include a from field. Keep text values under 160 characters and "
        "evidence under 80 characters so the complete JSON fits the response budget.\n"
        "Allowed fields and values: "
        + allowed
        + "\n"
        f"At most {MAX_CONTRACT_CRITIC_ISSUES} issues. Return "
        + '{"issues": []}'
        + " when the contract is consistent.\n"
    )


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def _coerce_patch_value(field: str, value: Any) -> Any:
    if field == "requiresReturnToStart":
        if isinstance(value, bool):
            return value
        return _value_text(value) == "true"
    return value


def parse_contract_critic_issues(raw: Any) -> list[dict[str, Any]] | None:
    """Validate a critic response into whitelist-constrained patch issues.

    Returns None when the response is not a JSON object with an ``issues``
    list (the caller retries once); an empty list means the contract was
    judged consistent.
    """
    payload = raw if isinstance(raw, dict) else _parse_json_object(raw if isinstance(raw, str) else "")
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        return None
    parsed: list[dict[str, Any]] = []
    for item in payload["issues"]:
        if not isinstance(item, dict):
            continue
        if len(parsed) >= MAX_CONTRACT_CRITIC_ISSUES:
            break
        field = str(item.get("field") or "").strip()
        if field not in PATCHABLE_CONTRACT_FIELDS:
            continue
        allowed = PATCHABLE_CONTRACT_FIELDS[field]
        if field == "requiredPhases":
            phases = item.get("value")
            if not isinstance(phases, list) or not 1 <= len(phases) <= 8 or any(
                not isinstance(phase, str) or not TEXT_FIELD_MIN_CHARS <= len(phase.strip()) <= TEXT_FIELD_MAX_CHARS
                for phase in phases
            ):
                return None
            normalized_value = [phase.strip() for phase in phases]
        elif allowed is None:
            text_value = str(item.get("value") or "").strip()
            if not TEXT_FIELD_MIN_CHARS <= len(text_value) <= TEXT_FIELD_MAX_CHARS:
                continue
            normalized_value: object = text_value
        else:
            normalized_value = _value_text(item.get("value"))
            if normalized_value not in allowed:
                continue
        evidence = str(item.get("evidence") or "").strip()
        if not evidence:
            return None
        issue: dict[str, Any] = {
            "field": field,
            "value": normalized_value,
            "evidence": evidence[:TEXT_FIELD_MAX_CHARS],
        }
        from_text = item.get("from")
        if from_text is not None and str(from_text).strip():
            issue["from"] = str(from_text).strip()
        parsed.append(issue)
    return parsed


def apply_contract_critic_patches(
    contract: dict[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply replace-only patches; drop stale or inapplicable operations."""
    patched = dict(contract)
    applied: list[dict[str, Any]] = []
    for issue in issues:
        field = str(issue.get("field") or "")
        keys = field.split(".")
        target: dict[str, Any] = patched
        walked = True
        for key in keys[:-1]:
            nested = target.get(key)
            if not isinstance(nested, dict) or keys[-1] not in nested:
                walked = False
                break
            nested = dict(nested)
            target[key] = nested
            target = nested
        if not walked:
            continue
        current = target.get(keys[-1])
        if current is None:
            continue
        claimed_from = issue.get("from")
        if claimed_from and _value_text(current) != _value_text(claimed_from):
            continue
        coerced = _coerce_patch_value(field, issue["value"])
        if current == coerced:
            continue
        target[keys[-1]] = coerced
        recorded = dict(issue)
        recorded["value"] = coerced
        applied.append(recorded)
    return patched, applied


def critique_exercise_motion_contract(
    *,
    exercise_name: str,
    equipment: str | None,
    contract: dict[str, Any],
    caption_images: Callable[..., str],
    caption_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run an advisory critic call, with one bounded malformed-response retry."""
    prompt = build_contract_critic_prompt(
        exercise_name=exercise_name,
        equipment=equipment,
        contract=contract,
    )
    kwargs: dict[str, Any] = {
        **(caption_kwargs or {}),
        "frame_paths": [],
        "prompt": prompt,
        "max_tokens": CONTRACT_CRITIC_MAX_TOKENS,
    }
    for _ in range(2):
        raw = caption_images(**kwargs)
        parsed = parse_contract_critic_issues(raw)
        if parsed is not None:
            if contract.get("contractScope") == "definition_only":
                parsed = [issue for issue in parsed if issue["field"] in contract]
            return parsed
    raise ValueError("Contract critic returned malformed advice after two attempts.")

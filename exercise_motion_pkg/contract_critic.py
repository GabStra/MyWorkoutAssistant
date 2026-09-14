"""Advisory LLM critic for generated exercise-motion contracts.

Deterministic contract validation can only reject contracts that contradict
themselves; a regenerated contract can be internally consistent and still
semantically wrong for the requested movement (for example a traveling
lunge described as returning to its exact start). The critic reads the
contract's own phases and states, flags such contradictions structurally,
and returns replace-only patch operations constrained to a closed field
whitelist. Applying the patch, re-normalizing, and re-validating the
contract stay in deterministic code; the critic never invents fields or
values outside the vocabulary.
"""
from __future__ import annotations

import json
from typing import Any, Callable


CONTRACT_CRITIC_PROMPT_MARKER = "semantic consistency review"
MAX_CONTRACT_CRITIC_ISSUES = 3
CONTRACT_CRITIC_MAX_TOKENS = 384

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
    "handRelationship": ("rigid_pair", "independent", "single", "none", "unknown"),
    "validStartState": None,
    "validEndState": None,
    **{f"startPoseConstraints.{key}": values for key, values in POSE_CONSTRAINT_ENUMS.items()},
    **{f"endPoseConstraints.{key}": values for key, values in POSE_CONSTRAINT_ENUMS.items()},
}


def contract_critic_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """The critic only needs the fields it can reason about and patch."""
    keys = (
        "movementType",
        "completionMode",
        "requiresReturnToStart",
        "groundContactMode",
        "handRelationship",
        "validStartState",
        "validEndState",
        "startPoseConstraints",
        "endPoseConstraints",
        "requiredPhases",
        "singleExecutionDurationSeconds",
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
    allowed = "; ".join(
        f"{field}: {', '.join(values)}" if values else f"{field}: corrected short posture sentence"
        for field, values in PATCHABLE_CONTRACT_FIELDS.items()
    )
    return (
        f"{CONTRACT_CRITIC_PROMPT_MARKER}: validate this structured exercise movement contract.\n"
        f"Exercise request: {exercise_name}"
        + (f" (equipment: {equipment})" if equipment else "")
        + "\nContract:\n"
        + json.dumps(contract_critic_projection(contract), ensure_ascii=False)
        + "\nCheck that the structured fields agree with the movement the required phases and states actually describe:\n"
        "- If the phases travel or advance to a new position (stepping or walking forward, a carry distance, "
        "moving between positions), completionMode must not be return_to_start unless a phase explicitly "
        "returns to the exact starting position; prefer distinct_end_state or active_travel.\n"
        "- A hold uses stable_hold; a carry uses active_travel; a transition sequence ends in a distinct state.\n"
        "- requiresReturnToStart is true only for return_to_start.\n"
        "- The end state must describe where the phases actually finish and must differ from the start state "
        "when completionMode is distinct_end_state.\n"
        "- Start and end pose constraints must match the described postures.\n"
        "Only report clear semantic contradictions with the described movement; do not invent requirements "
        "and do not judge exercise quality or difficulty.\n"
        "Return minified JSON only with this schema: "
        '{"issues": [{"field": "<field>", "from": "<current value>", "value": "<corrected value>", '
        '"evidence": "<short reason quoting the contract>"}]}\n'
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
        if allowed is None:
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
            continue
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
        target[keys[-1]] = coerced
        recorded = dict(issue)
        recorded["value"] = coerced
        applied.append(recorded)
    return patched, applied


def critic_issue_validation_texts(issues: list[dict[str, Any]]) -> list[str]:
    """Format critic ops for the existing repair-prompt validation-issues list."""
    texts: list[str] = []
    for issue in issues:
        field = str(issue.get("field") or "").strip()
        value = issue.get("value")
        evidence = str(issue.get("evidence") or "").strip()
        claimed_from = issue.get("from")
        if claimed_from is not None and str(claimed_from).strip():
            texts.append(
                f"critic: {field} from {claimed_from} -> {value}: {evidence}"
            )
        else:
            texts.append(f"critic: {field} -> {value}: {evidence}")
    return texts


def critique_exercise_motion_contract(
    *,
    exercise_name: str,
    equipment: str | None,
    contract: dict[str, Any],
    caption_images: Callable[..., str],
    caption_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run one advisory critic call; retry once on malformed JSON; [] on skip."""
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
            return parsed
    return []

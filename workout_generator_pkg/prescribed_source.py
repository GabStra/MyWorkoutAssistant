"""Strict source adapter for an already-prescribed workout plan."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .api_client import chat_call
from .plan_contract import validate_plan_index_contract
from .prescribed_recurrence import (
    LOAD_HISTORY_POLICY,
    PRESCRIPTION_LABEL,
    PRESCRIPTION_ORDINAL,
    RECURRING_EXERCISE_KEY,
    RECURRING_PROGRAM_KEY,
    RECURRING_SESSION_KEY,
    normalize_recurring_prescription_fields,
)


class PrescribedSourceError(ValueError):
    def __init__(self, message: str, unresolved: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.unresolved = unresolved or []


def _read(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise PrescribedSourceError("PDF input needs the installed pypdf package; OCR is not supported.") from error
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if not text.strip():
            raise PrescribedSourceError("The PDF has no extractable text; scanned-image OCR is not supported.")
        return text, "pdf-text"
    if path.suffix.lower() in {".txt", ".md", ".text"}:
        text = path.read_text(encoding="utf-8")
        if text.strip():
            return text, "text"
        raise PrescribedSourceError("Source text is empty.")
    raise PrescribedSourceError(f"Unsupported source extension: {path.suffix or '(none)'}")


def _spans(text: str) -> dict[str, str]:
    spans: dict[str, str] = {}
    occurrences: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if line:
            key = "SRC_" + hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
            occurrences[key] = occurrences.get(key, 0) + 1
            spans[f"{key}_{occurrences[key]}"] = line
    return spans


def extract_prescribed_facts(path: str | Path, *, extract: Callable[..., dict[str, Any]] | None = None,
                             client: Any = None, logger: Any = None) -> dict[str, Any]:
    """Extract source-only facts once; safe to cache independently from library mappings."""
    path = Path(path)
    raw = path.read_bytes()
    text, kind = _read(path)
    spans = _spans(text)
    if extract is None:
        messages = [
            {"role": "system", "content": (
                "Extract source facts only; do not choose library exercises, invent IDs, compute quantities, "
                "convert units, or supply numeric prescriptions. Return JSON with planName, exercises, workouts, "
                "and unresolved. Each exercise has rawName, sourceKey, evidenceKeys. Each workout has name and "
                "ordered blocks; each block has type (straight/superset), exerciseKeys, and optional roundsKey/restKey. "
                "Recurring fields are allowed only when the supplied source instructions explicitly state them. "
                "When recurring keys are explicit, return recurringProgramKey only if the source explicitly gives "
                "a stable program identifier; do not derive it from the plan name or file. "
                "Use a stable recurringSessionKey for every workout that the source explicitly assigns to the same "
                "recurring session/template; use prescriptionOrdinal and prescriptionLabel only when explicitly stated. "
                "On an exercise, use a stable recurringExerciseKey only when the source explicitly identifies that "
                "prescription slot across repeated sessions; do not infer recurrence from repeated exercise names, "
                "similar names, or repeated prescriptions. Set loadHistoryPolicy to NONE, LAST_WORKING_LOAD or "
                "PRESCRIBED_WEIGHT only when explicitly stated. Use PRESCRIBED_WEIGHT only when the source "
                "explicitly fixes a recurring week's load (such as a fixed override or deload); an initial load "
                "alone does not imply it. "
                "when the source explicitly prescribes that reuse; LAST_WORKING_LOAD requires the same explicit "
                "recurringExerciseKey. Never derive a recurring key from a library definition or display name. "
                "Evidence and block keys must be copied from sourceSpans; recurring keys are stable labels "
                "derived only from explicit recurrence wording. Do not omit or duplicate a prescribed movement. "
                "Report unsupported ambiguity in unresolved; never guess." )},
            {"role": "user", "content": json.dumps({"sourceSpans": spans}, ensure_ascii=False)},
        ]
        from .api_metrics import api_metrics_scope
        with api_metrics_scope(logger, "source_interpretation"):
            content, _, _ = chat_call(client, messages, reasoning_effort="low", max_tokens=8192,
                                     response_format={"type": "json_object"}, retry=False)
        try:
            facts = json.loads(content)
        except (TypeError, json.JSONDecodeError) as error:
            raise PrescribedSourceError("The single extraction response was not valid JSON.",
                                        [{"reason": "invalid_extraction_json"}]) from error
    else:
        facts = extract(text, spans)
    if not isinstance(facts, dict):
        raise PrescribedSourceError("Extraction did not return a source-facts object.", [{"reason": "invalid_facts"}])
    source = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "format": kind,
              "spans": spans}
    return {"facts": facts, "source": source}


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _validation_library(plan: dict[str, Any], library: dict[str, Any], equipment_map: dict[str, str] | None = None,
                        accessory_map: dict[str, str] | None = None) -> dict[str, Any]:
    """Project the current catalog into the PlanIndex's code-owned placeholder IDs."""
    result = copy.deepcopy(library)
    if equipment_map is None:
        by_name = {_norm_name(x.get("name", "")): x.get("id") for x in result.get("equipments", [])}
        equipment_map = {by_name.get(_norm_name(x.get("name", ""))): x.get("id")
                         for x in plan.get("equipments", [])}
    if accessory_map is None:
        by_name = {_norm_name(x.get("name", "")): x.get("id") for x in result.get("accessoryEquipments", [])}
        accessory_map = {by_name.get(_norm_name(x.get("name", ""))): x.get("id")
                         for x in plan.get("accessoryEquipments", [])}
    for item in result.get("equipments", []):
        item["id"] = equipment_map.get(item.get("id"), item.get("id"))
    for item in result.get("accessoryEquipments", []):
        item["id"] = accessory_map.get(item.get("id"), item.get("id"))
    for definition in result.get("exerciseDefinitions", []):
        definition["equipmentId"] = equipment_map.get(definition.get("equipmentId"), definition.get("equipmentId"))
        definition["requiredAccessoryEquipmentIds"] = [accessory_map.get(x, x)
            for x in definition.get("requiredAccessoryEquipmentIds", [])]
    return result


def _parse_rest(text: str, source_key: str) -> tuple[int | None, dict[str, Any] | None]:
    match = re.search(r"\brest\s*(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*(min(?:ute)?s?|s|sec(?:ond)?s?|['’″\"]{1,2})?", text, re.I)
    if not match:
        return None, {"sourceKey": source_key, "reason": "rest_value_not_parseable"}
    unit = (match.group(3) or "").lower()
    seconds = float(match.group(2) or match.group(1))
    if unit.startswith("min"):
        seconds *= 60
    elif not unit:
        return None, {"sourceKey": source_key, "reason": "rest_unit_missing"}
    if not seconds.is_integer():
        return None, {"sourceKey": source_key, "reason": "fractional_rest_not_supported"}
    return int(seconds), None


def _source_exercise_name(line: str) -> str | None:
    """Return the whole exercise name before the supported prescription quantities."""
    text = line.strip()
    text = re.sub(r"^[A-Z]\s*[.)-]\s*", "", text, flags=re.I)
    prescription = re.search(r"(?<![\d.])\d+\s*[x×]\s*\d+(?:\s*[-–]\s*\d+)?(?![.\d])", text, re.I)
    if prescription:
        name = text[:prescription.start()]
    else:
        leading = re.match(r"^\s*\d+(?:\s*[-–]\s*\d+)?\s*(?:/\s*(?:side|lato))?\s+(.+)$", text, re.I)
        if not leading:
            return None
        name = leading.group(1)
        # A trailing load or effort cue ends the name when the source uses a
        # leading-rep format (for example, `8-10 Bench Press @RPE 7`).
        name = re.split(r"\s+(?=@?RPE\b|\d+(?:\.\d+)?\s*(?:kg|lb|lbs)\b)", name, maxsplit=1, flags=re.I)[0]
    name = re.sub(r"[\s,:;@-]+$", "", name).strip()
    return name or None


def _parse_exercise(member: dict[str, Any], lines: list[str], definition: dict[str, Any], rounds: int | None,
                    rest: int | None, ids: dict[str, str], *, pair_load: bool) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    unresolved: list[dict[str, Any]] = []
    # Prescription quantities belong to the primary cited line only. Other
    # cited lines are retained as notes but cannot donate numbers.
    raw = lines[0] if lines else ""
    # Supported quantity grammar: `3 x 8-10`, `8-10 Exercise`, and explicit `8/side` forms.
    mx = re.search(r"(?<![\d.\-])(\d+)\s*[x×]\s*(\d+)(?:\s*[-–]\s*(\d+))?(?![.\d])", raw, re.I)
    lead = re.search(r"^\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*(?:/\s*(?:side|lato))?\s+", raw, re.I)
    if re.search(r"(?:^|\s)-\s*\d+(?:\.\d+)?\s*(?:kg|lb|lbs)\b", raw, re.I):
        unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "negative_load_not_supported"})
        return None, unresolved
    if re.search(r"(?<!\d)\d+\.\d+\s*[x×]|[x×]\s*\d+\.\d+", raw, re.I):
        unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "fractional_sets_or_reps_not_supported"})
        return None, unresolved
    if mx:
        sets, low, high = int(mx.group(1)), int(mx.group(2)), int(mx.group(3) or mx.group(2))
    elif lead and rounds:
        sets, low, high = rounds, int(lead.group(1)), int(lead.group(2) or lead.group(1))
    else:
        unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "unsupported_or_missing_sets_reps"})
        return None, unresolved
    if rounds and mx and sets != rounds:
        unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "rounds_count_conflicts_with_sets",
                           "rounds": rounds, "sets": sets})
        return None, unresolved
    if rounds and mx is None:
        sets = rounds
    per_side = bool(re.search(r"/\s*(?:side|lato)|\bper\s+side\b", raw, re.I))
    intra = 0 if per_side else None
    load_match = re.search(r"(?<![A-Za-z0-9.,+\-])\+?(\d+(?:\.\d+)?)(?![\d.,])\s*(kg|lb|lbs)(?![A-Za-z])(?:\s*(per\s*hand|each\s*hand|/\s*hand))?", raw, re.I)
    load = None
    if load_match:
        load = float(load_match.group(1))
        if load_match.group(2).lower().startswith("lb"):
            load = round(load * 0.45359237, 4)
        if load_match.group(3):
            # The app uses the total selectable load for a dumbbell pair.
            if pair_load:
                load *= 2
            else:
                unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "per_hand_load_without_pair_equipment"})
                return None, unresolved
    elif definition.get("exerciseType") == "WEIGHT":
        unresolved.append({"sourceKey": member.get("sourceKey"), "reason": "exact_load_missing_from_source"})
        return None, unresolved
    rpe = re.search(r"\bRPE\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?)", raw, re.I)
    rest_note = f" Rest {rest}s (selected from the cited prescription)." if rest is not None else ""
    note_parts = [*lines]
    if rpe:
        note_parts.append(f"Source effort: RPE {rpe.group(1)}.")
    if rest_note:
        note_parts.append(rest_note.strip())
    exercise = {
        "id": ids["exercise"], "libraryDefinitionId": definition["id"],
        "name": definition["name"], "nameOverride": member.get("rawName"),
        "equipmentId": definition.get("equipmentId"),
        "exerciseType": definition.get("exerciseType"),
        "bodyWeightPercentage": definition.get("bodyWeightPercentage"),
        "intraSetRestInSeconds": intra,
        "muscleGroups": definition.get("muscleGroups", []),
        "secondaryMuscleGroups": definition.get("secondaryMuscleGroups", []),
        "requiredAccessoryEquipmentIds": definition.get("requiredAccessoryEquipmentIds", []),
        "exerciseCategory": definition.get("exerciseCategory"),
        "numWorkSets": sets, "generateWarmUpSets": False,
        "minReps": low, "maxReps": high, "restBetweenSetsSeconds": rest or 0,
        "placementNotes": "\n".join(note_parts),
    }
    if per_side:
        exercise["reviewedExecution"] = {"setMode": "paired_sides"}
    if load is not None:
        field = "additionalWeight" if exercise["exerciseType"] == "BODY_WEIGHT" else "weight"
        exercise["targetSetPrescriptions"] = [
            {"workSetIndex": i, "reps": low, field: load} for i in range(sets)]
    return exercise, unresolved


def map_prescribed_facts(extracted: dict[str, Any], library: dict[str, Any]) -> dict[str, Any]:
    """Map cached source facts through the current library; no model or numeric guess is used here."""
    facts = extracted.get("facts", extracted)
    source = extracted.get("source", {})
    spans = source.get("spans", {})
    unresolved = list(facts.get("unresolved", []))
    if not isinstance(spans, dict) or not isinstance(facts.get("exercises"), list) or not isinstance(facts.get("workouts"), list):
        return {"planIndex": None, "source": source, "unresolved": [{"reason": "source_facts_shape_invalid"}]}
    definitions = library.get("exerciseDefinitions", [])
    overrides = extracted.get("definitionMappings", {})
    if not isinstance(overrides, dict):
        return {"planIndex": None, "source": source,
                "unresolved": [{"reason": "operator_definition_mappings_must_be_object"}]}
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_id = {}
    for definition in definitions:
        by_name.setdefault(_norm_name(definition.get("name", "")), []).append(definition)
        if definition.get("id"):
            by_id[definition["id"]] = definition
    member_rows = [m for m in facts.get("exercises", []) if isinstance(m, dict)]
    member_keys = [m.get("sourceKey") for m in member_rows]
    if len(member_keys) != len(set(member_keys)):
        unresolved.append({"reason": "duplicate_member_source_key"})
    members = {m.get("sourceKey"): m for m in member_rows}
    unknown_override_keys = sorted(set(overrides) - set(members))
    if unknown_override_keys:
        unresolved.append({"reason": "operator_mapping_source_key_unknown", "sourceKeys": unknown_override_keys})
    selected: dict[str, dict[str, Any]] = {}
    consumed_keys: set[str] = set()
    for source_key, member in members.items():
        citations = member.get("evidenceKeys", [source_key])
        if not citations or source_key not in citations or any(key not in spans for key in citations):
            unresolved.append({"sourceKey": source_key, "reason": "missing_or_unknown_source_evidence"})
            continue
        source_name = _source_exercise_name(spans[source_key])
        if not source_name or _norm_name(member.get("rawName", "")) != _norm_name(source_name):
            unresolved.append({"sourceKey": source_key, "reason": "exercise_name_not_present_in_source_line"})
            continue
        borrowed_rows = [key for key in citations if key != source_key and
                         re.search(r"(?<![\d.])\d+\s*[x×]\s*\d+(?:\s*[-–]\s*\d+)?(?![.\d])", spans[key])]
        if borrowed_rows:
            unresolved.append({"sourceKey": source_key, "reason": "other_prescription_row_used_as_evidence",
                               "evidenceKeys": borrowed_rows})
            continue
        consumed_keys.update(citations)
        if source_key in overrides:
            definition_id = overrides[source_key]
            definition = by_id.get(definition_id) if isinstance(definition_id, str) else None
            if definition is None:
                unresolved.append({"sourceKey": source_key, "reason": "operator_mapping_definition_unknown",
                                   "sourceRawName": member.get("rawName"), "definitionId": definition_id})
                continue
            selected[source_key] = definition
            continue
        hits = by_name.get(_norm_name(member.get("rawName", "")), [])
        if len(hits) != 1:
            close_names = difflib.get_close_matches(_norm_name(member.get("rawName", "")), list(by_name), n=4, cutoff=0.35)
            candidates = [definition for name in close_names for definition in by_name[name]]
            unresolved.append({"sourceKey": source_key,
                "reason": "library_definition_missing" if not hits else "library_definition_ambiguous",
                "sourceRawName": member.get("rawName"),
                "candidates": [{"id": definition["id"], "name": definition.get("name")}
                               for definition in (hits if hits else candidates)]})
            continue
        selected[source_key] = hits[0]
    used = set(members)
    assigned_keys = [key for workout in facts.get("workouts", []) for block in workout.get("blocks", [])
                     for key in block.get("exerciseKeys", [])]
    if len(assigned_keys) != len(set(assigned_keys)):
        unresolved.append({"reason": "duplicate_prescription_assignment"})
    if set(assigned_keys) != used:
        unresolved.append({"reason": "unassigned_or_unknown_exercise_fact",
                           "unassigned": sorted(used - set(assigned_keys)),
                           "unknown": sorted(set(assigned_keys) - used)})
    source_position = {key: index for index, key in enumerate(spans)}
    ordered_assigned = [key for workout in facts.get("workouts", []) for block in workout.get("blocks", [])
                        for key in block.get("exerciseKeys", []) if key in source_position]
    if ordered_assigned != sorted(ordered_assigned, key=source_position.__getitem__):
        unresolved.append({"reason": "source_occurrence_order_mismatch",
                           "sourceKeys": ordered_assigned})
    consumed_keys.update(used)
    for workout in facts.get("workouts", []):
        workout_name = str(workout.get("name", ""))
        if re.search(r"\b(?:week|day)\s*\d+\b", workout_name, re.I):
            first_member = min((source_position[key] for block in workout.get("blocks", [])
                                for key in block.get("exerciseKeys", []) if key in source_position), default=len(spans))
            headings = [line for index, (key, line) in enumerate(spans.items())
                        if index < first_member and re.match(
                            r"^\s*(?:plan|program|week|settimana|workout|day|giorno|allenamento)\b", line, re.I)]
            headings.extend(spans[key] for key in workout.get("evidenceKeys", []) if key in spans)
            normalized_heading = _norm_name(" ".join(headings))
            normalized_name = _norm_name(workout_name)
            if normalized_name not in normalized_heading:
                unresolved.append({"reason": "workout_phase_name_not_grounded_in_source_heading",
                                   "workout": workout_name, "headingEvidence": headings})
        for block in workout.get("blocks", []):
            for key in block.get("evidenceKeys", []):
                if key not in spans:
                    unresolved.append({"reason": "unknown_block_evidence", "evidence": key})
                consumed_keys.add(key)
            for field in ("roundsKey", "restKey"):
                key = block.get(field)
                if key:
                    if key not in spans:
                        unresolved.append({"reason": "unknown_block_evidence", "evidence": key})
                    consumed_keys.add(key)
            if block.get("type") == "superset":
                grouping_evidence = [spans[key] for key in block.get("evidenceKeys", []) if key in spans]
                rounds_key = block.get("roundsKey")
                if rounds_key in spans:
                    grouping_evidence.append(spans[rounds_key])
                if not any(re.search(r"\b(?:supersets?|superserie|circuits?|rounds?)\b", line, re.I)
                           for line in grouping_evidence):
                    unresolved.append({"reason": "superset_grouping_evidence_missing",
                                       "exerciseKeys": block.get("exerciseKeys", [])})
    for key, line in spans.items():
        if key not in consumed_keys and not re.match(
                r"^\s*(?:plan|program|week|settimana|workout|day|giorno|allenamento)\b", line, re.I):
            unresolved.append({"sourceKey": key, "reason": "source_instruction_not_assigned_or_unsupported", "text": line})
    block_rest_seconds = {}
    for wi, workout in enumerate(facts.get("workouts", [])):
        for bi, block in enumerate(workout.get("blocks", [])):
            rest_key = block.get("restKey")
            if rest_key in spans:
                parsed_rest, issue = _parse_rest(spans[rest_key], rest_key)
                if issue:
                    unresolved.append(issue)
                else:
                    block_rest_seconds[(wi, bi)] = parsed_rest
    if unresolved:
        return {"planIndex": None, "source": source, "unresolved": unresolved}

    equipment_by_id = {item.get("id"): item for item in library.get("equipments", [])}
    accessory_by_id = {item.get("id"): item for item in library.get("accessoryEquipments", [])}
    equipment_ids = list(dict.fromkeys(d.get("equipmentId") for d in selected.values() if d.get("equipmentId")))
    accessory_ids = list(dict.fromkeys(a for d in selected.values() for a in d.get("requiredAccessoryEquipmentIds", [])))
    if any(x not in equipment_by_id for x in equipment_ids):
        unresolved.append({"reason": "selected_definition_equipment_missing_from_library"})
    if any(x not in accessory_by_id for x in accessory_ids):
        unresolved.append({"reason": "selected_definition_accessory_missing_from_library"})
    if unresolved:
        return {"planIndex": None, "source": source, "unresolved": unresolved}
    emap = {old: f"EQUIPMENT_{i}" for i, old in enumerate(equipment_ids)}
    amap = {old: f"ACCESSORY_{i}" for i, old in enumerate(accessory_ids)}
    plan_exercises = []
    exercise_ids = {}
    facts_by_key = {e["sourceKey"]: e for e in facts.get("exercises", [])}
    for i, (key, definition) in enumerate(sorted(selected.items(), key=lambda item: source_position[item[0]])):
        exercise_id = f"EXERCISE_{i}"
        exercise_ids[key] = exercise_id
        member = facts_by_key[key]
        evidence_keys = member.get("evidenceKeys", [key])
        lines = [spans[key], *[spans[k] for k in evidence_keys if k != key]]
        related_blocks = [(wi, bi, block) for wi, workout in enumerate(facts.get("workouts", []))
                          for bi, block in enumerate(workout.get("blocks", [])) if key in block.get("exerciseKeys", [])]
        rounds = None; rest = None
        if related_blocks:
            _, _, block = related_blocks[0]
            for field in ("roundsKey", "restKey"):
                span_key = block.get(field)
                if span_key and span_key not in spans:
                    unresolved.append({"sourceKey": key, "reason": "unknown_block_evidence", "evidence": span_key})
            if block.get("roundsKey") in spans:
                match = re.search(r"\b(\d+)\s*rounds?\b", spans[block["roundsKey"]], re.I)
                if match: rounds = int(match.group(1))
            rest = block_rest_seconds.get((related_blocks[0][0], related_blocks[0][1]))
        # A standalone line may carry its own exact rest and set count.
        joined = " ".join(lines)
        if re.search(r"\brest\s*", joined, re.I):
            rest, issue = _parse_rest(joined, member.get("sourceKey", key))
            if issue: unresolved.append(issue)
        if rest is None:
            unresolved.append({"sourceKey": key, "reason": "prescribed_rest_missing_or_unsupported"})
            continue
        equipment_record = equipment_by_id.get(definition.get("equipmentId"), {})
        exercise, issues = _parse_exercise(member, lines, definition, rounds, rest,
            {"exercise": exercise_id}, pair_load=equipment_record.get("type") == "DUMBBELLS")
        unresolved.extend(issues)
        if exercise:
            block_notes = []
            for block in (item[2] for item in related_blocks):
                for field in ("evidenceKeys", "roundsKey", "restKey"):
                    values = block.get(field, []) if field == "evidenceKeys" else [block.get(field)]
                    for evidence_key in values:
                        if evidence_key in spans and spans[evidence_key] not in block_notes:
                            block_notes.append(spans[evidence_key])
            if block_notes:
                exercise["placementNotes"] = "\n".join([exercise["placementNotes"], *block_notes])
            if _norm_name(member.get("rawName", "")) != _norm_name(definition.get("name", "")):
                exercise["placementNotes"] += (
                    f"\nOperator library mapping: source name {member.get('rawName')!r} mapped to "
                    f"{definition.get('name')!r} (definitionId {definition['id']}).")
            if exercise.get("equipmentId") is not None:
                exercise["equipmentId"] = emap[exercise["equipmentId"]]
            exercise["requiredAccessoryEquipmentIds"] = [amap[x] for x in exercise.get("requiredAccessoryEquipmentIds", [])]
            if member.get(RECURRING_EXERCISE_KEY) is not None:
                exercise[RECURRING_EXERCISE_KEY] = member[RECURRING_EXERCISE_KEY]
            if member.get(LOAD_HISTORY_POLICY) is not None:
                exercise[LOAD_HISTORY_POLICY] = member[LOAD_HISTORY_POLICY]
            plan_exercises.append(exercise)
    if unresolved:
        return {"planIndex": None, "source": source, "unresolved": unresolved}

    workouts = []
    for i, workout in enumerate(facts.get("workouts", [])):
        workout_id = f"WORKOUT_{i}"
        ordered_keys = [key for block in workout.get("blocks", []) for key in block.get("exerciseKeys", [])]
        if len(ordered_keys) != len(set(ordered_keys)) or any(key not in exercise_ids for key in ordered_keys):
            unresolved.append({"workout": workout.get("name"), "reason": "duplicate_or_unknown_exercise_reference"})
            continue
        groups = []
        rest_to_next = [0] * len(ordered_keys)
        for block_index, block in enumerate(workout.get("blocks", [])):
            block_ids = [exercise_ids[key] for key in block.get("exerciseKeys", [])]
            rest = block_rest_seconds.get((i, block_index), 0)
            if block.get("type") == "superset":
                if len(block_ids) < 2:
                    unresolved.append({"workout": workout.get("name"), "reason": "superset_needs_two_members"})
                else:
                    # The block rest is the between-round recovery; the app
                    # omits it after the last round and it is not an additional
                    # standalone transition between exercise blocks.
                    groups.append({"exerciseIds": block_ids, "restSecondsByExercise":
                        {identifier: 0 for identifier in block_ids[:-1]} | {block_ids[-1]: rest}})
            # A straight block's rest is already its exercise-level
            # restBetweenSetsSeconds. Neither block type creates an automatic
            # transition rest after the completed block.
        plan_workout = {"id": workout_id, "name": workout.get("name", f"Workout {i+1}"),
            "description": "Prescribed source; citations in exercise notes.",
            "exerciseIds": [exercise_ids[k] for k in ordered_keys],
            "hasSupersets": bool(groups), "supersetGroups": groups,
            "hasRestComponents": any(rest_to_next),
            "restToNextSeconds": rest_to_next}
        for field in (RECURRING_SESSION_KEY, PRESCRIPTION_ORDINAL, PRESCRIPTION_LABEL):
            if workout.get(field) is not None:
                plan_workout[field] = workout[field]
        workouts.append(plan_workout)
    if unresolved:
        return {"planIndex": None, "source": source, "unresolved": unresolved}
    plan = {"planName": facts.get("planName", "Prescribed workout"),
        "auditTargets": {"weeklyEffectiveSets": {}, "perSessionEffectiveSets": {}},
        "equipments": [{"id": emap[x], "name": equipment_by_id[x]["name"], "type": equipment_by_id[x]["type"]}
                       for x in equipment_ids],
        "accessoryEquipments": [{"id": amap[x], "name": accessory_by_id[x]["name"], "type": "ACCESSORY"}
                                for x in accessory_ids],
        "exercises": plan_exercises, "workouts": workouts}
    if facts.get(RECURRING_PROGRAM_KEY) is not None:
        plan[RECURRING_PROGRAM_KEY] = facts[RECURRING_PROGRAM_KEY]
    recurring_issues = normalize_recurring_prescription_fields(plan)
    if recurring_issues:
        return {"planIndex": None, "source": source, "unresolved": [
            {"reason": issue.code, "detail": issue.message,
             **({"sourceKey": issue.exercise_id} if issue.exercise_id else {})}
            for issue in recurring_issues
        ]}
    validation_library = _validation_library(plan, library, emap, amap)
    try:
        validate_plan_index_contract(plan, validation_library)
    except Exception as error:
        return {"planIndex": None, "source": source, "unresolved": [{"reason": "planindex_contract_failed", "detail": str(error)}]}
    return {"planIndex": plan, "source": {**source, "operatorDefinitionMappings": {
        key: value for key, value in overrides.items()}}, "unresolved": []}


def load_prescribed_source(path: str | Path, library: dict[str, Any], *, extract: Callable[..., dict[str, Any]] | None = None,
                           client: Any = None, logger: Any = None) -> dict[str, Any]:
    """Directly load PlanIndex JSON, or extract text/PDF once then map facts against the current library."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = path.read_bytes()
        try: payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PrescribedSourceError("PlanIndex JSON is invalid.", [{"reason": "invalid_planindex_json"}]) from error
        plan = payload.get("planIndex", payload) if isinstance(payload, dict) else None
        if not isinstance(plan, dict) or not {"planName", "exercises", "workouts"}.issubset(plan):
            raise PrescribedSourceError("JSON source must already be a PlanIndex (planName, exercises, workouts).")
        recurring_issues = normalize_recurring_prescription_fields(plan)
        if recurring_issues:
            raise PrescribedSourceError(
                "PlanIndex recurring-prescription metadata is invalid.",
                [{"reason": issue.code, "detail": issue.message,
                  **({"sourceKey": issue.exercise_id} if issue.exercise_id else {})}
                 for issue in recurring_issues],
            )
        validate_plan_index_contract(plan, _validation_library(plan, library))
        return {"planIndex": plan, "source": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "format": "json"}, "unresolved": []}
    extracted = extract_prescribed_facts(path, extract=extract, client=client, logger=logger)
    extracted["source"]["path"] = str(path)
    return map_prescribed_facts(extracted, library)

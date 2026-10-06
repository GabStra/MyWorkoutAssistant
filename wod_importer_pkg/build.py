"""Encodes a WodIR into a schemaVersion 2 WorkoutPlanPackage dict.

Near-zero-interaction encoding rules (the athlete cannot enter reps/weights
during a WOD; at most they tap to advance a movement):
- timed blocks (Hyrox "From a-b'") and EMOM slots -> auto-start/auto-stop
  countdown sets: the watch advances by itself, zero taps.
- AMRAP -> superset with an estimated round count (tap to advance; finish
  early at the cap).
- rounds-for-time -> superset with exactly N rounds.
- chippers -> flat tap-through exercises, rest lines become Rest components.
Set shape follows the RESOLVED definition's exerciseType (WeightSet for
WEIGHT, BodyWeightSet for BODY_WEIGHT); prescribed values parsed from the
text ride along as defaults.
"""

from __future__ import annotations

import re
from datetime import date

from wod_importer_pkg.mapping import MovementMapper, stable_id
from wod_importer_pkg.parse import Block, Movement, WodIR

_SECONDS_PER_REP = 2.5   # crude per-rep duration for AMRAP round estimation
_SECONDS_PER_METER = 1.0  # crude per-meter duration (shuttle/run)


def _weight_set(key: str, reps: int, weight: float) -> dict:
    return {
        "id": stable_id("set", f"{key}:{reps}x{weight}"),
        "type": "WeightSet",
        "reps": reps,
        "weight": weight,
        "subCategory": "WorkSet",
        "shouldReapplyHistoryToSet": True,
    }


def _bodyweight_set(key: str, reps: int) -> dict:
    return {
        "id": stable_id("set", f"{key}:x{reps}"),
        "type": "BodyWeightSet",
        "reps": reps,
        "additionalWeight": 0.0,
        "subCategory": "WorkSet",
        "shouldReapplyHistoryToSet": True,
    }


def _timed_set(key: str, minutes: float) -> dict:
    return {
        "id": stable_id("set", f"{key}:t{minutes}"),
        "type": "TimedDurationSet",
        "timeInMillis": int(minutes * 60_000),
        "autoStart": True,
        "autoStop": True,
        "subCategory": "WorkSet",
    }


def _prescribed_weight(movement: Movement) -> float:
    if not movement.weight_hint or "%" in movement.weight_hint:
        return 0.0
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)", movement.weight_hint)
    return float(match.group(1).replace(",", ".")) if match else 0.0


def _exercise(movement: Movement, definition: dict, sets: list[dict], notes: str) -> dict:
    note_bits = [bit for bit in (notes, movement.note, movement.reps_text and f"reps {movement.reps_text}") if bit]
    return {
        "id": stable_id("component", f"{definition['name']}:{movement.raw}"),
        "type": "Exercise",
        "enabled": True,
        "name": definition["name"],
        "notes": "; ".join(note_bits),
        "sets": sets,
        "exerciseType": definition["exerciseType"],
        "equipmentId": definition["equipmentId"],
        "bodyWeightPercentage": definition.get("bodyWeightPercentage"),
        "generateWarmUpSets": False,
        "progressionMode": "OFF",
        "keepScreenOn": False,
        "showCountDownTimer": definition["exerciseType"] in ("COUNTDOWN", "COUNTUP"),
        "intraSetRestInSeconds": None,
        "exerciseDefinitionId": definition["id"],
        "muscleGroups": [],
        "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [],
        "requiresLoadCalibration": False,
        "exerciseCategory": definition.get("exerciseCategory"),
    }


def _sets_for(key: str, movement: Movement, exercise_type: str, rounds: int) -> list[dict]:
    weight = _prescribed_weight(movement)
    reps = movement.reps or 10
    if exercise_type == "WEIGHT":
        return [_weight_set(f"{key}:{index}", reps, weight) for index in range(rounds)]
    return [_bodyweight_set(f"{key}:{index}", reps) for index in range(rounds)]


def _estimate_rounds(block: Block, movements: list[Movement]) -> int:
    if block.rounds:
        return block.rounds
    cap = block.cap_min or block.minutes
    if not cap:
        return 4
    seconds = sum(
        (movement.reps or (40 if movement.max_effort else 10)) * _SECONDS_PER_REP
        + (20 if movement.unit == "m" else 0) * _SECONDS_PER_METER
        for movement in movements
    )
    return max(2, min(10, int(cap * 60 / seconds))) if seconds > 0 else 4


def _superset(name: str, exercises: list[dict]) -> dict:
    return {
        "id": stable_id("component", f"superset:{name}:{'-'.join(e['name'] for e in exercises)}"),
        "type": "Superset",
        "enabled": True,
        "exercises": exercises,
        "restSecondsByExercise": {exercise["id"]: 0 for exercise in exercises},
    }


def _block_notes(block: Block) -> str:
    bits = []
    if block.cap_min:
        bits.append(f"time cap {block.cap_min:g}' — finish early when reached")
    if block.on_minutes:
        bits.append(f"{block.on_minutes:g}' ON / {(block.off_minutes or 0):g}' OFF intervals")
    if block.rounds and block.kind == "chipper":
        bits.append(f"{block.rounds} intervals, alternate A/B")
    return "; ".join(bits)


def _build_block(mapper: MovementMapper, block: Block) -> list[dict]:
    if block.kind == "rest":
        seconds = sum(m.rest_seconds or 0 for m in block.movements)
        if not seconds:
            return []
        return [
            {
                "id": stable_id("component", f"rest:{block.movements[0].raw}"),
                "type": "Rest",
                "enabled": True,
                "timeInSeconds": seconds,
            }
        ]

    movements = [m for m in block.movements if m.name != "rest"]
    if not movements:
        return []
    notes = _block_notes(block)

    if block.kind == "timed":
        components = []
        for movement in movements:
            splits = movement.sub_splits_seconds or [int((block.minutes or 4) * 60)]
            resolution = mapper.resolve(movement.name, movement.weight_hint)
            definition = resolution.definition
            sets = [_timed_set(f"{movement.name}:{index}", seconds / 60) for index, seconds in enumerate(splits)]
            components.append(_exercise(movement, definition, sets, notes))
        return components

    if block.kind == "emom":
        slots = max(len(movements), 1)
        rounds = max(1, int((block.minutes or slots) // slots))
        exercises = []
        for movement in movements:
            resolution = mapper.resolve(movement.name, movement.weight_hint)
            definition = resolution.definition
            sets = [_timed_set(f"emom:{movement.name}:{index}", 1.0) for index in range(rounds)]
            exercises.append(_exercise(movement, definition, sets, f"EMOM slot — {rounds} rounds x 1'"))
        return [_superset("EMOM", exercises)]

    rounds = _estimate_rounds(block, movements)
    exercises = []
    for index, movement in enumerate(movements):
        resolution = mapper.resolve(movement.name, movement.weight_hint)
        definition = resolution.definition
        sets = _sets_for(f"{block.kind}:{movement.name}", movement, definition["exerciseType"], rounds)
        exercises.append(_exercise(movement, definition, sets, notes))
    label = f"{block.label}) " if block.label else ""
    return [_superset(f"{label}{block.kind.upper()} x{rounds}", exercises)]


def build_package(ir: WodIR, mapper: MovementMapper | None = None) -> dict:
    mapper = mapper or MovementMapper()
    components: list[dict] = []
    for block in ir.blocks:
        components.extend(_build_block(mapper, block))

    slug = re.sub(r"[^A-Za-z0-9]+", "-", ir.title or "WOD").strip("-")
    name = f"WOD {ir.date} {slug}".strip()
    workout = {
        "id": stable_id("workout", name),
        "name": name,
        "description": f"{ir.wod_type or 'WOD'} — imported from the gym board."
        + (f" Unparsed fragments: {' | '.join(ir.unparsed)}" if ir.unparsed else ""),
        "workoutComponents": components,
        "order": 0,
        "enabled": True,
        "heartRateSource": "WATCH_SENSOR",
        "creationDate": ir.date or date.today().isoformat(),
        "previousVersionId": None,
        "nextVersionId": None,
        "isActive": True,
        "timesCompletedInAWeek": None,
        "globalId": stable_id("global", name),
        "type": 0,
        "workoutPlanId": None,
    }
    return {
        "name": name,
        "schemaVersion": 2,
        "exerciseDefinitions": list(mapper.created_definitions.values()),
        "workouts": [workout],
        "equipments": list(mapper.created_equipment.values()),
        "accessoryEquipments": [],
        "exerciseMovements": [],
    }

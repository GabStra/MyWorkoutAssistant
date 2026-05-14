"""Type-specific exercise emission schemas and profiles."""

import copy

from .constants import JSON_SCHEMA, PLACEHOLDER_OR_UUID_PATTERN


def _build_type_specific_exercise_schema(
    *,
    exercise_type,
    work_set_def,
    allow_rest_sets,
    require_rep_range,
    body_weight_schema,
    show_countdown_schema,
    exercise_category_schema,
):
    properties = {
        "id": {"$ref": "#/$defs/UUID"},
        "type": {"const": "Exercise"},
        "enabled": {"type": "boolean"},
        "name": {"type": "string"},
        "notes": {"type": "string", "maxLength": 500},
        "sets": {
            "type": "array",
            "minItems": 1,
            "items": {
                "oneOf": (
                    [{"$ref": f"#/$defs/{work_set_def}"}]
                    + ([{"$ref": "#/$defs/RestSet"}] if allow_rest_sets else [])
                )
            },
        },
        "exerciseType": {"const": exercise_type},
        "lowerBoundMaxHRPercent": {"type": ["number", "null"]},
        "upperBoundMaxHRPercent": {"type": ["number", "null"]},
        "equipmentId": {
            "anyOf": [
                {"$ref": "#/$defs/UUID"},
                {"type": "null"},
            ]
        },
        "bodyWeightPercentage": body_weight_schema,
        "generateWarmUpSets": {"type": "boolean"},
        "progressionMode": {"$ref": "#/$defs/ProgressionMode"},
        "keepScreenOn": {"type": "boolean"},
        "showCountDownTimer": show_countdown_schema,
        "intraSetRestInSeconds": {"type": ["integer", "null"]},
        "loadJumpDefaultPct": {"type": ["number", "null"]},
        "loadJumpMaxPct": {"type": ["number", "null"]},
        "loadJumpOvercapUntil": {"type": ["integer", "null"]},
        "muscleGroups": {
            "type": "array",
            "items": {"$ref": "#/$defs/MuscleGroup"},
            "uniqueItems": True,
        },
        "secondaryMuscleGroups": {
            "type": "array",
            "items": {"$ref": "#/$defs/MuscleGroup"},
            "uniqueItems": True,
        },
        "requiredAccessoryEquipmentIds": {
            "type": "array",
            "items": {"$ref": "#/$defs/UUID"},
            "uniqueItems": True,
        },
        "requiresLoadCalibration": {"type": "boolean"},
        "exerciseCategory": exercise_category_schema,
    }
    required = [
        "id",
        "type",
        "enabled",
        "name",
        "notes",
        "sets",
        "exerciseType",
        "equipmentId",
        "bodyWeightPercentage",
        "generateWarmUpSets",
        "progressionMode",
        "keepScreenOn",
        "showCountDownTimer",
        "intraSetRestInSeconds",
        "muscleGroups",
        "secondaryMuscleGroups",
        "requiredAccessoryEquipmentIds",
        "requiresLoadCalibration",
        "exerciseCategory",
    ]
    if require_rep_range:
        properties["minReps"] = {"type": "integer"}
        properties["maxReps"] = {"type": "integer"}
        required.extend(["minReps", "maxReps"])
    defs = copy.deepcopy(JSON_SCHEMA["$defs"])
    defs["UUID"]["pattern"] = PLACEHOLDER_OR_UUID_PATTERN
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
        "$defs": defs,
    }


COMMON_EXERCISE_REQUIRED_TOP_LEVEL_FIELDS = [
    "id",
    "type",
    "enabled",
    "name",
    "notes",
    "sets",
    "exerciseType",
    "equipmentId",
    "bodyWeightPercentage",
    "generateWarmUpSets",
    "progressionMode",
    "keepScreenOn",
    "showCountDownTimer",
    "intraSetRestInSeconds",
    "muscleGroups",
    "secondaryMuscleGroups",
    "requiredAccessoryEquipmentIds",
    "requiresLoadCalibration",
    "exerciseCategory",
]

LOAD_BASED_REQUIRED_TOP_LEVEL_FIELDS = (
    COMMON_EXERCISE_REQUIRED_TOP_LEVEL_FIELDS[:7]
    + ["minReps", "maxReps"]
    + COMMON_EXERCISE_REQUIRED_TOP_LEVEL_FIELDS[7:]
)

TIMED_FORBIDDEN_TOP_LEVEL_FIELDS = ["minReps", "maxReps"]
TIMED_REQUIRED_SET_LEVEL_FIELDS = ["id", "type", "timeInMillis", "autoStart", "autoStop"]
TIMED_FORBIDDEN_SET_LEVEL_FIELDS = ["reps", "weight", "additionalWeight", "timeInSeconds", "subCategory"]


def _exercise_example_base(
    *,
    exercise_id,
    name,
    sets,
    exercise_type,
    equipment_id,
    body_weight_percentage,
    generate_warm_up_sets,
    progression_mode,
    keep_screen_on,
    show_countdown_timer,
    intra_set_rest_in_seconds,
    muscle_groups,
    secondary_muscle_groups,
    required_accessory_equipment_ids,
    requires_load_calibration,
    exercise_category,
):
    return {
        "id": exercise_id,
        "type": "Exercise",
        "enabled": True,
        "name": name,
        "notes": "",
        "sets": sets,
        "exerciseType": exercise_type,
        "equipmentId": equipment_id,
        "bodyWeightPercentage": body_weight_percentage,
        "generateWarmUpSets": generate_warm_up_sets,
        "progressionMode": progression_mode,
        "keepScreenOn": keep_screen_on,
        "showCountDownTimer": show_countdown_timer,
        "intraSetRestInSeconds": intra_set_rest_in_seconds,
        "muscleGroups": muscle_groups,
        "secondaryMuscleGroups": secondary_muscle_groups,
        "requiredAccessoryEquipmentIds": required_accessory_equipment_ids,
        "requiresLoadCalibration": requires_load_calibration,
        "exerciseCategory": exercise_category,
    }


def _build_emission_profile(
    *,
    exercise_type,
    allowed_work_set_type,
    required_top_level_fields,
    forbidden_top_level_fields,
    required_set_level_fields,
    forbidden_set_level_fields,
    schema,
    instruction_text,
    example_object,
):
    return {
        "exercise_type": exercise_type,
        "allowed_work_set_type": allowed_work_set_type,
        "allowed_rest_set": True,
        "required_top_level_fields": required_top_level_fields,
        "forbidden_top_level_fields": forbidden_top_level_fields,
        "required_set_level_fields": required_set_level_fields,
        "forbidden_set_level_fields": forbidden_set_level_fields,
        "schema": schema,
        "instruction_text": instruction_text,
        "example_object": example_object,
    }


WEIGHT_EXERCISE_SCHEMA = _build_type_specific_exercise_schema(
    exercise_type="WEIGHT",
    work_set_def="WeightSet",
    allow_rest_sets=True,
    require_rep_range=True,
    body_weight_schema={"type": "null"},
    show_countdown_schema={"type": "boolean"},
    exercise_category_schema={"$ref": "#/$defs/ExerciseCategory"},
)

BODY_WEIGHT_EXERCISE_SCHEMA = _build_type_specific_exercise_schema(
    exercise_type="BODY_WEIGHT",
    work_set_def="BodyWeightSet",
    allow_rest_sets=True,
    require_rep_range=True,
    body_weight_schema={"type": "number"},
    show_countdown_schema={"type": "boolean"},
    exercise_category_schema={"$ref": "#/$defs/ExerciseCategory"},
)

COUNTDOWN_EXERCISE_SCHEMA = _build_type_specific_exercise_schema(
    exercise_type="COUNTDOWN",
    work_set_def="TimedDurationSet",
    allow_rest_sets=True,
    require_rep_range=False,
    body_weight_schema={"type": "null"},
    show_countdown_schema={"const": True},
    exercise_category_schema={"type": "null"},
)

COUNTUP_EXERCISE_SCHEMA = _build_type_specific_exercise_schema(
    exercise_type="COUNTUP",
    work_set_def="EnduranceSet",
    allow_rest_sets=True,
    require_rep_range=False,
    body_weight_schema={"type": "null"},
    show_countdown_schema={"type": "boolean"},
    exercise_category_schema={"type": "null"},
)

EXERCISE_EMISSION_PROFILES = {
    "WEIGHT": _build_emission_profile(
        exercise_type="WEIGHT",
        allowed_work_set_type="WeightSet",
        required_top_level_fields=LOAD_BASED_REQUIRED_TOP_LEVEL_FIELDS,
        forbidden_top_level_fields=[],
        required_set_level_fields=["id", "type", "reps", "weight", "subCategory"],
        forbidden_set_level_fields=["additionalWeight", "timeInMillis", "timeInSeconds", "autoStart", "autoStop"],
        schema=WEIGHT_EXERCISE_SCHEMA,
        instruction_text=(
            "WEIGHT contract:\n"
            "- Output one Exercise object shaped exactly like the WEIGHT schema.\n"
            "- Work sets must be WeightSet objects only.\n"
            "- RestSet is allowed only between adjacent work sets when the plan calls for inter-set rest.\n"
            "- Every WeightSet must include reps, weight, and subCategory.\n"
            "- Use weight, never additionalWeight.\n"
            "- bodyWeightPercentage must be present and set to null.\n"
            "- minReps and maxReps must be present.\n"
            "- Copy exact plan-owned values for id, exerciseType, equipmentId, requiredAccessoryEquipmentIds, minReps, maxReps, exerciseCategory, and any target set prescriptions.\n"
        ),
        example_object={
            **_exercise_example_base(
                exercise_id="EXERCISE_0",
                name="Back Squat",
                sets=[
                    {"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 100.0, "subCategory": "WorkSet"},
                    {"id": "SET_1", "type": "RestSet", "timeInSeconds": 120, "subCategory": "WorkSet"},
                    {"id": "SET_2", "type": "WeightSet", "reps": 8, "weight": 100.0, "subCategory": "WorkSet"},
                ],
                exercise_type="WEIGHT",
                equipment_id="EQUIPMENT_0",
                body_weight_percentage=None,
                generate_warm_up_sets=True,
                progression_mode="AUTO_REGULATION",
                keep_screen_on=False,
                show_countdown_timer=False,
                intra_set_rest_in_seconds=None,
                muscle_groups=["FRONT_QUADRICEPS", "BACK_GLUTEAL"],
                secondary_muscle_groups=["BACK_HAMSTRING"],
                required_accessory_equipment_ids=[],
                requires_load_calibration=False,
                exercise_category="HEAVY_COMPOUND",
            ),
            "minReps": 6,
            "maxReps": 10,
        },
    ),
    "BODY_WEIGHT": _build_emission_profile(
        exercise_type="BODY_WEIGHT",
        allowed_work_set_type="BodyWeightSet",
        required_top_level_fields=LOAD_BASED_REQUIRED_TOP_LEVEL_FIELDS,
        forbidden_top_level_fields=[],
        required_set_level_fields=["id", "type", "reps", "additionalWeight", "subCategory"],
        forbidden_set_level_fields=["weight", "timeInMillis", "timeInSeconds", "autoStart", "autoStop"],
        schema=BODY_WEIGHT_EXERCISE_SCHEMA,
        instruction_text=(
            "BODY_WEIGHT contract:\n"
            "- Output one Exercise object shaped exactly like the BODY_WEIGHT schema.\n"
            "- Work sets must be BodyWeightSet objects only.\n"
            "- RestSet is allowed only between adjacent work sets when the plan calls for inter-set rest.\n"
            "- Every BodyWeightSet must include reps, additionalWeight, and subCategory.\n"
            "- Use additionalWeight, never weight.\n"
            "- bodyWeightPercentage must be present, numeric, and use percentage semantics such as 100.0 or 65.0.\n"
            "- minReps and maxReps must be present.\n"
            "- Copy exact plan-owned values for id, exerciseType, equipmentId, requiredAccessoryEquipmentIds, bodyWeightPercentage, minReps, maxReps, exerciseCategory, and any target set prescriptions.\n"
        ),
        example_object={
            **_exercise_example_base(
                exercise_id="EXERCISE_1",
                name="Ring Row",
                sets=[
                    {"id": "SET_3", "type": "BodyWeightSet", "reps": 10, "additionalWeight": 5.0, "subCategory": "WorkSet"},
                    {"id": "SET_4", "type": "RestSet", "timeInSeconds": 90, "subCategory": "WorkSet"},
                    {"id": "SET_5", "type": "BodyWeightSet", "reps": 10, "additionalWeight": 5.0, "subCategory": "WorkSet"},
                ],
                exercise_type="BODY_WEIGHT",
                equipment_id=None,
                body_weight_percentage=65.0,
                generate_warm_up_sets=False,
                progression_mode="AUTO_REGULATION",
                keep_screen_on=False,
                show_countdown_timer=False,
                intra_set_rest_in_seconds=None,
                muscle_groups=["BACK_UPPER_BACK", "FRONT_BICEPS"],
                secondary_muscle_groups=["BACK_DELTOIDS"],
                required_accessory_equipment_ids=["ACCESSORY_0"],
                requires_load_calibration=False,
                exercise_category="MODERATE_COMPOUND",
            ),
            "minReps": 8,
            "maxReps": 12,
        },
    ),
    "COUNTDOWN": _build_emission_profile(
        exercise_type="COUNTDOWN",
        allowed_work_set_type="TimedDurationSet",
        required_top_level_fields=COMMON_EXERCISE_REQUIRED_TOP_LEVEL_FIELDS,
        forbidden_top_level_fields=TIMED_FORBIDDEN_TOP_LEVEL_FIELDS,
        required_set_level_fields=TIMED_REQUIRED_SET_LEVEL_FIELDS,
        forbidden_set_level_fields=TIMED_FORBIDDEN_SET_LEVEL_FIELDS,
        schema=COUNTDOWN_EXERCISE_SCHEMA,
        instruction_text=(
            "COUNTDOWN contract:\n"
            "- Output one Exercise object shaped exactly like the COUNTDOWN schema.\n"
            "- Work sets must be TimedDurationSet objects only.\n"
            "- RestSet is allowed only between adjacent timed work sets when the plan includes restBetweenSetsSeconds.\n"
            "- TimedDurationSet uses timeInMillis, autoStart, and autoStop. Do not emit reps, weight, additionalWeight, or subCategory on timed work sets.\n"
            "- Do not output minReps or maxReps.\n"
            "- bodyWeightPercentage must be present and set to null.\n"
            "- showCountDownTimer must be true.\n"
            "- exerciseCategory must be null.\n"
            "- Copy exact plan-owned values for id, exerciseType, equipmentId, requiredAccessoryEquipmentIds, and any timed work-set count/rest constraints.\n"
        ),
        example_object=_exercise_example_base(
            exercise_id="EXERCISE_WARMUP",
            name="Warm Up",
            sets=[
                {"id": "SET_WARMUP", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
                {"id": "SET_6", "type": "RestSet", "timeInSeconds": 60, "subCategory": "WorkSet"},
                {"id": "SET_7", "type": "TimedDurationSet", "timeInMillis": 300000, "autoStart": True, "autoStop": True},
            ],
            exercise_type="COUNTDOWN",
            equipment_id=None,
            body_weight_percentage=None,
            generate_warm_up_sets=False,
            progression_mode="OFF",
            keep_screen_on=False,
            show_countdown_timer=True,
            intra_set_rest_in_seconds=None,
            muscle_groups=["FRONT_QUADRICEPS"],
            secondary_muscle_groups=[],
            required_accessory_equipment_ids=[],
            requires_load_calibration=False,
            exercise_category=None,
        ),
    ),
    "COUNTUP": _build_emission_profile(
        exercise_type="COUNTUP",
        allowed_work_set_type="EnduranceSet",
        required_top_level_fields=COMMON_EXERCISE_REQUIRED_TOP_LEVEL_FIELDS,
        forbidden_top_level_fields=TIMED_FORBIDDEN_TOP_LEVEL_FIELDS,
        required_set_level_fields=TIMED_REQUIRED_SET_LEVEL_FIELDS,
        forbidden_set_level_fields=TIMED_FORBIDDEN_SET_LEVEL_FIELDS,
        schema=COUNTUP_EXERCISE_SCHEMA,
        instruction_text=(
            "COUNTUP contract:\n"
            "- Output one Exercise object shaped exactly like the COUNTUP schema.\n"
            "- Work sets must be EnduranceSet objects only.\n"
            "- RestSet is allowed only between adjacent timed work sets when the plan includes restBetweenSetsSeconds.\n"
            "- EnduranceSet uses timeInMillis, autoStart, and autoStop. Do not emit reps, weight, additionalWeight, or subCategory on timed work sets.\n"
            "- Do not output minReps or maxReps.\n"
            "- bodyWeightPercentage must be present and set to null.\n"
            "- exerciseCategory must be null.\n"
            "- Copy exact plan-owned values for id, exerciseType, equipmentId, requiredAccessoryEquipmentIds, and any timed work-set count/rest constraints.\n"
        ),
        example_object=_exercise_example_base(
            exercise_id="EXERCISE_2",
            name="Air Bike",
            sets=[
                {"id": "SET_8", "type": "EnduranceSet", "timeInMillis": 60000, "autoStart": True, "autoStop": True},
                {"id": "SET_9", "type": "RestSet", "timeInSeconds": 30, "subCategory": "WorkSet"},
                {"id": "SET_10", "type": "EnduranceSet", "timeInMillis": 60000, "autoStart": True, "autoStop": True},
            ],
            exercise_type="COUNTUP",
            equipment_id=None,
            body_weight_percentage=None,
            generate_warm_up_sets=False,
            progression_mode="OFF",
            keep_screen_on=False,
            show_countdown_timer=False,
            intra_set_rest_in_seconds=None,
            muscle_groups=["FRONT_QUADRICEPS"],
            secondary_muscle_groups=[],
            required_accessory_equipment_ids=[],
            requires_load_calibration=False,
            exercise_category=None,
        ),
    ),
}


def get_exercise_emission_profile(exercise_type):
    profile = EXERCISE_EMISSION_PROFILES.get(exercise_type)
    if profile is None:
        raise ValueError(f"Unsupported exercise emission profile for exerciseType={exercise_type!r}")
    return {
        **profile,
        "schema": copy.deepcopy(profile["schema"]),
        "example_object": copy.deepcopy(profile["example_object"]),
    }

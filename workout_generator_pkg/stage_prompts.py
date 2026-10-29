"""Workflow-stage prompt and example definitions for workout generation."""

import json

from .constants import (
    EXERCISE_CATEGORY_ENUM_VALUES,
    EXERCISE_TYPE_ENUM_VALUES,
    JSON_SCHEMA,
    MUSCLE_GROUP_ENUM_VALUES,
    SET_SUBCATEGORY_ENUM_VALUES,
    WORKOUT_COMPONENT_TYPE_VALUES,
    SCHEMA_REPAIR_INSTRUCTION,
)

# Simplified equipment schema for incremental generation
EQUIPMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "equipments": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"$ref": "#/$defs/EquipmentBarbell"},
                    {"$ref": "#/$defs/EquipmentDumbbells"},
                    {"$ref": "#/$defs/EquipmentDumbbell"},
                    {"$ref": "#/$defs/EquipmentPlateLoadedCable"},
                    {"$ref": "#/$defs/EquipmentWeightVest"},
                    {"$ref": "#/$defs/EquipmentMachine"},
                    {"$ref": "#/$defs/EquipmentCardioMachine"},
                ]
            },
        }
    },
    "$defs": JSON_SCHEMA["$defs"],
}

EQUIPMENT_EXAMPLE = {
    "equipments": [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [
                {"weight": 20.0, "thickness": 30.0},
                {"weight": 15.0, "thickness": 25.0},
                {"weight": 10.0, "thickness": 20.0},
            ],
            "barWeight": 20.0,
            "sleeveLength": 406,
        },
        {
            "id": "EQUIPMENT_1",
            "type": "DUMBBELLS",
            "name": "Standard Dumbbells",
            "maxExtraWeightsPerLoadingPoint": 0,
            "extraWeights": [],
            "dumbbells": [
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0},
            ],
        },
        {
            "id": "EQUIPMENT_2",
            "type": "DUMBBELL",
            "name": "Single Dumbbell",
            "maxExtraWeightsPerLoadingPoint": 0,
            "extraWeights": [],
            "dumbbells": [
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0},
            ],
        },
        {
            "id": "EQUIPMENT_3",
            "type": "PLATELOADEDCABLE",
            "name": "Cable Machine",
            "availablePlates": [
                {"weight": 10.0, "thickness": 20.0},
                {"weight": 5.0, "thickness": 15.0},
                {"weight": 2.5, "thickness": 10.0},
            ],
            "sleeveLength": 300,
        },
        {
            "id": "EQUIPMENT_4",
            "type": "WEIGHTVEST",
            "name": "Weight Vest",
            "availableWeights": [
                {"weight": 5.0},
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0},
            ],
        },
        {
            "id": "EQUIPMENT_5",
            "type": "MACHINE",
            "name": "Weight Machine",
            "availableWeights": [
                {"weight": 5.0},
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0},
                {"weight": 25.0},
            ],
            "maxExtraWeightsPerLoadingPoint": 2,
            "extraWeights": [
                {"weight": 2.5},
                {"weight": 5.0},
            ],
        },
        {
            "id": "EQUIPMENT_6",
            "type": "ACCESSORY",
            "name": "Resistance Bands",
        },
    ]
}

EQUIPMENT_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations).\n"
    "Generate only the equipment list using placeholder IDs (EQUIPMENT_X, ACCESSORY_X).\n"
    "Do not use real UUIDs. Do not use IRONNECK.\n\n"
    "Allowed types (exact): BARBELL, DUMBBELLS, DUMBBELL, PLATELOADEDCABLE, WEIGHTVEST, MACHINE, CARDIO_MACHINE, ACCESSORY.\n"
    "Required structures:\n"
    "- BARBELL/PLATELOADEDCABLE availablePlates: array of {weight, thickness} objects.\n"
    "- DUMBBELLS/DUMBBELL extraWeights and dumbbells: array of {weight} objects.\n"
    "- WEIGHTVEST availableWeights: array of {weight} objects.\n"
    "- MACHINE availableWeights and extraWeights: array of {weight} objects.\n"
    "- CARDIO_MACHINE: id, type, name only; use for stationary cardio machines, never weight-loaded equipment.\n"
    "- ACCESSORY: id, type, name only.\n"
    "Never output numeric arrays for weight lists.\n\n"
    "Output format:\n"
    f"{json.dumps(EQUIPMENT_EXAMPLE, indent=2)}\n\n"
    "Generate all equipment needed for the workout based on the conversation."
)

EXERCISE_SCHEMA = {
    "type": "object",
    "properties": {
        "exercises": {
            "type": "array",
            "items": {"$ref": "#/$defs/Exercise"},
        }
    },
    "$defs": JSON_SCHEMA["$defs"],
}

EXERCISE_EXAMPLE = {
    "exercises": [
        {
            "id": "EXERCISE_WARMUP",
            "type": "Exercise",
            "enabled": True,
            "name": "Warm Up",
            "notes": "",
            "sets": [
                {
                    "id": "SET_WARMUP",
                    "type": "TimedDurationSet",
                    "timeInMillis": 300000,
                    "autoStart": True,
                    "autoStop": True,
                }
            ],
            "exerciseType": "COUNTDOWN",
            "equipmentId": None,
            "bodyWeightPercentage": None,
            "generateWarmUpSets": False,
            "progressionMode": "OFF",
            "keepScreenOn": False,
            "showCountDownTimer": True,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_QUADRICEPS"],
            "secondaryMuscleGroups": [],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": None,
        },
        {
            "id": "EXERCISE_0",
            "type": "Exercise",
            "enabled": True,
            "name": "Back Squat",
            "notes": "",
            "sets": [
                {
                    "id": "SET_0",
                    "type": "WeightSet",
                    "reps": 5,
                    "weight": 100.0,
                    "subCategory": "WorkSet",
                },
                {
                    "id": "SET_1",
                    "type": "RestSet",
                    "timeInSeconds": 120,
                    "subCategory": "WorkSet",
                },
            ],
            "exerciseType": "WEIGHT",
            "minReps": 5,
            "maxReps": 5,
            "equipmentId": "EQUIPMENT_0",
            "bodyWeightPercentage": None,
            "generateWarmUpSets": True,
            "progressionMode": "AUTO_REGULATION",
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_QUADRICEPS", "BACK_GLUTEAL"],
            "secondaryMuscleGroups": [],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": "HEAVY_COMPOUND",
        },
        {
            "id": "EXERCISE_1",
            "type": "Exercise",
            "enabled": True,
            "name": "Ring Rows",
            "notes": "",
            "sets": [
                {
                    "id": "SET_2",
                    "type": "BodyWeightSet",
                    "reps": 8,
                    "additionalWeight": 5.0,
                    "subCategory": "WorkSet",
                },
                {
                    "id": "SET_3",
                    "type": "RestSet",
                    "timeInSeconds": 90,
                    "subCategory": "WorkSet",
                },
                {
                    "id": "SET_4",
                    "type": "BodyWeightSet",
                    "reps": 8,
                    "additionalWeight": 5.0,
                    "subCategory": "WorkSet",
                },
            ],
            "exerciseType": "BODY_WEIGHT",
            "minReps": 5,
            "maxReps": 10,
            "equipmentId": None,
            "bodyWeightPercentage": 65.0,
            "generateWarmUpSets": False,
            "progressionMode": "AUTO_REGULATION",
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": ["FRONT_BICEPS", "BACK_DELTOIDS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "requiresLoadCalibration": False,
            "exerciseCategory": "MODERATE_COMPOUND",
        },
    ]
}

EXERCISE_SYSTEM_PROMPT = (
    "Preserve supplied library movement fields and muscle roles exactly; never reclassify them to fit a workout.\n"
    "Output JSON only (no markdown/explanations).\n"
    "Generate only the exercise list with placeholder IDs (EXERCISE_X, SET_X). Do not use UUIDs.\n"
    "Use only provided equipment/accessory placeholder IDs.\n\n"
    "Placeholder ID rules:\n"
    "- Use exact canonical numeric placeholders only: EXERCISE_<number>, SET_<number>, EQUIPMENT_<number>, ACCESSORY_<number>.\n"
    "- Do not invent semantic suffixes like EXERCISE_D1, SET_A_0, WORKOUT_PUSH, etc.\n"
    "Output completeness (required):\n"
    "- Never leave required fields empty or invalid.\n"
    "- If the exercise brief explicitly allows empty muscleGroups, an empty array is allowed when primary movers are genuinely unclear.\n"
    "- Preserve supplied muscle roles and approved prescriptions; do not infer missing material inputs from exercise names or noisy text.\n"
    "- Only harmless formatting defaults may be inferred. Report missing or contradictory required inputs explicitly rather than fabricating loads, reps, sets, rests or movement identity.\n\n"
    "Core constraints:\n"
    "- Name normalization: exercise name must be movement-only (no equipment/accessory words and no set/time details).\n"
    "- Remove equipment/accessory wording from names, e.g.:\n"
    "  * 'Barbell Back Squat' -> 'Back Squat'\n"
    "  * 'DB Bulgarian Split Squat' -> 'Bulgarian Split Squat'\n"
    "  * 'Cable Triceps Pushdown' -> 'Triceps Pushdown'\n"
    "  * '1-Arm DB Row (bench-supported)' -> '1-Arm Row'\n"
    "  * 'Warm up (spin bike)' -> 'Warm Up'\n"
    "- Type/set consistency: WEIGHT->WeightSet, BODY_WEIGHT->BodyWeightSet, COUNTUP->EnduranceSet, COUNTDOWN->TimedDurationSet. RestSet allowed only between sets.\n"
    f"- Valid ExerciseType enum values: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- Valid ExerciseCategory enum values: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    f"- Valid SetSubCategory enum values: {SET_SUBCATEGORY_ENUM_VALUES}.\n"
    "- TimedDurationSet/EnduranceSet use timeInMillis and do not include subCategory.\n"
    "- For COUNTUP/COUNTDOWN exercises, omit minReps and maxReps entirely (reps do not apply).\n"
    "- WEIGHT/BODY_WEIGHT exercises use positive minReps/maxReps when provided.\n"
    f"- muscleGroups must use valid MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- Keep muscleGroups non-empty unless the exercise brief explicitly allows an empty array.\n"
    "- requiredAccessoryEquipmentIds must use ACCESSORY_X placeholders (use [] when none).\n"
    "- CARDIO_MACHINE equipmentId is valid only for COUNTUP or COUNTDOWN exercises.\n"
    "- Non-cardio weight-loaded equipmentId is valid for WEIGHT, BODY_WEIGHT, COUNTUP, or COUNTDOWN exercises.\n"
    "- For externally loaded COUNTUP/COUNTDOWN work sets, use targetWeight from the selected equipment's available loads; omit it for cardio machines.\n"
    "- BODY_WEIGHT exercises must include bodyWeightPercentage and it must never be null.\n"
    "- bodyWeightPercentage uses percentage semantics, not unit fractions. Example: use 100.0 for full bodyweight and 65.0 for about sixty-five percent of bodyweight; do not use 1.0 to mean 100%.\n"
    "- bodyWeightPercentage is the percentage of the user's body mass that counts toward the movement's effective load baseline.\n"
    "- WEIGHT/COUNTUP/COUNTDOWN exercises must set bodyWeightPercentage to null.\n"
    "- WEIGHT work sets use weight and must never use additionalWeight.\n"
    "- BODY_WEIGHT work sets use additionalWeight and must never use weight.\n"
    "- If exact work-set loads are supplied, preserve them exactly.\n"
    "- Set weights/additionalWeight must be valid for equipment combinations.\n\n"
    "Timed exercise rule:\n"
    "- For COUNTDOWN exercises, emit exactly one TimedDurationSet, no RestSet, and showCountDownTimer=true.\n\n"
    "Other required behavior:\n"
    "- Preserve the supplied code-generated notes exactly; do not author technique or placement notes.\n"
    "- Set exerciseCategory for WEIGHT/BODY_WEIGHT (HEAVY_COMPOUND, MODERATE_COMPOUND, ISOLATION); null for COUNTUP/COUNTDOWN.\n"
    "- Set generateWarmUpSets explicitly to true or false for every exercise.\n"
    "- Set generateWarmUpSets=true for exercises that should normally ramp into work sets, especially heavy or technically demanding compound lifts with meaningful external load.\n"
    "- Set generateWarmUpSets=false for timed/cardio work, light isolation work, and exercises where extra ramp-up sets are not warranted.\n"
    "- If the conversation or plan explicitly says an exercise should or should not have warm-up sets, follow that instruction exactly.\n"
    "- A dedicated warm-up entry is handled by the plan/workout structure; do not invent one inside an unrelated exercise definition.\n"
    "- Unilateral intent must be encoded explicitly via intraSetRestInSeconds. This field means the rest in whole seconds between the two sides of one logical unilateral set, for example Left side, then rest, then Right side. Use a positive integer only for that unilateral side-to-side rest; otherwise set intraSetRestInSeconds=null.\n"
    "- progressionMode must be either OFF or AUTO_REGULATION. Do not use DOUBLE_PROGRESSION for now.\n"
    "- AUTO_REGULATION means double progression plus per-set RIR (or auto RIR) on every work set except the last.\n"
    "- Use AUTO_REGULATION for load-based exercises that should keep progressing once the work-set loads are known.\n"
    "- Use OFF for timed/cardio work and exercises that should not auto-progress.\n"
    "- requiresLoadCalibration is code-owned. Emit false as the required schema placeholder; Python derives the app's native calibration mode from exercise type, available load evidence and policy. Do not prescribe calibration sets, trial counts or calibration rests.\n"
    "- Optional HR/load-jump fields only when explicitly requested; otherwise null.\n\n"
    "Output format:\n"
    f"{json.dumps(EXERCISE_EXAMPLE, indent=2)}\n\n"
    "Emit only the requested exercise object(s) from the approved plan entries; do not add exercises or re-plan."
)

WORKOUT_STRUCTURE_EXAMPLE = {
    "workoutMetadata": {
        "name": "Example Workout",
        "description": "Example description",
        "order": 0,
        "enabled": True,
        "usePolarDevice": False,
        "creationDate": "2026-01-06",
        "isActive": True,
        "timesCompletedInAWeek": None,
        "type": 0,
    },
    "workoutComponents": [
        {
            "componentType": "Exercise",
            "exerciseId": "EXERCISE_0",
            "enabled": True,
        },
        {
            "componentType": "Rest",
            "enabled": True,
            "timeInSeconds": 180,
        },
        {
            "componentType": "Superset",
            "enabled": True,
            "exerciseIds": ["EXERCISE_1", "EXERCISE_2"],
            "restSecondsByExercise": {
                "EXERCISE_1": 0,
                "EXERCISE_2": 90,
            },
        },
    ],
}

WORKOUT_STRUCTURE_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations).\n"
    "Generate one workout structure using placeholder IDs (WORKOUT_X, COMPONENT_X, EXERCISE_X).\n\n"
    "Placeholder ID rules:\n"
    "- Use exact canonical numeric placeholders only: WORKOUT_<number>, COMPONENT_<number>, EXERCISE_<number>.\n"
    "- Do not invent semantic suffixes like WORKOUT_A, COMPONENT_DAY1, EXERCISE_D3, etc.\n"
    "Structure rules:\n"
    "- Return workoutMetadata + workoutComponents only.\n"
    "- workoutMetadata.order is 0-based and follows workout order.\n"
    "- workoutMetadata.description must be a short training-focus label within its supplied character budget; the final export including schedule text is capped at 50.\n"
    "- Make workoutMetadata.description a compact training-focus summary, not an exhaustive exercise list.\n"
    "- Prefer at most 2 to 4 short focus terms or movement themes.\n"
    f"- workoutComponents may contain only valid componentType values: {WORKOUT_COMPONENT_TYPE_VALUES}.\n"
    "- Never output null/empty components.\n\n"
    "Rest rules:\n"
    "- RestSet is internal to exercise.sets and must not be created here.\n"
    "- Rest component is between exercises in workoutComponents.\n"
    "- If restToNextSeconds is provided, use values exactly.\n"
    "- All rest values must be exact seconds, never ranges.\n"
    "- If a transition rest value is 0, do not add a Rest component.\n\n"
    "Warm-up rules:\n"
    "- Include a warm-up exercise reference only if it already exists in the workout plan entry's exerciseIds.\n"
    "- Do not invent or prepend EXERCISE_WARMUP when it is not present in the workout plan entry.\n\n"
    "Superset rules:\n"
    "- Include exerciseIds and restSecondsByExercise mapping with exactly one entry for every grouped exercise ID.\n"
    "- restSecondsByExercise[exerciseId] is the exact rest inserted immediately after that exercise during every work round.\n"
    "- For ordered exercises [A, B, C], A's value is the rest before B, B's value is the rest before C, and C's value is the rest before A in the next round.\n"
    "- The runtime automatically omits C's rest after the final round; do not create a separate Rest component for an internal superset transition.\n"
    "- Use 0 when the next grouped exercise should start immediately. Never omit a map entry and never invent a fallback.\n"
    "- Superset must include at least two valid exercises.\n\n"
    "Output format:\n"
    f"{json.dumps(WORKOUT_STRUCTURE_EXAMPLE, indent=2)}\n\n"
    "Generate workout structure based on the conversation and exercise list."
)

PLAN_INDEX_EXAMPLE = {
    "planName": "Example Strength Plan",
    "auditTargets": {"weeklyEffectiveSets": {}, "perSessionEffectiveSets": {}, "maximumSessionSeconds": None},
    "equipments": [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell",
        }
    ],
    "accessoryEquipments": [
        {
            "id": "ACCESSORY_0",
            "type": "ACCESSORY",
            "name": "Gymnastic Rings",
        }
    ],
    "exercises": [
        {
            "id": "EXERCISE_0",
            "equipmentId": "EQUIPMENT_0",
            "name": "Back Squat",
            "exerciseType": "WEIGHT",
            "bodyWeightPercentage": None,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["BACK_GLUTEAL", "FRONT_QUADRICEPS"],
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "HEAVY_COMPOUND",
            "numWorkSets": 2,
            "generateWarmUpSets": True,
            "minReps": 6,
            "maxReps": 10,
            "restBetweenSetsSeconds": 120,
            "targetSetPrescriptions": [
                {"workSetIndex": 0, "reps": 8, "weight": 100.0},
                {"workSetIndex": 1, "reps": 8, "weight": 100.0},
            ],
        },
        {
            "id": "EXERCISE_1",
            "equipmentId": None,
            "name": "Ring Row",
            "exerciseType": "BODY_WEIGHT",
            "bodyWeightPercentage": 65.0,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["BACK_UPPER_BACK"],
            "secondaryMuscleGroups": ["FRONT_BICEPS", "BACK_DELTOIDS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "exerciseCategory": "MODERATE_COMPOUND",
            "numWorkSets": 2,
            "generateWarmUpSets": False,
            "minReps": 8,
            "maxReps": 12,
            "restBetweenSetsSeconds": 90,
            "targetSetPrescriptions": [
                {"workSetIndex": 0, "reps": 10, "additionalWeight": 5.0},
                {"workSetIndex": 1, "reps": 10, "additionalWeight": 5.0},
            ],
        },
    ],
    "workouts": [
        {
            "id": "WORKOUT_0",
            "name": "Example Workout",
            "exerciseIds": ["EXERCISE_0", "EXERCISE_1"],
            "hasSupersets": False,
            "supersetGroups": [],
            "hasRestComponents": True,
            "restToNextSeconds": [90, 0],
        }
    ],
}

PLAN_INDEX_SYSTEM_PROMPT = (
    "Preserve supplied library movement fields and muscle roles exactly; never reclassify them to fit a workout.\n"
    "Output JSON only (no markdown/explanations).\n"
    "Exercise entries in the PlanIndex are workout-specific prescriptions, not reusable identity records.\n"
    "When an exercise-library catalog is supplied, every exercise must include a listed libraryDefinitionId.\n"
    "Never create a movement outside that catalog. nameOverride may provide a workout-local alias.\n"
    "Use generateWarmUpSets for app-generated ramp-up sets. Do not invent a standalone generic Warm Up or EXERCISE_WARMUP. An explicitly selected library warm-up exercise still needs a unique numeric EXERCISE_X prescription per occurrence.\n"
    "For periodized or versioned programming, emit a separate EXERCISE_X prescription for each "
    "independently programmed occurrence, even when multiple occurrences share the same movement.\n"
    "Shared movement identity fields (name, exerciseType, equipmentId, body-weight semantics, muscles, "
    "accessories, category, and movement reference) must remain identical across those occurrences; "
    "sets, reps, loads, rests, progression, and execution settings may differ.\n"
    "Generate a PlanIndex (not full workout JSON) using placeholder IDs only.\n"
    "IDs: EQUIPMENT_X, ACCESSORY_X, EXERCISE_X, WORKOUT_X.\n\n"
    "Placeholder ID rules:\n"
    "- Use exact canonical numeric placeholders only: EQUIPMENT_<number>, ACCESSORY_<number>, EXERCISE_<number>, WORKOUT_<number>.\n"
    "- Do not invent semantic suffixes like EQUIPMENT_HOME, EXERCISE_D1, WORKOUT_PUSH, etc.\n"
    "Plan constraints:\n"
    "- Include a top-level planName string for the single workout plan package.\n\n"
    "Equipment constraints:\n"
    "- Provided equipment/accessory lists are immutable.\n"
    "- Reuse existing IDs when available (especially accessories by same name).\n"
    "- Create new items only when missing, with non-conflicting placeholders.\n"
    "- equipmentId must be null or an EQUIPMENT_X placeholder only. Never use an ACCESSORY_X as equipmentId.\n"
    "- requiredAccessoryEquipmentIds must contain ACCESSORY_X placeholders only. Never use an EQUIPMENT_X there.\n"
    "- Ensure all equipmentId/requiredAccessoryEquipmentIds references exist.\n"
    "- CARDIO_MACHINE equipmentId is valid only for COUNTUP or COUNTDOWN exercises.\n"
    "- Non-cardio weight-loaded equipment is valid for WEIGHT, BODY_WEIGHT, COUNTUP, or COUNTDOWN exercises.\n"
    "- A timed exercise may prescribe targetWeight only when its selected non-cardio equipment supplies that load; cardio-machine timed sets omit it.\n\n"
    "Exercise constraints:\n"
    "- Exercise names must be movement-only labels (remove equipment/accessory wording and set/time details).\n"
    "- Examples: 'Barbell Back Squat' -> 'Back Squat', 'Cable Triceps Pushdown' -> 'Triceps Pushdown', 'Warm up (spin bike)' -> 'Warm Up'.\n"
    f"- exerciseType must use one of: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    "- MANDATORY runs: a stated run ('800 mt run', '1200 mt run') MUST use the 'Run' library entry (exerciseType RUNNING) and its prescription MUST carry targetDistanceMeters in meters. Never encode a run as reps or as a different movement.\n"
    f"- exerciseCategory (when present) must use one of: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    "- For accessory-dependent exercises, use requiredAccessoryEquipmentIds with ACCESSORY_X IDs; use [] when none.\n"
    f"- Use valid MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- If user provided sets/reps/rest structure, copy exact work-set counts and exact rest values into numWorkSets and restBetweenSetsSeconds for any exercise type when they are known.\n"
    "- Unilateral intent must be encoded explicitly via intraSetRestInSeconds.\n"
    "- intraSetRestInSeconds means the exact rest in whole seconds between the two sides of one logical unilateral set, for example left side, then rest, then right side.\n"
    "- CRITICAL: Every unilateral or single-side exercise (for example single-arm row, split squat, lunge, step-up, single-leg calf raise) MUST include an LLM-chosen exact positive integer intraSetRestInSeconds. null, 0, and omission are invalid; never rely on a generator default.\n"
    "- If the exercise is not unilateral, set intraSetRestInSeconds to null.\n"
    "- For timed exercises, numWorkSets counts timed work intervals and must be a positive integer when provided; omit minReps/maxReps for COUNTUP/COUNTDOWN.\n"
    "- MANDATORY cardio quantities: when the request states a distance or calories for a rowing, biking, skiing or running movement (for example 'max mt row (target 1100/1000)', '24/20 cal', '800 mt run'), the timed COUNTUP/COUNTDOWN prescription for that movement MUST carry targetDistanceMeters (in meters) or targetCalories, using the first value of male/female pairs. Omit both fields for all other exercises.\n"
    "- Goal-based sets without a stated duration: use autoStart=true and autoStop=false with timeInMillis=0 so the watch counts up and shows the target while the athlete works; autoStop=true is only valid with a positive timeInMillis.\n"
    "- restBetweenSetsSeconds must always be exact integers in seconds, never ranges.\n"
    "- If the request mentions a rest range, choose one exact value within that range and store only that exact value.\n"
    "- If user provided exact working loads, store them in targetSetPrescriptions.\n"
    "- Treat exact working loads in the request as mandatory structured output, not optional detail.\n"
    "- When an exercise line in the request includes an exact load such as '64kg', '21kgx2', '+4kg', or '(97kg)', you MUST emit targetSetPrescriptions for that exercise.\n"
    "- Do not leave a load-based exercise without targetSetPrescriptions if the request already specified the exact working load.\n"
    "- For those exact-load exercises, emit one targetSetPrescriptions item per work set and copy the exact load into every work set unless the request explicitly varies it by set.\n"
    "- Use targetSetPrescriptions for exact per-set targets, including reps-only targets when no starting load is prescribed and app-native load calibration is appropriate. Omit the load from every target in that calibration case; do not invent a numeric starting load.\n"
    "- Do not include targetSetPrescriptions for COUNTUP, COUNTDOWN, warm-up, or movement-only entries.\n"
    "- targetSetPrescriptions is an ordered list of indexed work sets only, one item per work set.\n"
    "- Every targetSetPrescriptions item must include workSetIndex, where workSetIndex is 0-based among work sets only.\n"
    "- Rest sets do not count toward workSetIndex.\n"
    "- Warm-up sets do not count toward workSetIndex.\n"
    "- Exercises that move the user's bodyweight, with or without extra vest/ring/pull-up load, must use exerciseType BODY_WEIGHT, not WEIGHT.\n"
    "- If the plan specifies baseline bodyweight and/or added load (for example dips, pull-ups, chin-ups, nordics, ab wheel, push-ups), use BODY_WEIGHT and store target loads as additionalWeight.\n"
    "- Every BODY_WEIGHT exercise in the PlanIndex must include bodyWeightPercentage explicitly. Do not omit it and do not leave it null.\n"
    "- bodyWeightPercentage is the percentage of the user's body mass that counts as the exercise's baseline load before any additionalWeight is added.\n"
    "- Use percentage semantics, not unit fractions. Example: use 100.0 for full bodyweight and 65.0 for about sixty-five percent of bodyweight; do not use 1.0 to mean 100%.\n"
    "- Preserve the correct load semantics from the source when choosing exerciseType, bodyWeightPercentage, and target-set load fields.\n"
    "- For BODY_WEIGHT exercises with positive additionalWeight targets, choose a real load-bearing primary equipmentId when one exists, such as a WEIGHTVEST. Do not leave equipmentId null if the added load comes from a primary load-bearing item.\n"
    "- Keep support gear such as rings, dip bars, benches, or pull-up bars in requiredAccessoryEquipmentIds, not equipmentId.\n"
    "- Do not use exerciseType WEIGHT together with additionalWeight targets.\n"
    "- Do not use exerciseType BODY_WEIGHT together with weight targets.\n"
    "- Preserve exact equipment semantics when the user or context specifies them. DUMBBELL means a single implement load; DUMBBELLS means paired implements with total selectable loads across both hands.\n"
    "- When the planner input lists selectable app loads for a provided equipment item, exact target loads must match those listed selectable values for the chosen equipmentId.\n"
    "- For exact target loads, choose an equipmentId whose selectable app loads can represent those exact values.\n"
    "- For WEIGHT exercises with a fixed load, each item must be {workSetIndex, reps, weight}; with native calibration, use {workSetIndex, reps}.\n"
    "- For BODY_WEIGHT exercises with a fixed added load, each item must be {workSetIndex, reps, additionalWeight}; with native calibration, use {workSetIndex, reps}.\n"
    "- Preserve exact load targets when they are provided.\n\n"
    "Workout plan constraints:\n"
    "- Include auditTargets: {weeklyEffectiveSets: {muscle: {minimum: number, maximum: number|null}}, perSessionEffectiveSets: {muscle: {minimum: number, maximum: number|null}}, maximumSessionSeconds: integer|null}. A null volume maximum means the source specified no upper limit.\n"
    "- Preserve the approved audit target keys exactly; do not introduce, split or merge target groups.\n"
    "- Copy the user's AGREED numeric targets, including explicitly accepted tradeoffs, into auditTargets. Never replace targets with the model's claimed achieved totals or lower them to fit a failing plan. Use empty maps/null for unspecified goals. Do not assign weekly targets across unrelated periodized phases.\n"
    "- For the programming audit, encode numWorkSets and generateWarmUpSets explicitly for every exercise, and maxReps for strength exercises.\n"
    "- Use only library muscleGroups (primary) and secondaryMuscleGroups (secondary). The deterministic audit credits each primary muscle group once per logical working set and each secondary group at 0.5, regardless of exercise category, with no primary/secondary double-counting. Do not infer additional muscles or require extra annotations.\n"
    "- Duration audit assumptions: 3 seconds per rep (both sides for unilateral sets), all executed rests, 5 minutes general warm-up, 2 minutes per exercise with generated warm-ups, and 60 seconds per exercise/setup transition. Fit the agreed time limit under these assumptions.\n"
    "- Preserve exact workout names from user plan (including day labels/prefixes such as 'A -', 'Day A:', etc.).\n"
    "- workout.exerciseIds defines exact order.\n"
    "- If provided, restToNextSeconds must match exerciseIds length and values exactly.\n"
    "- restToNextSeconds must always use exact integers in seconds, never ranges.\n"
    "- If the plan uses supersets, populate workout.supersetGroups explicitly.\n"
    "- Each supersetGroups item must be an object with exerciseIds containing the exact grouped exercises in order.\n"
    "- Superset exerciseIds must be a contiguous subsequence of workout.exerciseIds.\n"
    "- Do not rely on hasSupersets alone; when any exercises are supersetted, supersetGroups must encode the exact grouping.\n"
    "- Every supersetGroups item must include restSecondsByExercise with exactly one non-negative integer value per grouped exercise ID. These are the rests inside each round.\n"
    "- Inside an ordered superset [A, B, C], A's map value is rest before B, B's value is rest before C, and C's value is rest before A in the next round.\n"
    "- The last grouped exercise therefore carries the between-round rest even when it is the final exercise in the workout; it is not an outer Rest component after the completed superset.\n"
    "- restToNextSeconds remains required and represents standalone transitions: use 0 for non-final members of a superset and the desired outer transition rest after its last member. A final block may have outer rest 0 while retaining its between-round recovery in the group map.\n"
    "- Unless the user requested otherwise, use 0 between grouped exercises and choose one exact recovery duration after the final grouped exercise.\n"
    "- MANDATORY time caps: every AMRAP, rounds-for-time, or block the request bounds with a time window ('time cap 25\\'', \"In 12' time cap\", \"From 8'-12'\") MUST be a superset whose supersetGroups item carries timeCapSeconds set to that window in seconds (a block running from minute 8 to minute 12 gets timeCapSeconds=240).\n"
    "- MANDATORY AMRAP mode: an AMRAP ('Amrap 12' of: ...') MUST be one superset whose supersetGroups item carries amrap=true and timeCapSeconds set to the window in seconds; its members carry EXACTLY ONE work set each (the watch repeats the round until the cap expires). Never estimate AMRAP rounds by duplicating sets.\n"
    "- MANDATORY EMOM cadence: 'Every N minutes x T minutes' blocks MUST be one superset whose supersetGroups item carries roundDurationSeconds=N and whose members each carry T/N work sets ('Every 2\\' x 10\\'' -> roundDurationSeconds=120, 5 work sets per member). Never combine roundDurationSeconds and timeCapSeconds in the same group.\n"
    "- Every block and movement listed in the request must appear in the workout - never drop a block.\n\n"
    "Output format:\n"
    f"{json.dumps(PLAN_INDEX_EXAMPLE, indent=2)}\n\n"
    "Generate the PlanIndex based on the conversation context."
)

JSON_PATCH_REPAIR_SYSTEM_PROMPT = (
    "You are a JSON schema validation error fixer using JSON Patch (RFC 6902).\n\n"
    + SCHEMA_REPAIR_INSTRUCTION + "\n\n"
    "Fix only the reported failing fields, using Structured repair targets and their schema fragments. "
    "Preserve existing placeholders; never invent UUIDs or movements. "
    "Return only a JSON Patch array, without markdown or a wrapper. Each operation needs op/path and value or from where required by RFC 6902. "
    "For example, a supplied numeric weight of 5 may become {\"weight\":5} when the schema requires an object. "
    "Do not substitute null for a required component. If no evidence-backed repair is possible, return []."
)

"""Workflow-stage prompt and example definitions for workout generation."""

import json

from .constants import (
    EXACT_GENERATION_CONFIRMATION,
    EXAMPLE_JSON,
    EXERCISE_CATEGORY_ENUM_VALUES,
    EXERCISE_TYPE_ENUM_VALUES,
    JSON_SCHEMA,
    MUSCLE_GROUP_ENUM_VALUES,
    SET_SUBCATEGORY_ENUM_VALUES,
    WORKOUT_COMPONENT_TYPE_VALUES,
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
    "Allowed types (exact): BARBELL, DUMBBELLS, DUMBBELL, PLATELOADEDCABLE, WEIGHTVEST, MACHINE, ACCESSORY.\n"
    "Required structures:\n"
    "- BARBELL/PLATELOADEDCABLE availablePlates: array of {weight, thickness} objects.\n"
    "- DUMBBELLS/DUMBBELL extraWeights and dumbbells: array of {weight} objects.\n"
    "- WEIGHTVEST availableWeights: array of {weight} objects.\n"
    "- MACHINE availableWeights and extraWeights: array of {weight} objects.\n"
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
            "secondaryMuscleGroups": ["BACK_HAMSTRING"],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": "HEAVY_COMPOUND",
        },
        {
            "id": "EXERCISE_1",
            "type": "Exercise",
            "enabled": True,
            "name": "Ring Rows",
            "notes": "Pause briefly at the top and control the lowering phase",
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
            "muscleGroups": ["BACK_UPPER_BACK", "FRONT_BICEPS"],
            "secondaryMuscleGroups": ["BACK_DELTOIDS", "BACK_TRAPEZIUS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "requiresLoadCalibration": False,
            "exerciseCategory": "MODERATE_COMPOUND",
        },
    ]
}

EXERCISE_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations).\n"
    "Generate only the exercise list with placeholder IDs (EXERCISE_X, SET_X). Do not use UUIDs.\n"
    "Use only provided equipment/accessory placeholder IDs.\n\n"
    "Placeholder ID rules:\n"
    "- Use exact canonical numeric placeholders only: EXERCISE_<number>, SET_<number>, EQUIPMENT_<number>, ACCESSORY_<number>.\n"
    "- Do not invent semantic suffixes like EXERCISE_D1, SET_A_0, WORKOUT_PUSH, etc.\n"
    "- The only reserved exceptions are EXERCISE_WARMUP and SET_WARMUP.\n\n"
    "Output completeness (required):\n"
    "- Never leave required fields empty or invalid.\n"
    "- If the exercise brief explicitly allows empty muscleGroups, an empty array is allowed when primary movers are genuinely unclear.\n"
    "- Otherwise, do not output empty muscleGroups; if uncertain, infer best primary movers from exercise name.\n"
    "- If user input is ambiguous/noisy, infer sensible schema-valid values rather than leaving blanks.\n\n"
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
    "- Use notes as concise string (max 500 chars).\n"
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
    "- requiresLoadCalibration must always be set to true or false. Use true when calibration is needed; use false when a confident starting load is already specified or can be reasonably inferred.\n"
    "- Optional HR/load-jump fields only when explicitly requested; otherwise null.\n\n"
    "Output format:\n"
    f"{json.dumps(EXERCISE_EXAMPLE, indent=2)}\n\n"
    "Generate all exercises needed for the workout based on the conversation and equipment list."
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
                "EXERCISE_1": 60,
                "EXERCISE_2": 60,
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
    "- The only reserved exception is EXERCISE_WARMUP.\n\n"
    "Structure rules:\n"
    "- Return workoutMetadata + workoutComponents only.\n"
    "- workoutMetadata.order is 0-based and follows workout order.\n"
    "- workoutMetadata.description must be specific and <= 50 chars.\n"
    "- Make workoutMetadata.description a compact training-focus summary, not an exhaustive exercise list.\n"
    "- Prefer at most 2 to 4 short focus terms or movement themes.\n"
    "- Before finalizing, count the characters in workoutMetadata.description; if it exceeds 50, rewrite it until it is <= 50.\n"
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
    "- Include exerciseIds and restSecondsByExercise mapping.\n"
    "- Superset must include at least one valid exercise.\n\n"
    "Output format:\n"
    f"{json.dumps(WORKOUT_STRUCTURE_EXAMPLE, indent=2)}\n\n"
    "Generate workout structure based on the conversation and exercise list."
)

PLAN_INDEX_EXAMPLE = {
    "planName": "Example Strength Plan",
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
            "id": "EXERCISE_WARMUP",
            "equipmentId": None,
            "exerciseType": "COUNTDOWN",
            "name": "Warm Up",
            "bodyWeightPercentage": None,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": ["FRONT_QUADRICEPS"],
        },
        {
            "id": "EXERCISE_0",
            "equipmentId": "EQUIPMENT_0",
            "exerciseType": "WEIGHT",
            "name": "Back Squat",
            "bodyWeightPercentage": None,
            "muscleGroups": ["BACK_GLUTEAL", "FRONT_QUADRICEPS"],
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "HEAVY_COMPOUND",
            "numWorkSets": 2,
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
            "exerciseType": "BODY_WEIGHT",
            "name": "Ring Row",
            "bodyWeightPercentage": 65.0,
            "muscleGroups": ["BACK_UPPER_BACK", "FRONT_BICEPS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "exerciseCategory": "MODERATE_COMPOUND",
            "numWorkSets": 2,
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
    "Output JSON only (no markdown/explanations).\n"
    "Generate a PlanIndex (not full workout JSON) using placeholder IDs only.\n"
    "IDs: EQUIPMENT_X, ACCESSORY_X, EXERCISE_X, WORKOUT_X.\n\n"
    "Placeholder ID rules:\n"
    "- Use exact canonical numeric placeholders only: EQUIPMENT_<number>, ACCESSORY_<number>, EXERCISE_<number>, WORKOUT_<number>.\n"
    "- Do not invent semantic suffixes like EQUIPMENT_HOME, EXERCISE_D1, WORKOUT_PUSH, etc.\n"
    "- The only reserved exception is EXERCISE_WARMUP.\n\n"
    "Plan constraints:\n"
    "- Include a top-level planName string for the single workout plan package.\n\n"
    "Equipment constraints:\n"
    "- Provided equipment/accessory lists are immutable.\n"
    "- Reuse existing IDs when available (especially accessories by same name).\n"
    "- Create new items only when missing, with non-conflicting placeholders.\n"
    "- equipmentId must be null or an EQUIPMENT_X placeholder only. Never use an ACCESSORY_X as equipmentId.\n"
    "- requiredAccessoryEquipmentIds must contain ACCESSORY_X placeholders only. Never use an EQUIPMENT_X there.\n"
    "- Ensure all equipmentId/requiredAccessoryEquipmentIds references exist.\n\n"
    "Exercise constraints:\n"
    "- Exercise names must be movement-only labels (remove equipment/accessory wording and set/time details).\n"
    "- Examples: 'Barbell Back Squat' -> 'Back Squat', 'Cable Triceps Pushdown' -> 'Triceps Pushdown', 'Warm up (spin bike)' -> 'Warm Up'.\n"
    f"- exerciseType must use one of: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- exerciseCategory (when present) must use one of: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    "- For accessory-dependent exercises, use requiredAccessoryEquipmentIds with ACCESSORY_X IDs; use [] when none.\n"
    f"- Use valid MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- If user provided sets/reps/rest structure, copy exact work-set counts and exact rest values into numWorkSets and restBetweenSetsSeconds for any exercise type when they are known.\n"
    "- For timed exercises, numWorkSets counts timed work intervals and must be a positive integer when provided; omit minReps/maxReps for COUNTUP/COUNTDOWN.\n"
    "- restBetweenSetsSeconds and restToNextSeconds must always be exact integers in seconds, never ranges.\n"
    "- If the request mentions a rest range, choose one exact value within that range and store only that exact value.\n"
    "- If user provided exact working loads, store them in targetSetPrescriptions.\n"
    "- Treat exact working loads in the request as mandatory structured output, not optional detail.\n"
    "- When an exercise line in the request includes an exact load such as '64kg', '21kgx2', '+4kg', or '(97kg)', you MUST emit targetSetPrescriptions for that exercise.\n"
    "- Do not leave a load-based exercise without targetSetPrescriptions if the request already specified the exact working load.\n"
    "- For those exact-load exercises, emit one targetSetPrescriptions item per work set and copy the exact load into every work set unless the request explicitly varies it by set.\n"
    "- Only use targetSetPrescriptions for WEIGHT or BODY_WEIGHT exercises that actually have exact work-set load targets.\n"
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
    "- For WEIGHT exercises, each item must be {workSetIndex, reps, weight}.\n"
    "- For BODY_WEIGHT exercises, each item must be {workSetIndex, reps, additionalWeight}.\n"
    "- Preserve exact load targets when they are provided.\n\n"
    "Workout constraints:\n"
    "- Preserve exact workout names from user plan (including day labels/prefixes such as 'A -', 'Day A:', etc.).\n"
    "- workout.exerciseIds defines exact order.\n"
    "- If provided, restToNextSeconds must match exerciseIds length and values exactly.\n"
    "- If the plan uses supersets, populate workout.supersetGroups explicitly.\n"
    "- Each supersetGroups item must be an object with exerciseIds containing the exact grouped exercises in order.\n"
    "- Superset exerciseIds must be a contiguous subsequence of workout.exerciseIds.\n"
    "- Do not rely on hasSupersets alone; when any exercises are supersetted, supersetGroups must encode the exact grouping.\n"
    "- Use restToNextSeconds alongside supersetGroups: for a superset, grouped exercises usually have 0 rest to the next grouped exercise and the last grouped exercise carries the post-superset rest.\n"
    "- Include EXERCISE_WARMUP only when the intended workout actually has a dedicated warm-up exercise.\n"
    "- Do not invent EXERCISE_WARMUP when the workout can be represented without a dedicated warm-up exercise entry.\n\n"
    "Output format:\n"
    f"{json.dumps(PLAN_INDEX_EXAMPLE, indent=2)}\n\n"
    "Generate the PlanIndex based on the conversation context."
)

JSON_PATCH_REPAIR_SYSTEM_PROMPT = (
    "You are a JSON schema validation error fixer using JSON Patch (RFC 6902).\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. You will receive a JSON document with validation errors and a list of error messages\n"
    "2. You must output a JSON Patch array (RFC 6902) that fixes ONLY the validation errors\n"
    "3. Do NOT introduce new UUIDs - the document uses placeholder IDs (EQUIPMENT_X, EXERCISE_X, etc.)\n"
    "4. Do NOT modify fields that are already valid - only fix the specific errors mentioned\n"
    "5. Preserve all placeholder IDs and relationships\n"
    "5b. If you must create or replace a placeholder ID, use exact canonical numeric forms only: EQUIPMENT_<number>, ACCESSORY_<number>, EXERCISE_<number>, WORKOUT_<number>, COMPONENT_<number>, SET_<number>. Reserved exceptions: EXERCISE_WARMUP, SET_WARMUP.\n"
    "6. Use contextually appropriate values when fixing errors (e.g., infer muscle groups from exercise names)\n"
    "7. NEVER set values to null in workoutComponents arrays - if a component is invalid, use \"remove\" operation instead\n"
    "8. When fixing workoutComponents, ensure each element is a complete, valid component object (Exercise, Rest, or Superset)\n"
    "9. If a component cannot be fixed, remove it rather than setting it to null\n\n"
    "EQUIPMENT ARRAY FORMAT REQUIREMENTS:\n"
    "All equipment arrays must contain objects, NOT numbers:\n"
    "- BARBELL/PLATELOADEDCABLE: availablePlates must be array of objects with {weight: number, thickness: number}\n"
    "  Example: [{\"weight\": 20.0, \"thickness\": 30.0}, {\"weight\": 15.0, \"thickness\": 25.0}]\n"
    "- DUMBBELLS/DUMBBELL: dumbbells and extraWeights must be arrays of objects with {weight: number}\n"
    "  Example: [{\"weight\": 10.0}, {\"weight\": 15.0}, {\"weight\": 20.0}]\n"
    "- WEIGHTVEST/MACHINE: availableWeights and extraWeights must be arrays of objects with {weight: number}\n"
    "  Example: [{\"weight\": 5.0}, {\"weight\": 10.0}, {\"weight\": 15.0}]\n"
    "If you see arrays with numbers like [1.0, 2.0, 3.0], convert them to objects: [{\"weight\": 1.0}, {\"weight\": 2.0}, {\"weight\": 3.0}]\n"
    "For plates missing thickness, add a default thickness of 20.0 (mm).\n\n"
    "ENUM CONSTRAINTS (use exact values):\n"
    f"- ExerciseType: {EXERCISE_TYPE_ENUM_VALUES}\n"
    f"- ExerciseCategory: {EXERCISE_CATEGORY_ENUM_VALUES}\n"
    f"- MuscleGroup: {MUSCLE_GROUP_ENUM_VALUES}\n"
    f"- SetSubCategory: {SET_SUBCATEGORY_ENUM_VALUES}\n"
    f"- workoutComponents.componentType: {WORKOUT_COMPONENT_TYPE_VALUES}\n\n"
    "JSON PATCH FORMAT:\n"
    "Output an array of patch operations, each with:\n"
    "- op: The operation (\"add\", \"remove\", \"replace\", \"move\", \"copy\")\n"
    "- path: JSON Pointer to the field (e.g., \"/workouts/0/workoutComponents/2/muscleGroups/0\")\n"
    "- value: The new value (for \"add\" and \"replace\") - NEVER use null for workoutComponents items\n\n"
    "EXAMPLE:\n"
    "If error says 'muscleGroups array is empty' for exercise at /workouts/0/workoutComponents/0:\n"
    "[{\"op\": \"add\", \"path\": \"/workouts/0/workoutComponents/0/muscleGroups\", \"value\": [\"FRONT_QUADRICEPS\", \"BACK_GLUTEAL\"]}]\n"
    "For compound exercises, use 2+ primary groups (e.g. bench -> [\"FRONT_CHEST\", \"FRONT_DELTOIDS\", \"FRONT_TRICEPS\"]).\n\n"
    "If error says 'availableWeights[0] is not of type object' for equipment at /equipments/2:\n"
    "[{\"op\": \"replace\", \"path\": \"/equipments/2/availableWeights\", \"value\": [{\"weight\": 1.0}, {\"weight\": 2.0}, {\"weight\": 3.0}]}]\n\n"
    "If error says 'None is not valid' for workoutComponents item at /workouts/0/workoutComponents/10:\n"
    "[{\"op\": \"remove\", \"path\": \"/workouts/0/workoutComponents/10\"}]\n\n"
    "OUTPUT REQUIREMENTS:\n"
    "Output JSON only (no markdown/explanations) as a JSON Patch array.\n"
    "Return only the JSON Patch array that fixes the validation errors."
)

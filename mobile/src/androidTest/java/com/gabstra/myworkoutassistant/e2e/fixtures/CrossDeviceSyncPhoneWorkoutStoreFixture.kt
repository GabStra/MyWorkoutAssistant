package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

/**
 * Phone-side fixture for cross-device sync runs.
 * Keeps distinctive values aligned with Wear producer tests.
 */
object CrossDeviceSyncPhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Cross Device Sync Workout"
    const val CALIBRATION_WORKOUT_NAME = "Cross Device Calibration Workout"
    /**
     * Template values written into the phone workout_store before cross-device sync begins.
     * Wear applies workout progression before the session starts, so these are not the same
     * as the final executed values asserted after the producer run.
     */
    const val SET_A1_TEMPLATE_REPS = 7
    const val SET_A2_TEMPLATE_REPS = 6
    const val SET_B1_TEMPLATE_REPS = 12
    const val SET_C1_TEMPLATE_REPS = 10
    const val SET_D1_TEMPLATE_REPS = 8
    const val SET_D2_TEMPLATE_REPS = 6
    const val SET_A1_TEMPLATE_WEIGHT = 40.0
    const val SET_A2_TEMPLATE_WEIGHT = 50.0
    const val SET_B1_TEMPLATE_WEIGHT = 30.0
    const val SET_C1_TEMPLATE_WEIGHT = 20.0
    const val SET_D1_TEMPLATE_WEIGHT = 60.0
    const val SET_D2_TEMPLATE_WEIGHT = 70.0

    /**
     * Expected final values after the watch executes the progressed workout plan and applies
     * deterministic +1 rep edits on the first set of exercises A and D.
     */
    const val SET_A1_EXPECTED_REPS = 5
    const val SET_A2_EXPECTED_REPS = 6
    const val SET_B1_EXPECTED_REPS = 13
    const val SET_C1_EXPECTED_REPS = 11
    const val SET_D1_EXPECTED_REPS = 5
    const val SET_D2_EXPECTED_REPS = 6
    const val WEIGHT_TOLERANCE = 0.01
    const val PHONE_TO_WEAR_HISTORY_A1_REPS = 11
    const val PHONE_TO_WEAR_HISTORY_A1_WEIGHT = 42.5
    const val PHONE_TO_WEAR_HISTORY_A2_REPS = 9
    const val PHONE_TO_WEAR_HISTORY_A2_WEIGHT = 52.5

    const val SET_A1_EXPECTED_WEIGHT = 50.0
    const val SET_A2_EXPECTED_WEIGHT = 50.0
    const val SET_B1_EXPECTED_WEIGHT = 30.0
    const val SET_C1_EXPECTED_WEIGHT = 20.0
    const val SET_D1_EXPECTED_WEIGHT = 70.0
    const val SET_D2_EXPECTED_WEIGHT = 70.0
    const val CALIBRATION_SET_EXPECTED_REPS = 8

    val WORKOUT_ID: UUID = UUID.fromString("0ed4ca78-a798-4f4a-9ed1-5bd22c2f6f47")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("301e8ea8-b8a8-466b-8f97-9eb54e6b7c8a")
    val CALIBRATION_WORKOUT_ID: UUID = UUID.fromString("8fd7f6b3-a9f4-4a07-8be8-65b43f3d2de6")
    val CALIBRATION_WORKOUT_GLOBAL_ID: UUID = UUID.fromString("4f1d3f8f-4969-465b-a3c0-eec173919953")
    val EXERCISE_A_ID: UUID = UUID.fromString("5b206aca-7c4f-4cf2-9f8f-3fb0016f8d61")
    val EXERCISE_B_ID: UUID = UUID.fromString("d3f4e708-c4f7-46a5-9e1a-b96b8e6dc7df")
    val EXERCISE_C_ID: UUID = UUID.fromString("3d6f5e9e-8e0b-4a0e-bf77-2d4fdd7fc2be")
    val EXERCISE_D_ID: UUID = UUID.fromString("68c17d4a-3f08-422f-a424-9ec35a8cb4b5")

    val SET_A1_ID: UUID = UUID.fromString("8f7dc7af-fd0d-43f0-b30b-a3ea85b40d57")
    val SET_A2_ID: UUID = UUID.fromString("a4b80fc6-e44e-41bc-9e71-cf9df23b9d36")
    val SET_B1_ID: UUID = UUID.fromString("8a62bcfd-918f-4634-9f42-6e522332a2be")
    val SET_C1_ID: UUID = UUID.fromString("dbc5a1fd-96e8-4b60-b54c-a6ca3a6fdc66")
    val SET_D1_ID: UUID = UUID.fromString("8c8ec7a8-16db-4496-9d39-b036f6fe8e26")
    val SET_D2_ID: UUID = UUID.fromString("4f5a4e8d-b58e-4868-b66c-f2aa147537f1")
    val CALIBRATION_EXERCISE_ID: UUID = UUID.fromString("b6b0d71e-72fa-4f3f-8d22-09c4c65ad0e7")
    val CALIBRATION_SET_ID: UUID = UUID.fromString("f0935f93-a416-44ee-90de-9f8d7fd5a0fc")
    val PHONE_TO_WEAR_HISTORY_ID: UUID = UUID.fromString("c8f95ab8-4a27-448d-8f1a-45698b1d56a9")
    val PHONE_TO_WEAR_HISTORY_GLOBAL_ID: UUID = WORKOUT_GLOBAL_ID
    val PHONE_TO_WEAR_SET_HISTORY_A1_ID: UUID = UUID.fromString("2f9802de-89d8-43b2-95e4-b7d73bc0cf84")
    val PHONE_TO_WEAR_SET_HISTORY_A2_ID: UUID = UUID.fromString("c5d9eb2e-f056-41d5-83cf-d0904a47aa7e")

    fun createWorkoutStore(): WorkoutStore {
        val exercise = Exercise(
            id = EXERCISE_A_ID,
            enabled = true,
            name = "Complex A",
            notes = "",
            sets = listOf(
                WeightSet(id = SET_A1_ID, reps = SET_A1_TEMPLATE_REPS, weight = SET_A1_TEMPLATE_WEIGHT),
                WeightSet(id = SET_A2_ID, reps = SET_A2_TEMPLATE_REPS, weight = SET_A2_TEMPLATE_WEIGHT)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val exerciseB = Exercise(
            id = EXERCISE_B_ID,
            enabled = true,
            name = "Complex B",
            notes = "",
            sets = listOf(WeightSet(id = SET_B1_ID, reps = SET_B1_TEMPLATE_REPS, weight = SET_B1_TEMPLATE_WEIGHT)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val exerciseC = Exercise(
            id = EXERCISE_C_ID,
            enabled = true,
            name = "Complex C",
            notes = "",
            sets = listOf(WeightSet(id = SET_C1_ID, reps = SET_C1_TEMPLATE_REPS, weight = SET_C1_TEMPLATE_WEIGHT)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val exerciseD = Exercise(
            id = EXERCISE_D_ID,
            enabled = true,
            name = "Complex D",
            notes = "",
            sets = listOf(
                WeightSet(id = SET_D1_ID, reps = SET_D1_TEMPLATE_REPS, weight = SET_D1_TEMPLATE_WEIGHT),
                WeightSet(id = SET_D2_ID, reps = SET_D2_TEMPLATE_REPS, weight = SET_D2_TEMPLATE_WEIGHT)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Phone-side cross-device sync fixture",
            workoutComponents = listOf(exercise, exerciseB, exerciseC, exerciseD),
            order = 0,
            enabled = true,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = WORKOUT_GLOBAL_ID,
            type = 0
        )

        val calibrationExercise = Exercise(
            id = CALIBRATION_EXERCISE_ID,
            enabled = true,
            name = "Calibration Sync Press",
            notes = "",
            sets = listOf(
                WeightSet(id = CALIBRATION_SET_ID, reps = CALIBRATION_SET_EXPECTED_REPS, weight = 45.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            requiresLoadCalibration = true
        )

        val calibrationWorkout = Workout(
            id = CALIBRATION_WORKOUT_ID,
            name = CALIBRATION_WORKOUT_NAME,
            description = "Phone-side calibration sync fixture",
            workoutComponents = listOf(calibrationExercise),
            order = 1,
            enabled = true,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = CALIBRATION_WORKOUT_GLOBAL_ID,
            type = 0
        )

        return WorkoutStore(
            workouts = listOf(workout, calibrationWorkout),
            equipments = emptyList(),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }
}

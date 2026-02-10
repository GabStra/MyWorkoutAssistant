package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

/**
 * Fixture used by cross-device E2E tests.
 * This fixture is intentionally complex but deterministic:
 * - multiple exercises
 * - multiple exercises with multiple sets each
 * - fixed IDs for exact cross-device verification
 */
object CrossDeviceSyncWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Cross Device Sync Workout"
    private const val CALIBRATION_WORKOUT_NAME = "Cross Device Calibration Workout"
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
    const val CALIBRATION_EXERCISE_NAME = "Calibration Sync Press"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()

        val exerciseA = Exercise(
            id = EXERCISE_A_ID,
            enabled = true,
            name = "Complex A",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(id = SET_A1_ID, reps = 7, weight = 40.0),
                WeightSet(id = SET_A2_ID, reps = 6, weight = 50.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
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
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(id = SET_B1_ID, reps = 12, weight = 30.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
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
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(id = SET_C1_ID, reps = 10, weight = 20.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
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
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(id = SET_D1_ID, reps = 8, weight = 60.0),
                WeightSet(id = SET_D2_ID, reps = 6, weight = 70.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
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
            description = "Cross-device sync validation workout",
            workoutComponents = listOf(exerciseA, exerciseB, exerciseC, exerciseD),
            order = 0,
            enabled = true,
            usePolarDevice = false,
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
            name = CALIBRATION_EXERCISE_NAME,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(id = CALIBRATION_SET_ID, reps = 8, weight = 45.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
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
            description = "Cross-device calibration sync validation workout",
            workoutComponents = listOf(calibrationExercise),
            order = 1,
            enabled = true,
            usePolarDevice = false,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = CALIBRATION_WORKOUT_GLOBAL_ID,
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout, calibrationWorkout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME
    fun getCalibrationWorkoutName(): String = CALIBRATION_WORKOUT_NAME
}


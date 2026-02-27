package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID

/**
 * Fixture for a workout with a superset (Exercise A + Exercise B, 2 rounds each).
 * Used to validate that PageExercises shows unified sets (A1, B1, REST, A2, B2)
 * instead of per-exercise sets.
 */
object SupersetWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Superset Test Workout"
    const val EXERCISE_A_NAME = "Superset A"
    const val EXERCISE_B_NAME = "Superset B"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()

        val exerciseAId = UUID.randomUUID()
        val exerciseBId = UUID.randomUUID()
        val setA1Id = UUID.randomUUID()
        val setA2Id = UUID.randomUUID()
        val setB1Id = UUID.randomUUID()
        val setB2Id = UUID.randomUUID()
        val restAId = UUID.randomUUID()
        val restBId = UUID.randomUUID()

        val exerciseA = Exercise(
            id = exerciseAId,
            enabled = true,
            name = EXERCISE_A_NAME,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(setA1Id, 10, 60.0),
                RestSet(restAId, 30),
                WeightSet(setA2Id, 8, 60.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val exerciseB = Exercise(
            id = exerciseBId,
            enabled = true,
            name = EXERCISE_B_NAME,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(setB1Id, 12, 40.0),
                RestSet(restBId, 30),
                WeightSet(setB2Id, 10, 40.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val supersetId = UUID.randomUUID()
        val superset = Superset(
            id = supersetId,
            enabled = true,
            exercises = listOf(exerciseA, exerciseB),
            restSecondsByExercise = mapOf(
                exerciseAId to 30,
                exerciseBId to 30
            )
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Superset E2E test",
            workoutComponents = listOf(superset),
            order = 0,
            enabled = true,
            usePolarDevice = false,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME
}

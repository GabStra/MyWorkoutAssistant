package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import java.time.LocalDate
import java.util.UUID

object ExerciseToExerciseRestWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Exercise To Exercise Rest"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()

        val firstExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Bench Press",
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), 8, 100.0)),
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
            keepScreenOn = false,
            showCountDownTimer = false,
            requiresLoadCalibration = false
        )
        val secondExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Barbell Row",
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), 10, 70.0)),
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
            keepScreenOn = false,
            showCountDownTimer = false,
            requiresLoadCalibration = false
        )
        val betweenExercisesRest = Rest(
            id = UUID.randomUUID(),
            enabled = true,
            timeInSeconds = 60
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Inter exercise rest test",
            workoutComponents = listOf(firstExercise, betweenExercisesRest, secondExercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
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
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME
}

package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID

/**
 * Fixture for the superset round-cadence (EMOM) behavior: a single two-member
 * superset with a 5-second round cadence and three rounds per member. The cadence
 * must advance round-by-round hands-free and complete the workout after the last
 * boundary.
 */
object SupersetCadenceWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Superset Cadence Workout"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exercises = listOf("Cadence Member One", "Cadence Member Two").map { name ->
            Exercise(
                id = UUID.randomUUID(),
                enabled = true,
                name = name,
                notes = "",
                sets = listOf(
                    WeightSet(UUID.randomUUID(), 8, 40.0),
                    WeightSet(UUID.randomUUID(), 8, 40.0),
                    WeightSet(UUID.randomUUID(), 8, 40.0)
                ),
                exerciseType = ExerciseType.WEIGHT,
                minReps = 5,
                maxReps = 12,
                lowerBoundMaxHRPercent = null,
                upperBoundMaxHRPercent = null,
                equipmentId = equipment.id,
                bodyWeightPercentage = null,
                generateWarmUpSets = false,
                progressionMode = ProgressionMode.OFF,
                keepScreenOn = false,
                showCountDownTimer = false,
                intraSetRestInSeconds = null,
                loadJumpDefaultPct = null,
                loadJumpMaxPct = null,
                loadJumpOvercapUntil = null
            )
        }

        val superset = Superset(
            id = UUID.randomUUID(),
            enabled = true,
            exercises = exercises,
            restSecondsByExercise = exercises.associate { it.id to 0 },
            roundDurationSeconds = 5
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Superset round cadence e2e",
            workoutComponents = listOf(superset),
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

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
import com.gabstra.myworkoutassistant.shared.workoutcomponents.SupersetCadenceMode
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
    private const val ROTATING_WORKOUT_NAME = "Rotating EMOM Workout"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val workouts = listOf(
            buildWorkout(
                name = WORKOUT_NAME,
                description = "Superset round cadence e2e",
                equipmentId = equipment.id,
                roundDurationSeconds = 5,
                cadenceMode = SupersetCadenceMode.ROUND,
                order = 0
            ),
            buildWorkout(
                name = ROTATING_WORKOUT_NAME,
                description = "Rotating EMOM e2e: one member per slot",
                equipmentId = equipment.id,
                roundDurationSeconds = 5,
                cadenceMode = SupersetCadenceMode.MEMBER,
                order = 1
            )
        )

        val workoutStore = WorkoutStore(
            workouts = workouts,
            equipments = listOf(equipment),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME

    fun getRotatingWorkoutName(): String = ROTATING_WORKOUT_NAME

    private fun buildWorkout(
        name: String,
        description: String,
        equipmentId: UUID,
        roundDurationSeconds: Int,
        cadenceMode: SupersetCadenceMode,
        order: Int
    ): Workout {
        val exercises = listOf("Cadence Member One", "Cadence Member Two").map { exerciseName ->
            Exercise(
                id = UUID.randomUUID(),
                enabled = true,
                name = exerciseName,
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
                equipmentId = equipmentId,
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
            roundDurationSeconds = roundDurationSeconds,
            cadenceMode = cadenceMode
        )

        return Workout(
            id = UUID.randomUUID(),
            name = name,
            description = description,
            workoutComponents = listOf(superset),
            order = order,
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
    }
}

package com.gabstra.myworkoutassistant.benchmark

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.fixtures.TestBarbellFactory
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object PageExercisesScrollBenchmarkFixture {
    const val WORKOUT_NAME = "Page Exercises Scroll Benchmark"
    const val ROW_COUNT = 80

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Benchmark Bench Press",
            notes = "",
            sets = (1..ROW_COUNT).map { index ->
                WeightSet(
                    id = UUID.randomUUID(),
                    reps = 10,
                    weight = 100.0 + index
                )
            },
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
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Synthetic benchmark workout for PageExercises vertical scrolling.",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(
            context = context,
            workoutStore = WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(equipment),
                birthDateYear = 1990,
                weightKg = 75.0,
                progressionPercentageAmount = 0.0
            )
        )
    }
}

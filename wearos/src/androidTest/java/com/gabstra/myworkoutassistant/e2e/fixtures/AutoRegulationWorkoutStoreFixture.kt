package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

/**
 * Fixture for a workout containing one exercise with auto-regulation progression.
 * No calibration; first screen is the first work set. Completing a work set (reps in range)
 * shows the auto-regulation RIR screen; last work set has no RIR step.
 */
object AutoRegulationWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Auto-Regulation Workout"
    const val EXERCISE_NAME = "Auto-Reg Bench Press"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val restId = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = EXERCISE_NAME,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 8, 80.0),
                RestSet(restId, 60),
                WeightSet(set2Id, 8, 80.0)
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
            progressionMode = ProgressionMode.AUTO_REGULATION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            requiresLoadCalibration = false
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Auto-regulation E2E test workout",
            workoutComponents = listOf(exercise),
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

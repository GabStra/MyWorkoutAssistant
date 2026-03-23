package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object MinimalCrossDeviceInsertedRestWorkoutStoreFixture {
    const val WORKOUT_NAME = "Minimal Cross Device Inserted Rest Workout"
    val WORKOUT_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0301")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0302")
    val EXERCISE_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0303")
    val SET_1_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0304")
    val SET_2_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0305")

    fun initialSetIdsInOrder(): List<UUID> = listOf(SET_1_ID, SET_2_ID)

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Inserted Rest Sync Press",
            notes = "Base two-set workout for in-session inserted rest sync coverage",
            sets = listOf(
                WeightSet(id = SET_1_ID, reps = 5, weight = 40.0),
                WeightSet(id = SET_2_ID, reps = 5, weight = 45.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 8,
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

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Minimal inserted-rest cross-device sync workout",
            workoutComponents = listOf(exercise),
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

        TestWorkoutStoreSeeder.seedWorkoutStore(
            context,
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(equipment),
                polarDeviceId = null,
                birthDateYear = 1990,
                weightKg = 75.0,
                progressionPercentageAmount = 0.0
            )
        )
    }
}

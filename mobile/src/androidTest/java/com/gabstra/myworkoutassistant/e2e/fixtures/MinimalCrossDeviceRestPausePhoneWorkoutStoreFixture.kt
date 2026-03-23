package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Minimal Cross Device Rest Pause Workout"
    val WORKOUT_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0201")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0202")
    val EXERCISE_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0203")
    val SET_1_ID: UUID = UUID.fromString("0d80ca0d-c0de-4b1d-a001-1af17f7f0204")

    fun createWorkoutStore(): WorkoutStore {
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Rest Pause Sync Press",
            notes = "Phone-side rest-pause sync fixture",
            sets = listOf(WeightSet(id = SET_1_ID, reps = 6, weight = 50.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 8,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
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

        return WorkoutStore(
            workouts = listOf(
                Workout(
                    id = WORKOUT_ID,
                    name = WORKOUT_NAME,
                    description = "Phone-side rest-pause sync workout",
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
            ),
            equipments = emptyList(),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }
}

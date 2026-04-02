package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object MinimalCrossDeviceSyncPhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Minimal Cross Device Sync Workout"
    val WORKOUT_ID: UUID = UUID.fromString("a7d418b8-8d4d-4fe5-b1a2-4b4ac0ac6c11")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("d2c66465-37fe-4ec8-8bf7-8a01f32f4636")
    val EXERCISE_ID: UUID = UUID.fromString("8b060930-5753-43ff-87ff-c6c28516c632")
    val SET_1_ID: UUID = UUID.fromString("3ff6fd7e-52bf-468a-8653-46e993bb8dcb")
    val REST_1_ID: UUID = UUID.fromString("e9ce05df-0ccf-49a9-8f17-3dc90e3b7a60")
    val SET_2_ID: UUID = UUID.fromString("ba943c86-b603-471b-9803-c215f507aa18")
    val REST_2_ID: UUID = UUID.fromString("01f0bfa4-9fa2-45eb-b6d6-35976f9265e3")
    val SET_3_ID: UUID = UUID.fromString("3979c0bf-8d26-4133-8f0d-4162d3a624c6")

    fun expectedSetIdsInOrder(): List<UUID> = listOf(SET_1_ID, REST_1_ID, SET_2_ID, REST_2_ID, SET_3_ID)

    fun createWorkoutStore(): WorkoutStore {
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Minimal Sync Press",
            notes = "Phone-side minimal cross-device sync fixture",
            sets = listOf(
                WeightSet(id = SET_1_ID, reps = 5, weight = 40.0),
                RestSet(id = REST_1_ID, timeInSeconds = 30),
                WeightSet(id = SET_2_ID, reps = 5, weight = 45.0),
                RestSet(id = REST_2_ID, timeInSeconds = 45),
                WeightSet(id = SET_3_ID, reps = 6, weight = 50.0)
            ),
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
                    description = "Phone-side minimal cross-device sync workout",
                    workoutComponents = listOf(exercise),
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
            ),
            equipments = emptyList(),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }
}

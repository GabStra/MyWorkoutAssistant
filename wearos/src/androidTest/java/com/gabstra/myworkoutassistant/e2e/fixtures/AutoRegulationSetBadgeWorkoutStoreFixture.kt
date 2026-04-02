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

object AutoRegulationSetBadgeWorkoutStoreFixture {
    const val WORKOUT_NAME = "Auto Regulation Badge Workout"
    const val EXERCISE_NAME = "Auto-Reg Badge Press"
    const val TEMPLATE_REPS = 8
    const val TEMPLATE_WEIGHT = 80.0
    const val MIN_REPS = 5
    const val MAX_REPS = 12
    const val SECOND_SESSION_FIRST_SET_REPS = 14
    const val EXPECTED_ADJUSTED_SECOND_SET_WEIGHT = 82.5
    const val EXPECTED_BADGE_TEXT = "+2.50 kg"
    const val WEIGHT_TOLERANCE = 0.01

    val WORKOUT_ID: UUID = UUID.fromString("6d684d1e-0d59-4d71-b8af-415d3c4f4a9c")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("2b1d3e41-6f7c-4d05-8737-8a47779fba5c")
    val EXERCISE_ID: UUID = UUID.fromString("7b2d81a1-129d-4469-90d4-f4c4a0c820c7")
    val SET_1_ID: UUID = UUID.fromString("8ef11214-55f3-4f78-9836-74d65f61387d")
    val REST_1_ID: UUID = UUID.fromString("0df9f444-a9b7-4c44-952e-e399a097e68f")
    val SET_2_ID: UUID = UUID.fromString("2a0c8659-b7f7-4e5e-a102-49ff5d32d06c")

    val PHONE_TO_WEAR_HISTORY_ID: UUID = UUID.fromString("a0f27822-26cc-4a1e-9dc8-6f52698bb9d2")
    val PHONE_TO_WEAR_SET_HISTORY_1_ID: UUID = UUID.fromString("f6d711b2-2426-47fa-b04f-e18284d88866")
    val PHONE_TO_WEAR_SET_HISTORY_2_ID: UUID = UUID.fromString("0b96c2f4-cd81-4171-87c4-94b3381f4f96")

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = EXERCISE_NAME,
            notes = "Two-session auto-regulation badge verification",
            sets = listOf(
                WeightSet(id = SET_1_ID, reps = TEMPLATE_REPS, weight = TEMPLATE_WEIGHT),
                RestSet(id = REST_1_ID, timeInSeconds = 30),
                WeightSet(id = SET_2_ID, reps = TEMPLATE_REPS, weight = TEMPLATE_WEIGHT)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = MIN_REPS,
            maxReps = MAX_REPS,
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
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Auto-regulation badge verification workout",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = WORKOUT_GLOBAL_ID,
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

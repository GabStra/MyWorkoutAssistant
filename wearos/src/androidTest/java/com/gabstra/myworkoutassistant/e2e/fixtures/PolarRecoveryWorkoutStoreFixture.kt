package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object PolarRecoveryWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Polar Recovery Resume Workout"
    private const val POLAR_DEVICE_ID = "E2E-POLAR-DEVICE"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val exercise = Exercise(
            id = UUID.fromString("6025ced9-6aa7-4885-8a99-d6fcb775f869"),
            enabled = true,
            name = "Polar Bench Press",
            notes = "Minimal Polar-backed workout for recovery regression coverage",
            sets = listOf(
                WeightSet(
                    id = UUID.fromString("ba061b42-a552-45db-a3b0-a3ec4d36c2a3"),
                    reps = 5,
                    weight = 40.0
                )
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
            id = UUID.fromString("27daa2bc-8329-4676-99af-a5ca5dc52ce6"),
            name = WORKOUT_NAME,
            description = "Recovery dialog resume should re-enter Polar preparation and allow skip",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.POLAR_BLE,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.fromString("91e4cbbc-c1b0-4b71-a4c6-e8eb8af6be7f"),
            type = 0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(
            context,
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(equipment),
                externalHeartRateConfigs = listOf(
                    PolarHeartRateConfig(
                        deviceId = POLAR_DEVICE_ID,
                        displayName = "Polar H10"
                    )
                ),
                birthDateYear = 1990,
                weightKg = 75.0,
                progressionPercentageAmount = 0.0
            )
        )
    }

    fun getWorkoutName(): String = WORKOUT_NAME
}

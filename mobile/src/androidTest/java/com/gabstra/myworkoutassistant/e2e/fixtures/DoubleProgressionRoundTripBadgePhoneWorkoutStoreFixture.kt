package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Double Progression Round Trip Badge Workout"
    const val PREVIOUS_SESSION_REPS = 5
    const val PHONE_TEMPLATE_REPS = PREVIOUS_SESSION_REPS
    const val FIRST_WEAR_SESSION_REPS = 6
    const val TEMPLATE_WEIGHT = 40.0
    const val MIN_REPS = 4
    const val MAX_REPS = 8
    const val SECOND_WEAR_SESSION_REPS = 7
    const val THIRD_WEAR_SESSION_REPS = 8
    const val WEIGHT_TOLERANCE = 0.01

    val WORKOUT_ID: UUID = UUID.fromString("b1cb3d23-b5a3-46d7-a1df-506f93969411")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("b11e4924-869f-4c04-8d4d-5533e5f8fba5")
    val PREVIOUS_SESSION_HISTORY_ID: UUID = UUID.fromString("3213dc7d-badc-4fd8-a3cd-04cabefa24f0")
    val EXERCISE_ID: UUID = UUID.fromString("d10ebfb8-f748-4fb4-b8a9-a34db0fd02e4")
    val SET_ID: UUID = UUID.fromString("d8f30148-d4b0-4dd9-8105-56664f302f88")
    val EQUIPMENT_ID: UUID = UUID.fromString("6643d522-83d8-4cea-b339-9108754f9fb0")

    private fun createEquipment(): Barbell =
        Barbell(
            id = EQUIPMENT_ID,
            name = "Round Trip Test Barbell",
            availablePlates = listOf(
                Plate(20.0, 20.0),
                Plate(20.0, 20.0),
                Plate(10.0, 15.0),
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0),
                Plate(2.5, 5.0),
                Plate(1.25, 3.0),
                Plate(1.25, 3.0)
            ),
            sleeveLength = 200,
            barWeight = 20.0
        )

    fun createWorkoutStore(): WorkoutStore {
        val equipment = createEquipment()
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Round Trip Press",
            notes = "Cross-device first-phone-sync double progression badge reproduction",
            sets = listOf(WeightSet(id = SET_ID, reps = PHONE_TEMPLATE_REPS, weight = TEMPLATE_WEIGHT)),
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
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            requiresLoadCalibration = false
        )

        return WorkoutStore(
            workouts = listOf(
                Workout(
                    id = WORKOUT_ID,
                    name = WORKOUT_NAME,
                    description = "Double progression round-trip badge verification workout",
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
            ),
            equipments = listOf(equipment),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }
}

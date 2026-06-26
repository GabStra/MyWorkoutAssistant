package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object ZercherMovementPhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Zercher Squat Movement Preview"
    const val EXERCISE_NAME = "Barbell Zercher Squat"
    const val MOVEMENT_ID = "barbell-zercher-squat"
    private const val MOVEMENT_ASSET_NAME = "barbell_zercher_squat_wear_skeleton.json"

    val WORKOUT_ID: UUID = UUID.fromString("7422f146-cba6-45c7-a5d4-751c98e5b38f")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("0b95e364-9fe7-4b88-9fdd-d5e9a1d65a25")
    val EXERCISE_ID: UUID = UUID.fromString("5b534a2c-1ebc-47cc-bbc3-c5378b2134d6")
    val SET_ID: UUID = UUID.fromString("5e0f8c04-b183-4e02-991c-52278bd6e8c2")
    val EQUIPMENT_ID: UUID = UUID.fromString("bf625363-6e1f-49a6-bdd4-804c9a3fcd7e")

    fun readMovementJson(context: Context): String =
        context.assets.open(MOVEMENT_ASSET_NAME)
            .bufferedReader(Charsets.UTF_8)
            .use { reader -> reader.readText().trim() }

    fun movementRef(movementJson: String): ExerciseMovementRef =
        ExerciseMovementRef.forWearSkeletonJson(MOVEMENT_ID, movementJson)

    fun createWorkoutStore(movementRef: ExerciseMovementRef): WorkoutStore {
        val equipment = createTestBarbell()
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = EXERCISE_NAME,
            notes = "",
            sets = listOf(WeightSet(id = SET_ID, reps = 8, weight = 40.0)),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 4,
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
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            movementRef = movementRef
        )

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Minimal phone-to-Wear movement preview fixture",
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

        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }

    private fun createTestBarbell(): Barbell {
        val plates = listOf(
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
        )
        return Barbell(
            id = EQUIPMENT_ID,
            name = "Zercher Preview Test Barbell",
            availablePlates = plates,
            sleeveLength = 200,
            barWeight = 20.0
        )
    }
}

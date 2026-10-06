package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID

object CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Calibration Superset Cross Device"
    val WORKOUT_ID: UUID = UUID.fromString("642736f5-b52c-4b34-8789-e992939557bb")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("2125a6fb-4c2a-4422-8c7d-4969ebdb6c25")
    val SUPERSET_ID: UUID = UUID.fromString("bd65d577-8d83-4193-92b9-e55ef1fb424f")
    val EXERCISE_A_ID: UUID = UUID.fromString("cfbc9015-942f-4fb7-bf1c-6ed82cab35b7")
    val EXERCISE_B_ID: UUID = UUID.fromString("4240ad71-98d5-4eab-a557-fba429d6437d")
    val WORK_SET_A_ID: UUID = UUID.fromString("a2a639c0-6eb7-422c-b81b-fb16188d3846")
    val WORK_SET_B_ID: UUID = UUID.fromString("e1aba84c-8050-433b-989c-16fd7072488f")

    fun createWorkoutStore(): WorkoutStore {
        fun exercise(id: UUID, setId: UUID, name: String, weight: Double) = Exercise(
            id = id,
            enabled = true,
            name = name,
            notes = "",
            sets = listOf(WeightSet(setId, reps = 5, weight = weight)),
            exerciseType = ExerciseType.WEIGHT,
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
            loadJumpOvercapUntil = null,
            requiresLoadCalibration = true
        )

        val exerciseA = exercise(EXERCISE_A_ID, WORK_SET_A_ID, "Calibration Superset A", 40.0)
        val exerciseB = exercise(EXERCISE_B_ID, WORK_SET_B_ID, "Calibration Superset B", 30.0)
        return WorkoutStore(
            workouts = listOf(
                Workout(
                    id = WORKOUT_ID,
                    name = WORKOUT_NAME,
                    description = "Two calibration-required exercises in one superset",
                    workoutComponents = listOf(
                        Superset(
                            id = SUPERSET_ID,
                            enabled = true,
                            exercises = listOf(exerciseA, exerciseB),
                            restSecondsByExercise = mapOf(EXERCISE_A_ID to 0, EXERCISE_B_ID to 0)
                        )
                    ),
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

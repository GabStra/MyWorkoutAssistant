package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object EquipmentChangeWorkoutStoreFixture {
    private const val BODY_WEIGHT_WORKOUT_NAME = "Bodyweight Equipment Change Test Workout"
    private const val WEIGHT_WORKOUT_NAME = "Weight Equipment Change Test Workout"
    const val BODY_WEIGHT_EXERCISE_NAME = "Weighted Pull Ups"
    const val WEIGHT_EXERCISE_NAME = "Machine Press"
    const val BARBELL_NAME = "Test Barbell"
    const val MACHINE_NAME = "Test Machine"

    fun setupBodyWeightWorkoutStore(context: Context) {
        val barbell = TestBarbellFactory.createTestBarbell()
        val machine = Machine(
            id = UUID.randomUUID(),
            name = MACHINE_NAME,
            availableWeights = listOf(
                BaseWeight(20.0),
                BaseWeight(40.0),
                BaseWeight(60.0),
                BaseWeight(80.0)
            )
        )

        val bodyWeightExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = BODY_WEIGHT_EXERCISE_NAME,
            notes = "",
            sets = listOf(BodyWeightSet(UUID.randomUUID(), 8, 20.0)),
            exerciseType = ExerciseType.BODY_WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = machine.id,
            bodyWeightPercentage = 100.0,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val weightExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = WEIGHT_EXERCISE_NAME,
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), 10, 60.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = machine.id,
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
            name = BODY_WEIGHT_WORKOUT_NAME,
            description = "Bodyweight equipment reassignment test",
            workoutComponents = listOf(bodyWeightExercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
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
            equipments = listOf(barbell, machine),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun setupWeightWorkoutStore(context: Context) {
        val barbell = TestBarbellFactory.createTestBarbell()
        val machine = Machine(
            id = UUID.randomUUID(),
            name = MACHINE_NAME,
            availableWeights = listOf(
                BaseWeight(20.0),
                BaseWeight(40.0),
                BaseWeight(60.0),
                BaseWeight(80.0)
            )
        )

        val weightExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = WEIGHT_EXERCISE_NAME,
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), 10, 60.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = machine.id,
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
            name = WEIGHT_WORKOUT_NAME,
            description = "Weight equipment reassignment test",
            workoutComponents = listOf(weightExercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
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
            equipments = listOf(barbell, machine),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getBodyWeightWorkoutName(): String = BODY_WEIGHT_WORKOUT_NAME

    fun getWeightWorkoutName(): String = WEIGHT_WORKOUT_NAME
}

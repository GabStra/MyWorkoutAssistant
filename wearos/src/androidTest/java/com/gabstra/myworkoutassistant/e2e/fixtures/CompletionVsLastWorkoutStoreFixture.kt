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

object CompletionVsLastWorkoutStoreFixture {
    data class SetTemplate(
        val id: UUID,
        val reps: Int,
        val weight: Double
    )

    private const val WORKOUT_NAME = "Completion Vs Last Workout"
    const val EXERCISE_NAME = "Vs Last Press"
    val WORKOUT_ID: UUID = UUID.fromString("b9727cc7-5956-4415-ae7e-95bc33ed6f6e")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("cb9c1210-fec8-4dbf-9310-8016136be845")
    val EXERCISE_ID: UUID = UUID.fromString("d803ab73-60bf-41ff-8825-a1208b92bc74")
    val SET_ID: UUID = UUID.fromString("f654a2f0-c5c1-4e89-b839-e4f15a3eb6dc")
    val SECOND_SET_ID: UUID = UUID.fromString("0bb3a091-0d8a-4da0-9af0-c2df7ed5d4cf")
    const val TEMPLATE_REPS = 10
    const val TEMPLATE_WEIGHT = 100.0
    const val SECOND_TEMPLATE_REPS = 12

    val defaultTemplates: List<SetTemplate> = listOf(
        SetTemplate(
            id = SET_ID,
            reps = TEMPLATE_REPS,
            weight = TEMPLATE_WEIGHT
        )
    )

    val mixedTemplates: List<SetTemplate> = listOf(
        SetTemplate(
            id = SET_ID,
            reps = TEMPLATE_REPS,
            weight = TEMPLATE_WEIGHT
        ),
        SetTemplate(
            id = SECOND_SET_ID,
            reps = SECOND_TEMPLATE_REPS,
            weight = TEMPLATE_WEIGHT
        )
    )

    fun setupWorkoutStore(
        context: Context,
        setTemplates: List<SetTemplate> = defaultTemplates
    ) {
        val equipment = TestBarbellFactory.createTestBarbell()

        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = EXERCISE_NAME,
            notes = "",
            sets = setTemplates.map { template ->
                WeightSet(id = template.id, reps = template.reps, weight = template.weight)
            },
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
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Wear completion vs last validation workout",
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

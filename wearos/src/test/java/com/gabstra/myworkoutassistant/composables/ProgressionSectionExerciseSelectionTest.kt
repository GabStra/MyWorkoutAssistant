package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class ProgressionSectionExerciseSelectionTest {
    @Test
    fun progressionExercisesForWorkout_includesExecutedSupersetChildrenInWorkoutOrder() {
        val standalone = exercise("Standalone")
        val supersetA = exercise("Superset A")
        val supersetB = exercise("Superset B")
        val notExecuted = exercise("Not executed")
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Progress workout",
            description = "",
            workoutComponents = listOf(
                standalone,
                Superset(
                    id = UUID.randomUUID(),
                    enabled = true,
                    exercises = listOf(supersetA, supersetB),
                    restSecondsByExercise = emptyMap()
                ),
                notExecuted
            ),
            order = 0,
            enabled = true,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )

        val result = progressionExercisesForWorkout(
            workout = workout,
            executedExerciseIds = setOf(standalone.id, supersetA.id, supersetB.id)
        )

        assertEquals(
            listOf("Standalone", "Superset A", "Superset B"),
            result.map { it.name }
        )
    }

    private fun exercise(name: String): Exercise {
        return Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = name,
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), reps = 5, weight = 40.0)),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 4,
            maxReps = 8,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }
}

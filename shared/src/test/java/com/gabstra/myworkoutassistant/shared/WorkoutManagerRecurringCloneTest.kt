package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.duplicatePrescription
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkoutManagerRecurringCloneTest {
    @Test
    fun `cloned exercises start independent of recurring load history`() {
        val exercise = recurringExercise()
        val direct = WorkoutManager.cloneWorkoutComponent(exercise) as Exercise
        val superset = WorkoutManager.cloneWorkoutComponent(
            Superset(UUID.randomUUID(), true, listOf(exercise), mapOf(exercise.id to 60))
        ) as Superset
        val nested = superset.exercises.single()
        val duplicate = exercise.duplicatePrescription()

        assertEquals(LoadHistoryPolicy.LAST_WORKING_LOAD, exercise.loadHistoryPolicy)
        listOf(direct, nested, duplicate).forEach { copy ->
            assertNotEquals(exercise.id, copy.id)
            assertNull(copy.recurringExerciseId)
            assertEquals(LoadHistoryPolicy.NONE, copy.loadHistoryPolicy)
        }
    }

    private fun recurringExercise() = Exercise(
        id = UUID.randomUUID(),
        enabled = true,
        name = "Press",
        notes = "",
        sets = listOf(WeightSet(UUID.randomUUID(), 8, 40.0)),
        exerciseType = ExerciseType.WEIGHT,
        minReps = 5,
        maxReps = 10,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = UUID.randomUUID(),
        bodyWeightPercentage = null,
        recurringExerciseId = UUID.randomUUID(),
        loadHistoryPolicy = LoadHistoryPolicy.LAST_WORKING_LOAD,
    )
}

package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class WorkoutManagerVersioningTest {
    @Test
    fun `updateWorkout keeps nested exercise and set ids stable across workout versions`() {
        val workoutGlobalId = UUID.randomUUID()
        val workoutId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        val originalWorkout = Workout(
            id = workoutId,
            name = "Push Day",
            description = "Original",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Bench Press",
                    notes = "",
                    sets = listOf(WeightSet(id = setId, reps = 8, weight = 80.0)),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 0.0,
                    maxLoadPercent = 100.0,
                    minReps = 5,
                    maxReps = 12,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = null,
                    bodyWeightPercentage = null
                )
            ),
            order = 0,
            creationDate = LocalDate.of(2026, 4, 2),
            globalId = workoutGlobalId,
            type = 0
        )

        val updatedWorkout = originalWorkout.copy(
            description = "Updated description"
        )

        val versioned = WorkoutManager.updateWorkout(
            workouts = listOf(originalWorkout),
            oldWorkout = originalWorkout,
            updatedWorkout = updatedWorkout
        )

        val oldVersion = versioned.single { it.id == workoutId }
        val newVersion = versioned.single { it.id != workoutId }
        val newExercise = newVersion.workoutComponents.single() as Exercise
        val newSet = newExercise.sets.single()

        assertNotEquals(originalWorkout.id, newVersion.id)
        assertEquals(workoutGlobalId, newVersion.globalId)
        assertEquals(originalWorkout.id, newVersion.previousVersionId)
        assertEquals(newVersion.id, oldVersion.nextVersionId)
        assertEquals(exerciseId, newExercise.id)
        assertEquals(setId, newSet.id)
    }
}

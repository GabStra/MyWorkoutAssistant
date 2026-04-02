package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutStoreValidationTest {
    @Test
    fun `validateWorkoutStoreForRuntimeUse allows repeated set ids across workout versions`() {
        val sharedSetId = UUID.randomUUID()
        val sharedExerciseId = UUID.randomUUID()
        val workoutGlobalId = UUID.randomUUID()
        val oldWorkoutId = UUID.randomUUID()
        val newWorkoutId = UUID.randomUUID()

        val workoutStore = WorkoutStore(
            workouts = listOf(
                createWorkout(
                    workoutId = oldWorkoutId,
                    workoutGlobalId = workoutGlobalId,
                    exercise = createExercise(
                        exerciseId = sharedExerciseId,
                        name = "Bench Press",
                        setIds = listOf(sharedSetId)
                    ),
                    isActive = false,
                    previousVersionId = null,
                    nextVersionId = newWorkoutId,
                    order = 0
                ),
                createWorkout(
                    workoutId = newWorkoutId,
                    workoutGlobalId = workoutGlobalId,
                    exercise = createExercise(
                        exerciseId = sharedExerciseId,
                        name = "Bench Press",
                        setIds = listOf(sharedSetId)
                    ),
                    isActive = true,
                    previousVersionId = oldWorkoutId,
                    nextVersionId = null,
                    order = 1
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0
        )

        validateWorkoutStoreForRuntimeUse(workoutStore)
    }

    @Test
    fun `validateWorkoutStoreForRuntimeUse rejects duplicate set ids inside one workout`() {
        val duplicatedSetId = UUID.randomUUID()
        val workoutStore = WorkoutStore(
            workouts = listOf(
                createWorkout(
                    workoutId = UUID.randomUUID(),
                    workoutGlobalId = UUID.randomUUID(),
                    exercise = createExercise(
                        exerciseId = UUID.randomUUID(),
                        name = "Bench Press",
                        setIds = listOf(duplicatedSetId)
                    ),
                    secondaryExercise = createExercise(
                        exerciseId = UUID.randomUUID(),
                        name = "Incline Press",
                        setIds = listOf(duplicatedSetId)
                    )
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0
        )

        val exception = try {
            validateWorkoutStoreForRuntimeUse(workoutStore)
            error("Expected workout-store validation to fail.")
        } catch (exception: WorkoutStoreValidationException) {
            exception
        }

        assertEquals(1, exception.duplicateSetIdIssues.size)
        assertEquals("Bench Press", exception.duplicateSetIdIssues.single().exerciseNames[0])
        assertTrue(exception.userMessage.contains("Incline Press"))
    }

    private fun createWorkout(
        workoutId: UUID,
        workoutGlobalId: UUID,
        exercise: Exercise,
        secondaryExercise: Exercise? = null,
        isActive: Boolean = true,
        previousVersionId: UUID? = null,
        nextVersionId: UUID? = null,
        order: Int = 0
    ): Workout {
        return Workout(
            id = workoutId,
            name = "Test Workout",
            description = "Workout validation test",
            workoutComponents = listOfNotNull(exercise, secondaryExercise),
            order = order,
            creationDate = LocalDate.of(2026, 4, 2),
            previousVersionId = previousVersionId,
            nextVersionId = nextVersionId,
            isActive = isActive,
            globalId = workoutGlobalId,
            type = 0
        )
    }

    private fun createExercise(
        exerciseId: UUID,
        name: String,
        setIds: List<UUID>
    ): Exercise {
        return Exercise(
            id = exerciseId,
            enabled = true,
            name = name,
            notes = "",
            sets = setIds.mapIndexed { index, setId ->
                WeightSet(
                    id = setId,
                    reps = 8 + index,
                    weight = 80.0 + index
                )
            },
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
    }
}

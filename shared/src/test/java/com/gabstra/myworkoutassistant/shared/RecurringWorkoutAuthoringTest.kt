package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RecurringWorkoutAuthoringTest {
    @Test
    fun `start attach explicit link unlink and detach keep track identity intentional`() {
        val source = workout("Press", listOf(exercise("Bench"), exercise("Bench")))
        val first = RecurringWorkoutAuthoring.startFamily(source, LoadHistoryPolicy.LAST_WORKING_LOAD, "Week 1")
        val firstExercises = first.workoutComponents.filterIsInstance<Exercise>()

        assertEquals(1, first.prescriptionOrdinal)
        assertEquals("Week 1", first.prescriptionLabel)
        assertTrue(firstExercises.all { it.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD })
        assertNotEquals(firstExercises[0].recurringExerciseId, firstExercises[1].recurringExerciseId)
        val choices = RecurringWorkoutAuthoring.compatibleTrackChoices(firstExercises.first(), listOf(first))
        assertEquals(2, choices.size)
        assertEquals(listOf(1, 2), choices.map { it.exercisePosition })

        val second = RecurringWorkoutAuthoring.attach(workout("Other", listOf(exercise("Bench"))), listOf(first))
        val secondExercise = second.workoutComponents.single() as Exercise
        val existingChoice = RecurringWorkoutAuthoring.compatibleTrackChoices(secondExercise, listOf(first)).first()
        assertEquals(firstExercises.first().recurringExerciseId, existingChoice.trackId)
        assertEquals(1, existingChoice.prescriptionOrdinal)
        assertNotEquals(firstExercises.first().recurringExerciseId, secondExercise.recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, secondExercise.loadHistoryPolicy)

        val linked = RecurringWorkoutAuthoring.linkExerciseTrack(
            second, secondExercise.id, existingChoice.trackId, LoadHistoryPolicy.LAST_WORKING_LOAD, listOf(first)
        )
        assertEquals(existingChoice.trackId, (linked.workoutComponents.single() as Exercise).recurringExerciseId)
        val newTrack = RecurringWorkoutAuthoring.createExerciseTrack(second, secondExercise.id, LoadHistoryPolicy.LAST_WORKING_LOAD)
        assertNotEquals(existingChoice.trackId, (newTrack.workoutComponents.single() as Exercise).recurringExerciseId)
        val unlinked = RecurringWorkoutAuthoring.unlinkExerciseTrack(linked, secondExercise.id)
        assertNull((unlinked.workoutComponents.single() as Exercise).recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, (unlinked.workoutComponents.single() as Exercise).loadHistoryPolicy)

        val detached = RecurringWorkoutAuthoring.detach(first)
        assertNull(detached.recurringSessionId)
        assertNull(detached.prescriptionOrdinal)
        assertNull((detached.workoutComponents.first() as Exercise).recurringExerciseId)
        assertEquals(firstExercises.first().sets, (detached.workoutComponents.first() as Exercise).sets)
    }

    @Test
    fun `clone and versioned metadata edits preserve tracks and validate only current family members`() {
        val first = RecurringWorkoutAuthoring.startFamily(workout("Press", listOf(exercise("Bench"))))
        val clone = RecurringWorkoutAuthoring.cloneNext(first, listOf(first), "Week 2")
        val firstExercise = first.workoutComponents.single() as Exercise
        val cloneExercise = clone.workoutComponents.single() as Exercise

        assertEquals(first.recurringSessionId, clone.recurringSessionId)
        assertEquals(2, clone.prescriptionOrdinal)
        assertEquals(firstExercise.recurringExerciseId, cloneExercise.recurringExerciseId)
        assertNotEquals(first.id, clone.id)
        assertNotEquals(first.globalId, clone.globalId)
        assertNotEquals(firstExercise.id, cloneExercise.id)
        assertNotEquals(firstExercise.sets.single().id, cloneExercise.sets.single().id)
        assertEquals((firstExercise.sets.single() as WeightSet).reps, (cloneExercise.sets.single() as WeightSet).reps)
        assertEquals((firstExercise.sets.single() as WeightSet).note, (cloneExercise.sets.single() as WeightSet).note)

        var workouts = listOf(first, clone)
        val edited = RecurringWorkoutAuthoring.updatePrescriptionLabel(clone, "Heavy week", workouts)
        workouts = WorkoutManager.updateWorkout(workouts, clone, edited)
        validateWorkoutStoreForRuntimeUse(store(workouts))
        val currentClone = workouts.single { it.globalId == clone.globalId && it.isActive }
        assertEquals(first.recurringSessionId, currentClone.recurringSessionId)
        assertEquals(clone.globalId, currentClone.globalId)
        assertEquals(2, currentClone.prescriptionOrdinal)
        assertTrue(workouts.any { it.id == clone.id && !it.isActive })

        val activeFamily = workouts.filter { it.isActive }
        val named = RecurringWorkoutAuthoring.renameFamily(activeFamily, "Bench cycle")
        named.filter { it.isActive }.forEach { replacement ->
            val old = workouts.single { it.id == replacement.id }
            workouts = WorkoutManager.updateWorkout(workouts, old, replacement)
        }
        val renamedFamily = workouts.filter { it.isActive }
        val reordered = RecurringWorkoutAuthoring.reorderFamily(
            renamedFamily,
            renamedFamily.sortedByDescending { it.prescriptionOrdinal }.map { it.id },
        )
        reordered.forEach { replacement ->
            val old = workouts.single { it.id == replacement.id }
            workouts = WorkoutManager.updateWorkout(workouts, old, replacement)
        }

        validateWorkoutStoreForRuntimeUse(store(workouts))
        val active = workouts.filter { it.isActive }.sortedBy { it.prescriptionOrdinal }
        assertEquals(listOf(1, 2), active.map { it.prescriptionOrdinal })
        assertTrue(active.all { it.name == "Bench cycle" })
        assertEquals(first.recurringSessionId, active.first().recurringSessionId)
        assertTrue(workouts.filterNot { it.isActive }.all { it.recurringSessionId == first.recurringSessionId })
    }

    @Test
    fun `label edit preserves list position and incompatible linked tracks are rejected`() {
        val first = RecurringWorkoutAuthoring.startFamily(workout("Cycle", listOf(exercise("Bench"))))
        val second = RecurringWorkoutAuthoring.cloneNext(first, listOf(first), "Week 2")
        val labelEdit = RecurringWorkoutAuthoring.updatePrescriptionLabel(second, "Heavy", listOf(first, second))
        assertEquals(2, labelEdit.prescriptionOrdinal)
        assertEquals("Heavy", labelEdit.prescriptionLabel)

        val currentExercise = (second.workoutComponents.single() as Exercise).copy(equipmentId = UUID.randomUUID())
        val incompatible = second.copy(workoutComponents = listOf(currentExercise))
        try {
            RecurringWorkoutAuthoring.linkExerciseTrack(
                incompatible,
                currentExercise.id,
                (first.workoutComponents.single() as Exercise).recurringExerciseId!!,
                LoadHistoryPolicy.LAST_WORKING_LOAD,
                listOf(first, second),
            )
            throw AssertionError("Expected incompatible track to be rejected")
        } catch (expected: RecurringWorkoutAuthoringException) {
            assertEquals(RecurringWorkoutAuthoringErrorCode.INCOMPATIBLE_TRACK, expected.code)
            assertTrue(expected.message.orEmpty().contains("incompatible"))
        }
    }

    @Test
    fun `validation failures expose stable codes and keep english diagnostics`() {
        val source = workout("Press", listOf(exercise("Bench")))
        val first = RecurringWorkoutAuthoring.startFamily(source)
        val clone = RecurringWorkoutAuthoring.cloneNext(first, listOf(first), "Week 2")
        val otherFamily = RecurringWorkoutAuthoring.startFamily(workout("Other", listOf(exercise("Squat"))))

        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.WORKOUT_ALREADY_IN_RECURRING_SESSION,
            "Workout already belongs to a recurring session.",
        ) { RecurringWorkoutAuthoring.startFamily(first) }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.DETACH_BEFORE_ATTACH,
            "Detach this workout before attaching it to another recurring session.",
        ) { RecurringWorkoutAuthoring.attach(first, listOf(first)) }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.SOURCE_NOT_IN_RECURRING_SESSION,
            "Source workout is not in this recurring session.",
        ) { RecurringWorkoutAuthoring.cloneNext(source, listOf(first), null) }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.EMPTY_SESSION_NAME,
            "Recurring session name cannot be empty.",
        ) { RecurringWorkoutAuthoring.renameFamily(listOf(first), "   ") }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.WORKOUT_NOT_IN_RECURRING_SESSION,
            "Workout is not in this recurring session.",
        ) { RecurringWorkoutAuthoring.updatePrescriptionLabel(source, null, listOf(first)) }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.REORDER_INCOMPLETE,
            "Reordering must include each active prescription exactly once.",
        ) { RecurringWorkoutAuthoring.reorderFamily(listOf(first, clone), listOf(first.id)) }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.WORKOUT_NOT_RECURRING_FOR_TRACK,
            "Add this workout to a recurring session before creating a history track.",
        ) {
            RecurringWorkoutAuthoring.createExerciseTrack(
                source,
                (source.workoutComponents.single() as Exercise).id,
                LoadHistoryPolicy.NONE,
            )
        }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.LOAD_POLICY_UNSUPPORTED,
            "Load policies support loaded weight and bodyweight exercises.",
        ) {
            RecurringWorkoutAuthoring.createExerciseTrack(
                exercise("Run").copy(exerciseType = ExerciseType.RUNNING),
                LoadHistoryPolicy.LAST_WORKING_LOAD,
                listOf(first),
            )
        }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.EXERCISE_NOT_IN_WORKOUT,
            "Exercise is not part of this workout.",
        ) {
            RecurringWorkoutAuthoring.linkExerciseTrack(
                first,
                UUID.randomUUID(),
                UUID.randomUUID(),
                LoadHistoryPolicy.NONE,
                listOf(first),
            )
        }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.NO_ACTIVE_PRESCRIPTIONS,
            "Recurring session has no active prescriptions.",
        ) { RecurringWorkoutAuthoring.renameFamily(emptyList(), "Cycle") }
        assertAuthoringFailure(
            RecurringWorkoutAuthoringErrorCode.MIXED_RECURRING_SESSIONS,
            "Selected workouts do not belong to one recurring session.",
        ) { RecurringWorkoutAuthoring.renameFamily(listOf(first, otherFamily), "Cycle") }
    }

    @Test
    fun `clone next remaps superset member references and preserves prescription details`() {
        val left = exercise("Left press").copy(notes = "Left note")
        val right = exercise("Right press").copy(notes = "Right note")
        val source = workout("Alternating", emptyList()).copy(
            workoutComponents = listOf(
                Superset(
                    id = UUID.randomUUID(),
                    enabled = true,
                    exercises = listOf(left, right),
                    restSecondsByExercise = mapOf(left.id to 50, right.id to 70),
                    timeCapSeconds = 180,
                    roundDurationSeconds = 60,
                ),
            ),
        )
        val first = RecurringWorkoutAuthoring.startFamily(source)
        val sourceSuperset = first.workoutComponents.single() as Superset
        val cloned = RecurringWorkoutAuthoring.cloneNext(first, listOf(first), "Week 2")
        val cloneSuperset = cloned.workoutComponents.single() as Superset

        assertNotEquals(sourceSuperset.id, cloneSuperset.id)
        assertEquals(sourceSuperset.timeCapSeconds, cloneSuperset.timeCapSeconds)
        assertEquals(sourceSuperset.roundDurationSeconds, cloneSuperset.roundDurationSeconds)
        assertEquals(sourceSuperset.exercises.size, cloneSuperset.exercises.size)
        sourceSuperset.exercises.zip(cloneSuperset.exercises).forEach { (original, copy) ->
            assertNotEquals(original.id, copy.id)
            assertNotEquals(original.sets.single().id, copy.sets.single().id)
            assertEquals(original.recurringExerciseId, copy.recurringExerciseId)
            assertEquals(original.notes, copy.notes)
            assertEquals(original.sets, copy.sets.map { clonedSet ->
                val originalSet = original.sets.single()
                when (clonedSet) {
                    is WeightSet -> clonedSet.copy(id = originalSet.id)
                    else -> clonedSet
                }
            })
        }
        assertEquals(50, cloneSuperset.restSecondsByExercise[cloneSuperset.exercises[0].id])
        assertEquals(70, cloneSuperset.restSecondsByExercise[cloneSuperset.exercises[1].id])
    }

    private fun store(workouts: List<Workout>) = WorkoutStore(
        workouts = workouts,
        birthDateYear = 1990,
        weightKg = 80.0,
        progressionPercentageAmount = 0.0,
    )

    private fun assertAuthoringFailure(
        code: RecurringWorkoutAuthoringErrorCode,
        message: String,
        block: () -> Unit,
    ) {
        try {
            block()
            throw AssertionError("Expected $code to be raised")
        } catch (expected: RecurringWorkoutAuthoringException) {
            assertEquals(code, expected.code)
            assertEquals(message, expected.message)
        }
    }

    private fun workout(name: String, exercises: List<Exercise>) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = exercises,
        order = 0,
        creationDate = LocalDate.of(2026, 11, 15),
        globalId = UUID.randomUUID(),
        type = 0,
    )

    private fun exercise(name: String) = Exercise(
        id = UUID.randomUUID(),
        enabled = true,
        name = name,
        notes = "Keep controlled",
        sets = listOf(WeightSet(UUID.randomUUID(), reps = 8, weight = 40.0, note = "Target")),
        exerciseType = ExerciseType.WEIGHT,
        minReps = 6,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = UUID(0L, 10L),
        bodyWeightPercentage = null,
        exerciseDefinitionId = UUID(0L, 1L),
    )
}

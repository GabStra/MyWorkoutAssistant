package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class RecurringExerciseControlsTest {
    @Test
    fun unchangedDefinitionValuesKeepOriginalNullEmptyAndPrecision() {
        assertNull(bodyWeightPercentageForSave(null, "", preserveOriginal = true))
        assertEquals(0.257, bodyWeightPercentageForSave(0.257, "0.257", preserveOriginal = true)!!, 0.0)
        assertEquals(0.0, bodyWeightPercentageForSave(null, "0", preserveOriginal = true)!!, 0.0)
        assertNull(nullableSelectionForSave(null, emptySet<String>(), emptySet()))
        assertEquals(emptySet<String>(), nullableSelectionForSave(emptySet(), emptySet<String>(), emptySet()))
        assertNull(nullableSelectionForSave(setOf("a"), emptySet<String>(), emptySet()))
    }

    @Test
    fun persistedUnlinkRemainsUnlinkedOnUnrelatedSave() {
        val exercise = exercise()
        val selection = initialRecurringTrackSelection(exercise, isNewPrescription = false)

        assertEquals(RecurringTrackMode.UNLINKED, selection.mode)
        val saved = applyRecurringExerciseEdit(
            exercise.copy(name = "Renamed exercise"),
            RecurringExerciseEdit(selection, LoadHistoryPolicy.NONE),
            emptyList(),
        )
        assertNull(saved.recurringExerciseId)
    }

    @Test
    fun newPrescriptionDefaultsToNewSlotAndExistingTrackIsRestored() {
        val trackId = UUID.randomUUID()

        assertEquals(
            RecurringTrackMode.NEW_TRACK,
            initialRecurringTrackSelection(exercise(), isNewPrescription = true).mode,
        )
        assertEquals(
            RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, trackId),
            initialRecurringTrackSelection(exercise(trackId = trackId), isNewPrescription = false),
        )
    }

    @Test
    fun onlyNewRecurringWeightPrescriptionsDefaultToFixedPolicy() {
        assertEquals(
            LoadHistoryPolicy.PRESCRIBED_WEIGHT,
            initialRecurringLoadPolicy(
                existingPolicy = LoadHistoryPolicy.NONE,
                isNewPrescription = true,
                isRecurringWorkout = true,
                exerciseType = ExerciseType.WEIGHT,
            ),
        )
        assertEquals(
            LoadHistoryPolicy.NONE,
            initialRecurringLoadPolicy(
                existingPolicy = LoadHistoryPolicy.NONE,
                isNewPrescription = false,
                isRecurringWorkout = true,
                exerciseType = ExerciseType.WEIGHT,
            ),
        )
        assertEquals(
            LoadHistoryPolicy.NONE,
            initialRecurringLoadPolicy(
                existingPolicy = LoadHistoryPolicy.NONE,
                isNewPrescription = true,
                isRecurringWorkout = true,
                exerciseType = ExerciseType.RUNNING,
            ),
        )
    }

    @Test
    fun prescribedWeightDoesNotRequireHistoryOrExistingWorkSets() {
        assertEquals(
            LoadHistoryPolicy.PRESCRIBED_WEIGHT,
            recurringLoadPolicyFor(
                LoadHistoryPolicy.PRESCRIBED_WEIGHT,
                ExerciseType.WEIGHT,
                RecurringTrackSelection(RecurringTrackMode.UNLINKED),
                hasLoadableWorkingSet = false,
            ),
        )
    }

    @Test
    fun changingAWeightExerciseToUnsupportedTypeClearsStaleHistoryMetadata() {
        val linkedWeightExercise = exercise(
            trackId = UUID.randomUUID(),
            policy = LoadHistoryPolicy.LAST_WORKING_LOAD,
        )

        val converted = sanitizeRecurringTrackMetadata(
            exercise = linkedWeightExercise.copy(exerciseType = ExerciseType.RUNNING),
            originalExercise = linkedWeightExercise,
            isRecurringWorkout = true,
            family = emptyList(),
        )

        assertNull(converted.recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, converted.loadHistoryPolicy)
    }

    @Test
    fun unchangedUnsupportedImportedNoneTrackIsPreserved() {
        val imported = exercise(
            type = ExerciseType.RUNNING,
            trackId = UUID.randomUUID(),
        )

        assertEquals(
            imported,
            sanitizeRecurringTrackMetadata(
                exercise = imported,
                originalExercise = imported,
                isRecurringWorkout = true,
                family = emptyList(),
            ),
        )
    }

    @Test
    fun equipmentChangeClearsNowIncompatibleTrack() {
        val original = exercise(trackId = UUID.randomUUID()).copy(equipmentId = UUID.randomUUID())
        val recurringWorkout = Workout(
            id = UUID.randomUUID(),
            name = "Workout A",
            description = "",
            workoutComponents = listOf(original),
            order = 0,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0,
            recurringSessionId = UUID.randomUUID(),
            prescriptionOrdinal = 1,
        )

        val changed = sanitizeRecurringTrackMetadata(
            exercise = original.copy(equipmentId = UUID.randomUUID()),
            originalExercise = original,
            isRecurringWorkout = true,
            family = listOf(recurringWorkout),
        )

        assertNull(changed.recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, changed.loadHistoryPolicy)
    }

    @Test
    fun freshTrackCreatedForChangedSignatureIsPreserved() {
        val original = exercise().copy(equipmentId = UUID.randomUUID())
        val recurringWorkout = Workout(
            id = UUID.randomUUID(),
            name = "Workout A",
            description = "",
            workoutComponents = listOf(original),
            order = 0,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0,
            recurringSessionId = UUID.randomUUID(),
            prescriptionOrdinal = 1,
        )
        val freshTrackId = UUID.randomUUID()
        val candidate = original.copy(
            equipmentId = UUID.randomUUID(),
            recurringExerciseId = freshTrackId,
        )

        val sanitized = sanitizeRecurringTrackMetadata(
            exercise = candidate,
            originalExercise = original,
            isRecurringWorkout = true,
            family = listOf(recurringWorkout),
        )

        assertEquals(freshTrackId, sanitized.recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, sanitized.loadHistoryPolicy)
    }

    @Test
    fun unavailableSelectedTrackFallsBackToANewSlot() {
        val selectedTrackId = UUID.randomUUID()

        assertEquals(
            RecurringTrackSelection(RecurringTrackMode.NEW_TRACK),
            normalizeRecurringTrackSelection(
                RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, selectedTrackId),
                emptySet(),
            ),
        )
        assertEquals(
            RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, selectedTrackId),
            normalizeRecurringTrackSelection(
                RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, selectedTrackId),
                setOf(selectedTrackId),
            ),
        )
    }

    @Test
    fun lastWorkingLoadRequiresSupportedLinkedPrescriptionWithLoadableSets() {
        val newTrack = RecurringTrackSelection(RecurringTrackMode.NEW_TRACK)

        assertEquals(
            LoadHistoryPolicy.LAST_WORKING_LOAD,
            recurringLoadPolicyFor(LoadHistoryPolicy.LAST_WORKING_LOAD, ExerciseType.WEIGHT, newTrack, true),
        )
        assertEquals(
            LoadHistoryPolicy.NONE,
            recurringLoadPolicyFor(
                LoadHistoryPolicy.LAST_WORKING_LOAD,
                ExerciseType.BODY_WEIGHT,
                RecurringTrackSelection(RecurringTrackMode.UNLINKED),
                true,
            ),
        )
        assertEquals(
            LoadHistoryPolicy.NONE,
            recurringLoadPolicyFor(LoadHistoryPolicy.LAST_WORKING_LOAD, ExerciseType.WEIGHT, newTrack, false),
        )
        assertEquals(
            LoadHistoryPolicy.NONE,
            recurringLoadPolicyFor(LoadHistoryPolicy.LAST_WORKING_LOAD, ExerciseType.RUNNING, newTrack, true),
        )
    }

    private fun exercise(
        type: ExerciseType = ExerciseType.WEIGHT,
        trackId: UUID? = null,
        policy: LoadHistoryPolicy = LoadHistoryPolicy.NONE,
    ) = Exercise(
        id = UUID.randomUUID(),
        enabled = true,
        name = "Bench press",
        notes = "",
        sets = emptyList(),
        exerciseType = type,
        minReps = 5,
        maxReps = 8,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        recurringExerciseId = trackId,
        loadHistoryPolicy = policy,
    )
}

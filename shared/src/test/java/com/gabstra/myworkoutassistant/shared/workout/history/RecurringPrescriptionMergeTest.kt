package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID
import com.gabstra.myworkoutassistant.shared.toExecutedSimpleSets
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import org.junit.Assert.assertEquals
import org.junit.Test

class RecurringPrescriptionMergeTest {
    @Test
    fun `completion stores actual load but keeps prescribed reps and note`() {
        val set = WeightSet(UUID.randomUUID(), reps = 9, weight = 55.0, note = "Week 2 target")
        val history = SetHistory(
            id = UUID.randomUUID(), setId = set.id, order = 0u,
            startTime = null, endTime = null,
            setData = WeightSetData(actualReps = 7, actualWeight = 57.5, volume = 402.5),
            skipped = false,
        )

        val result = ExerciseSessionReconstruction.mergeCompletedSession(
            templateSets = listOf(set), rawSetHistoriesForExercise = listOf(history),
            allRestHistories = emptyList(), exerciseId = UUID.randomUUID(), preservePrescription = true,
        )
        val merged = result.mergedSets().single() as WeightSet

        assertEquals(9, merged.reps)
        assertEquals(55.0, merged.weight, 0.0)
        assertEquals("Week 2 target", merged.note)
        assertEquals(7, result.snapshot.toExecutedSimpleSets().single().reps)
    }

    @Test
    fun `standalone fixed prescription keeps target while completion records actual performance`() {
        val set = WeightSet(UUID.randomUUID(), reps = 6, weight = 35.0, note = "Fixed")
        val exercise = Exercise(
            id = UUID.randomUUID(), enabled = true, name = "Press", notes = "",
            sets = listOf(set), exerciseType = ExerciseType.WEIGHT,
            minReps = 5, maxReps = 10, lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null, equipmentId = null, bodyWeightPercentage = null,
            loadHistoryPolicy = LoadHistoryPolicy.PRESCRIBED_WEIGHT,
        )
        val history = SetHistory(
            id = UUID.randomUUID(), setId = set.id, order = 0u,
            startTime = null, endTime = null,
            setData = WeightSetData(actualReps = 8, actualWeight = 40.0, volume = 320.0),
            skipped = false,
        )

        val result = ExerciseSessionReconstruction.mergeCompletedSession(
            templateSets = listOf(set), rawSetHistoriesForExercise = listOf(history),
            allRestHistories = emptyList(), exerciseId = exercise.id,
            preservePrescription = ExerciseSessionReconstruction.shouldPreservePrescription(exercise),
        )

        val futureTarget = result.mergedSets().single() as WeightSet
        assertEquals(35.0, futureTarget.weight, 0.0)
        assertEquals(6, futureTarget.reps)
        assertEquals("Fixed", futureTarget.note)
        assertEquals(40.0, result.snapshot.toExecutedSimpleSets().single().weight, 0.0)
        assertEquals(8, result.snapshot.toExecutedSimpleSets().single().reps)
    }
}

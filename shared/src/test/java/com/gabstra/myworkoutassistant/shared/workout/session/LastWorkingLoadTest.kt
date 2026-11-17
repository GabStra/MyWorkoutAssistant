package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Test

class LastWorkingLoadTest {
    @Test
    fun prescribedWeightIgnoresHigherHistoryWhileLastWorkingLoadStillCarriesIt() {
        val set = WeightSet(UUID.randomUUID(), reps = 9, weight = 32.5, note = "Fixed target")
        val exercise = Exercise(
            id = UUID.randomUUID(), enabled = true, name = "Press", notes = "",
            sets = listOf(set), exerciseType = ExerciseType.WEIGHT,
            minReps = 6, maxReps = 12, lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null, equipmentId = null, bodyWeightPercentage = null,
            recurringExerciseId = null, loadHistoryPolicy = LoadHistoryPolicy.PRESCRIBED_WEIGHT,
        )
        val prior = setHistory(WeightSetData(8, 55.0, 440.0))

        val fixed = exercise.withHistoryPolicyLoads(mapOf(set.id to prior)).sets.single() as WeightSet
        val carried = exercise.copy(loadHistoryPolicy = LoadHistoryPolicy.LAST_WORKING_LOAD)
            .withHistoryPolicyLoads(mapOf(set.id to prior)).sets.single() as WeightSet

        assertEquals(32.5, fixed.weight, 0.0)
        assertEquals(9, fixed.reps)
        assertEquals("Fixed target", fixed.note)
        assertEquals(55.0, carried.weight, 0.0)
        assertEquals(9, carried.reps)
    }

    @Test
    fun weightCarryChangesOnlyLoadAndRecomputesVolume() {
        val set = WeightSet(UUID.randomUUID(), reps = 12, weight = 40.0)
        val current = WeightSetData(12, 40.0, 480.0, autoRegulationRIR = 2.0)
        val prior = setHistory(WeightSetData(8, 55.0, 440.0, autoRegulationRIR = 1.0))

        val carried = current.withLastWorkingLoad(set, prior) as WeightSetData

        assertEquals(12, carried.actualReps)
        assertEquals(55.0, carried.actualWeight, 0.0)
        assertEquals(660.0, carried.volume, 0.0)
        assertEquals(2.0, carried.autoRegulationRIR!!, 0.0)
        assertEquals(null, carried.calibrationRIR)
    }

    @Test
    fun bodyWeightCarryChangesOnlyAdditionalLoad() {
        val set = BodyWeightSet(UUID.randomUUID(), reps = 10, additionalWeight = 0.0)
        val current = BodyWeightSetData(10, 0.0, 60.0, 600.0, autoRegulationRIR = 3.0)
        val prior = setHistory(BodyWeightSetData(8, 5.0, 60.0, 520.0))

        val carried = current.withLastWorkingLoad(set, prior) as BodyWeightSetData

        assertEquals(10, carried.actualReps)
        assertEquals(5.0, carried.additionalWeight, 0.0)
        assertEquals(650.0, carried.volume, 0.0)
        assertEquals(3.0, carried.autoRegulationRIR!!, 0.0)
        assertEquals(SetSubCategory.WorkSet, carried.subCategory)
    }

    private fun setHistory(data: com.gabstra.myworkoutassistant.shared.setdata.SetData) = SetHistory(
        id = UUID.randomUUID(),
        setId = UUID.randomUUID(),
        order = 0u,
        startTime = null,
        endTime = null,
        setData = data,
        skipped = false,
    )
}

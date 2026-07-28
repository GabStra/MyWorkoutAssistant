package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test
import java.util.UUID

class ExerciseEquipmentSetReconcilerTest {
    @Test
    fun changingEquipmentSnapsWeightedSetsAndPreservesOtherFields() {
        val previousEquipmentId = UUID.randomUUID()
        val selectedEquipment = machine(20.0, 40.0, 60.0)
        val weightSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 8,
            weight = 57.0,
            subCategory = SetSubCategory.WarmupSet,
            shouldReapplyHistoryToSet = false
        )
        val bodyWeightSet = BodyWeightSet(
            id = UUID.randomUUID(),
            reps = 10,
            additionalWeight = 37.0,
            subCategory = SetSubCategory.CalibrationPendingSet,
            shouldReapplyHistoryToSet = false
        )
        val restSet = RestSet(UUID.randomUUID(), 90)

        val result = reconcileSetsForEquipmentChange(
            sets = listOf(weightSet, restSet, bodyWeightSet),
            previousEquipmentId = previousEquipmentId,
            selectedEquipment = selectedEquipment
        )

        assertEquals(weightSet.copy(weight = 60.0), result[0])
        assertSame(restSet, result[1])
        assertEquals(bodyWeightSet.copy(additionalWeight = 40.0), result[2])
    }

    @Test
    fun clearingBodyWeightEquipmentResetsAdditionalWeight() {
        val bodyWeightSet = BodyWeightSet(UUID.randomUUID(), reps = 8, additionalWeight = 20.0)

        val result = reconcileSetsForEquipmentChange(
            sets = listOf(bodyWeightSet),
            previousEquipmentId = UUID.randomUUID(),
            selectedEquipment = null
        )

        assertEquals(bodyWeightSet.copy(additionalWeight = 0.0), result.single())
    }

    @Test
    fun keepingSameEquipmentDoesNotRewriteSets() {
        val selectedEquipment = machine(20.0, 40.0)
        val sets = listOf(WeightSet(UUID.randomUUID(), reps = 8, weight = 37.0))

        val result = reconcileSetsForEquipmentChange(
            sets = sets,
            previousEquipmentId = selectedEquipment.id,
            selectedEquipment = selectedEquipment
        )

        assertSame(sets, result)
    }

    private fun machine(vararg weights: Double) = Machine(
        id = UUID.randomUUID(),
        name = "Test Machine",
        availableWeights = weights.map(::BaseWeight)
    )
}

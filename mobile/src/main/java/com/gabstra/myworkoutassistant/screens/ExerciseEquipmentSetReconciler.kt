package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID
import kotlin.math.abs

internal fun reconcileSetsForEquipmentChange(
    sets: List<Set>,
    previousEquipmentId: UUID?,
    selectedEquipment: WeightLoadedEquipment?
): List<Set> {
    if (previousEquipmentId == selectedEquipment?.id) return sets

    val availableWeights = selectedEquipment?.getWeightsCombinations().orEmpty()
    return sets.map { set ->
        when {
            set is BodyWeightSet && selectedEquipment == null -> set.copy(additionalWeight = 0.0)
            set is BodyWeightSet && availableWeights.isNotEmpty() -> set.copy(
                additionalWeight = availableWeights.closestTo(set.additionalWeight)
            )
            set is WeightSet && availableWeights.isNotEmpty() -> set.copy(
                weight = availableWeights.closestTo(set.weight)
            )
            else -> set
        }
    }
}

private fun Collection<Double>.closestTo(target: Double): Double =
    minBy { candidate -> abs(candidate - target) }

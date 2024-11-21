package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class Dumbbells (
    id : UUID,
    override val name: String,
    val availableDumbbells: List<DumbbellUnit>, // List of available dumbbells
    additionalPlates: List<Plate> = emptyList(),
    maxAdditionalItems: Int = 0
) : Equipment(id,additionalPlates, maxAdditionalItems, EquipmentType.DUMBBELLS) {

    override fun calculateBaseCombinations(): Set<Double> {
        return availableDumbbells.map { it.weight }.toSet()
    }
}
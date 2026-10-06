package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class CardioMachine(
    id: UUID,
    override val name: String,
) : WeightLoadedEquipment(id, EquipmentType.CARDIO_MACHINE) {
    override fun getBaseCombinations(): Set<List<BaseWeight>> = emptySet()

    override fun formatWeight(weight: Double): String = ""
}

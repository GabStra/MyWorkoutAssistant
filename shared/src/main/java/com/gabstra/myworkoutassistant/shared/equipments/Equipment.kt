package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

abstract class Equipment(
    val id: UUID,
    val type: EquipmentType
) {
    abstract val name: String
}
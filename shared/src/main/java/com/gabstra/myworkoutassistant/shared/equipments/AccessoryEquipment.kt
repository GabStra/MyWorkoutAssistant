package com.gabstra.myworkoutassistant.shared.equipments

import java.util.UUID

class AccessoryEquipment(
    id: UUID,
    override val name: String,
) : Equipment(id, EquipmentType.ACCESSORY)


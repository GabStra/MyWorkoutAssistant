package com.gabstra.myworkoutassistant.shared.equipments

enum class EquipmentType {
    GENERIC,
    BARBELL,
    DUMBBELLS,
    DUMBBELL,
    PLATELOADEDCABLE,
    WEIGHTVEST,
    MACHINE,
    IRONNECK
}


fun EquipmentType.toDisplayText(): String {
    return when (this) {
        EquipmentType.GENERIC -> "Generic"
        EquipmentType.BARBELL -> "Barbell"
        EquipmentType.DUMBBELLS -> "Dumbbells"
        EquipmentType.DUMBBELL -> "Dumbbell"
        EquipmentType.PLATELOADEDCABLE -> "Plate Loaded Cable"
        EquipmentType.WEIGHTVEST -> "Weight Vest"
        EquipmentType.MACHINE -> "Machine"
        EquipmentType.IRONNECK -> "Iron Neck"
    }
}
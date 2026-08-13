package com.gabstra.myworkoutassistant.shared.equipments

import com.gabstra.myworkoutassistant.shared.ExerciseType

enum class EquipmentType {
    GENERIC,
    BARBELL,
    DUMBBELLS,
    DUMBBELL,
    PLATELOADEDCABLE,
    WEIGHTVEST,
    MACHINE,
    CARDIO_MACHINE,
    IRONNECK,
    ACCESSORY
}


fun EquipmentType.toDisplayText(): String {
    return when (this) {
        EquipmentType.GENERIC -> "Generic"
        EquipmentType.BARBELL -> "Barbell"
        EquipmentType.DUMBBELLS -> "Dumbbell Pair"
        EquipmentType.DUMBBELL -> "Dumbbell"
        EquipmentType.PLATELOADEDCABLE -> "Plate Loaded Cable"
        EquipmentType.WEIGHTVEST -> "Weight Vest"
        EquipmentType.MACHINE -> "Machine"
        EquipmentType.CARDIO_MACHINE -> "Cardio Machine"
        EquipmentType.IRONNECK -> "Iron Neck"
        EquipmentType.ACCESSORY -> "Accessory"
    }
}

fun WeightLoadedEquipment.isCompatibleWith(exerciseType: ExerciseType): Boolean {
    return when (type) {
        EquipmentType.CARDIO_MACHINE ->
            exerciseType == ExerciseType.COUNTUP || exerciseType == ExerciseType.COUNTDOWN
        EquipmentType.ACCESSORY -> false
        else ->
            exerciseType == ExerciseType.WEIGHT || exerciseType == ExerciseType.BODY_WEIGHT
    }
}

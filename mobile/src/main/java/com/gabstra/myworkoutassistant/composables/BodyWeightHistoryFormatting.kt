package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData

fun formatHistoricalBodyWeightSetValue(
    setData: BodyWeightSetData,
    equipment: WeightLoadedEquipment?
): String {
    val bodyWeightText = formatWeight(setData.relativeBodyWeightInKg)
    val additionalWeight = setData.additionalWeight

    if (additionalWeight == 0.0) {
        return bodyWeightText
    }

    val formattedAdditionalWeight = equipment?.formatWeight(kotlin.math.abs(additionalWeight))
        ?: formatWeight(kotlin.math.abs(additionalWeight))
    val separator = if (additionalWeight > 0) " + " else " - "

    return bodyWeightText + separator + formattedAdditionalWeight
}

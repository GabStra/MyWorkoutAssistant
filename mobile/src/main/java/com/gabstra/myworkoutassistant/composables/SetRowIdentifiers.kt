package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet

private const val CalibrationSetIdentifier = "Cal"
private const val WarmupSetIdentifierPrefix = "W"

internal fun buildSetRowIdentifier(
    baseIdentifier: Int,
    setSubCategory: SetSubCategory?,
): String {
    return when (setSubCategory) {
        SetSubCategory.WarmupSet -> "$WarmupSetIdentifierPrefix$baseIdentifier"
        SetSubCategory.CalibrationSet -> CalibrationSetIdentifier
        else -> baseIdentifier.toString()
    }
}

internal fun resolveSetSubCategory(set: Set): SetSubCategory? {
    return when (set) {
        is WeightSet -> set.subCategory
        is BodyWeightSet -> set.subCategory
        is RestSet -> set.subCategory
        else -> null
    }
}

internal fun resolveSetSubCategory(setData: SetData): SetSubCategory? {
    return when (setData) {
        is WeightSetData -> setData.subCategory
        is BodyWeightSetData -> setData.subCategory
        is RestSetData -> setData.subCategory
        else -> null
    }
}

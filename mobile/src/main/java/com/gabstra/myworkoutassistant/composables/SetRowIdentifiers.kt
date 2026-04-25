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
import com.gabstra.myworkoutassistant.shared.workout.display.SetDisplayCounterKind
import com.gabstra.myworkoutassistant.shared.workout.display.displayCounterKindForSubCategory

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

internal class SetRowIdentifierCounter {
    private var workSetCount = 0
    private var warmupSetCount = 0
    private var calibrationSetCount = 0

    fun nextIdentifier(setSubCategory: SetSubCategory?): String {
        return when (displayCounterKindForSubCategory(setSubCategory)) {
            SetDisplayCounterKind.Warmup -> {
                warmupSetCount += 1
                buildSetRowIdentifier(warmupSetCount, setSubCategory)
            }
            SetDisplayCounterKind.Calibration -> {
                calibrationSetCount += 1
                buildSetRowIdentifier(calibrationSetCount, setSubCategory)
            }
            SetDisplayCounterKind.Work -> {
                workSetCount += 1
                buildSetRowIdentifier(workSetCount, setSubCategory)
            }
        }
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

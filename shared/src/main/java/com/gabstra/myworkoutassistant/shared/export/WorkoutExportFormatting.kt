package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlin.math.abs

internal fun formatSetInlineForExport(set: Set): String {
    return when (set) {
        is WeightSet -> {
            var str = "${formatNumber(set.weight)} kg x ${set.reps} reps"
            if (set.subCategory != SetSubCategory.WorkSet) {
                str += " [${set.subCategory.name}]"
            }
            str
        }
        is BodyWeightSet -> {
            var str = "Body weight"
            if (set.additionalWeight > 0) {
                str += " + ${formatNumber(set.additionalWeight)} kg"
            } else if (set.additionalWeight < 0) {
                str += " - ${formatNumber(-set.additionalWeight)} kg"
            }
            str += " x ${set.reps} reps"
            if (set.subCategory != SetSubCategory.WorkSet) {
                str += " [${set.subCategory.name}]"
            }
            str
        }
        is TimedDurationSet -> {
            val minutes = set.timeInMillis / 60000
            val seconds = (set.timeInMillis % 60000) / 1000
            "${minutes}:${String.format("%02d", seconds)}"
        }
        is EnduranceSet -> {
            val minutes = set.timeInMillis / 60000
            val seconds = (set.timeInMillis % 60000) / 1000
            "${minutes}:${String.format("%02d", seconds)} (endurance)"
        }
        is RestSet -> "${set.timeInSeconds} seconds rest"
    }
}

internal fun normalizeWeightForExport(
    targetWeight: Double,
    achievableWeights: List<Double>?
): Double {
    if (achievableWeights.isNullOrEmpty()) return targetWeight
    return achievableWeights.minByOrNull { achievable -> abs(achievable - targetWeight) } ?: targetWeight
}

internal fun formatVolumeKgForExport(volumeKg: Double): String {
    val rounded = kotlin.math.round(volumeKg)
    return if (abs(volumeKg - rounded) < 0.0001) {
        rounded.toInt().toString()
    } else {
        "%.2f".format(volumeKg)
            .replace(",", ".")
            .replace(Regex("""\.?0+$"""), "")
    }
}

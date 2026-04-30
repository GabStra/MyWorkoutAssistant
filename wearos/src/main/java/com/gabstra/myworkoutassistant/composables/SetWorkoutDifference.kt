package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

enum class SetComparison {
    BETTER, EQUAL, WORSE, MIXED
}

/** Per-metric direction for a displayed delta line (null when that line is not shown). */
enum class SetSegmentTrend {
    BETTER,
    WORSE,
    EQUAL,
}

data class SetDeltaLine(val text: String, val trend: SetSegmentTrend?)

data class SetDifference(
    val comparison: SetComparison = SetComparison.EQUAL,
    val weightText: String? = null,
    val weightTrend: SetSegmentTrend? = null,
    val repsText: String? = null,
    val repsTrend: SetSegmentTrend? = null,
    val durationText: String? = null,
    val durationTrend: SetSegmentTrend? = null,
) {
    val displayText: String
        get() {
            val parts = listOfNotNull(weightText, repsText, durationText)
            return if (parts.isEmpty()) "No change" else parts.joinToString(" ")
        }

    /** Non-empty weight / reps / duration lines with their segment trends (for split rendering). */
    val deltaLines: List<SetDeltaLine>
        get() = buildList {
            weightText?.let { add(SetDeltaLine(it, weightTrend)) }
            repsText?.let { add(SetDeltaLine(it, repsTrend)) }
            durationText?.let { add(SetDeltaLine(it, durationTrend)) }
        }
}

private fun segmentTrendFromSignedInt(diff: Int): SetSegmentTrend = when {
    diff > 0 -> SetSegmentTrend.BETTER
    diff < 0 -> SetSegmentTrend.WORSE
    else -> SetSegmentTrend.EQUAL
}

private fun segmentTrendFromSignedDouble(diff: Double): SetSegmentTrend = when {
    diff > 0.0 -> SetSegmentTrend.BETTER
    diff < 0.0 -> SetSegmentTrend.WORSE
    else -> SetSegmentTrend.EQUAL
}

private fun compareRepsAndWeight(
    beforeReps: Int,
    beforeWeight: Double,
    afterReps: Int,
    afterWeight: Double,
): SetComparison = when {
    afterReps == beforeReps && afterWeight == beforeWeight -> SetComparison.EQUAL
    (afterWeight > beforeWeight && afterReps < beforeReps) ||
        (afterWeight < beforeWeight && afterReps > beforeReps) -> SetComparison.MIXED
    (afterWeight == beforeWeight && afterReps > beforeReps) ||
        (afterReps == beforeReps && afterWeight > beforeWeight) ||
        (afterReps > beforeReps && afterWeight > beforeWeight) -> SetComparison.BETTER
    else -> SetComparison.WORSE
}

private fun compareDurationMs(beforeDurationMs: Int, afterDurationMs: Int): SetComparison = when {
    afterDurationMs == beforeDurationMs -> SetComparison.EQUAL
    afterDurationMs > beforeDurationMs -> SetComparison.BETTER
    else -> SetComparison.WORSE
}

fun compareSets(beforeSetData: SetData?, afterSetData: SetData?): SetComparison {
    if (beforeSetData == null || afterSetData == null) {
        return SetComparison.EQUAL
    }

    return when {
        beforeSetData is WeightSetData && afterSetData is WeightSetData ->
            compareRepsAndWeight(
                beforeSetData.actualReps,
                beforeSetData.actualWeight,
                afterSetData.actualReps,
                afterSetData.actualWeight,
            )
        beforeSetData is BodyWeightSetData && afterSetData is BodyWeightSetData ->
            compareRepsAndWeight(
                beforeSetData.actualReps,
                beforeSetData.getWeight(),
                afterSetData.actualReps,
                afterSetData.getWeight(),
            )
        beforeSetData is EnduranceSetData && afterSetData is EnduranceSetData ->
            compareDurationMs(
                beforeSetData.endTimer - beforeSetData.startTimer,
                afterSetData.endTimer - afterSetData.startTimer,
            )
        beforeSetData is TimedDurationSetData && afterSetData is TimedDurationSetData ->
            compareDurationMs(
                beforeSetData.endTimer - beforeSetData.startTimer,
                afterSetData.endTimer - afterSetData.startTimer,
            )
        else -> SetComparison.EQUAL
    }
}

private fun setDifferenceForElapsedSeconds(
    comparison: SetComparison,
    beforeElapsedSeconds: Int,
    afterElapsedSeconds: Int,
): SetDifference {
    val durationDiff = afterElapsedSeconds - beforeElapsedSeconds
    if (durationDiff == 0) return SetDifference(comparison = comparison)
    val sign = if (durationDiff > 0) "+" else ""
    return SetDifference(
        comparison = comparison,
        durationText = "$sign${FormatTime(durationDiff)}",
        durationTrend = segmentTrendFromSignedInt(durationDiff),
    )
}

fun calculateSetDifference(
    beforeSetData: SetData?,
    afterSetData: SetData?,
    equipment: Equipment?,
): SetDifference {
    if (beforeSetData == null || afterSetData == null) {
        return SetDifference()
    }

    val comparison = compareSets(beforeSetData, afterSetData)

    return when {
        beforeSetData is WeightSetData && afterSetData is WeightSetData ->
            weightAndRepsDifference(
                beforeWeight = beforeSetData.actualWeight,
                afterWeight = afterSetData.actualWeight,
                beforeReps = beforeSetData.actualReps,
                afterReps = afterSetData.actualReps,
                equipment = equipment,
                comparison = comparison,
            )
        beforeSetData is BodyWeightSetData && afterSetData is BodyWeightSetData ->
            weightAndRepsDifference(
                beforeWeight = beforeSetData.getWeight(),
                afterWeight = afterSetData.getWeight(),
                beforeReps = beforeSetData.actualReps,
                afterReps = afterSetData.actualReps,
                equipment = equipment,
                comparison = comparison,
            )
        beforeSetData is EnduranceSetData && afterSetData is EnduranceSetData ->
            setDifferenceForElapsedSeconds(
                comparison = comparison,
                beforeElapsedSeconds = (beforeSetData.endTimer - beforeSetData.startTimer) / 1000,
                afterElapsedSeconds = (afterSetData.endTimer - afterSetData.startTimer) / 1000,
            )
        beforeSetData is TimedDurationSetData && afterSetData is TimedDurationSetData ->
            setDifferenceForElapsedSeconds(
                comparison = comparison,
                beforeElapsedSeconds = (beforeSetData.endTimer - beforeSetData.startTimer) / 1000,
                afterElapsedSeconds = (afterSetData.endTimer - afterSetData.startTimer) / 1000,
            )
        else -> SetDifference(comparison = comparison)
    }
}

private fun weightAndRepsDifference(
    beforeWeight: Double,
    afterWeight: Double,
    beforeReps: Int,
    afterReps: Int,
    equipment: Equipment?,
    comparison: SetComparison,
): SetDifference {
    val weightDiff = afterWeight - beforeWeight
    val repsDiff = afterReps - beforeReps

    val weightText = if (weightDiff != 0.0 && equipment is WeightLoadedEquipment) {
        val sign = if (weightDiff > 0) "+" else ""
        "$sign${equipment.formatWeight(weightDiff)}"
    } else {
        null
    }
    val repsText = if (repsDiff != 0) {
        val sign = if (repsDiff > 0) "+" else ""
        "$sign$repsDiff"
    } else {
        null
    }

    return SetDifference(
        comparison = comparison,
        weightText = weightText,
        weightTrend = weightText?.let { segmentTrendFromSignedDouble(weightDiff) },
        repsText = repsText,
        repsTrend = repsText?.let { segmentTrendFromSignedInt(repsDiff) },
    )
}

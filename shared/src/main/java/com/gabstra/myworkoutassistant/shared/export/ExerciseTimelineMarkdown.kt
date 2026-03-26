package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.formatRestLineForMarkdown
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDateTime
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Appends merged set + intra-exercise rest timeline for one exercise. Returns (total volume kg, total timed work seconds).
 */
internal fun appendExerciseTimelineToMarkdown(
    markdown: StringBuilder,
    exercise: Exercise,
    activeSetHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    workoutHistory: WorkoutHistory,
    workoutStore: WorkoutStore,
    userAge: Int,
    achievableWeights: List<Double>?,
    equipmentNameForHeader: String?,
) {
    var totalVolume = 0.0
    var totalDuration = 0
    val timeline = mergeSessionTimeline(activeSetHistories, restsForExercise)
    var workSetOrdinal = 0
    for (step in timeline) {
        when (step) {
            is SessionTimelineItem.RestStep -> {
                val rh = step.history
                val restLine = StringBuilder(formatRestLineForMarkdown(rh))
                appendIntervalHeartRateLineForExport(
                    restLine,
                    workoutHistory,
                    rh.startTime,
                    rh.endTime,
                    exercise,
                    userAge,
                    workoutStore
                )
                markdown.append(restLine.toString()).append("\n")
            }
            is SessionTimelineItem.SetStep -> {
                workSetOrdinal += 1
                val setHistory = step.history
                val setLine = StringBuilder()
                if (setHistory.skipped) {
                    setLine.append("[skipped] ")
                }
                setLine.append("S$workSetOrdinal: ")
                when (val setData = setHistory.setData) {
                    is WeightSetData -> {
                        val (adjustedWeight, adjustedVolume) = adjustWeightAndVolumeForExport(
                            setData.actualWeight,
                            setData.actualReps,
                            achievableWeights
                        )
                        setLine.append("${formatNumber(adjustedWeight)}kg×${setData.actualReps} Vol:${formatNumber(adjustedVolume)}kg")
                        if (setData.subCategory == SetSubCategory.RestPauseSet) setLine.append(" [RP]")
                        totalVolume += adjustedVolume
                    }
                    is BodyWeightSetData -> {
                        val totalWeight = setData.getWeight()
                        setLine.append("${formatNumber(totalWeight)}kg×${setData.actualReps} Vol:${formatNumber(setData.volume)}kg")
                        if (setData.subCategory == SetSubCategory.RestPauseSet) setLine.append(" [RP]")
                        totalVolume += setData.volume
                    }
                    is TimedDurationSetData -> {
                        val durationSeconds = (setData.endTimer - setData.startTimer) / 1000
                        setLine.append("Dur:${formatDurationForExport(durationSeconds)}")
                        totalDuration += durationSeconds
                    }
                    is EnduranceSetData -> {
                        val durationSeconds = setData.endTimer / 1000
                        setLine.append("Dur:${formatDurationForExport(durationSeconds)}")
                        totalDuration += durationSeconds
                    }
                    else -> setLine.append("Rest/Other")
                }
                val snapName = setHistory.equipmentNameSnapshot
                if (!snapName.isNullOrBlank() && snapName != equipmentNameForHeader) {
                    setLine.append(" (@ $snapName)")
                }
                appendIntervalHeartRateLineForExport(
                    setLine,
                    workoutHistory,
                    setHistory.startTime,
                    setHistory.endTime,
                    exercise,
                    userAge,
                    workoutStore
                )
                markdown.append(setLine.toString()).append("\n")
            }
        }
    }
    val totalsLine = StringBuilder()
    if (totalVolume > 0) {
        totalsLine.append("Total Vol: ${formatNumber(totalVolume)}kg")
    }
    if (totalDuration > 0) {
        if (totalsLine.isNotEmpty()) totalsLine.append(" | ")
        totalsLine.append("Total Dur: ${formatDurationForExport(totalDuration)}")
    }
    if (totalsLine.isNotEmpty()) {
        markdown.append(totalsLine.toString()).append("\n")
    }
}

internal fun appendIntervalHeartRateLineForExport(
    line: StringBuilder,
    workoutHistory: WorkoutHistory,
    intervalStart: LocalDateTime?,
    intervalEnd: LocalDateTime?,
    exercise: Exercise?,
    userAge: Int,
    workoutStore: WorkoutStore,
) {
    val raw = sliceHeartRateRecords(
        workoutHistory.startTime,
        workoutHistory.heartBeatRecords,
        intervalStart,
        intervalEnd
    )
    val setHRRecords = raw.filter { it > 0 }
    if (setHRRecords.isEmpty()) return
    val setAvgHR = setHRRecords.average().toInt()
    val setMinHR = setHRRecords.minOrNull() ?: 0
    val setMaxHR = setHRRecords.maxOrNull() ?: 0
    line.append(" | HR: $setAvgHR bpm (${setMinHR}–${setMaxHR})")

    if (exercise == null) return
    val loPct = exercise.lowerBoundMaxHRPercent
    val hiPct = exercise.upperBoundMaxHRPercent
    if (loPct != null && hiPct != null) {
        val lowHr = getHeartRateFromPercentage(
            loPct,
            userAge,
            workoutStore.measuredMaxHeartRate,
            workoutStore.restingHeartRate
        )
        val highHr = getHeartRateFromPercentage(
            hiPct,
            userAge,
            workoutStore.measuredMaxHeartRate,
            workoutStore.restingHeartRate
        )
        val hrInZoneCount = setHRRecords.count { it in lowHr..highHr }
        val zonePercentage = if (setHRRecords.isNotEmpty()) {
            (hrInZoneCount.toFloat() / setHRRecords.size * 100).roundToInt()
        } else {
            0
        }
        line.append(" | Target zone: $zonePercentage%")
    }
}

internal fun formatDurationForExport(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

private fun adjustWeightAndVolumeForExport(
    actualWeight: Double,
    reps: Int,
    achievableWeights: List<Double>?
): Pair<Double, Double> {
    if (actualWeight <= 0.0 || reps <= 0) {
        return actualWeight to (actualWeight * reps)
    }
    val adjustedWeight = findClosestAchievableWeightForExport(actualWeight, achievableWeights)
    return adjustedWeight to adjustedWeight * reps
}

private fun findClosestAchievableWeightForExport(
    targetWeight: Double,
    achievableWeights: List<Double>?
): Double {
    if (achievableWeights.isNullOrEmpty()) return targetWeight
    return achievableWeights.minByOrNull { achievable -> abs(achievable - targetWeight) } ?: targetWeight
}

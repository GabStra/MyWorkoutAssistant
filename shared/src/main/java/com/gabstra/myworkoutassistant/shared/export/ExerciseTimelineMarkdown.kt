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
import com.gabstra.myworkoutassistant.shared.workout.display.SetDisplayCounterKind
import com.gabstra.myworkoutassistant.shared.workout.display.displayCounterKindForSubCategory
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDateTime
import kotlin.math.roundToInt

/**
 * Appends merged set + intra-exercise rest timeline for one exercise. Returns (total volume kg, total timed work seconds).
 */
internal fun appendExerciseTimelineToMarkdown(
    markdown: StringBuilder,
    exercise: Exercise,
    setHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    workoutHistory: WorkoutHistory,
    workoutStore: WorkoutStore,
    userAge: Int,
    achievableWeights: List<Double>?,
    equipmentNameForHeader: String?,
) {
    val timeline = mergeSessionTimeline(setHistories, restsForExercise)
    val setOrdinalCounter = TimelineSetOrdinalCounter()
    markdown.append("#### Executed Timeline\n")
    for (step in timeline) {
        when (step) {
            is SessionTimelineItem.RestStep -> {
                val rh = step.history
                markdown.append(formatRestLineForMarkdown(rh)).append("\n")
            }
            is SessionTimelineItem.SetStep -> {
                val setHistory = step.history
                val setLine = StringBuilder()
                if (setHistory.skipped) {
                    setLine.append("[skipped] ")
                }
                when (val setData = setHistory.setData) {
                    is WeightSetData -> {
                        setLine.append("${setOrdinalCounter.nextLabel(setData.subCategory)}: ")
                        val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
                        setLine.append("${formatNumber(adjustedWeight)} kg x ${setData.actualReps}")
                        appendSetCategoryLabel(setLine, setData.subCategory)
                    }
                    is BodyWeightSetData -> {
                        setLine.append("${setOrdinalCounter.nextLabel(setData.subCategory)}: ")
                        val totalWeight = setData.getWeight()
                        setLine.append("${formatNumber(totalWeight)} kg x ${setData.actualReps}")
                        appendSetCategoryLabel(setLine, setData.subCategory)
                    }
                    is TimedDurationSetData -> {
                        setLine.append("${setOrdinalCounter.nextLabel(null)}: ")
                        val durationSeconds = (setData.endTimer - setData.startTimer) / 1000
                        setLine.append("Dur:${formatDurationForExport(durationSeconds)}")
                    }
                    is EnduranceSetData -> {
                        setLine.append("${setOrdinalCounter.nextLabel(null)}: ")
                        val durationSeconds = setData.endTimer / 1000
                        setLine.append("Dur:${formatDurationForExport(durationSeconds)}")
                    }
                    else -> setLine.append("Rest/Other")
                }
                val snapName = setHistory.equipmentNameSnapshot
                if (!snapName.isNullOrBlank() && snapName != equipmentNameForHeader) {
                    setLine.append(" (@ $snapName)")
                }
                markdown.append(setLine.toString()).append("\n")
            }
        }
    }
}

private class TimelineSetOrdinalCounter {
    private var workSetCount = 0
    private var warmupSetCount = 0
    private var calibrationSetCount = 0

    fun nextLabel(subCategory: SetSubCategory?): String {
        return when (displayCounterKindForSubCategory(subCategory)) {
            SetDisplayCounterKind.Warmup -> {
                warmupSetCount += 1
                "W$warmupSetCount"
            }
            SetDisplayCounterKind.Calibration -> {
                calibrationSetCount += 1
                "Cal"
            }
            SetDisplayCounterKind.Work -> {
                workSetCount += 1
                workSetCount.toString()
            }
        }
    }
}

private fun appendSetCategoryLabel(
    line: StringBuilder,
    subCategory: SetSubCategory,
) {
    when (subCategory) {
        SetSubCategory.WarmupSet -> line.append(" [warm-up]")
        SetSubCategory.RestPauseSet -> line.append(" [rest-pause]")
        SetSubCategory.CalibrationSet -> line.append(" [calibration]")
        SetSubCategory.CalibrationPendingSet -> line.append(" [calibration-pending]")
        else -> Unit
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

package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlin.math.roundToInt

/**
 * Session-level HR block. When [exerciseForTargetBand] is non-null, appends the exercise-configured
 * target band line; omit for whole-workout export or when no per-exercise target applies.
 */
internal fun appendSessionHeartRateMarkdown(
    markdown: StringBuilder,
    workoutHistory: WorkoutHistory,
    userAge: Int,
    workoutStore: WorkoutStore,
    exerciseForTargetBand: Exercise?,
) {
    val records = workoutHistory.heartBeatRecords
    val valid = records.filter { it > 0 }
    if (valid.isEmpty()) return

    val zoneBounds = heartRateZoneBoundsBpm(
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    val zoneCounts = countZoneSamples(valid, zoneBounds)
    val zoneTime = zoneCounts
        .indices
        .mapNotNull { index ->
            val count = zoneCounts[index]
            if (count <= 0) null else "Z$index ${formatDurationForSessionHr(count)}"
        }
        .joinToString(" | ")
        .takeIf { it.isNotBlank() }
        ?: return

    markdown.append("#### Session Heart Rate\n")
    markdown.append("- Duration: ${formatDurationForSessionHr(valid.size)}\n")
    markdown.append("- Zone time: $zoneTime\n")

    exerciseForTargetBand?.let { exercise ->
        val loBoundPct = exercise.lowerBoundMaxHRPercent
        val hiBoundPct = exercise.upperBoundMaxHRPercent
        if (loBoundPct != null && hiBoundPct != null) {
            val lowHr = getHeartRateFromPercentage(
                loBoundPct,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val highHr = getHeartRateFromPercentage(
                hiBoundPct,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val hrInZoneCount = valid.count { it in lowHr..highHr }
            val zonePct = if (valid.isNotEmpty()) {
                (hrInZoneCount.toFloat() / valid.size * 100).roundToInt()
            } else 0
            markdown.append(
                "- Target band: $zonePct% between $lowHr-$highHr bpm\n"
            )
        }
    }
    markdown.append("\n")
}

internal fun appendExerciseHeartRateMarkdown(
    markdown: StringBuilder,
    workoutHistory: WorkoutHistory,
    setHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    userAge: Int,
    workoutStore: WorkoutStore,
    exerciseForTargetBand: Exercise,
) {
    val records = workoutHistory.heartBeatRecords
    if (records.isEmpty()) return

    val intervalSamples = buildList {
        setHistories.forEach { setHistory ->
            addAll(
                sliceHeartRateRecords(
                    workoutStart = workoutHistory.startTime,
                    records = records,
                    intervalStart = setHistory.startTime,
                    intervalEnd = setHistory.endTime
                )
            )
        }
        restsForExercise.forEach { restHistory ->
            addAll(
                sliceHeartRateRecords(
                    workoutStart = workoutHistory.startTime,
                    records = records,
                    intervalStart = restHistory.startTime,
                    intervalEnd = restHistory.endTime
                )
            )
        }
    }.filter { it > 0 }
    if (intervalSamples.isEmpty()) return

    val zoneBounds = heartRateZoneBoundsBpm(
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    val zoneCounts = countZoneSamples(intervalSamples, zoneBounds)
    val zoneTime = zoneCounts
        .indices
        .mapNotNull { index ->
            val count = zoneCounts[index]
            if (count <= 0) null else "Z$index ${formatDurationForSessionHr(count)}"
        }
        .joinToString(" | ")
        .takeIf { it.isNotBlank() }
        ?: return

    markdown.append("#### Exercise Heart Rate\n")
    markdown.append("- Duration: ${formatDurationForSessionHr(intervalSamples.size)}\n")
    markdown.append("- Zone time: $zoneTime\n")

    val loBoundPct = exerciseForTargetBand.lowerBoundMaxHRPercent
    val hiBoundPct = exerciseForTargetBand.upperBoundMaxHRPercent
    if (loBoundPct != null && hiBoundPct != null) {
        val lowHr = getHeartRateFromPercentage(
            loBoundPct,
            userAge,
            workoutStore.measuredMaxHeartRate,
            workoutStore.restingHeartRate
        )
        val highHr = getHeartRateFromPercentage(
            hiBoundPct,
            userAge,
            workoutStore.measuredMaxHeartRate,
            workoutStore.restingHeartRate
        )
        val hrInZoneCount = intervalSamples.count { it in lowHr..highHr }
        val zonePct = (hrInZoneCount.toFloat() / intervalSamples.size * 100).roundToInt()
        markdown.append("- Target band: $zonePct% between $lowHr-$highHr bpm\n")
    }
    markdown.append("\n")
}

private fun formatDurationForSessionHr(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

private fun countZoneSamples(
    samples: List<Int>,
    zoneBounds: List<IntRange>,
): IntArray {
    if (zoneBounds.isEmpty()) return IntArray(0)
    val counts = IntArray(zoneBounds.size)
    samples.forEach { sample ->
        if (sample <= 0) return@forEach
        val zoneIndex = zoneIndexForBpm(sample, zoneBounds).coerceIn(0, zoneBounds.lastIndex)
        counts[zoneIndex]++
    }
    return counts
}

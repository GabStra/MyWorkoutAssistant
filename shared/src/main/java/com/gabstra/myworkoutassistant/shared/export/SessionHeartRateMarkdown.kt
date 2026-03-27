package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.getEffectiveMaxHeartRate
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.zoneRanges
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
    val storedSampleCount = records.size
    val recordedSpanSeconds = storedSampleCount

    val zoneBounds = heartRateZoneBoundsBpm(
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    val fractions = standardZoneSampleFractions(valid, zoneBounds)
    val derived = computeSessionHrDerived(
        valid,
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    ) ?: return

    markdown.append("#### Session Heart Rate\n\n")
    markdown.append("- Mean: ${derived.mean} bpm\n")
    derived.median?.let { markdown.append("- Median: $it bpm\n") }
    markdown.append("- Min–Max: ${derived.min}–${derived.max} bpm\n")
    derived.stdDev?.let { sd ->
        markdown.append("- Std dev: ${"%.1f".format(sd)} bpm\n")
    }
    derived.avgPctOfMaxHr?.let {
        markdown.append("- Average as % of max HR: ${"%.1f".format(it)}%\n")
    }
    derived.peakPctOfMaxHr?.let {
        markdown.append("- Peak as % of max HR: ${"%.1f".format(it)}%\n")
    }
    if (workoutStore.restingHeartRate != null) {
        derived.avgHrrPct?.let {
            markdown.append("- Average as % heart-rate reserve: ${"%.1f".format(it)}%\n")
        }
        derived.peakHrrPct?.let {
            markdown.append("- Peak as % heart-rate reserve: ${"%.1f".format(it)}%\n")
        }
    }
    derived.fractionAbove85PctMax?.let { f ->
        markdown.append("- Time at or above 85% of max HR: ${(f * 100.0).roundToInt()}% of samples\n")
    }
    derived.fractionAbove90PctMax?.let { f ->
        markdown.append("- Time at or above 90% of max HR: ${(f * 100.0).roundToInt()}% of samples\n")
    }

    markdown.append("- Standard zones (% of samples, bpm range):\n")
    for (i in fractions.indices) {
        val pct = (fractions[i] * 100.0).roundToInt()
        val range = zoneBounds[i]
        val (loPct, hiPct) = zoneRanges[i]
        markdown.append(
            "  - Z$i (${loPct}%–${hiPct}% reserve): $pct% of samples, ${range.first}–${range.last} bpm\n"
        )
    }

    markdown.append("- Stored HR samples: $storedSampleCount\n")
    markdown.append("- Valid HR samples: ${derived.validSampleCount}\n")
    if (storedSampleCount > 0) {
        val coveragePct = (derived.validSampleCount.toDouble() / storedSampleCount.toDouble() * 100.0).roundToInt()
        markdown.append("- Valid HR coverage: $coveragePct% of stored samples\n")
    }
    markdown.append(
        "- Approx. recorded HR span (from stored samples): ${formatDurationForSessionHr(recordedSpanSeconds)} (~1.0 s between samples)\n"
    )
    if (workoutHistory.duration > 0 && recordedSpanSeconds < workoutHistory.duration - 30) {
        markdown.append(
            "- Workout duration: ${formatDurationForSessionHr(workoutHistory.duration)} (stored HR span may be shorter if the sensor stream paused or samples were not captured)\n"
        )
    }

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
                "- Exercise target band: $zonePct% of samples between $lowHr–$highHr bpm (exercise-configured zone)\n"
            )
        }
    }

    val maxHrResolved = getEffectiveMaxHeartRate(userAge, workoutStore.measuredMaxHeartRate)
    markdown.append("- Max HR reference: ")
    if (workoutStore.measuredMaxHeartRate != null) {
        markdown.append("measured ${workoutStore.measuredMaxHeartRate} bpm\n\n")
    } else {
        markdown.append("age-based estimate ($maxHrResolved bpm)\n\n")
    }
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

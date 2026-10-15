package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.workout.display.formatWorkoutDurationSecondsForDisplay
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Deterministic, app-computed numbers for a finished workout session. The lines
 * are appended to the tool-calling prompt as authoritative quotes and to the
 * tool-context markdown so the numeric allow-list admits them verbatim.
 */
internal data class WorkoutSessionFacts(
    val lines: List<String>,
    /**
     * Grounded fallback when the model omits next-session advice or its advice is
     * removed by validation. Null when no next-session target fact exists.
     */
    val nextSessionTargetBullet: String? = null,
)

internal fun WorkoutSessionFacts.asPromptBlock(): String =
    if (lines.isEmpty()) {
        ""
    } else {
        "\n\nPrecomputed session facts (computed by the app from the recorded data; authoritative):\n" +
            lines.joinToString("\n")
    }

internal object WorkoutSessionFactsBuilder {
    internal const val MAX_PREVIOUS_SESSIONS = 3
    private const val MIN_SAMPLES_FOR_DRIFT = 8

    /**
     * @param previousSessionsNewestFirst completed sessions of the same workout,
     *   excluding the current one, newest first
     * @param targetBoundsPercentMaxHr flagged target zone of the session's
     *   exercises, as percent-of-max-HR bounds
     */
    fun build(
        workoutHistory: WorkoutHistory,
        previousSessionsNewestFirst: List<WorkoutHistory>,
        targetBoundsPercentMaxHr: Pair<Float, Float>?,
        userAge: Int?,
        measuredMaxHeartRate: Int?,
        restingHeartRate: Int?,
    ): WorkoutSessionFacts {
        val lines = mutableListOf<String>()
        val previous = previousSessionsNewestFirst.take(MAX_PREVIOUS_SESSIONS)
        val durationSeconds = workoutHistory.duration
        val durationMinutes = durationSeconds / 60.0
        lines += "FACT Session duration: ${formatWorkoutDurationSecondsForDisplay(durationSeconds)} (${durationMinutes.roundToInt()} minutes)"

        val heartRates = workoutHistory.heartBeatRecords.filter { it > 0 }
        var currentAverageBpm: Double? = null
        var currentDriftBpm: Int? = null
        var targetZoneBpm: String? = null
        if (heartRates.isNotEmpty()) {
            val average = heartRates.average()
            currentAverageBpm = average
            lines += "FACT Average heart rate: ${average.roundToInt()} bpm; peak ${heartRates.max()} bpm"

            if (heartRates.size >= MIN_SAMPLES_FOR_DRIFT) {
                val half = heartRates.size / 2
                val firstHalf = heartRates.subList(0, half).average()
                val secondHalf = heartRates.subList(heartRates.size - half, heartRates.size).average()
                val deltaBpm = (secondHalf - firstHalf).roundToInt()
                currentDriftBpm = deltaBpm
                val sign = if (deltaBpm >= 0) "+" else ""
                lines += "FACT Heart-rate drift: the second half averaged $sign$deltaBpm bpm versus the first half"
            }

            targetBoundsPercentMaxHr?.let { bounds ->
                val age = userAge
                if (age != null && age > 0) {
                    // Zone bounds were historically stored as 0..1 fractions or 0..100 percents.
                    val lowPercent = if (bounds.first in 0f..1f) bounds.first * 100f else bounds.first
                    val highPercent = if (bounds.second in 0f..1f) bounds.second * 100f else bounds.second
                    val lowBpm = getHeartRateFromPercentage(
                        lowPercent,
                        age,
                        measuredMaxHeartRate,
                        restingHeartRate,
                    )
                    val highBpm = getHeartRateFromPercentage(
                        highPercent,
                        age,
                        measuredMaxHeartRate,
                        restingHeartRate,
                    )
                    targetZoneBpm = "$lowBpm-$highBpm bpm"
                    val inZone = heartRates.count { sample ->
                        val percentage = getMaxHearthRatePercentage(
                            heartRate = sample,
                            age = age,
                            measuredMaxHeartRate = measuredMaxHeartRate,
                            restingHeartRate = restingHeartRate,
                        )
                        percentage in lowPercent..highPercent
                    }
                    val percentInZone = (inZone * 100.0 / heartRates.size).roundToInt()
                    lines += "FACT Whole-session time in target zone: $percentInZone% of HR samples inside " +
                        "${lowPercent.roundToInt()}-${highPercent.roundToInt()}% of heart-rate reserve ($lowBpm-$highBpm bpm)"
                }
            }
        }

        if (previous.isNotEmpty()) {
            val recentDurationMinutes = previous.map { it.duration / 60.0 }.average()
            lines += "FACT Session duration versus recent sessions of this workout: ${durationMinutes.roundToInt()} minutes versus ${recentDurationMinutes.roundToInt()} minutes typical"
        }
        if (currentAverageBpm != null) {
            val previousAverages = previous
                .map { history -> history.heartBeatRecords.filter { it > 0 } }
                .filter { it.isNotEmpty() }
                .map { it.average() }
            if (previousAverages.isNotEmpty()) {
                val recentAverage = previousAverages.average()
                val deltaBpm = (currentAverageBpm - recentAverage).roundToInt()
                val comparison = when {
                    deltaBpm <= -2 ->
                        "average HR is ${abs(deltaBpm)} bpm below the recent ${recentAverage.roundToInt()} bpm average"
                    deltaBpm >= 2 ->
                        "average HR is $deltaBpm bpm above the recent ${recentAverage.roundToInt()} bpm average"
                    else ->
                        "average HR is within 1 bpm of the recent ${recentAverage.roundToInt()} bpm average"
                }
                lines += "FACT Trend over the last ${previousAverages.size} sessions of this workout: $comparison"
            }
        }
        if (currentDriftBpm != null) {
            val previousDrifts = previous
                .map { history -> history.heartBeatRecords.filter { it > 0 } }
                .filter { it.size >= MIN_SAMPLES_FOR_DRIFT }
                .map { samples ->
                    val half = samples.size / 2
                    (samples.subList(samples.size - half, samples.size).average() -
                        samples.subList(0, half).average()).roundToInt()
                }
            if (previousDrifts.isNotEmpty()) {
                val typicalDrift = previousDrifts.average().roundToInt()
                val currentSign = if (currentDriftBpm >= 0) "+" else ""
                val typicalSign = if (typicalDrift >= 0) "+" else ""
                lines += "FACT HR drift this session: $currentSign$currentDriftBpm bpm versus your typical $typicalSign$typicalDrift bpm on this workout"
            }
        }

        var nextSessionTargetBullet: String? = null
        if (targetZoneBpm != null) {
            lines += "FACT Next-session target: stay within the configured $targetZoneBpm zone during the targeted exercise"
            nextSessionTargetBullet = "Repeat the planned work in the configured $targetZoneBpm zone; compare heart rate only at a similar workload."
        }

        return WorkoutSessionFacts(lines, nextSessionTargetBullet)
    }
}

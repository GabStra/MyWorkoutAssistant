package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.workout.display.formatWorkoutDurationSecondsForDisplay
import kotlin.math.abs
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Deterministic, app-computed numbers for a finished workout session. The lines
 * are appended to the tool-calling prompt as authoritative quotes and to the
 * tool-context markdown so the numeric allow-list admits them verbatim.
 */
internal data class WorkoutSessionFacts(val lines: List<String>)

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
    private const val TARGET_MINUTE_STEP = 5

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
                    val inZone = heartRates.count { sample ->
                        val percentage = getMaxHearthRatePercentage(
                            heartRate = sample,
                            age = age,
                            measuredMaxHeartRate = measuredMaxHeartRate,
                            restingHeartRate = restingHeartRate,
                        )
                        percentage in bounds.first..bounds.second
                    }
                    val percentInZone = (inZone * 100.0 / heartRates.size).roundToInt()
                    lines += "FACT $percentInZone% of HR samples stayed inside the ${bounds.first.roundToInt()}-${bounds.second.roundToInt()}% target zone"
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
                val direction = when {
                    deltaBpm <= -2 ->
                        "improving — average HR is ${abs(deltaBpm)} bpm below the recent ${recentAverage.roundToInt()} bpm average"
                    deltaBpm >= 2 ->
                        "regressing — average HR is $deltaBpm bpm above the recent ${recentAverage.roundToInt()} bpm average"
                    else ->
                        "steady — average HR within 1 bpm of the recent ${recentAverage.roundToInt()} bpm average"
                }
                lines += "FACT Trend over the last ${previousAverages.size} sessions of this workout: $direction; at a similar duration, a lower average HR means better aerobic efficiency"
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

        val immediatePrevious = previous.firstOrNull()
        if (currentAverageBpm != null && immediatePrevious != null) {
            val previousHeartRates = immediatePrevious.heartBeatRecords.filter { it > 0 }
            if (previousHeartRates.isNotEmpty()) {
                val targetBpm = previousHeartRates.average().roundToInt()
                val targetMinutes = targetMinutesBucket(immediatePrevious.duration)
                val met = currentAverageBpm <= targetBpm + 2 &&
                    durationSeconds >= immediatePrevious.duration - 300
                val verdict = if (met) "target met" else "target not met"
                lines += "FACT Previous-session target check: the target was average HR at or under $targetBpm bpm for about $targetMinutes minutes; this session averaged ${currentAverageBpm.roundToInt()} bpm across ${durationMinutes.roundToInt()} minutes — $verdict"
            }
        }
        if (currentAverageBpm != null) {
            val targetMinutes = targetMinutesBucket(durationSeconds)
            lines += "FACT Next-session target: average heart rate at or under ${currentAverageBpm.roundToInt()} bpm for about $targetMinutes minutes"
        }

        return WorkoutSessionFacts(lines)
    }

    private fun targetMinutesBucket(durationSeconds: Int): Int =
        maxOf(TARGET_MINUTE_STEP, durationSeconds / 60 / TARGET_MINUTE_STEP * TARGET_MINUTE_STEP)
}

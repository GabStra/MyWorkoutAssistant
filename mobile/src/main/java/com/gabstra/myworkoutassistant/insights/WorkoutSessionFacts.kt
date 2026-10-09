package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.workout.display.formatWorkoutDurationSecondsForDisplay
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
        val durationSeconds = workoutHistory.duration
        val durationMinutes = durationSeconds / 60.0
        lines += "FACT Session duration: ${formatWorkoutDurationSecondsForDisplay(durationSeconds)} (${durationMinutes.roundToInt()} minutes)"

        val heartRates = workoutHistory.heartBeatRecords.filter { it > 0 }
        var currentAverageBpm: Double? = null
        if (heartRates.isNotEmpty()) {
            val average = heartRates.average()
            currentAverageBpm = average
            lines += "FACT Average heart rate: ${average.roundToInt()} bpm; peak ${heartRates.max()} bpm"

            if (heartRates.size >= MIN_SAMPLES_FOR_DRIFT) {
                val half = heartRates.size / 2
                val firstHalf = heartRates.subList(0, half).average()
                val secondHalf = heartRates.subList(heartRates.size - half, heartRates.size).average()
                val deltaBpm = (secondHalf - firstHalf).roundToInt()
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

        val previous = previousSessionsNewestFirst.take(MAX_PREVIOUS_SESSIONS)
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
                val sign = if (deltaBpm >= 0) "+" else ""
                lines += "FACT Average heart rate versus recent sessions of this workout: $sign$deltaBpm bpm versus ${recentAverage.roundToInt()} bpm (at a similar duration, a lower average HR means better aerobic efficiency)"
            }
        }

        return WorkoutSessionFacts(lines)
    }
}

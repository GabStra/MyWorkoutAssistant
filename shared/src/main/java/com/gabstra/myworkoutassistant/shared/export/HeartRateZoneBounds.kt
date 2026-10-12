package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.Calendar
import java.util.Locale
import kotlin.math.roundToInt

/**
 * Target HR zones are flagged as percent bounds, but the app computes them against the
 * heart-rate RESERVE (Karvonen: (HR - resting) / (max - resting)), not against max HR.
 * Every surfaced zone line must say "% of heart-rate reserve" and include the bpm bounds,
 * otherwise "60-70% of max HR" reads as a different (and wrong) target to the user.
 */
const val HEART_RATE_RESERVE_UNIT_PHRASE = "of heart-rate reserve"

/** Zone bounds were historically stored either as 0..1 fractions or as 0..100 percents. */
fun normalizeHeartRatePercentBound(value: Float): Float =
    if (value in 0f..1f) value * 100f else value

fun formatHeartRatePercentBound(value: Float): String {
    val percent = normalizeHeartRatePercentBound(value).toDouble()
    return if (percent == percent.roundToInt().toDouble()) {
        percent.roundToInt().toString()
    } else {
        String.format(Locale.US, "%.1f", percent)
    }
}

/**
 * Resolves an exercise's flagged target zone to bpm bounds, or null when either bound
 * is missing. [userAge] defaults to the store-derived age used by the export builders.
 */
fun targetZoneBpmBounds(
    exercise: Exercise,
    workoutStore: WorkoutStore,
    userAge: Int? = null,
): Pair<Int, Int>? {
    val lower = exercise.lowerBoundMaxHRPercent ?: return null
    val upper = exercise.upperBoundMaxHRPercent ?: return null
    val age = userAge ?: (Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear)
    val normalizedLower = normalizeHeartRatePercentBound(lower)
    val normalizedUpper = normalizeHeartRatePercentBound(upper)
    val lowBpm = getHeartRateFromPercentage(
        normalizedLower,
        age,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate,
    )
    val highBpm = getHeartRateFromPercentage(
        normalizedUpper,
        age,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate,
    )
    return lowBpm to highBpm
}

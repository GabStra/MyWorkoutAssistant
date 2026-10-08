package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.roundToInt

/**
 * Heart-rate based energy-expenditure estimation (Keytel et al. 2005).
 *
 * This is an ESTIMATE with real error bars (roughly ±15% for steady-state aerobic
 * work; weaker for intervals and strength work). Machine displays that use actual
 * power output remain the more accurate number for rowers/bike ergs.
 *
 * @param heartRateBpm average or instantaneous heart rate; clamped to 30-250
 * @param durationMillis elapsed duration of the effort
 * @param weightKg body weight in kilograms
 * @param ageYears age in years
 * @param female sex drives the published coefficient sets; when unknown (the app
 *   profile has no sex field) the two formulas are averaged
 * @return whole kilocalories, 0 when inputs are unusable
 */
fun estimateCaloriesKcal(
    heartRateBpm: Int,
    durationMillis: Long,
    weightKg: Double,
    ageYears: Int,
    female: Boolean? = null,
): Int {
    if (durationMillis <= 0L || weightKg <= 0.0 || ageYears <= 0) {
        return 0
    }
    val clampedHr = heartRateBpm.coerceIn(30, 250)
    val minutes = durationMillis / 60000.0
    val maleKcalPerMinute =
        (-55.0969 + 0.6309 * clampedHr + 0.1988 * weightKg + 0.2017 * ageYears) / 4.184
    val femaleKcalPerMinute =
        (-20.4022 + 0.4472 * clampedHr - 0.1263 * weightKg + 0.074 * ageYears) / 4.184
    val kcalPerMinute = when (female) {
        true -> femaleKcalPerMinute
        false -> maleKcalPerMinute
        null -> (maleKcalPerMinute + femaleKcalPerMinute) / 2.0
    }
    return (kcalPerMinute * minutes).roundToInt().coerceAtLeast(0)
}

package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.roundToInt

/**
 * Heart-rate based energy-expenditure rate in kcal/minute.
 *
 * Two engines, chosen by input availability:
 *  1. VO2max-aware (preferred): converts heart rate into % of heart-rate reserve
 *     (Karvonen), maps %HRR to %VO2 reserve (the ACSM ~1:1 relationship), applies
 *     it to the user's VO2max with a 3.5 mL/kg/min resting floor, and converts
 *     oxygen consumed to energy at 5.05 kcal/L (RER ~0.9). This corrects the
 *     fitness bias of population formulas: fitter users burn less at the same HR.
 *  2. Keytel et al. 2005 fallback when no VO2max is available. Sex drives the
 *     published coefficient sets; when unknown the two formulas are averaged.
 *
 * This is an ESTIMATE with real error bars (roughly ±15% for steady-state aerobic
 * work; weaker for intervals and strength work). Machine displays that use actual
 * power output remain the more accurate number for rowers/bike ergs.
 *
 * The rate can be negative at near-resting heart rates (both formulas have a
 * negative intercept); callers integrating over time decide how to handle that.
 *
 * @param heartRateBpm average or instantaneous heart rate; clamped to 30-250
 * @param weightKg body weight in kilograms
 * @param ageYears age in years
 * @param female sex for the Keytel coefficients; null = average both
 * @param vo2MaxMlKgMin user/estimated VO2max; enables the VO2max engine
 * @param maxHeartRateBpm effective HRmax (measured or age-predicted)
 * @param restingHeartRateBpm effective resting HR (user, Health Connect, or 60 default)
 * @return kcal per minute, 0.0 when inputs are unusable
 */
fun estimateKcalPerMinute(
    heartRateBpm: Int,
    weightKg: Double,
    ageYears: Int,
    female: Boolean? = null,
    vo2MaxMlKgMin: Double? = null,
    maxHeartRateBpm: Int? = null,
    restingHeartRateBpm: Int? = null,
): Double {
    if (weightKg <= 0.0 || ageYears <= 0) {
        return 0.0
    }
    val vo2Max = vo2MaxMlKgMin?.takeIf { it in 15.0..90.0 }
    val hrMax = maxHeartRateBpm?.takeIf { it in 100..250 }
    if (vo2Max != null && hrMax != null) {
        val clampedHr = heartRateBpm.coerceIn(30, 250)
        val hrRest = (restingHeartRateBpm ?: 60).coerceIn(25, 120)
        val heartRateReserve = (hrMax - hrRest).coerceAtLeast(1)
        val fractionOfReserve = (clampedHr - hrRest).toDouble() / heartRateReserve
        if (fractionOfReserve in 0.10..1.10) {
            // %VO2R maps ~1:1 to %HRR (ACSM); VO2 = VO2rest + %VO2R * (VO2max - VO2rest)
            val vo2MlKgMin = 3.5 + fractionOfReserve.coerceAtMost(1.0) * (vo2Max - 3.5)
            val litersO2PerMinute = vo2MlKgMin * weightKg / 1000.0
            return litersO2PerMinute * 5.05
        }
    }

    val clampedHr = heartRateBpm.coerceIn(30, 250)
    val maleKcalPerMinute =
        (-55.0969 + 0.6309 * clampedHr + 0.1988 * weightKg + 0.2017 * ageYears) / 4.184
    val femaleKcalPerMinute =
        (-20.4022 + 0.4472 * clampedHr - 0.1263 * weightKg + 0.074 * ageYears) / 4.184
    return when (female) {
        true -> femaleKcalPerMinute
        false -> maleKcalPerMinute
        null -> (maleKcalPerMinute + femaleKcalPerMinute) / 2.0
    }
}

/**
 * Whole-effort form of [estimateKcalPerMinute]: the rate applied over one
 * [durationMillis] span, rounded to whole kilocalories.
 *
 * @return whole kilocalories, 0 when inputs are unusable
 */
fun estimateCaloriesKcal(
    heartRateBpm: Int,
    durationMillis: Long,
    weightKg: Double,
    ageYears: Int,
    female: Boolean? = null,
    vo2MaxMlKgMin: Double? = null,
    maxHeartRateBpm: Int? = null,
    restingHeartRateBpm: Int? = null,
): Int {
    if (durationMillis <= 0L) {
        return 0
    }
    val kcalPerMinute = estimateKcalPerMinute(
        heartRateBpm = heartRateBpm,
        weightKg = weightKg,
        ageYears = ageYears,
        female = female,
        vo2MaxMlKgMin = vo2MaxMlKgMin,
        maxHeartRateBpm = maxHeartRateBpm,
        restingHeartRateBpm = restingHeartRateBpm,
    )
    return (kcalPerMinute * (durationMillis / 60000.0)).roundToInt().coerceAtLeast(0)
}

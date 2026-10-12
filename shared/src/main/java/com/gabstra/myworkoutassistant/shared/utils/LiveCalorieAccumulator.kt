package com.gabstra.myworkoutassistant.shared.utils

/**
 * Incremental integrator behind the live calorie estimate shown on workout
 * timer screens.
 *
 * Each heart-rate sample charges the interval since the previous sample at the
 * PREVIOUS sample's rate, so the running total is a true integral of past
 * heart-rate data: it only ever grows during a set, a dropped sensor reading
 * simply pauses accumulation, and no later sample can shrink what was already
 * burned. This replaces the stateless `rate(currentHr) x elapsed` display,
 * which fell back whenever the current heart rate dipped.
 *
 * Intervals are measured on the caller's on-screen elapsed clock, so paused
 * time is charged nothing. A clock that jumps backwards well beyond tick
 * jitter (set restarted, next set started) begins a fresh run at zero.
 *
 * Not thread-safe; callers must serialize feeds.
 */
class LiveCalorieAccumulator {

    private var cumulativeKcal = 0.0
    private var lastHeartRateBpm = 0
    private var lastElapsedMillis = NO_SAMPLE

    /**
     * Folds one sample into the running total.
     *
     * @param heartRateBpm the new heart-rate reading
     * @param elapsedMillis the set's on-screen elapsed clock at this sample
     * @param kcalPerMinuteFor converts a heart-rate sample into kcal/minute
     * @return the un-rounded cumulative total in kcal
     */
    fun onSample(
        heartRateBpm: Int,
        elapsedMillis: Long,
        kcalPerMinuteFor: (Int) -> Double,
    ): Double {
        if (lastElapsedMillis != NO_SAMPLE &&
            elapsedMillis < lastElapsedMillis - RESTART_TOLERANCE_MILLIS
        ) {
            reset()
        }
        if (lastElapsedMillis == NO_SAMPLE) {
            // First sample of a run: baseline only, there is no interval to charge.
            lastHeartRateBpm = heartRateBpm
            lastElapsedMillis = elapsedMillis
            return cumulativeKcal
        }
        val deltaMillis = (elapsedMillis - lastElapsedMillis).coerceIn(0L, MAX_SAMPLE_INTERVAL_MILLIS)
        if (deltaMillis > 0) {
            // Keytel goes negative at near-resting HR; a rest segment must not
            // drain the total, so the interval rate is floored at zero.
            val rate = kcalPerMinuteFor(lastHeartRateBpm).coerceAtLeast(0.0)
            cumulativeKcal += rate * deltaMillis / 60000.0
        }
        lastHeartRateBpm = heartRateBpm
        lastElapsedMillis = elapsedMillis
        return cumulativeKcal
    }

    fun reset() {
        cumulativeKcal = 0.0
        lastHeartRateBpm = 0
        lastElapsedMillis = NO_SAMPLE
    }

    private companion object {
        const val NO_SAMPLE = -1L

        // Bounds the charge of a single sample across screen-off gaps or timer
        // edits so one weird reading cannot add minutes of phantom burn.
        const val MAX_SAMPLE_INTERVAL_MILLIS = 120_000L

        // Small backwards jitter (timer re-anchor after recovery) is ignored;
        // only a real restart moves the clock backwards by more than this.
        const val RESTART_TOLERANCE_MILLIS = 5_000L
    }
}

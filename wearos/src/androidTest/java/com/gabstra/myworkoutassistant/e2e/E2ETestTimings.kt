package com.gabstra.myworkoutassistant.e2e

object E2ETestTimings {
    const val DEFAULT_TIMEOUT_MS: Long = 2_000

    /** Per-attempt timeout for app window to appear. Used with retry for reliability. */
    const val APP_LAUNCH_WINDOW_TIMEOUT_MS: Long = 4_000

    /** Max time to wait for main screen content after window is visible. */
    const val APP_LAUNCH_CONTENT_READY_MS: Long = 6_000

    const val SHORT_IDLE_MS: Long = 100

    const val MEDIUM_IDLE_MS: Long = 200

    const val LONG_IDLE_MS: Long = 350

    const val CROSS_DEVICE_SYNC_TIMEOUT_MS: Long = 45_000

    const val CROSS_DEVICE_WORKOUT_TIMEOUT_MS: Long = 180_000

    const val CROSS_DEVICE_REST_AUTO_ADVANCE_TIMEOUT_MS: Long = 25_000

    const val WORKOUT_HISTORY_SYNC_DEBOUNCE_MS: Long = 600

    /**
     * Intermediate cross-device sync is debounced on Wear through E2E runtime preferences.
     * The producer must pause longer than that debounce so the phone can observe each
     * cumulative checkpoint before the next set is completed.
     */
    const val CROSS_DEVICE_INTERMEDIATE_SYNC_SETTLE_MS: Long =
        WORKOUT_HISTORY_SYNC_DEBOUNCE_MS + 400
}

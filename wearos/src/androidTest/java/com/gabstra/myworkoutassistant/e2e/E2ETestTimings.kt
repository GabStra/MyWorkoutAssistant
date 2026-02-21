package com.gabstra.myworkoutassistant.e2e

object E2ETestTimings {
    const val DEFAULT_TIMEOUT_MS: Long = 4_000
    /** Per-attempt timeout for app window to appear. Used with retry for reliability. */
    const val APP_LAUNCH_WINDOW_TIMEOUT_MS: Long = 10_000
    /** Max time to wait for main screen content after window is visible. */
    const val APP_LAUNCH_CONTENT_READY_MS: Long = 5_000
    const val SHORT_IDLE_MS: Long = 200
    const val MEDIUM_IDLE_MS: Long = 400
    const val LONG_IDLE_MS: Long = 700
}

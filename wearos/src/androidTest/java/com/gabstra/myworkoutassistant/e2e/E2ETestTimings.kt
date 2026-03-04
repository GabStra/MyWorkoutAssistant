package com.gabstra.myworkoutassistant.e2e

import androidx.test.platform.app.InstrumentationRegistry

object E2ETestTimings {
    private val fastProfile: Boolean by lazy {
        runCatching {
            InstrumentationRegistry.getArguments().getString("e2e_profile")?.equals("fast", true) == true
        }.getOrDefault(false)
    }

    val DEFAULT_TIMEOUT_MS: Long
        get() = if (fastProfile) 2_000 else 4_000

    /** Per-attempt timeout for app window to appear. Used with retry for reliability. */
    val APP_LAUNCH_WINDOW_TIMEOUT_MS: Long
        get() = if (fastProfile) 4_000 else 10_000

    /** Max time to wait for main screen content after window is visible. */
    val APP_LAUNCH_CONTENT_READY_MS: Long
        get() = if (fastProfile) 6_000 else 15_000

    val SHORT_IDLE_MS: Long
        get() = if (fastProfile) 100 else 200

    val MEDIUM_IDLE_MS: Long
        get() = if (fastProfile) 200 else 400

    val LONG_IDLE_MS: Long
        get() = if (fastProfile) 350 else 700

    val CROSS_DEVICE_SYNC_TIMEOUT_MS: Long
        get() = if (fastProfile) 45_000 else 120_000

    val CROSS_DEVICE_WORKOUT_TIMEOUT_MS: Long
        get() = if (fastProfile) 180_000 else 420_000

    val CROSS_DEVICE_REST_AUTO_ADVANCE_TIMEOUT_MS: Long
        get() = if (fastProfile) 25_000 else 75_000
}

package com.gabstra.myworkoutassistant.screens

/**
 * The watch HR sensor is part of every session now (dual recording), so preparing must see at
 * least one of its samples before starting. It is a local sensor and normally reports within a
 * couple of seconds; after this cap we stop blocking so a stuck sensor cannot trap the user.
 */
internal const val WATCH_HR_READY_TIMEOUT_MS = 10_000L

internal fun isWatchHeartRateReady(
    samplesSinceStart: Int,
    elapsedMillis: Int,
): Boolean = samplesSinceStart > 0 || elapsedMillis >= WATCH_HR_READY_TIMEOUT_MS

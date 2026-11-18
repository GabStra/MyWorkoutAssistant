package com.gabstra.myworkoutassistant.shared.datalayer

/**
 * How many recent workout histories per exercise are kept on the watch, and therefore how many
 * the phone sends. Plateau detection inspects the last 3 non-deload sessions and needs at least 4
 * sessions inside a 30-day window (see PlateauDetectionHelper), so a window of 5 leaves slack
 * without shipping sessions nothing can read.
 */
object SyncHistoryRetention {
    const val SESSIONS_PER_EXERCISE = 5
}

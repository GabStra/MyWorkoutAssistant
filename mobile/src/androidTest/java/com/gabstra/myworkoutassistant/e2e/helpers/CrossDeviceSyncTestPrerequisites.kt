package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import kotlinx.coroutines.delay
import java.util.UUID

object CrossDeviceSyncTestPrerequisites {
    private const val POLL_INTERVAL_MS = 500L
    private const val LIVE_OBSERVER_MODE = "observe_live"

    fun resolvedTimeoutMs(timeoutMs: Long): Long = timeoutMs

    fun isLiveObserverRun(): Boolean =
        InstrumentationRegistry.getArguments()
            .getString("cross_device_sync_mode")
            ?.equals(LIVE_OBSERVER_MODE, true) == true

    suspend fun findRecentMatchingHistoryId(
        context: Context,
        timeoutMs: Long,
        matches: suspend (db: AppDatabase, history: WorkoutHistory) -> Boolean
    ): UUID? {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs

        do {
            val matchingHistoryId = db.workoutHistoryDao()
                .getAllWorkoutHistories()
                .firstOrNull { history -> matches(db, history) }
                ?.id
            if (matchingHistoryId != null) {
                return matchingHistoryId
            }
            if (System.currentTimeMillis() >= deadline) {
                return null
            }
            delay(POLL_INTERVAL_MS)
        } while (true)
    }
}

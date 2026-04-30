package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context

object WorkoutHistorySyncFaultInjectionHelper {
    private const val PREFS_NAME = "e2e_workout_history_sync_faults"
    private const val TARGET_CHUNK_INDEX_KEY = "target_chunk_index"
    private const val SKIP_INITIAL_CHUNK_ONCE_KEY = "skip_initial_chunk_once"
    private const val SKIP_INITIAL_CHUNK_CONSUMED_KEY = "skip_initial_chunk_consumed"
    private const val SEND_STALE_RETRY_AFTER_COMPLETION_ONCE_KEY =
        "send_stale_retry_after_completion_once"
    private const val SEND_STALE_RETRY_AFTER_COMPLETION_CONSUMED_KEY =
        "send_stale_retry_after_completion_consumed"

    fun configureSkipChunkOnce(
        context: Context,
        targetChunkIndex: Int = 1
    ) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(SKIP_INITIAL_CHUNK_ONCE_KEY, true)
            .putInt(TARGET_CHUNK_INDEX_KEY, targetChunkIndex)
            .putBoolean(SKIP_INITIAL_CHUNK_CONSUMED_KEY, false)
            .commit()
    }

    fun configureLateStaleRetryAfterCompletionOnce(
        context: Context,
        targetChunkIndex: Int = 1
    ) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(SEND_STALE_RETRY_AFTER_COMPLETION_ONCE_KEY, true)
            .putInt(TARGET_CHUNK_INDEX_KEY, targetChunkIndex)
            .putBoolean(SEND_STALE_RETRY_AFTER_COMPLETION_CONSUMED_KEY, false)
            .commit()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}

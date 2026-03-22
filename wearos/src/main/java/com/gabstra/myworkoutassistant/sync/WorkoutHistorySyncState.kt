package com.gabstra.myworkoutassistant.sync

import android.content.Context
import androidx.core.content.edit
import kotlinx.coroutines.sync.Mutex
import java.util.UUID

object PendingWorkoutHistorySyncTracker {
    private const val PREFS_NAME = "pending_outbound_workout_history_ids"
    private const val IDS_KEY = "ids"

    fun getPendingIds(context: Context): Set<UUID> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ids = prefs.getStringSet(IDS_KEY, null) ?: emptySet()
        return ids.mapNotNull { runCatching { UUID.fromString(it) }.getOrNull() }.toSet()
    }

    fun enqueue(context: Context, id: UUID) {
        enqueue(context, listOf(id))
    }

    fun enqueue(context: Context, ids: Collection<UUID>) {
        if (ids.isEmpty()) return
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(IDS_KEY, null)?.toMutableSet() ?: mutableSetOf()
        current.addAll(ids.map(UUID::toString))
        prefs.edit { putStringSet(IDS_KEY, current) }
    }

    fun dequeue(context: Context, id: UUID) {
        dequeue(context, listOf(id))
    }

    fun dequeue(context: Context, ids: Collection<UUID>) {
        if (ids.isEmpty()) return
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(IDS_KEY, null)?.toMutableSet() ?: return
        if (current.removeAll(ids.map(UUID::toString).toSet())) {
            prefs.edit {
                if (current.isEmpty()) {
                    remove(IDS_KEY)
                } else {
                    putStringSet(IDS_KEY, current)
                }
            }
        }
    }

    fun retain(context: Context, validIds: Set<UUID>) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(IDS_KEY, null)?.toMutableSet() ?: return
        val validStrings = validIds.map(UUID::toString).toSet()
        if (current.retainAll(validStrings)) {
            prefs.edit {
                if (current.isEmpty()) {
                    remove(IDS_KEY)
                } else {
                    putStringSet(IDS_KEY, current)
                }
            }
        }
    }

    fun clear(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit { remove(IDS_KEY) }
    }
}

object WorkoutHistoryTransferCoordinator {
    val sendMutex = Mutex()
}

package com.gabstra.myworkoutassistant.sync

import android.content.Context
import androidx.core.content.edit
import kotlinx.coroutines.sync.Mutex
import java.util.UUID

/**
 * Pure helpers for the persisted set of already-synced sensor session ids. Extracted for testing;
 * [SensorSessionSyncedIdTracker] persists the set via SharedPreferences.
 */
internal object SensorSessionSyncedIds {
    fun parse(raw: Collection<String>): Set<UUID> {
        return raw.mapNotNull { value ->
            runCatching { UUID.fromString(value) }.getOrNull()
        }.toSet()
    }

    fun encode(ids: Collection<UUID>): Set<String> {
        return ids.map(UUID::toString).toSet()
    }

    fun add(current: Collection<String>, id: UUID): Set<String> {
        val updated = current.toMutableSet()
        updated.add(id.toString())
        return updated
    }
}

internal object SensorSessionSyncedIdTracker {
    private const val PREFS_NAME = "sensor_session_sync_state"
    private const val SYNCED_IDS_KEY = "synced_session_ids"

    fun getSyncedIds(context: Context): Set<UUID> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val raw = prefs.getStringSet(SYNCED_IDS_KEY, null) ?: emptySet()
        return SensorSessionSyncedIds.parse(raw)
    }

    fun markSynced(context: Context, sessionId: UUID) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(SYNCED_IDS_KEY, null) ?: emptySet()
        prefs.edit {
            putStringSet(SYNCED_IDS_KEY, SensorSessionSyncedIds.add(current, sessionId))
        }
    }
}

/** Serializes sensor-session payload transfers so only one session is on the wire at a time. */
internal object SensorSessionTransferCoordinator {
    val sendMutex = Mutex()
}

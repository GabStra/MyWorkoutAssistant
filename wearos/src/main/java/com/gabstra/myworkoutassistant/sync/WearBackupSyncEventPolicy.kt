package com.gabstra.myworkoutassistant.sync

/**
 * Pure policy for whether an incoming app-backup Data Layer event should be ignored.
 * Used by [com.gabstra.myworkoutassistant.DataLayerListenerService]; extracted for JVM unit tests (no Android Log).
 */
internal object WearBackupSyncEventPolicy {

    /**
     * @return true if the event should be dropped (not processed).
     */
    fun shouldIgnoreBackupEvent(
        isTransactionCompleted: (String) -> Boolean,
        transactionId: String?,
        timestampStr: String?,
        isRetry: Boolean,
        eventType: String,
        ignoreUntilStartOrEnd: Boolean,
        nowMs: Long,
        staleThresholdMs: Long
    ): Boolean {
        if (transactionId != null && isTransactionCompleted(transactionId)) {
            return true
        }

        if (!isRetry && timestampStr != null) {
            if (eventType == "app_backup_start" && ignoreUntilStartOrEnd) {
                return false
            }
            val eventTimestamp = timestampStr.toLongOrNull()
            if (eventTimestamp != null) {
                val eventAge = nowMs - eventTimestamp
                if (eventAge > staleThresholdMs) {
                    return true
                }
            }
        }

        return false
    }
}

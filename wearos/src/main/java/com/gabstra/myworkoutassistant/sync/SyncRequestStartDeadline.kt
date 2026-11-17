package com.gabstra.myworkoutassistant.sync

import android.os.Handler

/** Bounds the handshake-to-backup-start gap without letting duplicate requests extend it. */
internal class SyncRequestStartDeadline(
    private val handler: Handler,
    private val timeoutMillis: Long,
    private val onTimeout: (String) -> Unit,
) {
    sealed interface Cancellation {
        data object None : Cancellation
        data class Cancelled(val transactionId: String) : Cancellation
        data class DifferentPendingRequest(val transactionId: String) : Cancellation
    }

    private var pendingTransactionId: String? = null
    private var timeoutRunnable: Runnable? = null

    @Synchronized
    fun onRequest(transactionId: String) {
        if (pendingTransactionId == transactionId) return
        cancelPending()
        pendingTransactionId = transactionId
        timeoutRunnable = Runnable {
            synchronized(this) {
                if (pendingTransactionId != transactionId) return@synchronized
                pendingTransactionId = null
                timeoutRunnable = null
                onTimeout(transactionId)
            }
        }.also { handler.postDelayed(it, timeoutMillis) }
    }

    /** A started backup now owns the sync UI, so any older handshake deadline is stale. */
    @Synchronized
    fun onBackupStarted() = cancelPending()

    @Synchronized
    fun cancel(transactionId: String? = null): Cancellation {
        val pending = pendingTransactionId ?: return Cancellation.None
        if (transactionId != null && pending != transactionId) {
            return Cancellation.DifferentPendingRequest(pending)
        }
        val cancelledTransactionId = pendingTransactionId
        cancelPending()
        return Cancellation.Cancelled(checkNotNull(cancelledTransactionId))
    }

    @Synchronized
    private fun cancelPending() {
        timeoutRunnable?.let(handler::removeCallbacks)
        timeoutRunnable = null
        pendingTransactionId = null
    }
}

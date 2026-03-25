package com.gabstra.myworkoutassistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Documents that [SyncError.ConnectionError] is the type thrown when phone→Wear backup
 * is skipped because no watch node is connected — [MobileSyncToWatchWorker] treats it as failure/retry.
 */
class SyncErrorConnectionTest {

    @Test
    fun connectionError_carriesTransactionId() {
        val e = SyncError.ConnectionError("test-tx-id")
        assertTrue(e.message!!.contains("not connected"))
        assertEquals("test-tx-id", e.transactionId)
    }
}

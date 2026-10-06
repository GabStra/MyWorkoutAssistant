package com.gabstra.myworkoutassistant.shared.datalayer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SyncProgressUpdateTest {

    @Test
    fun roundTrip_preservesAcknowledgedTransferProgress() {
        val update = SyncProgressUpdate(
            phase = SyncPhase.TRANSFERRING,
            progress = 13f / 31f
        )

        assertEquals(update, SyncProgressUpdate.fromByteArray(update.toByteArray()))
    }

    @Test
    fun decode_rejectsMalformedPayload() {
        assertNull(SyncProgressUpdate.fromByteArray("TRANSFERRING".toByteArray()))
        assertNull(SyncProgressUpdate.fromByteArray("UNKNOWN|0.5".toByteArray()))
        assertNull(SyncProgressUpdate.fromByteArray("TRANSFERRING|NaN".toByteArray()))
    }

    @Test
    fun encode_clampsProgressToProtocolRange() {
        val decoded = SyncProgressUpdate.fromByteArray(
            SyncProgressUpdate(SyncPhase.TRANSFERRING, 2f).toByteArray()
        )

        assertEquals(1f, decoded?.progress)
    }
}

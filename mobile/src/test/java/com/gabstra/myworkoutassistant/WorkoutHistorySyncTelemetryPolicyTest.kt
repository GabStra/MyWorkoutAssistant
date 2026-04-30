package com.gabstra.myworkoutassistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutHistorySyncTelemetryPolicyTest {

    @Test
    fun `records retry requests and stale retry ignores`() {
        val afterRetryRequest = WorkoutHistorySyncTelemetryPolicy.recordRetryRequested(
            WorkoutHistorySyncTelemetrySnapshot()
        )
        val afterStaleRetryIgnore = WorkoutHistorySyncTelemetryPolicy.recordStaleRetryIgnored(
            afterRetryRequest
        )

        assertEquals(1, afterStaleRetryIgnore.requestedRetryGenerations)
        assertEquals(1, afterStaleRetryIgnore.staleRetryChunksIgnored)
        assertEquals(0, afterStaleRetryIgnore.transactionsRecoveredAfterRetry)
    }

    @Test
    fun `records recovered after retry only when a retry generation was requested`() {
        val unchanged = WorkoutHistorySyncTelemetryPolicy.recordRecoveredAfterRetry(
            snapshot = WorkoutHistorySyncTelemetrySnapshot(),
            latestRequestedRetryGeneration = 0
        )
        val recovered = WorkoutHistorySyncTelemetryPolicy.recordRecoveredAfterRetry(
            snapshot = unchanged,
            latestRequestedRetryGeneration = 2
        )

        assertEquals(0, unchanged.transactionsRecoveredAfterRetry)
        assertEquals(1, recovered.transactionsRecoveredAfterRetry)
    }

    @Test
    fun `renders structured telemetry log line`() {
        val logLine = WorkoutHistorySyncTelemetryPolicy.toLogLine(
            snapshot = WorkoutHistorySyncTelemetrySnapshot(
                requestedRetryGenerations = 2,
                staleRetryChunksIgnored = 1,
                transactionsRecoveredAfterRetry = 1
            ),
            transactionId = "tx-1",
            reason = "processing_complete"
        )

        assertTrue(logLine.contains("tx=tx-1"))
        assertTrue(logLine.contains("reason=processing_complete"))
        assertTrue(logLine.contains("retryRequests=2"))
        assertTrue(logLine.contains("staleRetryChunksIgnored=1"))
        assertTrue(logLine.contains("transactionsRecoveredAfterRetry=1"))
    }
}

package com.gabstra.myworkoutassistant.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WearBackupSyncEventPolicyTest {

    private val staleThresholdMs = 300_000L
    private val nowMs = 1_000_000_000_000L

    @Test
    fun `replay completed transaction is ignored`() {
        assertTrue(
            WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
                isTransactionCompleted = { it == "tx1" },
                transactionId = "tx1",
                timestampStr = nowMs.toString(),
                isRetry = false,
                eventType = "app_backup_start",
                ignoreUntilStartOrEnd = false,
                nowMs = nowMs,
                staleThresholdMs = staleThresholdMs
            )
        )
    }

    @Test
    fun `stale app_backup_start ignored when not gated`() {
        val oldTs = (nowMs - staleThresholdMs - 60_000).toString()
        assertTrue(
            WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
                isTransactionCompleted = { false },
                transactionId = "tx2",
                timestampStr = oldTs,
                isRetry = false,
                eventType = "app_backup_start",
                ignoreUntilStartOrEnd = false,
                nowMs = nowMs,
                staleThresholdMs = staleThresholdMs
            )
        )
    }

    @Test
    fun `stale app_backup_start not ignored when gated recovery`() {
        val oldTs = (nowMs - staleThresholdMs - 60_000).toString()
        assertFalse(
            WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
                isTransactionCompleted = { false },
                transactionId = "tx3",
                timestampStr = oldTs,
                isRetry = false,
                eventType = "app_backup_start",
                ignoreUntilStartOrEnd = true,
                nowMs = nowMs,
                staleThresholdMs = staleThresholdMs
            )
        )
    }

    @Test
    fun `stale chunk still ignored when gated`() {
        val oldTs = (nowMs - staleThresholdMs - 60_000).toString()
        assertTrue(
            WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
                isTransactionCompleted = { false },
                transactionId = "tx4",
                timestampStr = oldTs,
                isRetry = false,
                eventType = "app_backup_chunk",
                ignoreUntilStartOrEnd = true,
                nowMs = nowMs,
                staleThresholdMs = staleThresholdMs
            )
        )
    }

    @Test
    fun `retry bypasses stale for chunk`() {
        val oldTs = (nowMs - staleThresholdMs - 60_000).toString()
        assertFalse(
            WearBackupSyncEventPolicy.shouldIgnoreBackupEvent(
                isTransactionCompleted = { false },
                transactionId = "tx5",
                timestampStr = oldTs,
                isRetry = true,
                eventType = "app_backup_chunk",
                ignoreUntilStartOrEnd = true,
                nowMs = nowMs,
                staleThresholdMs = staleThresholdMs
            )
        )
    }
}

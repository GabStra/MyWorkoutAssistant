package com.gabstra.myworkoutassistant

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutHistoryInboundStatePolicyTest {

    @Test
    fun `ignores replay for terminal transaction`() {
        assertTrue(
            WorkoutHistoryInboundStatePolicy.shouldIgnoreTerminalReplay(
                isTerminalTransaction = true
            )
        )
    }

    @Test
    fun `keeps retry chunks on same transaction from resetting active transfer`() {
        assertFalse(
            WorkoutHistoryInboundStatePolicy.shouldResetForDifferentActiveTransaction(
                currentTransactionId = "tx-1",
                currentState = WorkoutHistoryInboundState.WaitingForTrailingChunks,
                incomingTransactionId = "tx-1",
                isStart = false,
                hasChunkPayload = true,
                isRetry = true
            )
        )
    }

    @Test
    fun `resets when a different transaction starts while one is active`() {
        assertTrue(
            WorkoutHistoryInboundStatePolicy.shouldResetForDifferentActiveTransaction(
                currentTransactionId = "tx-1",
                currentState = WorkoutHistoryInboundState.Receiving,
                incomingTransactionId = "tx-2",
                isStart = true,
                hasChunkPayload = false,
                isRetry = false
            )
        )
    }

    @Test
    fun `rejects stray chunk when no active transaction exists`() {
        assertTrue(
            WorkoutHistoryInboundStatePolicy.shouldResetForDifferentActiveTransaction(
                currentTransactionId = null,
                currentState = WorkoutHistoryInboundState.Idle,
                incomingTransactionId = "tx-1",
                isStart = false,
                hasChunkPayload = true,
                isRetry = false
            )
        )
    }

    @Test
    fun `ignores retry chunk from older retry generation`() {
        assertTrue(
            WorkoutHistoryInboundStatePolicy.shouldIgnoreStaleRetryChunk(
                isRetry = true,
                retryGeneration = 1,
                latestRequestedRetryGeneration = 2
            )
        )
    }

    @Test
    fun `keeps latest retry generation active`() {
        assertFalse(
            WorkoutHistoryInboundStatePolicy.shouldIgnoreStaleRetryChunk(
                isRetry = true,
                retryGeneration = 2,
                latestRequestedRetryGeneration = 2
            )
        )
    }
}

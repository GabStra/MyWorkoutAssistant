package com.gabstra.myworkoutassistant

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutHistoryChunkProcessingPolicyTest {

    @Test
    fun `does not process immediately when terminal chunk arrives before all chunks`() {
        assertFalse(
            WorkoutHistoryChunkProcessingPolicy.shouldProcessImmediately(
                receivedChunks = 4,
                expectedChunks = 5
            )
        )
        assertTrue(
            WorkoutHistoryChunkProcessingPolicy.shouldScheduleSettleWindow(
                receivedChunks = 4,
                expectedChunks = 5,
                sawTerminalChunk = true,
                alreadyWaitingForTrailingChunks = false
            )
        )
    }

    @Test
    fun `processes immediately once all expected chunks are present`() {
        assertTrue(
            WorkoutHistoryChunkProcessingPolicy.shouldProcessImmediately(
                receivedChunks = 5,
                expectedChunks = 5
            )
        )
        assertFalse(
            WorkoutHistoryChunkProcessingPolicy.shouldScheduleSettleWindow(
                receivedChunks = 5,
                expectedChunks = 5,
                sawTerminalChunk = true,
                alreadyWaitingForTrailingChunks = true
            )
        )
    }

    @Test
    fun `keeps settle window armed when trailing chunks are still arriving`() {
        assertTrue(
            WorkoutHistoryChunkProcessingPolicy.shouldScheduleSettleWindow(
                receivedChunks = 3,
                expectedChunks = 5,
                sawTerminalChunk = false,
                alreadyWaitingForTrailingChunks = true
            )
        )
    }
}

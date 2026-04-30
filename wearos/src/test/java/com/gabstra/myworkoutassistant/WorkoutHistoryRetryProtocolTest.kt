package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.data.WorkoutHistoryRetryProtocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkoutHistoryRetryProtocolTest {

    @Test
    fun `parses retry generation and missing indices from current error format`() {
        val parsed = WorkoutHistoryRetryProtocol.parseMissingChunksError(
            "MISSING_CHUNKS: Retry generation: 3. Expected 10 chunks, received 7. Missing indices: [2, 5, 7]"
        )

        requireNotNull(parsed)
        assertEquals(3, parsed.retryGeneration)
        assertEquals(listOf(2, 5, 7), parsed.missingIndices)
    }

    @Test
    fun `defaults retry generation to one for older error format`() {
        val parsed = WorkoutHistoryRetryProtocol.parseMissingChunksError(
            "MISSING_CHUNKS: Expected 4 chunks, received 3. Missing indices: [1]"
        )

        requireNotNull(parsed)
        assertEquals(1, parsed.retryGeneration)
        assertEquals(listOf(1), parsed.missingIndices)
    }

    @Test
    fun `returns null when missing indices are absent`() {
        val parsed = WorkoutHistoryRetryProtocol.parseMissingChunksError(
            "MISSING_CHUNKS: Retry generation: 2. Expected 4 chunks, received 4."
        )

        assertNull(parsed)
    }
}

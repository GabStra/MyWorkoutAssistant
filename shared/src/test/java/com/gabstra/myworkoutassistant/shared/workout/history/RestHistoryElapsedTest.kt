package com.gabstra.myworkoutassistant.shared.workout.history

import java.time.LocalDateTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RestHistoryElapsedTest {

    @Test
    fun elapsedSecondsFromHistoryBounds_computesDuration() {
        val start = LocalDateTime.of(2026, 3, 22, 10, 0, 0)
        val end = LocalDateTime.of(2026, 3, 22, 10, 1, 32)
        assertEquals(92, elapsedSecondsFromHistoryBounds(start, end))
    }

    @Test
    fun elapsedSecondsFromHistoryBounds_nullIfMissingBound() {
        assertNull(elapsedSecondsFromHistoryBounds(null, LocalDateTime.now()))
        assertNull(elapsedSecondsFromHistoryBounds(LocalDateTime.now(), null))
    }
}

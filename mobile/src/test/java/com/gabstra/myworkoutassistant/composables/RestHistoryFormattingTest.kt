package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import java.time.LocalDateTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Test

class RestHistoryFormattingTest {

    @Test
    fun `formatHistoricalRestValue prefers persisted timestamps`() {
        val start = LocalDateTime.of(2026, 3, 22, 10, 0, 0)
        val end = start.plusSeconds(75)
        val history = restHistory(
            startTimer = 90,
            endTimer = 60,
            startTime = start,
            endTime = end
        )

        assertEquals("REST 01:15", formatHistoricalRestValue(history))
    }

    @Test
    fun `formatHistoricalRestValue falls back to timer delta when timestamps are missing`() {
        val history = restHistory(
            startTimer = 90,
            endTimer = 35,
            startTime = null,
            endTime = null
        )

        assertEquals("REST 00:55", formatHistoricalRestValue(history))
    }

    private fun restHistory(
        startTimer: Int,
        endTimer: Int,
        startTime: LocalDateTime?,
        endTime: LocalDateTime?
    ): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            setId = UUID.randomUUID(),
            order = 0u,
            startTime = startTime,
            endTime = endTime,
            setData = RestSetData(startTimer = startTimer, endTimer = endTimer),
            skipped = false
        )
    }
}

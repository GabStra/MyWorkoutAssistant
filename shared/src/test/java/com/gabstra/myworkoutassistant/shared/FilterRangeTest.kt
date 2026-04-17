package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalTime
import java.util.UUID

class FilterRangeTest {

    private val fixedToday: LocalDate = LocalDate.of(2024, 6, 15)

    private fun historyOn(date: LocalDate): WorkoutHistory {
        val id = UUID.nameUUIDFromBytes(date.toString().toByteArray())
        return WorkoutHistory(
            id = id,
            workoutId = id,
            date = date,
            time = LocalTime.NOON,
            startTime = date.atTime(12, 0),
            duration = 0,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = id,
        )
    }

    @Test
    fun `dateRangeFor ALL spans min and max`() {
        val (start, end) = dateRangeFor(FilterRange.ALL, fixedToday)
        assertEquals(LocalDate.MIN, start)
        assertEquals(LocalDate.MAX, end)
    }

    @Test
    fun `dateRangeFor LAST_WEEK is previous calendar week Monday through Sunday`() {
        val (start, end) = dateRangeFor(FilterRange.LAST_WEEK, fixedToday)
        assertEquals(LocalDate.of(2024, 6, 3), start)
        assertEquals(LocalDate.of(2024, 6, 9), end)
    }

    @Test
    fun `dateRangeFor LAST_7_DAYS is seven inclusive days ending today`() {
        val (start, end) = dateRangeFor(FilterRange.LAST_7_DAYS, fixedToday)
        assertEquals(LocalDate.of(2024, 6, 9), start)
        assertEquals(fixedToday, end)
    }

    @Test
    fun `dateRangeFor THIS_MONTH covers full month`() {
        val (start, end) = dateRangeFor(FilterRange.THIS_MONTH, fixedToday)
        assertEquals(LocalDate.of(2024, 6, 1), start)
        assertEquals(LocalDate.of(2024, 6, 30), end)
    }

    @Test
    fun `filterBy LAST_WEEK keeps only dates in range`() {
        val rows = listOf(
            historyOn(LocalDate.of(2024, 6, 2)),
            historyOn(LocalDate.of(2024, 6, 5)),
            historyOn(LocalDate.of(2024, 6, 10)),
        )
        val filtered = rows.filterBy(FilterRange.LAST_WEEK, fixedToday)
        assertEquals(1, filtered.size)
        assertEquals(LocalDate.of(2024, 6, 5), filtered.single().date)
    }

    @Test
    fun `filterBy ALL returns everything`() {
        val rows = listOf(
            historyOn(LocalDate.of(2020, 1, 1)),
            historyOn(LocalDate.of(2030, 1, 1)),
        )
        assertEquals(rows, rows.filterBy(FilterRange.ALL, fixedToday))
    }

    @Test
    fun `filterBy LAST_7_DAYS includes boundary dates`() {
        val rows = listOf(
            historyOn(LocalDate.of(2024, 6, 8)),
            historyOn(LocalDate.of(2024, 6, 9)),
            historyOn(LocalDate.of(2024, 6, 15)),
            historyOn(LocalDate.of(2024, 6, 16)),
        )
        val filtered = rows.filterBy(FilterRange.LAST_7_DAYS, fixedToday).map { it.date }.toSet()
        assertTrue(LocalDate.of(2024, 6, 8) !in filtered)
        assertTrue(LocalDate.of(2024, 6, 9) in filtered)
        assertTrue(LocalDate.of(2024, 6, 15) in filtered)
        assertTrue(LocalDate.of(2024, 6, 16) !in filtered)
    }
}

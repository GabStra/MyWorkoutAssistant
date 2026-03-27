package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AlarmScheduleValidationTest {

    @Test
    fun `recurring alarm requires at least one day`() {
        val message = validateAlarmScheduleInput(
            useSpecificDate = false,
            specificDate = null,
            hour = 9,
            minute = 0,
            daysOfWeek = 0,
            now = LocalDateTime.of(2026, 3, 27, 8, 0)
        )

        assertEquals("Select at least one day for recurring alarms.", message)
    }

    @Test
    fun `one-time alarm must be in the future`() {
        val message = validateAlarmScheduleInput(
            useSpecificDate = true,
            specificDate = LocalDate.of(2026, 3, 27),
            hour = 9,
            minute = 0,
            daysOfWeek = 0,
            now = LocalDateTime.of(2026, 3, 27, 9, 0)
        )

        assertEquals("Pick a future date and time for one-time alarms.", message)
    }

    @Test
    fun `future one-time alarm is accepted`() {
        val message = validateAlarmScheduleInput(
            useSpecificDate = true,
            specificDate = LocalDate.of(2026, 3, 27),
            hour = 9,
            minute = 30,
            daysOfWeek = 0,
            now = LocalDateTime.of(2026, 3, 27, 9, 0)
        )

        assertNull(message)
    }

    @Test
    fun `editing same executed one-time trigger preserves executed state`() {
        val existingSchedule = oneTimeSchedule(
            specificDate = LocalDate.of(2026, 3, 28),
            hour = 9,
            minute = 30,
            hasExecuted = true
        )

        assertTrue(
            resolveEditedScheduleHasExecuted(
                existingSchedule = existingSchedule,
                specificDate = LocalDate.of(2026, 3, 28),
                hour = 9,
                minute = 30
            )
        )
    }

    @Test
    fun `moving executed one-time trigger resets executed state`() {
        val existingSchedule = oneTimeSchedule(
            specificDate = LocalDate.of(2026, 3, 28),
            hour = 9,
            minute = 30,
            hasExecuted = true
        )

        assertFalse(
            resolveEditedScheduleHasExecuted(
                existingSchedule = existingSchedule,
                specificDate = LocalDate.of(2026, 3, 29),
                hour = 9,
                minute = 30
            )
        )
    }

    private fun oneTimeSchedule(
        specificDate: LocalDate,
        hour: Int,
        minute: Int,
        hasExecuted: Boolean
    ): WorkoutSchedule {
        return WorkoutSchedule(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            hour = hour,
            minute = minute,
            specificDate = specificDate,
            hasExecuted = hasExecuted
        )
    }
}

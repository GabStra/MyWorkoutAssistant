package com.gabstra.myworkoutassistant.screens

import java.time.LocalDate
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Test

class ImportedHistoryDatePickerTest {

    @Test
    fun `date picker conversion round trips date only values in UTC`() {
        listOf(
            LocalDate.of(2026, 11, 12),
            LocalDate.of(2026, 11, 14),
        ).forEach { date ->
            val millis = importedHistoryDatePickerMillis(date)

            assertEquals(date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(), millis)
            assertEquals(date, importedHistoryDateFromPickerMillis(millis))
        }
    }
}

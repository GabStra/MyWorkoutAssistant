package com.gabstra.myworkoutassistant.shared.export

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime

class HeartRateExportStatsTest {

    @Test
    fun sliceHeartRateRecords_usesOneSamplePerSecondAlignment() {
        val workoutStart = LocalDateTime.of(2026, 3, 26, 10, 0, 0)
        val records = (0 until 120).toList()

        val slice = sliceHeartRateRecords(
            workoutStart = workoutStart,
            records = records,
            intervalStart = workoutStart.plusSeconds(30),
            intervalEnd = workoutStart.plusSeconds(40)
        )

        assertEquals((30 until 40).toList(), slice)
    }
}

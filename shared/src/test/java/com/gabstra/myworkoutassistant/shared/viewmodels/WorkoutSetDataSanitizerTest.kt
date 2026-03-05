package com.gabstra.myworkoutassistant.shared.viewmodels

import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

class WorkoutSetDataSanitizerTest {

    @Test
    fun resetTimeSetProgressForNewSession_resetsTimedDurationEndToStart() {
        val historical = TimedDurationSetData(
            startTimer = 60_000,
            endTimer = 0,
            autoStart = true,
            autoStop = false
        )

        val sanitized = resetTimeSetProgressForNewSession(historical) as TimedDurationSetData

        assertEquals(60_000, sanitized.startTimer)
        assertEquals(60_000, sanitized.endTimer)
    }

    @Test
    fun resetTimeSetProgressForNewSession_resetsEnduranceElapsedToZero() {
        val historical = EnduranceSetData(
            startTimer = 45_000,
            endTimer = 33_000,
            autoStart = true,
            autoStop = true
        )

        val sanitized = resetTimeSetProgressForNewSession(historical) as EnduranceSetData

        assertEquals(45_000, sanitized.startTimer)
        assertEquals(0, sanitized.endTimer)
    }

    @Test
    fun resetTimeSetProgressForNewSession_keepsNonTimeDataUntouched() {
        val weight = WeightSetData(
            actualReps = 8,
            actualWeight = 80.0,
            volume = 640.0
        )

        val sanitized = resetTimeSetProgressForNewSession(weight)

        assertSame(weight, sanitized)
    }
}

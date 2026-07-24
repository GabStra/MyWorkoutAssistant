package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import org.junit.Assert.assertEquals
import org.junit.Test

class SetWorkoutDifferenceProgressionContextTest {
    private val previous = WeightSetData(actualReps = 10, actualWeight = 100.0, volume = 1_000.0)

    @Test
    fun `planned load jump with rep reset is improvement`() {
        val current = WeightSetData(actualReps = 6, actualWeight = 105.0, volume = 630.0)

        assertEquals(
            SetComparison.BETTER,
            compareSets(
                beforeSetData = previous,
                afterSetData = current,
                plannedNextSet = SimpleSet(weight = 105.0, reps = 6),
            )
        )
    }

    @Test
    fun `raw retry comparison follows canonical weight-first ordering`() {
        val current = WeightSetData(actualReps = 12, actualWeight = 95.0, volume = 1_140.0)

        assertEquals(
            SetComparison.WORSE,
            compareSets(
                beforeSetData = previous,
                afterSetData = current,
                plannedNextSet = null,
            )
        )
    }

    @Test
    fun `fewer reps at old load is worse in progression context`() {
        val current = WeightSetData(actualReps = 9, actualWeight = 100.0, volume = 900.0)

        assertEquals(
            SetComparison.WORSE,
            compareSets(
                beforeSetData = previous,
                afterSetData = current,
                plannedNextSet = SimpleSet(weight = 105.0, reps = 6),
            )
        )
    }

    @Test
    fun `longer elapsed endurance time is better`() {
        val before = EnduranceSetData(
            startTimer = 60_000,
            endTimer = 20_000,
            autoStart = false,
            autoStop = false,
        )
        val after = before.copy(endTimer = 10_000)

        assertEquals(SetComparison.BETTER, compareSets(before, after))
    }

    @Test
    fun `shorter elapsed timed duration is worse`() {
        val before = TimedDurationSetData(
            startTimer = 60_000,
            endTimer = 10_000,
            autoStart = false,
            autoStop = false,
        )
        val after = before.copy(endTimer = 20_000)

        assertEquals(SetComparison.WORSE, compareSets(before, after))
    }
}

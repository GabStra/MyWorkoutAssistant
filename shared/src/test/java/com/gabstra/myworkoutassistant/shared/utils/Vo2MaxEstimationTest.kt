package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.running.RunningResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Vo2MaxEstimationTest {

    @Test
    fun `resting hr estimate follows uth-sovoldius`() {
        // 15.3 * 190/60 = 48.45
        assertEquals(48.5, estimateVo2MaxFromRestingHr(190, 60)!!, 0.05)
        // fitter (lower resting HR) scores higher
        assertTrue(
            estimateVo2MaxFromRestingHr(190, 50)!! > estimateVo2MaxFromRestingHr(190, 70)!!
        )
    }

    @Test
    fun `resting hr estimate rejects implausible inputs`() {
        assertNull(estimateVo2MaxFromRestingHr(80, 60))
        assertNull(estimateVo2MaxFromRestingHr(190, 10))
        assertNull(estimateVo2MaxFromRestingHr(190, 200))
    }

    private fun run(
        distanceMeters: Double,
        durationMillis: Long,
        averageHeartRateBpm: Int?,
    ) = RunningResult(
        exerciseId = "run",
        elapsedTimeMillis = durationMillis,
        distanceMeters = distanceMeters,
        averagePaceSecondsPerKilometer = null,
        averageHeartRateBpm = averageHeartRateBpm,
        minHeartRateBpm = null,
        maxHeartRateBpm = null,
        route = emptyList(),
    )

    @Test
    fun `run estimate solves acsm equation scaled by hr`() {
        // 5 km in 25 min (3.33 m/s), avg HR 150, HRmax 190:
        // VO2sub = 0.2 * 200 + 3.5 = 43.5; fraction = 0.7895; VO2max = 55.1
        val result = estimateVo2MaxFromRun(run(5_000.0, 25 * 60_000L, 150), 190)!!
        assertEquals(55.1, result, 0.2)
    }

    @Test
    fun `run estimate rejects runs outside the submaximal window`() {
        val qualified = run(5_000.0, 25 * 60_000L, 150)
        assertNull(estimateVo2MaxFromRun(qualified.copy(averageHeartRateBpm = 110), 190)) // < 60%
        assertNull(estimateVo2MaxFromRun(qualified.copy(averageHeartRateBpm = 185), 190)) // > 90%
        assertNull(estimateVo2MaxFromRun(run(500.0, 3 * 60_000L, 150), 190)) // too short
        assertNull(estimateVo2MaxFromRun(run(5_000.0, 55 * 60_000L, 150), 190)) // walking pace
        assertNull(estimateVo2MaxFromRun(run(5_000.0, 25 * 60_000L, null), 190)) // no HR
        assertNull(estimateVo2MaxFromRun(run(5_000.0, 25 * 60_000L, 150), 80)) // bad HRmax
    }
}

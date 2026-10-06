package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CalorieEstimationTest {

    @Test
    fun `steady cardio effort yields plausible calories`() {
        // 75 kg, 30 years, HR 150 for 30 minutes: the male formula gives ~434,
        // the female ~283; the sex-unknown averaged estimate must sit between.
        val kcal = estimateCaloriesKcal(
            heartRateBpm = 150,
            durationMillis = 30 * 60_000L,
            weightKg = 75.0,
            ageYears = 30,
        )
        assertTrue("expected 280..440, got $kcal", kcal in 280..440)
    }

    @Test
    fun `male formula is higher than female at the same inputs`() {
        val male = estimateCaloriesKcal(150, 20 * 60_000L, 75.0, 30, female = false)
        val female = estimateCaloriesKcal(150, 20 * 60_000L, 75.0, 30, female = true)
        assertTrue(male > female)
    }

    @Test
    fun `zero or negative inputs yield zero without throwing`() {
        assertEquals(0, estimateCaloriesKcal(150, 0L, 75.0, 30))
        assertEquals(0, estimateCaloriesKcal(150, 60_000L, 0.0, 30))
        assertEquals(0, estimateCaloriesKcal(150, 60_000L, 75.0, 0))
    }

    @Test
    fun `absurd heart rate is clamped`() {
        val crazy = estimateCaloriesKcal(400, 60_000L, 75.0, 30)
        val max = estimateCaloriesKcal(250, 60_000L, 75.0, 30)
        assertEquals(max, crazy)
    }
}

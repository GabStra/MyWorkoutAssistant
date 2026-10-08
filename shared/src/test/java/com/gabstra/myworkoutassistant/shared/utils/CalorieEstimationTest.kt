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

    @Test
    fun `vo2max path is used when vo2max and hrmax are provided`() {
        val withVo2Max = estimateCaloriesKcal(
            heartRateBpm = 150,
            durationMillis = 30 * 60_000L,
            weightKg = 75.0,
            ageYears = 30,
            vo2MaxMlKgMin = 45.0,
            maxHeartRateBpm = 195,
        )
        val keytel = estimateCaloriesKcal(
            heartRateBpm = 150,
            durationMillis = 30 * 60_000L,
            weightKg = 75.0,
            ageYears = 30,
        )
        // The engines must disagree at this fitness level (the VO2max path exists to
        // correct Keytel's fitness bias) but stay within a believable band.
        assertTrue("vo2max path inactive: $withVo2Max vs keytel $keytel", withVo2Max != keytel)
        assertTrue(
            "engines diverge too far: $withVo2Max vs $keytel",
            withVo2Max > keytel * 0.5 && withVo2Max < keytel * 1.1,
        )
    }

    @Test
    fun `calories scale with vo2max at the same heart rate`() {
        fun burn(vo2Max: Double) = estimateCaloriesKcal(
            heartRateBpm = 160,
            durationMillis = 20 * 60_000L,
            weightKg = 75.0,
            ageYears = 30,
            vo2MaxMlKgMin = vo2Max,
            maxHeartRateBpm = 195,
        )
        // %HRR -> %VO2R keeps the relative effort equal, so absolute calories grow
        // with VO2max (a fitter user has a higher VO2 at the same HR).
        assertTrue("fit should burn more at the same HR", burn(55.0) > burn(35.0))
    }

    @Test
    fun `implausible vo2max or hrmax falls back to keytel`() {
        val keytel = estimateCaloriesKcal(150, 20 * 60_000L, 75.0, 30)
        val implausibleVo2Max = estimateCaloriesKcal(
            150, 20 * 60_000L, 75.0, 30, vo2MaxMlKgMin = 300.0, maxHeartRateBpm = 195,
        )
        val missingHrMax = estimateCaloriesKcal(
            150, 20 * 60_000L, 75.0, 30, vo2MaxMlKgMin = 45.0,
        )
        assertEquals(keytel, implausibleVo2Max)
        assertEquals(keytel, missingHrMax)
    }
}

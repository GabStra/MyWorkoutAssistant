package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Test

class LiveCalorieAccumulatorTest {

    // 1 bpm == 1/60 kcal per minute keeps the arithmetic legible: one minute at
    // HR 150 charges exactly 2.5 kcal.
    private val hrOver60Rate: (Int) -> Double = { it / 60.0 }

    @Test
    fun `first sample only baselines and charges nothing`() {
        val accumulator = LiveCalorieAccumulator()
        assertEquals(0.0, accumulator.onSample(150, 0, hrOver60Rate), 1e-9)
        // The first interval after the baseline does charge: half a minute at 150.
        assertEquals(1.25, accumulator.onSample(150, 30_000, hrOver60Rate), 1e-9)
    }

    @Test
    fun `interval is charged at the previous sample's rate`() {
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(150, 0, hrOver60Rate)
        // HR then drops to 100: the elapsed minute is still charged at 150's rate.
        assertEquals(2.5, accumulator.onSample(100, 60_000, hrOver60Rate), 1e-9)
        assertEquals(2.5 + 100.0 / 60.0, accumulator.onSample(100, 120_000, hrOver60Rate), 1e-9)
    }

    @Test
    fun `negative-rate segment never drains the total`() {
        val negativeAtRest: (Int) -> Double = { if (it < 60) -3.0 else it / 60.0 }
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(150, 0, negativeAtRest)
        // A near-rest reading would produce a negative rate; flooring it at zero
        // keeps the integral monotonic instead of paying back burned calories.
        assertEquals(2.5, accumulator.onSample(50, 60_000, negativeAtRest), 1e-9)
        // The interval just spent at the floored HR burns nothing, then growth resumes.
        assertEquals(2.5, accumulator.onSample(150, 120_000, negativeAtRest), 1e-9)
        assertEquals(2.5 + 2.5, accumulator.onSample(150, 180_000, negativeAtRest), 1e-9)
    }

    @Test
    fun `clock restart beyond tolerance begins a fresh run`() {
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(150, 0, hrOver60Rate)
        assertEquals(2.5, accumulator.onSample(100, 60_000, hrOver60Rate), 1e-9)
        // The next set's clock starts near zero: this is a new run, not jitter.
        assertEquals(0.0, accumulator.onSample(120, 10_000, hrOver60Rate), 1e-9)
        assertEquals(120.0 / 60.0, accumulator.onSample(120, 70_000, hrOver60Rate), 1e-9)
    }

    @Test
    fun `small backwards jitter is ignored without resetting`() {
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(150, 60_000, hrOver60Rate)
        // A 2-second re-anchor backwards is tick jitter: no charge, no reset.
        assertEquals(0.0, accumulator.onSample(150, 58_000, hrOver60Rate), 1e-9)
        assertEquals(2.5, accumulator.onSample(150, 118_000, hrOver60Rate), 1e-9)
    }

    @Test
    fun `a single sample cannot charge more than the interval cap`() {
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(120, 0, hrOver60Rate)
        // A 10-minute gap (screen off, sensor gone) charges at most 2 minutes.
        assertEquals(120.0 / 60.0 * 2.0, accumulator.onSample(120, 600_000, hrOver60Rate), 1e-9)
    }

    @Test
    fun `reset clears the total and the baseline`() {
        val accumulator = LiveCalorieAccumulator()
        accumulator.onSample(150, 0, hrOver60Rate)
        accumulator.onSample(150, 60_000, hrOver60Rate)
        accumulator.reset()
        assertEquals(0.0, accumulator.onSample(150, 60_000, hrOver60Rate), 1e-9)
        assertEquals(2.5, accumulator.onSample(150, 120_000, hrOver60Rate), 1e-9)
    }
}

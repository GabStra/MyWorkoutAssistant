package com.gabstra.myworkoutassistant.reps

import java.util.Random
import kotlin.math.PI
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Test

class RepDetectorTest {

    @Test
    fun tenThreeHertzCycles_countTenReps() {
        val detector = RepDetector()
        val samplingHz = 100.0
        val stepNs = (1_000_000_000L / samplingHz).toLong()
        var timestampNs = 0L

        repeat((2.0 * samplingHz).toInt()) {
            detector.addSample(timestampNs, 0f, 0f, 9.81f)
            timestampNs += stepNs
        }

        repeat((10.0 / 3.0 * samplingHz).toInt()) { i ->
            val t = i / samplingHz
            val az = 9.81f + 4f * sin(2.0 * PI * 3.0 * t).toFloat()
            detector.addSample(timestampNs, 0f, 0f, az)
            timestampNs += stepNs
        }

        assertEquals(10, detector.reps)

        detector.reset()
        assertEquals(0, detector.reps)
    }

    @Test
    fun smoothNoise_countsNoReps() {
        val detector = RepDetector()
        val random = Random(42)
        val samplingHz = 100.0
        val stepNs = (1_000_000_000L / samplingHz).toLong()
        var timestampNs = 0L

        repeat(1200) { i ->
            val t = i / samplingHz
            val noise = (random.nextFloat() - 0.5f) + (random.nextFloat() - 0.5f)
            val drift = 0.2f * sin(2.0 * PI * 0.3 * t).toFloat()
            detector.addSample(timestampNs, 0f, 0f, 9.81f + 0.4f * noise + drift)
            timestampNs += stepNs
        }

        assertEquals(0, detector.reps)
    }
}

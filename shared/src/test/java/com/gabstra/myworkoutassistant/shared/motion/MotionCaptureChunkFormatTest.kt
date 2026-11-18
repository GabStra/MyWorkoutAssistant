package com.gabstra.myworkoutassistant.shared.motion

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionCaptureChunkFormatTest {

    private fun sampleSet(): List<MotionSensorSample> = listOf(
        MotionSensorSample(MotionSensorType.ACCELEROMETER, 1731846000000L, 452811234567890L, 3, 0.1234567f, -9.8765432f, 3.5f),
        MotionSensorSample(MotionSensorType.GYROSCOPE, 1731846000020L, 452811254567890L, 3, 0.01f, -0.02f, 0.03f),
        // Timestamp jitter can produce negative deltas; w present only for rotation vector.
        MotionSensorSample(MotionSensorType.ROTATION_VECTOR, 1731846000015L, 452811274567890L, 3, 0.5f, 0.6f, 0.7f, 0.9f),
        MotionSensorSample(MotionSensorType.HEART_RATE, 1731846000030L, 452811294567890L, 3, 72f, Float.NaN, Float.NaN)
    )

    private fun assertSamplesEqual(expected: MotionSensorSample, actual: MotionSensorSample) {
        assertEquals(expected.sensorType, actual.sensorType)
        assertEquals(expected.epochTimeMs, actual.epochTimeMs)
        assertEquals(expected.elapsedRealtimeNanos, actual.elapsedRealtimeNanos)
        assertEquals(expected.accuracy, actual.accuracy)
        assertEquals(expected.x.toRawBits(), actual.x.toRawBits())
        assertEquals(expected.y.toRawBits(), actual.y.toRawBits())
        assertEquals(expected.z.toRawBits(), actual.z.toRawBits())
        assertEquals(expected.w?.toRawBits(), actual.w?.toRawBits())
    }

    @Test
    fun `encode and decode round-trip bit-exact including missing w and negative deltas`() {
        val samples = sampleSet()

        val decoded = MotionCaptureChunkFormat.decode(MotionCaptureChunkFormat.encode(samples))

        assertEquals(samples.size, decoded.size)
        samples.zip(decoded).forEach { (expected, actual) -> assertSamplesEqual(expected, actual) }
    }

    @Test
    fun `sensor type ordinals are pinned for the v2 chunk format`() {
        assertEquals(
            listOf(
                "ACCELEROMETER",
                "GYROSCOPE",
                "ROTATION_VECTOR",
                "HEART_RATE",
                "STEP_COUNTER",
                "GRAVITY",
                "LINEAR_ACCELERATION",
                "PRESSURE"
            ),
            MotionSensorType.entries.map { it.name }
        )
    }

    /**
     * Writes a fixed encoded fixture for the Python loader's parity check
     * (motion_annotation_pkg decodes it and compares against the same sample set).
     */
    @Test
    fun `encode fixture for python loader parity check`() {
        val file = File("build/motion_chunk_format_sample.bin")
        file.parentFile.mkdirs()
        file.writeBytes(MotionCaptureChunkFormat.encode(sampleSet()))
        assertTrue(file.length() > 0)
    }

    @Test
    fun `null w decodes as null while real w values survive`() {
        val withW = MotionSensorSample(MotionSensorType.ROTATION_VECTOR, 1L, 1L, 3, 1f, 2f, 3f, 4f)
        val withoutW = MotionSensorSample(MotionSensorType.ACCELEROMETER, 2L, 2L, 3, 1f, 2f, 3f)
        val decoded = MotionCaptureChunkFormat.decode(MotionCaptureChunkFormat.encode(listOf(withW, withoutW)))
        assertEquals(4f, decoded[0].w!!)
        assertNull(decoded[1].w)
    }
}

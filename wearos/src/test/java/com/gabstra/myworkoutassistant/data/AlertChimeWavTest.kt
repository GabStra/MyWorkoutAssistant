package com.gabstra.myworkoutassistant.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class AlertChimeWavTest {

    private val wav = buildAlertChimeWav()
    private val samples: ShortArray by lazy {
        val buffer = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        val pcmBytes = buffer.getInt(40)
        val pcm = ShortArray(pcmBytes / Short.SIZE_BYTES)
        buffer.position(44)
        buffer.asShortBuffer().get(pcm)
        pcm
    }

    @Test
    fun `chime is a valid 16 kHz mono 16-bit wav`() {
        assertEquals(44 + samples.size * Short.SIZE_BYTES, wav.size)
        assertEquals(16_000, ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN).getInt(24))
        assertTrue(samples.isNotEmpty())
    }

    @Test
    fun `chime starts and ends at silence so playback cannot click`() {
        assertEquals(0, samples.first().toInt())
        assertEquals(0, samples.last().toInt())
    }

    @Test
    fun `chime is loud but stays below clipping`() {
        val peak = samples.maxOf { kotlin.math.abs(it.toInt()) }
        assertTrue("peak $peak too quiet", peak >= 25_000)
        assertTrue("peak $peak would clip", peak <= 30_000)

        fun energyBetween(fromMs: Int, toMs: Int): Double {
            val from = 16 * fromMs
            val to = 16 * toMs
            return (from until to).sumOf { samples[it].toDouble() * samples[it] }
        }

        // One 2637 Hz ping decaying through the file.
        assertTrue(energyBetween(5, 120) > 0.0)
    }
}

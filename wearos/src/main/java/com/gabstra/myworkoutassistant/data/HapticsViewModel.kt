package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTimestamp
import android.media.AudioTrack
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.coroutines.EmptyCoroutineContext
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin

private const val CHIME_SAMPLE_RATE_HZ = 16_000
private const val CHIME_DURATION_MS = 180
private const val CHIME_ATTACK_MS = 3
private const val CHIME_DECAY_MS = 40.0
private const val CHIME_RELEASE_MS = 5
private const val CHIME_SECOND_HARMONIC_MIX = 0.25
// Short of full scale so the tiny watch speaker does not distort; loudness comes from the
// 2.6 kHz ping, where a watch speaker is most efficient and the ear most sensitive.
private const val CHIME_PEAK_AMPLITUDE = 28_000
private const val WAV_HEADER_SIZE = 44

private class ChimeNote(val frequencyHz: Double, val startMs: Int, val gain: Double)

// One bright ping (E7): loud, short and percussive so it can fire repeatedly without smear.
// Synthesized at runtime to keep the watch app free of audio assets.
private val CHIME_NOTES = listOf(
    ChimeNote(frequencyHz = 2_637.0, startMs = 0, gain = 1.0),
)

internal fun buildAlertChimeWav(): ByteArray {
    val sampleCount = CHIME_SAMPLE_RATE_HZ * CHIME_DURATION_MS / 1_000
    val pcmSize = sampleCount * Short.SIZE_BYTES
    val attackSeconds = CHIME_ATTACK_MS / 1_000.0
    val decaySeconds = CHIME_DECAY_MS / 1_000.0
    val releaseSamples = CHIME_SAMPLE_RATE_HZ * CHIME_RELEASE_MS / 1_000

    val samples = DoubleArray(sampleCount)
    repeat(sampleCount) { sampleIndex ->
        val seconds = sampleIndex.toDouble() / CHIME_SAMPLE_RATE_HZ
        var sample = 0.0
        for (note in CHIME_NOTES) {
            val localSeconds = seconds - note.startMs / 1_000.0
            if (localSeconds < 0.0) continue
            // Half-cosine attack starts at zero amplitude and slope: no click on onset.
            val attackRamp = (localSeconds / attackSeconds).coerceIn(0.0, 1.0)
            val attackEnvelope = 0.5 - 0.5 * cos(PI * attackRamp)
            val decayEnvelope = exp(-localSeconds / decaySeconds)
            val phase = 2.0 * PI * note.frequencyHz * localSeconds
            val tone = sin(phase) + CHIME_SECOND_HARMONIC_MIX * sin(2.0 * phase)
            sample += tone * attackEnvelope * decayEnvelope * note.gain
        }
        val release = ((sampleCount - 1 - sampleIndex) / (releaseSamples - 1).toDouble())
            .coerceIn(0.0, 1.0)
        samples[sampleIndex] = sample * release
    }
    // Normalize to the peak so every note contributes at full loudness without clipping.
    val peak = samples.maxOf { abs(it) }.coerceAtLeast(1e-9)
    val gain = CHIME_PEAK_AMPLITUDE / peak

    return ByteBuffer.allocate(WAV_HEADER_SIZE + pcmSize)
        .order(ByteOrder.LITTLE_ENDIAN)
        .apply {
            put("RIFF".toByteArray())
            putInt(36 + pcmSize)
            put("WAVEfmt ".toByteArray())
            putInt(16)
            putShort(1)
            putShort(1)
            putInt(CHIME_SAMPLE_RATE_HZ)
            putInt(CHIME_SAMPLE_RATE_HZ * Short.SIZE_BYTES)
            putShort(Short.SIZE_BYTES.toShort())
            putShort(16)
            put("data".toByteArray())
            putInt(pcmSize)
            repeat(sampleCount) { sampleIndex ->
                putShort(
                    (samples[sampleIndex] * gain)
                        .toInt()
                        .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
                        .toShort()
                )
            }
        }
        .array()
}

class HapticsHelper(context: Context) {
    private companion object {
        const val HARD_VIBRATION_DURATION_MS = 200
        const val GENTLE_VIBRATION_DURATION_MS = 80
        // Leaves a short silence between repeated pulses so they read as separate chimes.
        const val ALERT_PERIOD_MS = 340L

        // The speaker path on this watch takes up to ~250 ms to go from idle to audible
        // (deep-buffer standby, route apply, PCM open), while the motor starts in ~24 ms.
        // The chime therefore plays after a silent pre-roll: once the audio position advances,
        // the pre-roll's remaining frames give an exact countdown to the first audible sample.
        const val AUDIO_PREROLL_MS = 200
        const val MOTOR_LEAD_MS = 20L
        const val AUDIO_START_TIMEOUT_MS = 600L
    }

    private val appContext = context.applicationContext
    private val vibrator: Vibrator? = try {
        (appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
            .defaultVibrator
    } catch (_: Exception) {
        null
    }
    private val hasAmplitudeControl = vibrator?.hasAmplitudeControl() == true

    private fun createChimeTrack(pcm: ShortArray): AudioTrack? = runCatching {
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(CHIME_SAMPLE_RATE_HZ)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
            .build()
        AudioTrack.Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(format)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(pcm.size * Short.SIZE_BYTES)
            .build()
            .apply { write(pcm, 0, pcm.size) }
    }.getOrNull()

    private fun chimeSourcePcm(): ShortArray {
        val wav = buildAlertChimeWav()
        val chime = ShortArray((wav.size - WAV_HEADER_SIZE) / Short.SIZE_BYTES)
        ByteBuffer.wrap(wav)
            .order(ByteOrder.LITTLE_ENDIAN)
            .apply { position(WAV_HEADER_SIZE) }
            .asShortBuffer()
            .get(chime)
        return chime
    }

    // One preroll followed by every pulse at its final spacing: the whole cue is a single track,
    // so pulses cannot cut each other off and their offsets are sample-exact.
    private fun chimePatternPcm(pulseCount: Int): ShortArray {
        val chime = chimeSourcePcm()
        val preRollSamples = CHIME_SAMPLE_RATE_HZ * AUDIO_PREROLL_MS / 1_000
        val periodSamples = CHIME_SAMPLE_RATE_HZ * ALERT_PERIOD_MS.toInt() / 1_000
        return ShortArray(preRollSamples + periodSamples * (pulseCount - 1) + chime.size).also {
            repeat(pulseCount) { pulseIndex ->
                chime.copyInto(it, preRollSamples + pulseIndex * periodSamples)
            }
        }
    }

    private fun vibrate(durationMs: Int, amplitude: Int) {
        runCatching {
            vibrator?.vibrate(VibrationEffect.createOneShot(durationMs.toLong(), amplitude))
        }
    }

    fun vibrateHard() {
        val amplitude = if (hasAmplitudeControl) 255 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(HARD_VIBRATION_DURATION_MS, amplitude)
    }

    fun vibrateGentle() {
        val amplitude = if (hasAmplitudeControl) 128 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(GENTLE_VIBRATION_DURATION_MS, amplitude)
    }

    suspend fun playHardAlertPattern(pulseCount: Int) {
        val track = createChimeTrack(chimePatternPcm(pulseCount))
        if (track == null) {
            repeat(pulseCount) { pulseIndex ->
                if (pulseIndex > 0) delay(ALERT_PERIOD_MS)
                vibrateHard()
            }
            return
        }
        try {
            track.play()
            val onsetNanos = awaitChimeOnset(track)
            repeat(pulseCount) { pulseIndex ->
                val pulseNanos = pulseIndex * ALERT_PERIOD_MS * 1_000_000L
                if (onsetNanos != null) {
                    delayUntil(onsetNanos + pulseNanos - MOTOR_LEAD_MS * 1_000_000L)
                } else if (pulseIndex > 0) {
                    delay(ALERT_PERIOD_MS)
                }
                vibrateHard()
            }
            // Keep the track alive until the last chime has finished sounding.
            delay(ALERT_PERIOD_MS * (pulseCount - 1) + CHIME_DURATION_MS + 100L)
        } finally {
            runCatching { track.release() }
        }
    }

    // Waits for the HAL's presentation timestamp, then returns the wall-clock instant of the
    // first audible sample. playbackHeadPosition is useless here: it advances while the HAL is
    // still buffering, ~200 ms before the DAC starts. getTimestamp reports presentation time.
    private suspend fun awaitChimeOnset(track: AudioTrack): Long? {
        val timestamp = AudioTimestamp()
        val deadline = System.nanoTime() + AUDIO_START_TIMEOUT_MS * 1_000_000L
        while (System.nanoTime() < deadline) {
            if (track.getTimestamp(timestamp)) {
                val firstFrameNanos = timestamp.nanoTime -
                    timestamp.framePosition * 1_000_000_000L / CHIME_SAMPLE_RATE_HZ
                return firstFrameNanos + AUDIO_PREROLL_MS * 1_000_000L
            }
            delay(2)
        }
        return null
    }

    private suspend fun delayUntil(targetNanos: Long) {
        val remainingNanos = targetNanos - System.nanoTime()
        if (remainingNanos > 0) {
            delay((remainingNanos + 999_999L) / 1_000_000L)
        }
    }
}

class HapticsViewModel(
    private val appContext: Context,
    private val haptics: HapticsHelper
) : ViewModel() {
    private val appCoroutineContext
        get() = (appContext.applicationContext as? MyApplication)?.coroutineExceptionHandler
            ?: EmptyCoroutineContext

    private fun isAlertSoundEnabled(): Boolean = AlertSoundPreferences.isEnabled(appContext)

    fun doHardVibration() = haptics.vibrateHard()

    fun doGentleVibration() = haptics.vibrateGentle()

    fun doHardVibrationWithBeep() = launchHardAlertPattern(pulseCount = 1)

    fun doHardVibrationTwice() = viewModelScope.launch(appCoroutineContext) {
        repeatVibration(pulseCount = 2)
    }

    fun doHardVibrationTwiceWithBeep() = launchHardAlertPattern(pulseCount = 2)

    fun doShortImpulse() = viewModelScope.launch(appCoroutineContext) {
        repeatVibration(pulseCount = 3)
    }

    fun doShortImpulseWithBeep() = launchHardAlertPattern(pulseCount = 3)

    private fun launchHardAlertPattern(pulseCount: Int) =
        viewModelScope.launch(appCoroutineContext) {
            if (isAlertSoundEnabled()) {
                haptics.playHardAlertPattern(pulseCount)
            } else {
                repeatVibration(pulseCount)
            }
        }

    private suspend fun repeatVibration(pulseCount: Int) {
        repeat(pulseCount) { pulseIndex ->
            haptics.vibrateHard()
            if (pulseIndex < pulseCount - 1) {
                delay(200)
            }
        }
    }
}

class HapticsViewModelFactory(private val appContext: Context) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(HapticsViewModel::class.java)) {
            return HapticsViewModel(appContext, HapticsHelper(appContext)) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class: ${modelClass.name}")
    }
}

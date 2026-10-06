package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.SoundPool
import android.media.audiofx.HapticGenerator
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.coroutines.EmptyCoroutineContext
import kotlin.math.PI
import kotlin.math.sin

class HapticsHelper(context: Context) {
    private companion object {
        const val HARD_VIBRATION_DURATION_MS = 200
        const val GENTLE_VIBRATION_DURATION_MS = 80
        const val BEEP_DURATION_MS = 150
        const val ALERT_PERIOD_MS = 200L

        // The speaker path normally starts later than the vibration motor. Sound is dispatched
        // first so their physical onsets are perceptually aligned on the fallback path.
        const val FALLBACK_VIBRATION_DELAY_MS = 35L

        const val SAMPLE_RATE_HZ = 16_000
        const val BEEP_FREQUENCY_HZ = 880.0
        const val WAV_HEADER_SIZE = 44
        const val PCM_MAX_AMPLITUDE = 20_000
    }

    private val appContext = context.applicationContext
    private val vibrator: Vibrator? = try {
        (appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
            .defaultVibrator
    } catch (_: Exception) {
        null
    }
    private val hasAmplitudeControl = vibrator?.hasAmplitudeControl() == true

    private val audioSessionId =
        appContext.getSystemService(AudioManager::class.java)?.generateAudioSessionId()
            ?: AudioManager.AUDIO_SESSION_ID_GENERATE
    private val soundPool: SoundPool? = createSoundPool()
    private var beepSoundId = 0
    @Volatile
    private var isBeepLoaded = false
    private val hapticGenerator: HapticGenerator? = createHapticGenerator()

    init {
        soundPool?.setOnLoadCompleteListener { _, soundId, status ->
            if (soundId == beepSoundId && status == 0) {
                isBeepLoaded = true
            }
        }
        beepSoundId = runCatching {
            soundPool?.load(createBeepFile().absolutePath, 1) ?: 0
        }.getOrDefault(0)
    }

    private fun createSoundPool(): SoundPool? = runCatching {
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .setHapticChannelsMuted(false)
            .build()
        SoundPool.Builder()
            .setMaxStreams(1)
            .setAudioAttributes(attributes)
            .setAudioSessionId(audioSessionId)
            .build()
    }.getOrNull()

    private fun createHapticGenerator(): HapticGenerator? = runCatching {
        if (HapticGenerator.isAvailable()) {
            HapticGenerator.create(audioSessionId).apply { enabled = true }
        } else {
            null
        }
    }.getOrNull()

    private fun createBeepFile(): File {
        val beepFile = File(appContext.cacheDir, "wear_alert_beep.wav")
        if (!beepFile.exists()) {
            beepFile.writeBytes(createBeepWav())
        }
        return beepFile
    }

    private fun createBeepWav(): ByteArray {
        val sampleCount = SAMPLE_RATE_HZ * BEEP_DURATION_MS / 1_000
        val pcmSize = sampleCount * Short.SIZE_BYTES
        return ByteBuffer.allocate(WAV_HEADER_SIZE + pcmSize)
            .order(ByteOrder.LITTLE_ENDIAN)
            .apply {
                put("RIFF".toByteArray())
                putInt(36 + pcmSize)
                put("WAVEfmt ".toByteArray())
                putInt(16)
                putShort(1)
                putShort(1)
                putInt(SAMPLE_RATE_HZ)
                putInt(SAMPLE_RATE_HZ * Short.SIZE_BYTES)
                putShort(Short.SIZE_BYTES.toShort())
                putShort(16)
                put("data".toByteArray())
                putInt(pcmSize)
                repeat(sampleCount) { sampleIndex ->
                    val fadeSamples = SAMPLE_RATE_HZ / 100
                    val envelope = when {
                        sampleIndex < fadeSamples -> sampleIndex.toDouble() / fadeSamples
                        sampleIndex >= sampleCount - fadeSamples ->
                            (sampleCount - sampleIndex - 1).toDouble() / fadeSamples
                        else -> 1.0
                    }
                    val phase = 2.0 * PI * BEEP_FREQUENCY_HZ * sampleIndex / SAMPLE_RATE_HZ
                    putShort((sin(phase) * PCM_MAX_AMPLITUDE * envelope).toInt().toShort())
                }
            }
            .array()
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

    suspend fun playHardAlert() {
        val soundStarted = playBeep()
        if (hapticGenerator == null) {
            if (soundStarted) {
                delay(FALLBACK_VIBRATION_DELAY_MS)
            }
            vibrateHard()
        }
    }

    private fun playBeep(): Boolean {
        if (!isBeepLoaded || beepSoundId == 0) return false
        return runCatching {
            soundPool?.play(beepSoundId, 1f, 1f, 1, 0, 1f) != 0
        }.getOrDefault(false)
    }

    suspend fun playHardAlertPattern(pulseCount: Int) {
        val patternStartNanos = SystemClock.elapsedRealtimeNanos()
        repeat(pulseCount) { pulseIndex ->
            delayUntil(patternStartNanos + pulseIndex * ALERT_PERIOD_MS * 1_000_000L)
            playHardAlert()
        }
    }

    private suspend fun delayUntil(targetNanos: Long) {
        val remainingNanos = targetNanos - SystemClock.elapsedRealtimeNanos()
        if (remainingNanos > 0) {
            delay((remainingNanos + 999_999L) / 1_000_000L)
        }
    }

    fun release() {
        runCatching { hapticGenerator?.release() }
        runCatching { soundPool?.release() }
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

    override fun onCleared() {
        haptics.release()
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

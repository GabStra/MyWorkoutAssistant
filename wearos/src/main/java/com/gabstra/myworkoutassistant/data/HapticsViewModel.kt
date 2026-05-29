package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.coroutines.EmptyCoroutineContext

class HapticsHelper(context: Context) {
    private val appContext = context.applicationContext

    private val vibrator: Vibrator? = try {
        (appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
            .defaultVibrator
    } catch (e: Exception) {
        null
    }

    private val hasAmp: Boolean = vibrator?.hasAmplitudeControl() == true

    // STREAM_ALARM is audible on Wear; STREAM_NOTIFICATION often is not.
    private val tone: ToneGenerator? = try {
        ToneGenerator(AudioManager.STREAM_ALARM, ToneGenerator.MAX_VOLUME)
    } catch (e: Exception) {
        null
    }

    private fun vibrate(durationMs: Int, amplitude: Int) {
        try {
            val effect = VibrationEffect.createOneShot(durationMs.toLong(), amplitude)
            vibrator?.vibrate(effect)
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }

    fun vibrateHard() {
        val amp = if (hasAmp) 255 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(200, amp)
    }

    fun vibrateGentle() {
        val amp = if (hasAmp) 128 else VibrationEffect.DEFAULT_AMPLITUDE
        try {
            vibrate(80, amp)
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }

    fun vibrateHardAndBeep() {
        vibrateHard()
        playBeep()
    }

    fun playBeep() {
        try {
            tone?.startTone(ToneGenerator.TONE_PROP_ACK, 150)
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }

    fun release() {
        try {
            tone?.release()
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }
}

class HapticsViewModel(
    private val appContext: Context,
    private val haptics: HapticsHelper
) : ViewModel() {

    private val appCeh get() = (appContext.applicationContext as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext
    private fun isAlertSoundEnabled(): Boolean = AlertSoundPreferences.isEnabled(appContext)

    fun doHardVibration() = haptics.vibrateHard()
    fun doGentleVibration() = haptics.vibrateGentle()
    fun doHardVibrationWithBeep() {
        if (isAlertSoundEnabled()) {
            haptics.vibrateHardAndBeep()
        } else {
            haptics.vibrateHard()
        }
    }
    fun doHardVibrationTwice() = viewModelScope.launch(appCeh) {
        haptics.vibrateHard(); delay(200); haptics.vibrateHard()
    }
    fun doHardVibrationTwiceWithBeep() = viewModelScope.launch(appCeh) {
        doHardVibrationWithBeep(); delay(200); doHardVibrationWithBeep()
    }
    fun doShortImpulse() = viewModelScope.launch(appCeh) {
        haptics.vibrateHard(); delay(200); haptics.vibrateHard(); delay(200); haptics.vibrateHard()
    }
    fun doShortImpulseWithBeep() = viewModelScope.launch(appCeh) {
        repeat(3) { index ->
            doHardVibrationWithBeep()
            if (index < 2) {
                delay(200)
            }
        }
    }

    override fun onCleared() { super.onCleared(); haptics.release() }
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

package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.media.AudioManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.lang.reflect.Constructor

class HapticsHelper(context: Context) {
    private val appContext = context.applicationContext

    // Modern vibrator on API 31+; fallback otherwise
    private val vibrator: Vibrator? = try {
        (appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
            .defaultVibrator
    } catch (e: Exception) {
        null
    }

    private val hasAmp: Boolean = vibrator?.hasAmplitudeControl() == true

    // Use reflection to avoid loading ToneGenerator class in preview mode
    private val tone: Any? = try {
        val toneGeneratorClass = Class.forName("android.media.ToneGenerator")
        val constructor = toneGeneratorClass.getConstructor(
            Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType
        )
        // AudioManager.STREAM_NOTIFICATION = 5, ToneGenerator.MAX_VOLUME = 100
        constructor.newInstance(5, 100)
    } catch (e: Exception) {
        null // Preview mode or Android API not available
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
        vibrate(150, amp)
    }

    fun vibrateGentle() {
        val amp = if (hasAmp) 128 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(50, amp)
    }

    // fire sound + vibration together
    fun vibrateHardAndBeep() {
        vibrateHard()
        try {
            tone?.let {
                val startToneMethod = it.javaClass.getMethod(
                    "startTone",
                    Int::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType
                )
                // ToneGenerator.TONE_PROP_BEEP = 24
                startToneMethod.invoke(it, 24, 100)
            }
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }

    fun release() {
        try {
            tone?.let {
                val releaseMethod = it.javaClass.getMethod("release")
                releaseMethod.invoke(it)
            }
        } catch (e: Exception) {
            // Preview mode - ignore
        }
    }
}

class HapticsViewModel(
    private val haptics: HapticsHelper
) : ViewModel() {

    fun doHardVibration() = haptics.vibrateHard()
    fun doGentleVibration() = haptics.vibrateGentle()
    fun doHardVibrationWithBeep() = haptics.vibrateHardAndBeep()
    fun doHardVibrationTwice() = viewModelScope.launch {
        haptics.vibrateHard(); delay(200); haptics.vibrateHard()
    }
    fun doHardVibrationTwiceWithBeep() = viewModelScope.launch {
        haptics.vibrateHardAndBeep(); delay(200); haptics.vibrateHardAndBeep()
    }
    fun doShortImpulse() = viewModelScope.launch {
        haptics.vibrateHard(); delay(200); haptics.vibrateHard(); delay(200); haptics.vibrateHard()
    }

    override fun onCleared() { super.onCleared(); haptics.release() }
}

class HapticsViewModelFactory(private val appContext: Context) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(HapticsViewModel::class.java)) {
            return HapticsViewModel(HapticsHelper(appContext)) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class: ${modelClass.name}")
    }
}

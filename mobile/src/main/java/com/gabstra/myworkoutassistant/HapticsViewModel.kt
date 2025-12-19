package com.gabstra.myworkoutassistant

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class HapticsHelper(context: Context) {
    private val appContext = context.applicationContext

    // Modern vibrator on API 31+; fallback otherwise
    private val vibrator: Vibrator? =
        (appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
            .defaultVibrator

    private val hasAmp: Boolean = vibrator?.hasAmplitudeControl() == true

    private val tone: ToneGenerator = ToneGenerator(
        AudioManager.STREAM_NOTIFICATION,
        ToneGenerator.MAX_VOLUME
    )

    private fun vibrate(durationMs: Int, amplitude: Int) {
        val effect = VibrationEffect.createOneShot(durationMs.toLong(), amplitude)
        vibrator?.vibrate(effect)
    }

    fun vibrateHard() {
        val amp = if (hasAmp) 255 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(200, amp)
    }

    fun vibrateGentle() {
        val amp = if (hasAmp) 128 else VibrationEffect.DEFAULT_AMPLITUDE
        vibrate(80, amp)
    }

    // fire sound + vibration together
    fun vibrateHardAndBeep() {
        vibrateHard()
        tone.startTone(ToneGenerator.TONE_DTMF_0, 100)
    }

    fun release() {
        tone.release()
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

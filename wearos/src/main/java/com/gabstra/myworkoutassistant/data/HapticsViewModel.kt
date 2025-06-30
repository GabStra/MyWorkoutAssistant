package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class HapticsHelper(context: Context) {
    private val vibrator: Vibrator? =
        ContextCompat.getSystemService(context, Vibrator::class.java)
    private var toneGen: ToneGenerator? =
        ToneGenerator(AudioManager.STREAM_ALARM, ToneGenerator.MAX_VOLUME)

    fun vibrateHard() {
        vibrator?.let { v ->
            v.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    fun vibrateGentle() {
        vibrator?.let { v ->
            v.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    fun vibrateHardAndBeep() {
        val t = toneGen ?: return
        vibrator?.let { v ->
            v.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
            t.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 100)
        }
    }

    fun release() {
        toneGen?.release()
        toneGen = null
    }
}

class HapticsViewModel(
    private val haptics: HapticsHelper
) : ViewModel() {

    fun doHardVibration() {
        haptics.vibrateHard()
    }

    fun doGentleVibration() {
        haptics.vibrateGentle()
    }

    fun doHardVibrationWithBeep() {
        haptics.vibrateHardAndBeep()
    }

    fun doHardVibrationTwice() {
        viewModelScope.launch {
            haptics.vibrateHard()
            delay(200)
            haptics.vibrateHard()
        }
    }

    fun doHardVibrationTwiceWithBeep() {
        viewModelScope.launch {
            haptics.vibrateHardAndBeep()
            delay(200)
            haptics.vibrateHardAndBeep()
        }
    }

    fun doShortImpulse() {
        viewModelScope.launch {
            haptics.vibrateHard()
            delay(100)
            haptics.vibrateHard()
            delay(100)
            haptics.vibrateHard()
        }
    }

    override fun onCleared() {
        super.onCleared()
        haptics.release()
    }
}

class HapticsViewModelFactory(
    private val appContext: Context
) : ViewModelProvider.Factory {

    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(HapticsViewModel::class.java)) {
            val helper = HapticsHelper(appContext)
            return HapticsViewModel(helper) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class: ${modelClass.name}")
    }
}
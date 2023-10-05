package com.gabstra.myworkoutassistant.data

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.shared.Workout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

fun FormatTime(seconds: Int): String {
    val minutes = seconds / 60
    val remainingSeconds = seconds % 60
    return String.format("%02d:%02d", minutes, remainingSeconds)
}

fun VibrateOnce(context: Context,durationInMillis:Long=30) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)

    vibrator?.let {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            it.vibrate(VibrationEffect.createOneShot(durationInMillis, VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            @Suppress("DEPRECATION")
            it.vibrate(durationInMillis)
        }
    }
}

fun VibrateTwice(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val timings = longArrayOf(
        0,
        30,
        50,
        30,
    ) // Start immediately, vibrate 100ms, pause 100ms, vibrate 100ms.

    vibrator?.let {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            it.vibrate(VibrationEffect.createWaveform(timings, -1)) // -1 means don't repeat.
        } else {
            @Suppress("DEPRECATION")
            it.vibrate(timings, -1)
        }
    }
}

// Trigger vibration: two short impulses with a gap in between.
fun VibrateShortImpulse(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val timings = longArrayOf(
        0,
        100,
        50,
        100,
        50,
        100
    ) // Start immediately, vibrate 100ms, pause 100ms, vibrate 100ms.

    vibrator?.let {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            it.vibrate(VibrationEffect.createWaveform(timings, -1)) // -1 means don't repeat.
        } else {
            @Suppress("DEPRECATION")
            it.vibrate(timings, -1)
        }
    }
}



fun GetMHRPercentage(heartRate: Float, age: Int): Float{
    val mhr = 208 - (0.7f * age)
    return (heartRate / mhr) * 100
}

fun CoroutineScope.onClickWithDelay(
    delayMillis: Long = 500L,
    onClick: () -> Unit
): () -> Unit {
    var lastClickTime = 0L

    return {
        val currentTime = System.currentTimeMillis()
        if (currentTime - lastClickTime > delayMillis) {
            lastClickTime = currentTime
            launch {
                onClick()
            }
        }
    }
}

fun Context.findActivity(): Activity? {
    var currentContext = this
    while (currentContext is ContextWrapper) {
        if (currentContext is Activity) {
            return currentContext
        }
        currentContext = currentContext.baseContext
    }
    return null
}

fun getEnabledItems(workouts: List<Workout>): List<Workout> {
    return workouts.filter { it.enabled }.map { workout ->
        workout.copy(
            exerciseGroups = workout.exerciseGroups.filter { it.enabled }.map { exerciseGroup ->
                exerciseGroup.copy(
                    exercises = exerciseGroup.exercises.filter { it.enabled }
                )
            }
        )
    }
}
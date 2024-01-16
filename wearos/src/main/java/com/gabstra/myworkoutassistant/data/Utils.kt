package com.gabstra.myworkoutassistant.data

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.widget.Toast
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.AppHelperResultCode
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import com.google.gson.GsonBuilder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.util.concurrent.CancellationException

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



fun getMaxHearthRatePercentage(heartRate: Int, age: Int): Float{
    val mhr = 208 - (0.7f * age)
    return (heartRate / mhr) * 100
}

fun mapHeartRateToZonePercentage(hrPercentage: Float): Float {
    return if (hrPercentage <= 50) {
        hrPercentage * 0.00332f
    } else {
        0.166f + ((hrPercentage - 50) / 10) * 0.166f
    }
}

fun mapHearthRatePercentageToZone(percentage: Float): Int {
    val mappedValue = if (percentage <= 50) {
        percentage * 0.00332f
    } else {
        0.166f + ((percentage - 50) / 10) * 0.166f
    }

    return (mappedValue / 0.166f).toInt()
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
            workoutComponents = workout.workoutComponents.filter {isWorkoutComponentEnabled(it) }
        )
    }.filter { workout ->
        workout.workoutComponents.isNotEmpty()
    }
}

fun isWorkoutComponentEnabled(workoutComponent: WorkoutComponent): Boolean{
    return when (workoutComponent) {
        is Exercise -> workoutComponent.enabled
        is ExerciseGroup -> workoutComponent.workoutComponents.any { isWorkoutComponentEnabled(it) }
        else -> false // or true, depending on whether you want to include other types by default
    }
}

fun getFirstExercise(workoutComponents: List<WorkoutComponent>): Exercise {
    return workoutComponents.asReversed().firstOrNull { it is Exercise } as Exercise
}


fun sendWorkoutHistoryStore(dataClient: DataClient, workoutHistoryStore: WorkoutHistoryStore) {
    try {
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
            .create()
        val jsonString = gson.toJson(workoutHistoryStore)

        val request = PutDataMapRequest.create("/workoutHistoryStore").apply {
            dataMap.putString("json",jsonString)
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}

@OptIn(ExperimentalHorologistApi::class)
suspend fun openSettingsOnPhoneApp(context: Context, dataClient: DataClient, phoneNode: Node, appHelper: WearDataLayerAppHelper) {
    try {
        val result = appHelper.startRemoteOwnApp(phoneNode.id)
        if(result != AppHelperResultCode.APP_HELPER_RESULT_SUCCESS){
            Toast.makeText(context, "Failed to open app in phone", Toast.LENGTH_SHORT).show()
            return
        }

        val request = PutDataMapRequest.create("/openPagePath").apply {
            dataMap.putString("page","settings")
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
        Toast.makeText(context, "Opened Settings in phone", Toast.LENGTH_SHORT).show()
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}
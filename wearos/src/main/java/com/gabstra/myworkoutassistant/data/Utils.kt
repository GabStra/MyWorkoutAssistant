package com.gabstra.myworkoutassistant.data

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.logLargeString
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
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
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime
import java.util.concurrent.CancellationException

fun FormatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}
fun VibrateOnce(context: Context,durationInMillis:Long=20) {
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
        75,
        20,
        75,
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

fun sendWorkoutHistoryStore(dataClient: DataClient, workoutHistoryStore: WorkoutHistoryStore) {
    try {
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
            .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
            .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
            .create()
        val jsonString = gson.toJson(workoutHistoryStore)
        val compressedData = compressString(jsonString)
        val request = PutDataMapRequest.create("/workoutHistoryStore").apply {
            dataMap.putByteArray("compressedJson",compressedData)
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

@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPressOrTap(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onAction: () -> Unit,
    onTap: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        var repeatedActionHappening = false
        detectTapGestures(
            onPress = { _ ->
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    do {
                        repeatedActionHappening = true
                        onAction()
                        delay(intervalMillis)
                    } while (true)
                }
                tryAwaitRelease()
                job.cancel()
                repeatedActionHappening = false
            },
            onTap = {
                if(!repeatedActionHappening) onTap()
            }
        )
    }
)

@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onPressStart: () -> Unit,
    onBeforeLongPressRepeat: () -> Unit,
    onLongPressRepeat: () -> Unit,
    onRelease: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        detectTapGestures(
            onPress = { _ ->
                onPressStart()
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    onBeforeLongPressRepeat()
                    do {
                        delay(intervalMillis)
                        onLongPressRepeat()
                    } while (isActive)
                }

                tryAwaitRelease()
                job.cancel()
                onRelease()
            }
        )
    }
)

fun combineChunks(chunks: List<ByteArray>): ByteArray {
    val totalLength = chunks.sumOf { it.size }
    val combinedArray = ByteArray(totalLength)

    var currentPosition = 0
    for (chunk in chunks) {
        chunk.copyInto(combinedArray, currentPosition)
        currentPosition += chunk.size
    }

    return combinedArray
}
package com.gabstra.myworkoutassistant.data

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.VibrationEffect
import android.os.Vibrator
import android.widget.Toast
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.input.pointer.pointerInput
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.AppHelperResultCode
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import com.google.gson.GsonBuilder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.DelicateCoroutinesApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.max
import kotlin.math.min

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


@OptIn(DelicateCoroutinesApi::class)
fun VibrateHard(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)

    GlobalScope.launch(Dispatchers.Main) {
        launch{
            vibrator?.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }
}

@OptIn(DelicateCoroutinesApi::class)
fun VibrateGentle(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)

    GlobalScope.launch(Dispatchers.Main) {
        launch{
            vibrator?.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }
}

@OptIn(DelicateCoroutinesApi::class)
fun VibrateTwice(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)

    GlobalScope.launch(Dispatchers.Main) {
        repeat(2) {
            val vibratorJob = launch(start = CoroutineStart.LAZY){
                vibrator?.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
            }
            val startTime = System.currentTimeMillis()
            vibratorJob.join()
            if(System.currentTimeMillis() - startTime < 200){
                delay(200 - (System.currentTimeMillis() - startTime))
            }
        }
    }
}

// Trigger vibration: two short impulses with a gap in between.
@OptIn(DelicateCoroutinesApi::class)
fun VibrateShortImpulse(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val toneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)

    GlobalScope.launch(Dispatchers.Main) {
        repeat(3) {
            val startTime = System.currentTimeMillis()
            coroutineScope {
                // Create a countdown latch
                val readyCount = AtomicInteger(2)

                // Prepare both effects
                val job1 = launch {
                    readyCount.decrementAndGet()
                    while (readyCount.get() > 0) {
                        yield()
                    }
                    vibrator?.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
                }

                val job2 = launch {
                    readyCount.decrementAndGet()
                    while (readyCount.get() > 0) {
                        yield()
                    }
                    toneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 100)
                }

                joinAll(job1, job2)
            }

            val elapsedTime = System.currentTimeMillis() - startTime
            if (elapsedTime < 200) {
                delay(200 - elapsedTime)
            }
        }
    }
}

@OptIn(DelicateCoroutinesApi::class)
fun VibrateAndBeep(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val toneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)

    GlobalScope.launch(Dispatchers.Main) {
        val vibratorJob = launch(start = CoroutineStart.LAZY){
            vibrator?.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
        }

        val toneJob= launch(start = CoroutineStart.LAZY){
            toneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 100)
        }
        joinAll(toneJob,vibratorJob)
    }
}

@OptIn(DelicateCoroutinesApi::class)
fun VibrateTwiceAndBeep(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val toneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)

    GlobalScope.launch(Dispatchers.Main) {
        repeat(2) {
            val startTime = System.currentTimeMillis()
            coroutineScope {
                // Create a countdown latch
                val readyCount = AtomicInteger(2)

                // Prepare both effects
                val job1 = launch {
                    readyCount.decrementAndGet()
                    while (readyCount.get() > 0) {
                        yield()
                    }
                    vibrator?.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE))
                }

                val job2 = launch {
                    readyCount.decrementAndGet()
                    while (readyCount.get() > 0) {
                        yield()
                    }
                    toneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 100)
                }

                joinAll(job1, job2)
            }

            val elapsedTime = System.currentTimeMillis() - startTime
            if (elapsedTime < 200) {
                delay(200 - elapsedTime)
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

fun sendWorkoutHistoryStore(dataClient: DataClient, workoutHistoryStore: WorkoutHistoryStore) : Boolean {
    try {
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
            .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
            .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
            .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
            .create()
        val jsonString = gson.toJson(workoutHistoryStore)
        val compressedData = compressString(jsonString)
        val request = PutDataMapRequest.create("/workoutHistoryStore").apply {
            dataMap.putByteArray("compressedJson",compressedData)
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
        return true
    } catch(exception: Exception) {
        exception.printStackTrace()
        return false
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

@SuppressLint("SuspiciousModifierThen")
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

@SuppressLint("SuspiciousModifierThen")
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

fun calculateIntensity(weight: Float, oneRepMax: Float): Float {
    return weight / oneRepMax
}

fun calculateOneRepMax(weight: Float, reps: Int): Float {
    return weight / (1.0278f - (0.0278f * reps))
}

fun calculateVolume(weight: Float, reps: Int): Float {
    if(weight == 0f) return reps.toFloat()
    return weight * reps
}

fun getContrastRatio(color1: Color, color2: Color): Double {
    val luminance1 = color1.luminance()
    val luminance2 = color2.luminance()

    return (max(luminance1, luminance2) + 0.05) / (min(luminance1, luminance2) + 0.05)
}
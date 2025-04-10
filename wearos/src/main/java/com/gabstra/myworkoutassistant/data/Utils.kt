package com.gabstra.myworkoutassistant.data

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.runtime.Composable
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
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
import kotlin.math.exp
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

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color = Color.DarkGray,
    scrollBarColor: Color = Color.Black,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    /**
     * Optional explicit height for the scrollbar track.
     * If null (default), the track height will be 2/3 of the viewport height and centered vertically.
     * If provided, the track will use this height. If this provided height is less
     * than the viewport height, it will also be centered vertically.
     */
    trackHeight: Dp? = null
): Modifier {
    return drawWithContent {
        // Draw the column's content
        drawContent()

        // Dimensions and calculations
        val viewportHeight = this.size.height
        val totalContentHeight = scrollState.maxValue.toFloat() + viewportHeight
        val scrollValue = scrollState.value.toFloat()

        // Compute visibility ratio (how much of the total content is visible)
        // Avoid division by zero if totalContentHeight is equal to viewportHeight (or less, though unlikely)
        val visibleRatio = if (totalContentHeight > viewportHeight) {
            viewportHeight / totalContentHeight
        } else {
            1f
        }

        if (visibleRatio >= 1f) {
            return@drawWithContent
        }

        // Calculate actual track height: Use provided height or default to 2/3 of viewport
        val defaultTrackHeight = viewportHeight * (2f / 3f)
        val actualTrackHeight = trackHeight?.toPx() ?: defaultTrackHeight

        // Calculate track position (center it if its height is less than the viewport height)
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f // If track is as tall or taller than viewport, start at the top
        }

        // Draw the track (optional)
        if (showScrollBarTrack) {
            drawRoundRect(
                cornerRadius = CornerRadius(scrollBarCornerRadius),
                color = scrollBarTrackColor,
                topLeft = Offset(this.size.width - endPadding, trackTopOffset),
                size = Size(width.toPx(), actualTrackHeight),
            )
        }

        // Calculate scrollbar height (proportional to visible content ratio within the track height)
        // Ensure scrollbar height is at least a minimum size (e.g., width*2) for visibility? - Optional enhancement
        val scrollBarHeight = (visibleRatio * actualTrackHeight).coerceAtLeast(width.toPx() * 2) // Ensure minimum height


        // Calculate scrollbar position within the track
        val availableTrackSpace = actualTrackHeight - scrollBarHeight
        val scrollProgress = if (scrollState.maxValue > 0) {
            scrollValue / scrollState.maxValue.toFloat()
        } else {
            0f
        }
        // Ensure scroll progress is clamped between 0 and 1
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)

        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarStartOffset = trackTopOffset + scrollBarOffsetWithinTrack

        // Draw the scrollbar thumb
        drawRoundRect(
            cornerRadius = CornerRadius(scrollBarCornerRadius),
            color = scrollBarColor,
            topLeft = Offset(this.size.width - endPadding, scrollBarStartOffset),
            // Ensure the drawn size doesn't exceed the track boundaries if calculations are slightly off
            size = Size(width.toPx(), scrollBarHeight.coerceAtMost(actualTrackHeight))
        )
    }
}





@OptIn(DelicateCoroutinesApi::class)
fun VibrateAndBeep(context: Context) {
    val vibrator = ContextCompat.getSystemService(context, Vibrator::class.java)
    val toneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)

    GlobalScope.launch(Dispatchers.Default) {
        val vibratorJob = launch(start = CoroutineStart.LAZY){
            vibrator?.vibrate(VibrationEffect.createOneShot(100, 255))
        }

        val toneJob= launch(start = CoroutineStart.LAZY){
            toneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 100)
        }
        joinAll(toneJob,vibratorJob)
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

fun calculateOneRepMax(weight: Double, reps: Int): Double {
    return weight / (1.0278 - (0.0278 * reps))
}

fun calculateVolume(weight: Double, reps: Int): Double {
    if(weight == 0.0) return reps.toDouble()
    return weight * reps
}

fun getContrastRatio(color1: Color, color2: Color): Double {
    val luminance1 = color1.luminance()
    val luminance2 = color2.luminance()

    return (max(luminance1, luminance2) + 0.05) / (min(luminance1, luminance2) + 0.05)
}

fun Modifier.circleMask() = this.drawWithContent {
    // Create a circular path for the mask
    val path = androidx.compose.ui.graphics.Path().apply {
        val radius = size.width  * 0.45f
        val center = Offset(size.width / 2, size.height / 2)
        addOval(androidx.compose.ui.geometry.Rect(center.x - radius, center.y - radius, center.x + radius, center.y + radius))
    }

    // Clip the path and draw the content
    clipPath(path) {
        this@drawWithContent.drawContent()
    }
}

@SuppressLint("DefaultLocale")
fun formatNumber(value: Double, unit: String? = null): String = (when {
    value >= 1_000_000 -> String.format("%.1fM", value / 1_000_000f)
    value >= 1_000 -> String.format("%.1fk", value / 1_000f)
    else -> String.format("%.1f", value)
}.replace(",", ".").replace(".0", "") + (unit?.let { " $it" } ?: "")).trim()

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

fun getValueInRange(startAngle: Float, endAngle: Float, percentage: Float): Float {
    return startAngle + (endAngle - startAngle) * percentage
}
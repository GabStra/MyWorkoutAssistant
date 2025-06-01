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
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.concurrent.CancellationException
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

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



// Default height for the content fade gradient
private val DEFAULT_CONTENT_FADE_HEIGHT = 5.dp

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    // Scrollbar appearance
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color = Color.DarkGray,
    scrollBarColor: Color = Color.Black,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 0f,
    trackHeight: Dp? = null,
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color = Color.Black
): Modifier {
    // Remember updated state for all parameters accessed within draw lambda
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(scrollBarTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(scrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(contentFadeColor)

    return this.drawWithContent {
        // --- Draw the actual content first ---
        drawContent()

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        val componentWidth = size.width
        val componentHeight = size.height
        val currentScrollValue = scrollState.value.toFloat()
        val maxScrollValue = scrollState.maxValue.toFloat()

        // Only proceed with fade drawing if fade height is positive
        if (fadeHeightPx > 0f) {

            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                // Calculate alpha based on proximity to the top edge (within fadeHeightPx)
                // Alpha is 0.0 when scrollValue is 0, 1.0 when scrollValue >= fadeHeightPx
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the top)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) { // Also check if scrolling is possible at all
                // Calculate distance from the bottom edge
                val distanceToBottom = maxScrollValue - currentScrollValue

                // Calculate alpha based on proximity to the bottom edge (within fadeHeightPx)
                // Alpha is 0.0 when distance is 0 (at bottom), 1.0 when distance >= fadeHeightPx
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the bottom)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }


        // --- Scrollbar Logic (remains the same, drawn on top) ---
        val viewportHeight = componentHeight
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue // Use already fetched value
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val scrollBarHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        if (rememberedShowTrack) {
            drawRoundRect(
                color = rememberedTrackColor,
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                size = Size(barWidthPx, actualTrackHeight),
                cornerRadius = cornerRadius
            )
        }

        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
            size = Size(barWidthPx, scrollBarHeight),
            cornerRadius = cornerRadius
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

fun calculateOneRepMax(weight: Double, reps: Int): Double =
    weight * reps.toDouble().pow(0.10)

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



fun FormatWeightForSetScreen(equipment: WeightLoadedEquipment, weight: Double): String {
    if(weight <= 0) return "-"

    fun formatWeight(weight:Double): String {
        if (weight % 1.0 == 0.0) {
            return weight.toInt().toString()
        }

        return "%.2f".format(weight).replace(",", ".")
    }

    return when (equipment) {
        is Barbell -> {
            val sideWeight = (weight - equipment.barWeight) / 2
            if(sideWeight == 0.0) return "Empty"


            "${formatWeight(weight)} kg ($sideWeight kg/side)"

            "${formatWeight(sideWeight)} kg/side (Tot: ${formatWeight(weight)} kg)".replace(",", ".")
        }
        is Dumbbells -> {
            val dumbbellWeight = weight / 2
            "${formatWeight(dumbbellWeight)} kg/dumbbell (Tot: ${formatWeight(weight)} kg)".replace(",", ".")
        }
        is Dumbbell ->
            "${formatWeight(weight)} kg"
        is PlateLoadedCable -> "${formatWeight(weight)} kg".replace(",", ".")
        is Machine -> "${formatWeight(weight)} kg".replace(",", ".")
        is WeightVest -> "${formatWeight(weight)} kg".replace(",", ".")
        else -> "$weight kg".replace(",", ".")
    }
}
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
import androidx.compose.foundation.lazy.LazyListState
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
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.ErrorLog
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
import kotlinx.coroutines.withContext
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
    scrollBarTrackColor: Color = MediumGray,
    scrollBarColor: Color = MaterialTheme.colorScheme.onBackground,
    scrollBarCornerRadius: Dp = 4.dp,           // Dp radius for both track and thumb
    endPadding: Float = 0f,                     // px from the right edge
    trackHeight: Dp? = null,
    // Gap between track segments and the thumb (vertical gap above and below the thumb)
    thumbGap: Dp = 2.dp,
    // Content fade effect
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color = MaterialTheme.colorScheme.background
): Modifier {
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
    val rememberedThumbGap by rememberUpdatedState(thumbGap)

    return this.drawWithContent {
        // Draw content first
        drawContent()

        // --- Fades ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        val componentWidth = size.width
        val componentHeight = size.height
        val currentScrollValue = scrollState.value.toFloat()
        val maxScrollValue = scrollState.maxValue.toFloat()

        if (fadeHeightPx > 0f) {
            if (rememberedEnableTopFade) {
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)
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
            if (rememberedEnableBottomFade && maxScrollValue > 0) {
                val distanceToBottom = maxScrollValue - currentScrollValue
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)
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

        // --- Scrollbar ---
        val viewportHeight = componentHeight
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)
        if (visibleRatio >= 1f || maxScrollValue <= 0) return@drawWithContent

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight =
            rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight

        val trackTop = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else 0f
        val trackBottom = trackTop + actualTrackHeight

        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding
        val radiusPx = rememberedCornerRadius.toPx()
        val gapPx = rememberedThumbGap.toPx().coerceAtLeast(0f)
        val corner = CornerRadius(radiusPx, radiusPx)

        val minThumbHeight = barWidthPx * 2
        val thumbHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)

        val scrollProgress =
            if (maxScrollValue > 0f) (currentScrollValue / maxScrollValue).coerceIn(0f, 1f) else 0f
        val thumbTop = trackTop + scrollProgress * (actualTrackHeight - thumbHeight)
        val thumbBottom = thumbTop + thumbHeight

        val x = componentWidth - paddingPx - barWidthPx

        // 1) TRACK ABOVE (rounded at both ends)
        if (rememberedShowTrack) {
            val topSegTop = trackTop
            val topSegBottom = (thumbTop - gapPx).coerceAtLeast(topSegTop)
            val topHeight = (topSegBottom - topSegTop).coerceAtLeast(0f)
            if (topHeight > 0f) {
                // Limit radius to half height to keep ends nicely rounded for short segments
                val r = minOf(radiusPx, topHeight / 2f)
                drawRoundRect(
                    color = rememberedTrackColor,
                    topLeft = Offset(x, topSegTop),
                    size = Size(barWidthPx, topHeight),
                    cornerRadius = CornerRadius(r, r)
                )
            }

            // 2) TRACK BELOW (rounded at both ends)
            val botSegTop = (thumbBottom + gapPx).coerceAtMost(trackBottom)
            val botSegBottom = trackBottom
            val botHeight = (botSegBottom - botSegTop).coerceAtLeast(0f)
            if (botHeight > 0f) {
                val r = minOf(radiusPx, botHeight / 2f)
                drawRoundRect(
                    color = rememberedTrackColor,
                    topLeft = Offset(x, botSegTop),
                    size = Size(barWidthPx, botHeight),
                    cornerRadius = CornerRadius(r, r)
                )
            }
        }

        // 3) THUMB (rounded at both ends)
        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(x, thumbTop),
            size = Size(barWidthPx, thumbHeight),
            cornerRadius = corner
        )
    }
}

@Composable
fun Modifier.verticalLazyColumnScrollbar(
    lazyListState: LazyListState,
    // Scrollbar appearance
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color = MaterialTheme.colorScheme.surfaceContainerHigh,
    scrollBarColor: Color = MaterialTheme.colorScheme.onBackground,
    scrollBarCornerRadius: Dp = 4.dp,
    endPadding: Float = 0f,
    trackHeight: Dp? = null,
    thumbGap: Dp = 2.dp,
    // Content fade effect
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color = MaterialTheme.colorScheme.background
): Modifier {
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
    val rememberedThumbGap by rememberUpdatedState(thumbGap)

    val layoutInfo = lazyListState.layoutInfo
    val visibleItemsInfo = layoutInfo.visibleItemsInfo

    return this.drawWithContent {
        drawContent()

        val componentWidth = size.width
        val componentHeight = size.height
        val viewportHeight = componentHeight.toFloat()

        // Calculate scroll position and total content height
        val firstVisibleItem = visibleItemsInfo.firstOrNull()
        
        if (firstVisibleItem == null || layoutInfo.totalItemsCount == 0) {
            return@drawWithContent
        }

        // Calculate current scroll position (pixels scrolled)
        val currentScrollValue = if (firstVisibleItem.index > 0) {
            // Estimate: sum of heights of items before first visible item
            // Use average item height from visible items as estimate
            val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
                visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
            } else {
                firstVisibleItem.size.toFloat()
            }
            (firstVisibleItem.index * avgItemHeight) - firstVisibleItem.offset
        } else {
            (-firstVisibleItem.offset).toFloat()
        }

        // Calculate total content height
        // Estimate based on visible items and total item count
        val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
            visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
        } else {
            firstVisibleItem.size.toFloat()
        }
        val estimatedTotalHeight = layoutInfo.totalItemsCount * avgItemHeight
        val maxScrollValue = (estimatedTotalHeight - viewportHeight).coerceAtLeast(0f)

        // --- Fades ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        if (fadeHeightPx > 0f) {
            if (rememberedEnableTopFade) {
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)
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
            if (rememberedEnableBottomFade && maxScrollValue > 0) {
                val distanceToBottom = maxScrollValue - currentScrollValue
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)
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

        // --- Scrollbar ---
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)
        if (visibleRatio >= 1f || maxScrollValue <= 0) return@drawWithContent

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight =
            rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight

        val trackTop = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else 0f
        val trackBottom = trackTop + actualTrackHeight

        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding
        val radiusPx = rememberedCornerRadius.toPx()
        val gapPx = rememberedThumbGap.toPx().coerceAtLeast(0f)
        val corner = CornerRadius(radiusPx, radiusPx)

        val minThumbHeight = barWidthPx * 2
        val thumbHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)

        val scrollProgress =
            if (maxScrollValue > 0f) (currentScrollValue / maxScrollValue).coerceIn(0f, 1f) else 0f
        val thumbTop = trackTop + scrollProgress * (actualTrackHeight - thumbHeight)
        val thumbBottom = thumbTop + thumbHeight

        val x = componentWidth - paddingPx - barWidthPx

        // 1) TRACK ABOVE
        if (rememberedShowTrack) {
            val topSegTop = trackTop
            val topSegBottom = (thumbTop - gapPx).coerceAtLeast(topSegTop)
            val topHeight = (topSegBottom - topSegTop).coerceAtLeast(0f)
            if (topHeight > 0f) {
                val r = minOf(radiusPx, topHeight / 2f)
                drawRoundRect(
                    color = rememberedTrackColor,
                    topLeft = Offset(x, topSegTop),
                    size = Size(barWidthPx, topHeight),
                    cornerRadius = CornerRadius(r, r)
                )
            }

            // 2) TRACK BELOW
            val botSegTop = (thumbBottom + gapPx).coerceAtMost(trackBottom)
            val botSegBottom = trackBottom
            val botHeight = (botSegBottom - botSegTop).coerceAtLeast(0f)
            if (botHeight > 0f) {
                val r = minOf(radiusPx, botHeight / 2f)
                drawRoundRect(
                    color = rememberedTrackColor,
                    topLeft = Offset(x, botSegTop),
                    size = Size(barWidthPx, botHeight),
                    cornerRadius = CornerRadius(r, r)
                )
            }
        }

        // 3) THUMB
        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(x, thumbTop),
            size = Size(barWidthPx, thumbHeight),
            cornerRadius = corner
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

fun sendErrorLogsToMobile(dataClient: DataClient, errorLogs: List<ErrorLog>): Boolean {
    try {
        if (errorLogs.isEmpty()) {
            return true // No logs to send, consider it successful
        }
        
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
            .create()
        val jsonString = gson.toJson(errorLogs)
        val compressedData = compressString(jsonString)
        val request = PutDataMapRequest.create("/errorLogsSync").apply {
            dataMap.putByteArray("compressedJson", compressedData)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
        return true
    } catch (exception: Exception) {
        exception.printStackTrace()
        return false
    }
}

@OptIn(ExperimentalHorologistApi::class)
suspend fun openSettingsOnPhoneApp(context: Context, dataClient: DataClient, phoneNode: Node, appHelper: WearDataLayerAppHelper) : Boolean {
    try {
        val result = appHelper.startRemoteOwnApp(phoneNode.id)
        if(result != AppHelperResultCode.APP_HELPER_RESULT_SUCCESS){
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Failed to open app in phone", Toast.LENGTH_SHORT).show()
            }
            return false
        }

        val request = PutDataMapRequest.create("/openPagePath").apply {
            dataMap.putString("page","settings")
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
        return true

    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
        return false
    } catch (exception: Exception) {
        exception.printStackTrace()
        return false
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

fun Modifier.circleMask(radiusOffset: Dp = 0.dp) = this.drawWithContent {
    // Create a circular path for the mask
    val path = androidx.compose.ui.graphics.Path().apply {
        val radius = (size.width * 0.5f) - radiusOffset.toPx()
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

fun Float.round(decimals: Int): Float {
    var multiplier = 1.0f
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

fun Modifier.scrim(visible: Boolean, color: Color) = this.then(
    if (!visible) Modifier
    else Modifier
        .drawWithContent {
            drawContent()
            drawRect(color) // overlay on top
        }
        .pointerInput(Unit) { // swallow all pointer events while visible
            awaitPointerEventScope {
                while (true) {
                    val event = awaitPointerEvent()
                    event.changes.forEach { it.consume() }
                }
            }
        }
)
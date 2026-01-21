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
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
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
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
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
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import android.util.Log
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Node
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.tasks.Tasks
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.AppHelperResultCode
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import com.google.gson.GsonBuilder
import com.gabstra.myworkoutassistant.DataLayerListenerService
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.DelicateCoroutinesApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
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
    scrollBarTrackColor: Color = MediumDarkGray,
    scrollBarColor: Color = MaterialTheme.colorScheme.onBackground,
    scrollBarCornerRadius: Dp = 4.dp,           // Dp radius for both track and thumb
    endPadding: Float = 0f,                     // px from the right edge
    trackHeight: Dp? = null,
    // Gap between track segments and the thumb (vertical gap above and below the thumb)
    thumbGap: Dp = 2.dp,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
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
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    // State for scrollbar visibility
    var scrollbarVisible by remember { mutableStateOf(false) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    // Animate scrollbar opacity
    val scrollbarAlpha by animateFloatAsState(
        targetValue = if (scrollbarVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 250),
        label = "scrollbar_fade"
    )

    // Show scrollbar on scroll interaction
    LaunchedEffect(scrollState.value) {
        scrollbarVisible = true
        hideTimeoutJob?.cancel()
        hideTimeoutJob = coroutineScope.launch {
            delay(2500) // 2.5 seconds
            scrollbarVisible = false
        }
    }

    return this
        .pointerInput(Unit) {
            detectTapGestures {
                scrollbarVisible = true
                hideTimeoutJob?.cancel()
                hideTimeoutJob = coroutineScope.launch {
                    delay(2500)
                    scrollbarVisible = false
                }
            }
        }
        .drawWithContent {
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
        val maxThumbHeight = actualTrackHeight * rememberedMaxThumbHeightFraction.coerceIn(0f, 1f)
        val computedThumbHeight = visibleRatio * actualTrackHeight
        val thumbHeight = computedThumbHeight
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(maxThumbHeight)

        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - thumbHeight).coerceAtLeast(0f)
        val scrollProgress =
            if (availableScrollSpace > 0f) currentScrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val thumbTop = trackTop + clampedScrollProgress * availableTrackSpace
        val thumbBottom = thumbTop + thumbHeight

        val x = componentWidth - paddingPx - barWidthPx

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            // 1) TRACK ABOVE (rounded at both ends)
            if (rememberedShowTrack) {
                val topSegTop = trackTop
                val topSegBottom = (thumbTop - gapPx).coerceAtLeast(topSegTop)
                val topHeight = (topSegBottom - topSegTop).coerceAtLeast(0f)
                if (topHeight > 0f) {
                    // Limit radius to half height to keep ends nicely rounded for short segments
                    val r = minOf(radiusPx, topHeight / 2f)
                    drawRoundRect(
                        color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
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
                        color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                        topLeft = Offset(x, botSegTop),
                        size = Size(barWidthPx, botHeight),
                        cornerRadius = CornerRadius(r, r)
                    )
                }
            }

            // 3) THUMB (rounded at both ends)
            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(x, thumbTop),
                size = Size(barWidthPx, thumbHeight),
                cornerRadius = corner
            )
        }
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
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
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
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    // State for scrollbar visibility
    var scrollbarVisible by remember { mutableStateOf(false) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    // Animate scrollbar opacity
    val scrollbarAlpha by animateFloatAsState(
        targetValue = if (scrollbarVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 250),
        label = "scrollbar_fade"
    )

    val layoutInfo = lazyListState.layoutInfo
    val visibleItemsInfo = layoutInfo.visibleItemsInfo

    // Show scrollbar on scroll interaction - use firstVisibleItemIndex to track scroll changes
    val firstVisibleItemIndex = visibleItemsInfo.firstOrNull()?.index ?: 0
    LaunchedEffect(firstVisibleItemIndex, lazyListState.firstVisibleItemScrollOffset) {
        scrollbarVisible = true
        hideTimeoutJob?.cancel()
        hideTimeoutJob = coroutineScope.launch {
            delay(2500) // 2.5 seconds
            scrollbarVisible = false
        }
    }

    return this
        .pointerInput(Unit) {
            detectTapGestures {
                scrollbarVisible = true
                hideTimeoutJob?.cancel()
                hideTimeoutJob = coroutineScope.launch {
                    delay(2500)
                    scrollbarVisible = false
                }
            }
        }
        .drawWithContent {
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
        val maxThumbHeight = actualTrackHeight * rememberedMaxThumbHeightFraction.coerceIn(0f, 1f)
        val computedThumbHeight = visibleRatio * actualTrackHeight
        val thumbHeight = computedThumbHeight
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(maxThumbHeight)

        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - thumbHeight).coerceAtLeast(0f)
        val scrollProgress =
            if (availableScrollSpace > 0f) currentScrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val thumbTop = trackTop + clampedScrollProgress * availableTrackSpace
        val thumbBottom = thumbTop + thumbHeight

        val x = componentWidth - paddingPx - barWidthPx

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            // 1) TRACK ABOVE
            if (rememberedShowTrack) {
                val topSegTop = trackTop
                val topSegBottom = (thumbTop - gapPx).coerceAtLeast(topSegTop)
                val topHeight = (topSegBottom - topSegTop).coerceAtLeast(0f)
                if (topHeight > 0f) {
                    val r = minOf(radiusPx, topHeight / 2f)
                    drawRoundRect(
                        color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
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
                        color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                        topLeft = Offset(x, botSegTop),
                        size = Size(barWidthPx, botHeight),
                        cornerRadius = CornerRadius(r, r)
                    )
                }
            }

            // 3) THUMB
            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(x, thumbTop),
                size = Size(barWidthPx, thumbHeight),
                cornerRadius = corner
            )
        }
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

// Helper object to manage sync handshake state
object SyncHandshakeManager {
    private val pendingAcks = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingCompletions = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val pendingErrors = ConcurrentHashMap<String, CompletableDeferred<String>>()

    fun registerAckWaiter(transactionId: String): CompletableDeferred<Unit> {
        val deferred = CompletableDeferred<Unit>()
        pendingAcks[transactionId] = deferred
        return deferred
    }

    fun registerCompletionWaiter(transactionId: String): CompletableDeferred<Unit> {
        // Use compute to atomically check if there's already a completed deferred
        // This prevents race conditions where completion arrives between registration and wait
        return pendingCompletions.compute(transactionId) { _, existing ->
            if (existing != null && existing.isCompleted) {
                // Reuse the already-completed deferred
                existing
            } else {
                // Create new deferred, but cancel the old one if it exists and isn't completed
                existing?.cancel()
                CompletableDeferred<Unit>()
            }
        } ?: CompletableDeferred<Unit>()
    }

    fun registerErrorWaiter(transactionId: String): CompletableDeferred<String> {
        // Use compute to atomically check if there's already a completed deferred
        // This prevents race conditions where error arrives between registration and wait
        return pendingErrors.compute(transactionId) { _, existing ->
            if (existing != null && existing.isCompleted) {
                // Reuse the already-completed deferred
                existing
            } else {
                // Create new deferred, but cancel the old one if it exists and isn't completed
                existing?.cancel()
                CompletableDeferred<String>()
            }
        } ?: CompletableDeferred<String>()
    }
    
    fun hasError(transactionId: String): Boolean {
        val deferred = pendingErrors[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeAck(transactionId: String) {
        pendingAcks.remove(transactionId)?.complete(Unit)
    }

    fun completeCompletion(transactionId: String) {
        // Use compute to atomically complete and handle race conditions
        // This ensures we complete the deferred even if it's being checked/waiting concurrently
        pendingCompletions.compute(transactionId) { _, deferred ->
            deferred?.let {
                if (!it.isCompleted) {
                    it.complete(Unit)
                }
            }
            // Return null to remove from map after completion
            null
        }
    }

    fun hasCompletion(transactionId: String): Boolean {
        val deferred = pendingCompletions[transactionId]
        return deferred?.isCompleted == true
    }

    fun completeError(transactionId: String, errorMessage: String) {
        // Use compute to atomically complete and handle race conditions
        // This ensures we complete the deferred even if it's being checked/waiting concurrently
        pendingErrors.compute(transactionId) { _, deferred ->
            deferred?.let {
                if (!it.isCompleted) {
                    it.complete(errorMessage)
                }
            }
            // Return null to remove from map after completion
            null
        }
    }

    fun cleanup(transactionId: String) {
        pendingAcks.remove(transactionId)?.cancel()
        pendingCompletions.remove(transactionId)?.cancel()
        pendingErrors.remove(transactionId)?.cancel()
    }
}

/**
 * Checks if at least one connected node exists before attempting sync.
 * Retries up to 3 times with exponential backoff.
 */
suspend fun checkConnection(context: android.content.Context, maxRetries: Int = 3): Boolean {
    var attempt = 0
    while (attempt < maxRetries) {
        try {
            Log.d("DataLayerSync", "Checking connection (attempt ${attempt + 1}/$maxRetries)")
            val nodeClient = Wearable.getNodeClient(context)
            val nodes = Tasks.await(nodeClient.connectedNodes, 10, java.util.concurrent.TimeUnit.SECONDS)
            val hasConnection = nodes.isNotEmpty()
            
            if (hasConnection) {
                Log.d("DataLayerSync", "Connection verified: ${nodes.size} node(s) connected")
                return true
            } else {
                Log.w("DataLayerSync", "No connected nodes found (attempt ${attempt + 1}/$maxRetries)")
            }
        } catch (e: Exception) {
            Log.w("DataLayerSync", "Connection check failed (attempt ${attempt + 1}/$maxRetries): ${e.message}")
        }
        
        attempt++
        if (attempt < maxRetries) {
            // Exponential backoff: 500ms, 1000ms, 2000ms
            val delayMs = 500L * (1 shl (attempt - 1))
            delay(delayMs)
        }
    }
    
    Log.e("DataLayerSync", "Connection check failed after $maxRetries attempts")
    return false
}

suspend fun sendSyncRequest(dataClient: DataClient, transactionId: String, context: android.content.Context? = null): Boolean {
    val maxRetries = 3
    var attempt = 0
    
    while (attempt < maxRetries) {
        try {
            Log.d("DataLayerSync", "Starting handshake for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries)")
            
            // Check connection before attempting sync if context is provided
            if (context != null) {
                val hasConnection = checkConnection(context)
                if (!hasConnection) {
                    Log.e("DataLayerSync", "No connection available for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries)")
                    if (attempt < maxRetries - 1) {
                        // Exponential backoff with jitter
                        val baseDelay = 500L * (1 shl attempt)
                        val jitter = (0..100).random().toLong()
                        delay(baseDelay + jitter)
                        attempt++
                        continue
                    }
                    return false
                }
            }
            
            // Register waiter BEFORE sending request to avoid race condition
            val ackWaiter = SyncHandshakeManager.registerAckWaiter(transactionId)
            
            val requestPath = DataLayerPaths.buildPath(DataLayerPaths.SYNC_REQUEST_PREFIX, transactionId)
            val request = PutDataMapRequest.create(requestPath).apply {
                dataMap.putString("transactionId", transactionId)
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
            }.asPutDataRequest().setUrgent()
            
            Log.d("DataLayerSync", "Sending sync request for transaction: $transactionId")
            dataClient.putDataItem(request)
            
            // Small delay to allow message delivery
            delay(100)
            
            Log.d("DataLayerSync", "Waiting for acknowledgment for transaction: $transactionId")
            // Wait for acknowledgment with timeout
            val ackReceived = withTimeoutOrNull(DataLayerListenerService.HANDSHAKE_TIMEOUT_MS) {
                ackWaiter.await()
                Log.d("DataLayerSync", "Received acknowledgment for transaction: $transactionId")
                true
            } ?: false
            
            if (!ackReceived) {
                Log.e("DataLayerSync", "Handshake timeout for transaction: $transactionId after ${DataLayerListenerService.HANDSHAKE_TIMEOUT_MS}ms (attempt ${attempt + 1}/$maxRetries)")
                if (attempt < maxRetries - 1) {
                    // Exponential backoff with jitter
                    val baseDelay = 500L * (1 shl attempt)
                    val jitter = (0..100).random().toLong()
                    delay(baseDelay + jitter)
                    attempt++
                    continue
                }
                SyncHandshakeManager.cleanup(transactionId)
                return false
            } else {
                Log.d("DataLayerSync", "Handshake successful for transaction: $transactionId")
                return true
            }
        } catch (exception: Exception) {
            Log.e("DataLayerSync", "Error sending sync request for transaction: $transactionId (attempt ${attempt + 1}/$maxRetries): ${exception.message}", exception)
            if (attempt < maxRetries - 1) {
                // Exponential backoff with jitter
                val baseDelay = 500L * (1 shl attempt)
                val jitter = (0..100).random().toLong()
                delay(baseDelay + jitter)
                attempt++
                continue
            }
            SyncHandshakeManager.cleanup(transactionId)
            return false
        }
    }
    
    SyncHandshakeManager.cleanup(transactionId)
    return false
}

suspend fun waitForSyncCompletion(transactionId: String): Boolean {
    return try {
        val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
        
        // await() handles already-completed deferreds correctly, so we can use it directly
        // But check first for early return and logging
        if (completionWaiter.isCompleted) {
            Log.d("DataLayerSync", "Completion waiter already completed for transaction: $transactionId")
            SyncHandshakeManager.cleanup(transactionId)
            return true
        }
        
        val completionReceived = withTimeoutOrNull(DataLayerListenerService.COMPLETION_TIMEOUT_MS) {
            completionWaiter.await()
            true
        } ?: false
        
        if (!completionReceived) {
            Log.w("DataLayerSync", "Completion timeout for transaction: $transactionId (data may have been received)")
        }
        
        SyncHandshakeManager.cleanup(transactionId)
        completionReceived
    } catch (exception: Exception) {
        Log.e("DataLayerSync", "Error waiting for sync completion", exception)
        SyncHandshakeManager.cleanup(transactionId)
        false
    }
}

suspend fun sendWorkoutHistoryStore(dataClient: DataClient, workoutHistoryStore: WorkoutHistoryStore, context: android.content.Context? = null) : Boolean {
    val transactionId = UUID.randomUUID().toString()
    try {
        // Check if phone is connected before attempting sync
        // This prevents sync attempts when phone is not available
        if (context != null) {
            val hasConnection = checkConnection(context)
            if (!hasConnection) {
                Log.d("DataLayerSync", "Skipping workout history sync - phone not connected (transaction: $transactionId)")
                return false
            }
        }
        
        // Send sync request and wait for acknowledgment
        val handshakeSuccess = sendSyncRequest(dataClient, transactionId, context)
        if (!handshakeSuccess) {
            // Handshake (ACK) failed or timed out, but the phone clearly received the request
            // in our logs, so fall back to best-effort send instead of aborting.
            // This avoids blocking sync when the ACK data item doesn't make it back to the watch.
            Log.w(
                "DataLayerSync",
                "Handshake failed (no ACK) for transaction: $transactionId - proceeding with best-effort send"
            )
        }

        // Register completion and error waiters BEFORE sending data
        val completionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
        val errorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)

        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
            .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
            .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
            .registerTypeAdapter(SetData::class.java, SetDataAdapter())
            .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
            .create()
        val jsonString = gson.toJson(workoutHistoryStore)
        val chunkSize = 50000 // Adjust the chunk size as needed
        val compressedData = compressString(jsonString)
        val chunks = compressedData.asList().chunked(chunkSize).map { it.toByteArray() }

        val startPath = DataLayerPaths.buildPath(DataLayerPaths.WORKOUT_HISTORY_START_PREFIX, transactionId)
        val startRequest = PutDataMapRequest.create(startPath).apply {
            dataMap.putBoolean("isStart", true)
            dataMap.putInt("chunksCount", chunks.size)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(startRequest)

        delay(500)

        // Send chunks with indices
        chunks.forEachIndexed { index, chunk ->
            val isLastChunk = index == chunks.size - 1
            val chunkPath = DataLayerPaths.buildPath(DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX, transactionId, index)

            val request = PutDataMapRequest.create(chunkPath).apply {
                dataMap.putByteArray("chunk", chunk)
                dataMap.putInt("chunkIndex", index)
                if(isLastChunk) {
                    dataMap.putBoolean("isLastChunk", true)
                }
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request)

            if (!isLastChunk) {
                delay(500)
            }
        }
        
        // Small delay after last chunk to allow message delivery
        delay(100)

        // Calculate dynamic timeout based on chunk count
        val completionTimeout = DataLayerListenerService.calculateCompletionTimeout(chunks.size)
        Log.d("DataLayerSync", "Using dynamic completion timeout: ${completionTimeout}ms for ${chunks.size} chunks, transaction: $transactionId")

        // Wait for either completion, error, or timeout - with retry logic
        var retryAttempt = 0
        val maxRetries = 5 // Increased from 3 to 5 for better recovery
        var currentCompletionWaiter = completionWaiter
        var currentErrorWaiter = errorWaiter

        while (retryAttempt <= maxRetries) {
            // Use select which handles already-completed deferreds correctly
            // onAwait will immediately return if the deferred is already completed
            val result = withTimeoutOrNull(completionTimeout) {
                select<Pair<Boolean, String?>> {
                    currentCompletionWaiter.onAwait.invoke {
                        Pair(true, null)
                    }
                    currentErrorWaiter.onAwait.invoke { errorMessage ->
                        Pair(false, errorMessage)
                    }
                }
            }
            
            // Check if completion was already received (select handles this, but we check for logging)
            if (currentCompletionWaiter.isCompleted && result?.first != true) {
                Log.d("DataLayerSync", "Completion waiter was already completed for workout history transaction: $transactionId")
                SyncHandshakeManager.cleanup(transactionId)
                return true
            }
            
            when {
                result == null -> {
                    // Timeout occurred
                    Log.e("DataLayerSync", "Completion timeout for workout history transaction: $transactionId (attempt $retryAttempt)")
                    if (retryAttempt < maxRetries) {
                        // Exponential backoff with jitter for timeout retries
                        val baseDelay = 500L * (1 shl retryAttempt)
                        val jitter = (0..200).random().toLong()
                        delay(baseDelay + jitter)
                        retryAttempt++
                        // Re-register waiters for retry
                        currentCompletionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
                        currentErrorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)
                        continue
                    }
                    SyncHandshakeManager.cleanup(transactionId)
                    return false
                }
                result.first -> {
                    // Completion received
                    Log.d("DataLayerSync", "Sync completed successfully for workout history transaction: $transactionId")
                    SyncHandshakeManager.cleanup(transactionId)
                    return true
                }
                else -> {
                    // Error received
                    val errorMessage = result.second ?: "Unknown error"
                    Log.e("DataLayerSync", "Sync error for workout history transaction: $transactionId, error: $errorMessage (attempt $retryAttempt)")
                    
                    // Check if it's a missing chunks error and we can retry
                    if (errorMessage.startsWith("MISSING_CHUNKS:") && retryAttempt < maxRetries) {
                        val missingIndices = parseMissingChunks(errorMessage)
                        if (missingIndices.isNotEmpty()) {
                            // Check if completion was already received before starting retry
                            if (SyncHandshakeManager.hasCompletion(transactionId)) {
                                Log.d("DataLayerSync", "Completion already received before retry for transaction: $transactionId")
                                SyncHandshakeManager.cleanup(transactionId)
                                return true
                            }
                            
                            Log.d("DataLayerSync", "Attempting retry ${retryAttempt + 1} for missing chunks: $missingIndices")
                            try {
                                // Register new waiters for the retry attempt
                                // registerCompletionWaiter now handles race conditions atomically
                                currentCompletionWaiter = SyncHandshakeManager.registerCompletionWaiter(transactionId)
                                currentErrorWaiter = SyncHandshakeManager.registerErrorWaiter(transactionId)
                                
                                // Check immediately after registration if completion was already received
                                // This handles the case where completion arrives between error and retry registration
                                if (currentCompletionWaiter.isCompleted) {
                                    Log.d("DataLayerSync", "Completion already received when registering retry waiter for transaction: $transactionId")
                                    SyncHandshakeManager.cleanup(transactionId)
                                    return true
                                }
                                
                                retryMissingChunks(dataClient, transactionId, missingIndices, chunks)
                                retryAttempt++
                                // Exponential backoff with jitter: 500ms, 1000ms, 2000ms, 4000ms, 8000ms
                                val baseDelay = 500L * (1 shl (retryAttempt - 1))
                                val jitter = (0..200).random().toLong()
                                delay(baseDelay + jitter)
                                Log.d("DataLayerSync", "Retry delay: ${baseDelay + jitter}ms for attempt $retryAttempt")
                                
                                // Check again before continuing loop (completion might have arrived during retry)
                                if (currentCompletionWaiter.isCompleted) {
                                    Log.d("DataLayerSync", "Completion received during retry for transaction: $transactionId")
                                    SyncHandshakeManager.cleanup(transactionId)
                                    return true
                                }
                                
                                continue
                            } catch (retryException: Exception) {
                                Log.e("DataLayerSync", "Retry failed: ${retryException.message}", retryException)
                                SyncHandshakeManager.cleanup(transactionId)
                                return false
                            }
                        }
                    }
                    
                    // Not a retryable error or max retries reached
                    SyncHandshakeManager.cleanup(transactionId)
                    Log.e("DataLayerSync", "Sync failed for workout history transaction: $transactionId after $retryAttempt retry attempts: $errorMessage")
                    return false
                }
            }
        }
        
        // Should not reach here, but handle it anyway
        SyncHandshakeManager.cleanup(transactionId)
        return false
    } catch (cancellationException: CancellationException) {
        SyncHandshakeManager.cleanup(transactionId)
        cancellationException.printStackTrace()
        return false
    } catch(exception: Exception) {
        SyncHandshakeManager.cleanup(transactionId)
        Log.e("DataLayerSync", "Error sending workout history store", exception)
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

/**
 * Parses missing chunk indices from error message
 * Expected format: "MISSING_CHUNKS: Expected 10 chunks, received 7. Missing indices: [2, 5, 7]"
 */
private fun parseMissingChunks(errorMessage: String): List<Int> {
    return try {
        val indicesPattern = Regex("Missing indices: \\[(\\d+(?:, \\d+)*)\\]")
        val match = indicesPattern.find(errorMessage)
        match?.groupValues?.get(1)?.split(", ")?.mapNotNull { it.toIntOrNull() } ?: emptyList()
    } catch (e: Exception) {
        Log.e("DataLayerSync", "Failed to parse missing chunks from error message: $errorMessage", e)
        emptyList()
    }
}

/**
 * Retries sending specific missing chunks
 */
private suspend fun retryMissingChunks(
    dataClient: DataClient,
    transactionId: String,
    missingIndices: List<Int>,
    chunks: List<ByteArray>
) {
    if (missingIndices.isEmpty()) {
        Log.w("DataLayerSync", "retryMissingChunks called with empty missing indices list")
        return
    }

    Log.d("DataLayerSync", "Retrying ${missingIndices.size} missing chunks for transaction: $transactionId, indices: $missingIndices")

    // Send missing chunks one by one
    missingIndices.forEachIndexed { retryIndex, chunkIndex ->
        if (chunkIndex < 0 || chunkIndex >= chunks.size) {
            Log.e("DataLayerSync", "Invalid chunk index in retry: $chunkIndex (total chunks: ${chunks.size})")
            return@forEachIndexed
        }

        val chunk = chunks[chunkIndex]
        val isLastRetryChunk = retryIndex == missingIndices.size - 1

        val chunkPath = DataLayerPaths.buildPath(
            DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX,
            transactionId,
            chunkIndex
        )
        val request = PutDataMapRequest.create(chunkPath).apply {
            dataMap.putByteArray("chunk", chunk)
            dataMap.putInt("chunkIndex", chunkIndex)
            dataMap.putBoolean("isRetry", true)
            if (isLastRetryChunk) {
                dataMap.putBoolean("isLastRetryChunk", true)
            }
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)

        if (!isLastRetryChunk) {
            delay(500)
        }
    }

    // Small delay after last retry chunk
    delay(100)
    Log.d("DataLayerSync", "Finished sending retry chunks for transaction: $transactionId")
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

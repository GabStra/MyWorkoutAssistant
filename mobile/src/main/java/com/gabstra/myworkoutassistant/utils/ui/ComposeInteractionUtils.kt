package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.equipmentToJSON
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutPlanMarkdown
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.CancellationException
import java.text.SimpleDateFormat
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.pow
import kotlin.math.roundToInt
import java.security.MessageDigest

// Default height for the content fade gradient
private val DEFAULT_CONTENT_FADE_HEIGHT = 10.dp

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MediumDarkGray
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onBackground
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.background
    // Remember updated state for all parameters accessed within draw lambda
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
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

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            if (rememberedShowTrack) {
                drawRoundRect(
                    color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                    topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                    size = Size(barWidthPx, actualTrackHeight),
                    cornerRadius = cornerRadius
                )
            }

            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
                size = Size(barWidthPx, scrollBarHeight),
                cornerRadius = cornerRadius
            )
        }
    }
}

@Composable
fun Modifier.verticalLazyColumnScrollbar(
    lazyListState: LazyListState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MediumDarkGray
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onSurfaceVariant
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.background
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
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

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        if (fadeHeightPx > 0f) {
            // --- Top Fade Calculation ---
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

            // --- Bottom Fade Calculation ---
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

        // --- Scrollbar Logic ---
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue
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
        val maxThumbHeight = actualTrackHeight * rememberedMaxThumbHeightFraction.coerceIn(0f, 1f)
        val computedThumbHeight = visibleRatio * actualTrackHeight
        val scrollBarHeight = computedThumbHeight
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(maxThumbHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        // Only draw scrollbar if alpha > 0
        if (scrollbarAlpha > 0f) {
            if (rememberedShowTrack) {
                drawRoundRect(
                    color = rememberedTrackColor.copy(alpha = scrollbarAlpha),
                    topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                    size = Size(barWidthPx, actualTrackHeight),
                    cornerRadius = cornerRadius
                )
            }

            drawRoundRect(
                color = rememberedScrollBarColor.copy(alpha = scrollbarAlpha),
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
                size = Size(barWidthPx, scrollBarHeight),
                cornerRadius = cornerRadius
            )
        }
    }
}

fun ensureRestSeparatedBySets(components: List<com.gabstra.myworkoutassistant.shared.sets.Set>): List<com.gabstra.myworkoutassistant.shared.sets.Set> {
    val adjustedComponents = mutableListOf<Set>()
    var lastWasSet = false

    for (component in components) {
        if(component !is RestSet) {
            adjustedComponents.add(component)
            lastWasSet = true
        }else{
            if(lastWasSet){
                adjustedComponents.add(component)
            }

            lastWasSet = false
        }
    }
    return adjustedComponents
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if (component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        } else {
            if (lastWasExercise) {
                //check if the next component if exist is exercise and enabled
                val nextComponentIndex = components.indexOf(component) + 1
                if (nextComponentIndex < components.size) {
                    val nextComponent = components[nextComponentIndex]
                    if (nextComponent.enabled) {
                        adjustedComponents.add(component)
                    } else {
                        adjustedComponents.add(component.copy(enabled = false))
                    }
                }
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}

fun dateRangeFor(range: FilterRange): Pair<LocalDate, LocalDate> {
    val today = LocalDate.now()

    return when (range) {
        FilterRange.LAST_WEEK -> {
            val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val lastMonday = thisMonday.minusWeeks(1)
            val lastSunday = lastMonday.plusDays(6)
            lastMonday to lastSunday
        }
        FilterRange.LAST_7_DAYS -> {
            val start = today.minusDays(6)
            start to today
        }
        FilterRange.LAST_30_DAYS -> {
            val start = today.minusDays(29)
            start to today
        }
        FilterRange.THIS_MONTH -> {
            val ym = YearMonth.now()
            ym.atDay(1) to ym.atEndOfMonth()
        }
        FilterRange.LAST_3_MONTHS -> {
            val start = today.minusMonths(3)
            start to today
        }
        FilterRange.ALL -> LocalDate.MIN to LocalDate.MAX
    }
}

fun List<WorkoutHistory>.filterBy(range: FilterRange): List<WorkoutHistory> {
    val (start, end) = dateRangeFor(range)
    return this.filter { it.date >= start && it.date <= end }
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

suspend fun exportExerciseHistoryToMarkdown(
    context: Context,
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore
) {
    try {
        when (val result = buildExerciseHistoryMarkdown(
            exercise = exercise,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workouts = workouts,
            workoutStore = workoutStore
        )) {
            is ExerciseHistoryMarkdownResult.Success -> {
                val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
                val timestamp = sdf.format(Date())
                val sanitizedName = exercise.name.replace(Regex("[^a-zA-Z0-9]"), "_").take(50)
                val filename = "exercise_history_${sanitizedName}_$timestamp.md"
                writeMarkdownToDownloadsFolder(context, filename, result.markdown)
            }
            is ExerciseHistoryMarkdownResult.Failure -> {
                withContext(Dispatchers.Main) {
                    Toast.makeText(context, result.message, Toast.LENGTH_SHORT).show()
                }
            }
        }
    } catch (e: Exception) {
        Log.e("ExerciseExport", "Error exporting exercise history", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun exportWorkoutPlanToMarkdown(
    context: Context,
    workoutStore: WorkoutStore
) {
    try {
        val markdown = buildWorkoutPlanMarkdown(workoutStore)
        val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
        val timestamp = sdf.format(Date())
        val filename = "workout_plan_export_$timestamp.md"
        writeMarkdownToDownloadsFolder(context, filename, markdown)
    } catch (e: Exception) {
        Log.e("WorkoutPlanExport", "Error exporting workout plan", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun exportEquipmentToDownloads(
    context: Context,
    workoutStore: WorkoutStore
): String {
    return withContext(Dispatchers.IO) {
        try {
            val equipments = workoutStore.equipments
            val accessoryEquipments = workoutStore.accessoryEquipments
            val jsonString = equipmentToJSON(equipments, accessoryEquipments)
            
            val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
            val timestamp = sdf.format(Date())
            val filename = "equipment_$timestamp.json"
            writeJsonToDownloadsFolder(context, filename, jsonString)
            
            filename
        } catch (e: Exception) {
            Log.e("EquipmentExport", "Error exporting equipment", e)
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
            throw e
        }
    }
}


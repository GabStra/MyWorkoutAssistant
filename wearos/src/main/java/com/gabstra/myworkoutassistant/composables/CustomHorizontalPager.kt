package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.isSpecified
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.lerp
import androidx.wear.compose.foundation.ExperimentalWearFoundationApi
import androidx.wear.compose.foundation.LocalReduceMotion
import androidx.wear.compose.foundation.pager.HorizontalPager
import androidx.wear.compose.foundation.pager.PagerDefaults
import androidx.wear.compose.foundation.pager.PagerState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.HorizontalPageIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.absoluteValue


@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun ClippedBox(pagerState: PagerState, content: @Composable () -> Unit) {
    val shape = rememberClipWhenScrolling(pagerState)
    Box(
        modifier = Modifier
            .fillMaxSize()
    ) {
        content()
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun rememberClipWhenScrolling(state: PagerState): State<RoundedCornerShape?> {
    val shape = if (LocalConfiguration.current.isScreenRound) CircleShape else null
    return remember(state) {
        derivedStateOf {
            if (shape != null && state.currentPageOffsetFraction != 0f) {
                shape
            } else {
                null
            }
        }
    }
}

private fun Modifier.optionalClip(shapeState: State<RoundedCornerShape?>): Modifier {
    val shape = shapeState.value

    return if (shape != null) {
        clip(shape)
    } else {
        this
    }
}

fun getPageTransitionFraction(
    isCurrentPage: Boolean,
    currentPageOffsetFraction: Float,
): Float {
    return if (isCurrentPage) {
        currentPageOffsetFraction.absoluteValue
    } else {
        // interpolate left or right pages in opposite direction
        1 - currentPageOffsetFraction.absoluteValue
    }
}

@Composable
fun CustomAnimatedPage(
    pageIndex: Int,
    pagerState: PagerState,
    contentScrimColor: Color = Color.Unspecified,
    content: @Composable (() -> Unit),
) {
    val isReduceMotionEnabled = LocalReduceMotion.current
    val isRtlEnabled = LocalLayoutDirection.current == LayoutDirection.Rtl

    val graphicsLayerModifier =
        if (isReduceMotionEnabled) Modifier
        else
            Modifier.graphicsLayer {
                val direction = if (isRtlEnabled) -1 else 1
                val signedOffset = direction * pagerState.currentPageOffsetFraction
                val pageOffset = ((pagerState.currentPage - pageIndex) + signedOffset)
                    .absoluteValue
                    .coerceIn(0f, 1f)
                val scale = lerp(start = 1f, stop = 0.9f, fraction = pageOffset)
                scaleX = scale
                scaleY = scale
            }
    val pageModifier =
        if (!contentScrimColor.isSpecified) {
            graphicsLayerModifier
        } else {
            graphicsLayerModifier.drawWithContent {
                drawContent()
                val isCurrentPage: Boolean = pageIndex == pagerState.currentPage
                val pageTransitionFraction =
                    getPageTransitionFraction(isCurrentPage, pagerState.currentPageOffsetFraction)
                val color =
                    contentScrimColor.copy(
                        alpha = lerp(start = 0f, stop = 0.35f, fraction = pageTransitionFraction)
                    )
                drawCircle(color = color)
            }
        }

    Box(modifier = pageModifier) {
        content()
    }
}

private const val PAGER_INDICATOR_HIDE_DELAY_MS = 2500L
private const val PAGER_INDICATOR_FADE_DURATION_MS = 250

@OptIn(ExperimentalWearFoundationApi::class)
@Composable
fun CustomHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
    animatePages: Boolean = true,
    beyondViewportPageCount: Int = 1,
    pageContentPadding: PaddingValues = PaddingValues(),
    movingPlaceholder: (@Composable BoxScope.() -> Unit)? = null,
    pageOverlay: (@Composable BoxScope.(Int) -> Unit)? = null,
    content: @Composable (Int) -> Unit
) {
    var indicatorVisible by remember { mutableStateOf(true) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val scope = rememberWearCoroutineScope()
    val indicatorAlpha by animateFloatAsState(
        targetValue = if (indicatorVisible) 1f else 0f,
        animationSpec = tween(durationMillis = PAGER_INDICATOR_FADE_DURATION_MS),
        label = "pager_indicator"
    )

    LaunchedEffect(pagerState.currentPage, pagerState.isScrollInProgress) {
        indicatorVisible = true
        hideTimeoutJob?.cancel()
        if (!pagerState.isScrollInProgress) {
            hideTimeoutJob = scope.launch {
                delay(PAGER_INDICATOR_HIDE_DELAY_MS)
                indicatorVisible = false
            }
        }
    }

    Box(modifier = modifier) {
        // Skip pager when there's only a single page
        if (pagerState.pageCount == 1) {
            Box(modifier = Modifier.fillMaxSize()) {
                pageOverlay?.invoke(this, 0)
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(pageContentPadding)
                ) {
                    content(0)
                }
            }
        } else {
            HorizontalPager(
                state = pagerState,
                modifier = Modifier.fillMaxSize(),
                flingBehavior = PagerDefaults.snapFlingBehavior(state = pagerState),
                userScrollEnabled = userScrollEnabled,
                beyondViewportPageCount = beyondViewportPageCount,
            ) { page ->
                val isMoving =
                    pagerState.isScrollInProgress || pagerState.currentPageOffsetFraction != 0f
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                ) {
                    if (isMoving && movingPlaceholder != null) {
                        Box(modifier = Modifier.fillMaxSize()) {
                            movingPlaceholder()
                        }
                    } else if (animatePages) {
                        CustomAnimatedPage(
                            pageIndex = page,
                            pagerState = pagerState
                        ) {
                            Box(modifier = Modifier.fillMaxSize()) {
                                pageOverlay?.invoke(this, page)
                                Box(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(pageContentPadding)
                                ) {
                                    content(page)
                                }
                            }
                        }
                    } else {
                        Box(modifier = Modifier.fillMaxSize()) {
                            pageOverlay?.invoke(this, page)
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .padding(pageContentPadding)
                            ) {
                                content(page)
                            }
                        }
                    }
                }
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .graphicsLayer { alpha = indicatorAlpha },
                contentAlignment = Alignment.Center
            ) {
                HorizontalPageIndicator(
                    pagerState = pagerState,
                    unselectedColor = MediumDarkGray
                )
            }
        }
    }
}

@Composable
private fun DefaultPagerMovingPlaceholder() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator(
            modifier = Modifier.padding(8.dp),
            colors = ProgressIndicatorDefaults.colors(
                indicatorColor = MaterialTheme.colorScheme.onBackground,
                trackColor = MediumDarkGray
            )
        )
    }
}



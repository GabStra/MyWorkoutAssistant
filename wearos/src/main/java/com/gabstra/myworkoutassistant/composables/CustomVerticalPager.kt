package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.graphicsLayer
import androidx.wear.compose.foundation.ExperimentalWearFoundationApi
import androidx.wear.compose.foundation.pager.PagerDefaults
import androidx.wear.compose.foundation.pager.PagerState
import androidx.wear.compose.foundation.pager.VerticalPager
import androidx.wear.compose.material3.VerticalPageIndicator
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val PAGER_INDICATOR_HIDE_DELAY_MS = 2500L
private const val PAGER_INDICATOR_FADE_DURATION_MS = 250

/**
 * Vertical pager with animated page transitions and a vertically oriented page indicator
 * on the right side, vertically centered. The indicator is drawn over the content and
 * auto-hides after a short delay.
 *
 * Can be nested with [CustomHorizontalPager]: use a separate [PagerState] per pager and pass
 * [Modifier.fillMaxSize][androidx.compose.ui.Modifier.fillMaxSize] to the inner pager so it
 * fills the outer page.
 */
@OptIn(ExperimentalWearFoundationApi::class)
@Composable
fun CustomVerticalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
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

    LaunchedEffect(pagerState.currentPage) {
        indicatorVisible = true
        hideTimeoutJob?.cancel()
        hideTimeoutJob = scope.launch {
            delay(PAGER_INDICATOR_HIDE_DELAY_MS)
            indicatorVisible = false
        }
    }

    Box(modifier = modifier) {
        // Skip pager when there's only a single page
        if (pagerState.pageCount == 1) {
            content(0)
        } else {
            VerticalPager(
                state = pagerState,
                modifier = Modifier.fillMaxSize().clip(RectangleShape),
                flingBehavior = PagerDefaults.snapFlingBehavior(state = pagerState),
                userScrollEnabled = userScrollEnabled
            ) { page ->
                CustomAnimatedPage(pageIndex = page, pagerState = pagerState) {
                    content(page)
                }
            }
            Box(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .graphicsLayer { alpha = indicatorAlpha },
                contentAlignment = Alignment.CenterEnd
            ) {
                VerticalPageIndicator(
                    pagerState = pagerState,
                    unselectedColor = MediumDarkGray
                )
            }
        }
    }
}

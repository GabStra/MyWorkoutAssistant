package com.gabstra.myworkoutassistant.workout

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.PagerDefaults
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val PAGER_INDICATOR_HIDE_DELAY_MS = 2500L
private const val PAGER_INDICATOR_FADE_DURATION_MS = 250

/**
 * Vertical pager with a vertically oriented page indicator on the right side,
 * vertically centered. The indicator is drawn over the content and auto-hides
 * after a short delay.
 *
 * Can be nested with [CustomHorizontalPager]: use a separate [PagerState] per pager and pass
 * [Modifier.fillMaxSize][androidx.compose.ui.Modifier.fillMaxSize] to the inner pager so it
 * fills the outer page.
 */
@Composable
fun CustomVerticalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
    content: @Composable (Int) -> Unit
) {
    var indicatorVisible by remember { mutableStateOf(true) }
    var hideTimeoutJob by remember { mutableStateOf<Job?>(null) }
    val scope = rememberCoroutineScope()
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
                modifier = Modifier.fillMaxSize(),
                state = pagerState,
                flingBehavior = PagerDefaults.flingBehavior(state = pagerState),
                userScrollEnabled = userScrollEnabled
            ) { page ->
                content(page)
            }

            Box(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(start = 8.dp)
                    .graphicsLayer { alpha = indicatorAlpha }
            ) {
                Column(
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    repeat(pagerState.pageCount) { index ->
                        val selected = pagerState.currentPage == index
                        Box(
                            modifier = Modifier
                                .padding(3.dp)
                                .size(if (selected) 15.dp else 12.dp)
                                .clip(CircleShape)
                                .background(
                                    if (selected) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f)
                                )
                        )
                    }
                }
            }
        }
    }
}

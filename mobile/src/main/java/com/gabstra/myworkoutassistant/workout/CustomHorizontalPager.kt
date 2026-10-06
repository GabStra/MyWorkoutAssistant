package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerDefaults
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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

private val PagerNavigationReservedHeight = 52.dp

@Composable
fun CustomHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
    beyondViewportPageCount: Int = 0,
    pageLabel: ((Int) -> String)? = null,
    content: @Composable (Int) -> Unit
) {
    val scope = rememberCoroutineScope()

    Box(modifier = modifier) {
        // Skip pager when there's only a single page
        if (pagerState.pageCount == 1) {
            content(0)
        } else {
            HorizontalPager(
                modifier = Modifier.fillMaxSize(),
                state = pagerState,
                flingBehavior = PagerDefaults.flingBehavior(state = pagerState),
                userScrollEnabled = userScrollEnabled,
                beyondViewportPageCount = beyondViewportPageCount,
            ) { page ->
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(bottom = PagerNavigationReservedHeight)
                ) {
                    content(page)
                }
            }

            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 6.dp)
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    pageLabel?.let { resolveLabel ->
                        Text(
                            text = resolveLabel(pagerState.currentPage).uppercase(),
                            modifier = Modifier.width(180.dp),
                            style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center,
                            maxLines = 1,
                        )
                    }
                    Row(
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        repeat(pagerState.pageCount) { index ->
                            val selected = pagerState.currentPage == index
                            Box(
                                Modifier
                                    .padding(2.dp)
                                    .size(9.dp)
                                    .graphicsLayer {
                                        val selectedScale = if (selected) 1.25f else 1f
                                        scaleX = selectedScale
                                        scaleY = selectedScale
                                    }
                                    .clip(CircleShape)
                                    .background(
                                        if (selected) MaterialTheme.colorScheme.primary
                                        else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f)
                                    )
                                    .clickable {
                                        scope.launch {
                                            pagerState.animateScrollToPage(index)
                                        }
                                    }
                            )
                        }
                    }
                }
            }
        }
    }
}




package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.TransformOrigin
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
import androidx.wear.compose.foundation.pager.PagerState
import androidx.wear.compose.material3.HorizontalPageIndicator
import androidx.wear.compose.material3.HorizontalPagerScaffold
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumGray
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
    val orientation = remember(pagerState) { pagerState.layoutInfo.orientation }
    val configuration = LocalConfiguration.current
    val screenDp = if (orientation == Orientation.Horizontal)
        configuration.screenWidthDp
    else
        configuration.screenHeightDp

    val numberOfIntervals = remember(orientation, screenDp) { screenDp / 2 }

    val currentPageOffsetFraction by
    remember(pagerState, numberOfIntervals) {
        derivedStateOf {
            (pagerState.currentPageOffsetFraction * numberOfIntervals).toInt() /
                    numberOfIntervals.toFloat()
        }
    }

    val graphicsLayerModifier =
        if (isReduceMotionEnabled) Modifier
        else
            Modifier.graphicsLayer {
                val direction = if (isRtlEnabled) -1 else 1
                val offsetFraction = currentPageOffsetFraction
                val isSwipingRightToLeft = direction * offsetFraction > 0
                val isSwipingLeftToRight = direction * offsetFraction < 0
                val isCurrentPage: Boolean = pageIndex == pagerState.currentPage
                val shouldAnchorRight =
                    (isSwipingRightToLeft && isCurrentPage) ||
                            (isSwipingLeftToRight && !isCurrentPage)
                val pivotFractionX = if (shouldAnchorRight) 1f else 0f
                transformOrigin =
                    if (pagerState.layoutInfo.orientation == Orientation.Horizontal) {
                        TransformOrigin(pivotFractionX, 0.5f)
                    } else {
                        // Flip X and Y for vertical pager
                        TransformOrigin(0.5f, pivotFractionX)
                    }
                val pageTransitionFraction =
                    getPageTransitionFraction(isCurrentPage, offsetFraction)
                val scale = lerp(start = 1f, stop = 0.55f, fraction = pageTransitionFraction)
                scaleX = scale
                scaleY = scale
            }
    Box(
        modifier =
            graphicsLayerModifier
                .drawWithContent {
                    drawContent()
                    if (contentScrimColor.isSpecified) {
                        val isCurrentPage: Boolean = pageIndex == pagerState.currentPage

                        val pageTransitionFraction =
                            getPageTransitionFraction(isCurrentPage, currentPageOffsetFraction)
                        val color =
                            contentScrimColor.copy(
                                alpha =
                                    lerp(start = 0f, stop = 0.5f, fraction = pageTransitionFraction)
                            )

                        drawCircle(color = color)
                    }
                }
    ) {
        content()
    }
}

@OptIn(ExperimentalWearFoundationApi::class)
@Composable
fun CustomHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
    content: @Composable (Int) -> Unit
) {
    HorizontalPagerScaffold(
        modifier = modifier,
        pagerState = pagerState,
        pageIndicator = {
            HorizontalPageIndicator(
                pagerState = pagerState,
                unselectedColor = MediumGray
            )
        }
    ) {
        HorizontalPager(
            state = pagerState,
            modifier = Modifier.fillMaxSize().padding(bottom = 20.dp).clip(RectangleShape),
            userScrollEnabled = userScrollEnabled,
        ) { page ->
            CustomAnimatedPage(pageIndex = page, pagerState = pagerState) {
                content(page)
            }
        }
    }
}



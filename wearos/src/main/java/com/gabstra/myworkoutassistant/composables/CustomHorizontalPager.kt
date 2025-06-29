package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.ExperimentalWearFoundationApi
import androidx.wear.compose.foundation.HierarchicalFocusCoordinator
import androidx.wear.compose.material.HorizontalPageIndicator
import androidx.wear.compose.material.PageIndicatorStyle
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.google.android.horologist.compose.pager.PageScreenIndicatorState


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

@OptIn(ExperimentalWearFoundationApi::class)
@Composable
fun CustomHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    userScrollEnabled: Boolean = true,
    content: @Composable (Int) -> Unit
) {
    val pageIndicatorState = remember(pagerState) { PageScreenIndicatorState(pagerState) }

    Box(modifier = modifier) {
        HorizontalPager(
            modifier = Modifier.fillMaxSize().padding(bottom = 10.dp),
            state = pagerState,
            userScrollEnabled = userScrollEnabled,
        ) { page ->
            HierarchicalFocusCoordinator(requiresFocus = { page == pagerState.currentPage }) {
                content(page)
            }
        }

        HorizontalPageIndicator(
            modifier = Modifier.align(Alignment.BottomCenter),
            indicatorStyle = PageIndicatorStyle.Linear,
            pageIndicatorState = pageIndicatorState,
            selectedColor = LightGray,
            unselectedColor = MediumGray
        )
    }
}



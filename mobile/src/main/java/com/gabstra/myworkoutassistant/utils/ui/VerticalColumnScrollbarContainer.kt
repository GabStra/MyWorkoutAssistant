package com.gabstra.myworkoutassistant

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun Modifier.verticalColumnScrollbarContainer(
    scrollState: ScrollState,
    enabled: Boolean = true,
): Modifier = this
    .verticalColumnScrollbar(scrollState)
    .verticalScroll(scrollState, enabled = enabled)
    .padding(horizontal = Spacing.md)

/**
 * Same as [verticalColumnScrollbarContainer] for scrollable columns, but for a [LazyListState]
 * (use on [androidx.compose.foundation.lazy.LazyColumn]). Applies [verticalLazyColumnScrollbar]
 * plus the same horizontal padding as the [ScrollState] variant.
 */
@Composable
fun Modifier.verticalColumnScrollbarContainer(
    lazyListState: LazyListState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = 10.dp,
    contentFadeColor: Color? = null,
): Modifier = this
    .verticalLazyColumnScrollbar(
        lazyListState = lazyListState,
        width = width,
        showScrollBarTrack = showScrollBarTrack,
        scrollBarTrackColor = scrollBarTrackColor,
        scrollBarColor = scrollBarColor,
        scrollBarCornerRadius = scrollBarCornerRadius,
        endPadding = endPadding,
        trackHeight = trackHeight,
        maxThumbHeightFraction = maxThumbHeightFraction,
        enableTopFade = enableTopFade,
        enableBottomFade = enableBottomFade,
        contentFadeHeight = contentFadeHeight,
        contentFadeColor = contentFadeColor,
    )
    .padding(horizontal = Spacing.md)

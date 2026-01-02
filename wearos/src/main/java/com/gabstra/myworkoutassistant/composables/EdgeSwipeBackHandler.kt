package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.abs

@Composable
fun EdgeSwipeBackHandler(
    enabled: Boolean,
    edgeWidth: Dp = 24.dp,
    swipeThreshold: Dp = 64.dp,
    onSwipe: () -> Unit,
    content: @Composable () -> Unit
) {
    val density = LocalDensity.current
    val edgeWidthPx = with(density) { edgeWidth.toPx() }
    val thresholdPx = with(density) { swipeThreshold.toPx() }
    val currentOnSwipe by rememberUpdatedState(onSwipe)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(enabled, edgeWidthPx, thresholdPx) {
                if (!enabled) return@pointerInput
                awaitPointerEventScope {
                    while (true) {
                        val down = awaitFirstDown(requireUnconsumed = false)
                        if (down.position.x > edgeWidthPx) continue

                        var totalX = 0f
                        var totalY = 0f
                        val pointerId = down.id

                        while (true) {
                            val event = awaitPointerEvent()
                            val change = event.changes.firstOrNull { it.id == pointerId } ?: break
                            if (!change.pressed) break

                            val delta = change.position - change.previousPosition
                            totalX += delta.x
                            totalY += delta.y

                            if (totalX > thresholdPx && abs(totalX) > abs(totalY)) {
                                change.consume()
                                currentOnSwipe()
                                break
                            }
                        }
                    }
                }
            }
    ) {
        content()
    }
}

package com.gabstra.myworkoutassistant.composables

import android.view.MotionEvent
import android.view.ViewParent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.platform.LocalView

@Composable
private fun rememberChartTouchInteropHandler(
    parentView: ViewParent?,
    onInteractionChange: ((Boolean) -> Unit)?,
): (MotionEvent) -> Boolean {
    var isParentInterceptBlocked by remember { mutableStateOf(false) }

    return remember(parentView, onInteractionChange) {
        { motionEvent ->
            when (motionEvent.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    isParentInterceptBlocked = false
                    onInteractionChange?.invoke(false)
                }

                MotionEvent.ACTION_MOVE -> {
                    if (!isParentInterceptBlocked) {
                        parentView?.requestDisallowInterceptTouchEvent(true)
                        isParentInterceptBlocked = true
                    }
                    onInteractionChange?.invoke(true)
                }

                MotionEvent.ACTION_UP,
                MotionEvent.ACTION_CANCEL -> {
                    if (isParentInterceptBlocked) {
                        parentView?.requestDisallowInterceptTouchEvent(false)
                        isParentInterceptBlocked = false
                    }
                    onInteractionChange?.invoke(false)
                }
            }
            false
        }
    }
}

internal fun Modifier.chartTouchInterop(
    onInteractionChange: ((Boolean) -> Unit)? = null,
): Modifier = composed {
    val parentView = LocalView.current.parent
    val touchHandler = rememberChartTouchInteropHandler(
        parentView = parentView,
        onInteractionChange = onInteractionChange,
    )
    pointerInteropFilter(onTouchEvent = touchHandler)
}

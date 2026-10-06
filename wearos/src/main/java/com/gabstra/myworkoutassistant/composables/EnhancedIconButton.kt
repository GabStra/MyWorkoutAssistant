package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.FilledTonalIconButton
import androidx.wear.compose.material3.IconButtonColors
import androidx.wear.compose.material3.IconButtonDefaults

@Composable
fun EnhancedIconButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    buttonModifier: Modifier = Modifier,
    enabled: Boolean = true,
    colors: IconButtonColors = IconButtonDefaults.filledTonalIconButtonColors(),
    buttonSize: Dp = 48.dp,
    hitBoxScale: Float = 1.5f,
    content: @Composable () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val hitBoxSize = remember(buttonSize, hitBoxScale) {
        buttonSize * hitBoxScale
    }

    Box(
        modifier = modifier
            .size(hitBoxSize)
            .pointerInput(enabled) {
                awaitEachGesture {
                    // Observe the complete tap before the child visual button consumes it.
                    val down = awaitFirstDown(
                        requireUnconsumed = false,
                        pass = PointerEventPass.Initial
                    )
                    val press = PressInteraction.Press(down.position)
                    interactionSource.tryEmit(press)
                    val up = waitForUpOrCancellation(pass = PointerEventPass.Initial)
                    interactionSource.tryEmit(PressInteraction.Release(press))
                    if (enabled && up != null) {
                        onClick()
                    }
                }
            }
    ) {
        FilledTonalIconButton(
            onClick = { /* The expanded parent hit target owns the action. */ },
            modifier = buttonModifier
                .size(buttonSize)
                .align(Alignment.Center),
            enabled = enabled,
            colors = colors,
            interactionSource = interactionSource
        ) {
            content()
        }
    }
}

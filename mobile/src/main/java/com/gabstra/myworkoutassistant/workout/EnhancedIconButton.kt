package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.IconButtonColors
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

@Composable
fun EnhancedIconButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    buttonModifier: Modifier = Modifier,
    enabled: Boolean = true,
    colors: IconButtonColors? = null,
    buttonSize: Dp = 48.dp,  // Default button size
    hitBoxScale: Float = 1.5f,
    content: @Composable () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val hitBoxSize = remember(buttonSize, hitBoxScale) {
        buttonSize * hitBoxScale
    }
    val defaultColors = IconButtonDefaults.filledTonalIconButtonColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    val buttonColors = colors ?: defaultColors

    Box(
        modifier = modifier
            .size(hitBoxSize)
            .pointerInput(enabled) {
                coroutineScope {
                    awaitEachGesture {
                        val down = awaitFirstDown()
                        val press = PressInteraction.Press(down.position)
                        launch { interactionSource.emit(press) }
                        if (enabled) {
                            onClick()
                        }
                        waitForUpOrCancellation()
                        launch { interactionSource.emit(PressInteraction.Release(press)) }
                    }
                }
            }
    ) {
        FilledTonalIconButton(
            onClick = { /* Handled by Box */ },
            modifier = buttonModifier
                .size(buttonSize)
                .align(Alignment.Center),
            enabled = enabled,
            colors = buttonColors,
            interactionSource = interactionSource
        ) {
            content()
        }
    }
}

package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonColors
import androidx.wear.compose.material.ButtonDefaults
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

@Composable
fun EnhancedButton(
    onClick: () -> Unit,
    boxModifier: Modifier = Modifier,
    buttonModifier: Modifier = Modifier,
    enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.primaryButtonColors(),
    buttonSize: Dp = 48.dp,  // Default button size
    hitBoxScale: Float = 1.5f,
    content: @Composable () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val hitBoxSize = remember(buttonSize, hitBoxScale) {
        buttonSize * hitBoxScale
    }

    Box(
        modifier = boxModifier
            .size(hitBoxSize)
            .pointerInput(enabled) {
                coroutineScope {
                    while (true) {
                        val event = awaitPointerEventScope {
                            awaitPointerEvent()
                        }
                        when {
                            event.changes.any { it.pressed } -> {
                                launch {
                                    interactionSource.emit(PressInteraction.Press(event.changes.first().position))
                                    if (enabled) onClick()
                                }
                            }
                            event.changes.any { !it.pressed } -> {
                                launch {
                                    interactionSource.emit(PressInteraction.Release(PressInteraction.Press(event.changes.first().position)))
                                }
                            }
                        }
                    }
                }
            }
    ) {
        Button(
            onClick = { /* Handled by Box */ },
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
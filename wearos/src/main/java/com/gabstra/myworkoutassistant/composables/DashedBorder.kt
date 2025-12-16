package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * A custom Modifier extension to draw a dashed border around a Composable.
 *
 * @param strokeWidth The width of the border.
 * @param color The color of the border.
 * @param shape The shape of the border (e.g., RectangleShape, RoundedCornerShape).
 * @param onInterval The length of the dash segment in Dp.
 * @param offInterval The length of the gap segment in Dp.
 * @param phase The offset into the dash pattern, in Dp.
 */
fun Modifier.dashedBorder(
    strokeWidth: Dp,
    color: Color,
    shape: Shape,
    onInterval: Dp,
    offInterval: Dp,
    phase: Dp = 0.dp
): Modifier = composed {
    val density = LocalDensity.current
    val strokeWidthPx = density.run { strokeWidth.toPx() }
    val onIntervalPx = density.run { onInterval.toPx() }
    val offIntervalPx = density.run { offInterval.toPx() }
    val phasePx = density.run { phase.toPx() }

    this.then(
        Modifier.drawWithCache {
            onDrawWithContent {
                // Draw the content of the Composable first
                drawContent()

                // Then draw the dashed border on top
                val outline = shape.createOutline(size, layoutDirection, this)

                val stroke = Stroke(
                    width = strokeWidthPx,
                    pathEffect = PathEffect.dashPathEffect(
                        intervals = floatArrayOf(onIntervalPx, offIntervalPx),
                        phase = phasePx
                    )
                )

                drawOutline(
                    outline = outline,
                    color = color,
                    style = stroke
                )
            }
        }
    )
}


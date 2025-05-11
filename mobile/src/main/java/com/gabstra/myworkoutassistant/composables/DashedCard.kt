package com.gabstra.myworkoutassistant.composables


import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.ui.theme.DarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray

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
    shape: Shape = RectangleShape,
    onInterval: Dp,
    offInterval: Dp,
    phase: Dp = 0.dp // Added phase parameter for more control, defaulting to 0
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

@Composable
fun DashedCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    // Define dash properties in Dp
    val dashOnInterval = 4.dp
    val dashOffInterval = 4.dp
    val borderWidth = 1.dp

    Box(
        modifier = modifier
            .background(DarkGray)
            .dashedBorder(
                strokeWidth = borderWidth,
                color = MediumGray,
                onInterval = dashOnInterval,
                offInterval = dashOffInterval
                // You can also specify a shape, e.g., RoundedCornerShape(8.dp)
                // shape = RoundedCornerShape(8.dp)
            )
            .wrapContentSize(), // Adjusts the Box size to its content
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}
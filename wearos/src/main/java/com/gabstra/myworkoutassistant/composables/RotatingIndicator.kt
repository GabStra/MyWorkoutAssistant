package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

@Composable
fun RotatingIndicator(rotationAngle: Float, fillColor: Color, reverse: Boolean = false) {
    val bubbleSize = 10.dp

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val wPx = constraints.maxWidth.toFloat()
        val hPx = constraints.maxHeight.toFloat()
        val bubblePx = with(density) { bubbleSize.toPx() }

        val cx = wPx / 2f
        val cy = hPx / 2f
        val rx = cx - bubblePx / 2f
        val ry = cy - bubblePx / 2f

        val rad = Math.toRadians(rotationAngle.toDouble())
        val x = cx + rx * cos(rad).toFloat()
        val y = cy + ry * sin(rad).toFloat()

        Box(
            modifier = Modifier
                .offset { IntOffset((x - bubblePx / 2f).roundToInt(), (y - bubblePx / 2f).roundToInt()) }
                .size(bubbleSize)
                .clip(CircleShape)
                //.background(MaterialTheme.colorScheme.background)
        ) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val r = size.minDimension * 0.35f
                val c = Offset(size.width / 2f, size.height / 2f)
                val dy = -r / 3f // shift up so centroid = c

                val triangle = Path().apply {
                    moveTo(c.x, c.y - r + dy)      // apex
                    lineTo(c.x + r, c.y + r + dy)  // base right
                    lineTo(c.x - r, c.y + r + dy)  // base left
                    close()
                }

                val extra = if (reverse) 180f else 0f
                rotate(degrees = rotationAngle + 90f + extra, pivot = c) {
                    drawPath(path = triangle, color = fillColor)
                }
            }
        }
    }
}

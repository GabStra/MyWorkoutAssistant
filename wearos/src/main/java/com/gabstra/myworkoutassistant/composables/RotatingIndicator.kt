package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun RotatingIndicator(rotationAngle: Float, fillColor: Color) {
    val density = LocalDensity.current.density
    val triangleSize = 6f

    BoxWithConstraints(
        modifier = Modifier.fillMaxSize()
    ) {
        val boxWidth = (constraints.maxWidth/density).dp
        val boxHeight = (constraints.maxHeight/density).dp

        val angleInRadians = Math.toRadians(rotationAngle.toDouble())

        val widthOffset = (constraints.maxWidth/2) - 28
        val heightOffset = (constraints.maxHeight/2) - 28

        val xRadius = ((widthOffset * cos(angleInRadians)) / density).dp
        val yRadius = ((heightOffset * sin(angleInRadians)) / density).dp

        Box(
            modifier = Modifier
                .fillMaxSize()
                .absoluteOffset(
                    x = (boxWidth / 2) - (triangleSize / density).dp + xRadius,
                    y = (boxHeight / 2) - (triangleSize / density).dp + yRadius,
                ),
        ) {
            Canvas(modifier = Modifier.size((triangleSize * 2 / density).dp)) {
                val trianglePath = Path().apply {
                    val height = (triangleSize * 2 / density).dp.toPx()
                    val width = height

                    // Create triangle pointing upward initially
                    moveTo(width / 2, 0f)          // Top point
                    lineTo(width, height * 0.866f) // Bottom right
                    lineTo(0f, height * 0.866f)    // Bottom left
                    close()
                }

                // Calculate rotation to point in direction of movement
                // Add 90 degrees (π/2) because our triangle points up by default
                // and we want it to point in the direction of travel
                val directionAngle = angleInRadians - Math.PI / 2 + Math.PI

                withTransform({
                    rotate(
                        degrees = Math.toDegrees(directionAngle).toFloat(),
                        pivot = center
                    )
                }) {
                    // Draw filled white triangle
                    drawPath(
                        path = trianglePath,
                        color = fillColor
                    )
                }
            }
        }
    }
}
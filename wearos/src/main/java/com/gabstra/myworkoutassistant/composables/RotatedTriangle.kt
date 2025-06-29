package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun RotatedTriangle(
    baseAngleInDegrees: Float,
    triangleSize: Float, // Sets the size of the triangles
    color: Color,
    margin: Float = 0f // Sets the margin around the triangle
) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        // Apply a margin to the canvas size
        val width = size.width - 2 * margin
        val height = size.height - 2 * margin

        // Adjusted center points considering the margin
        val centerX = width / 2 + margin
        val centerY = height / 2 + margin
        val angleInRadians = Math.toRadians(baseAngleInDegrees.toDouble()).toFloat()

        val baseCenterX = centerX + (centerX - triangleSize - margin) * cos(angleInRadians)
        val baseCenterY = centerY + (centerX - triangleSize - margin) * sin(angleInRadians)

        // Calculate the vertices of the triangle
        val tip = Offset(
            centerX + (centerX - margin) * cos(angleInRadians),
            centerY + (centerX - margin) * sin(angleInRadians)
        )
        val leftVertex = Offset(
            baseCenterX + triangleSize * cos(angleInRadians + Math.PI.toFloat() / 2),
            baseCenterY + triangleSize * sin(angleInRadians + Math.PI.toFloat() / 2)
        )
        val rightVertex = Offset(
            baseCenterX + triangleSize * cos(angleInRadians - Math.PI.toFloat() / 2),
            baseCenterY + triangleSize * sin(angleInRadians - Math.PI.toFloat() / 2)
        )

        // Draw the triangle
        drawPath(
            path = Path().apply {
                moveTo(tip.x, tip.y)
                lineTo(leftVertex.x, leftVertex.y)
                lineTo(rightVertex.x, rightVertex.y)
                close()
            },
            color = color
        )
    }
}
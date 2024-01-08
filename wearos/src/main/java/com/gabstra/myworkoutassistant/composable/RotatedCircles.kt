package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun RotatedCircles(
    baseAngleInDegrees: Float,
    circleRadius: Float, // This parameter now sets the size of the circles
    color: Color,
    offsetDegrees: Float
) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        val centerX = size.width / 2
        val centerY = size.height / 2
        Log.d("RotatedCircles", "size.width: ${size.width}, size.height: ${size.height}")
        // Draw three circles with offsets
        for (i in 0..2) {
            // Calculate angle for each circle
            val angleInDegrees = baseAngleInDegrees + i * offsetDegrees
            val angleInRadians = Math.toRadians(angleInDegrees.toDouble()).toFloat()

            // Calculate the position of the circle
            val x = centerX + (centerX-circleRadius) * cos(angleInRadians)
            val y = centerY + (centerX-circleRadius) * sin(angleInRadians)

            // Draw the circle with the given radius (size)
            drawCircle(
                color = color,
                radius = circleRadius,
                center = Offset(x, y)
            )
        }
    }
}
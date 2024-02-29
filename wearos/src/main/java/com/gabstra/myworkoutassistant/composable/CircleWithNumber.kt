package com.gabstra.myworkoutassistant.composable

import android.graphics.Color.*
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin


@Composable
fun CircleWithNumber(
    baseAngleInDegrees: Float,
    circleRadius: Float, // Sets the radius of the circle
    circleColor: Color,
    number: Int, // The number to display inside the circle
    margin: Float = 0f, // Sets the margin around the circle
    transparency: Float = 1f // Alpha value for transparency
) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        val alphaInt = (transparency * 255).roundToInt().coerceIn(0, 255)

        // Apply a margin to the canvas size
        val width = size.width - 2 * margin
        val height = size.height - 2 * margin

        // Adjusted center points considering the margin
        val centerX = width / 2 + margin
        val centerY = height / 2 + margin
        val angleInRadians = Math.toRadians(baseAngleInDegrees.toDouble()).toFloat()

        // Position of the circle's center at the tip of the radius
        val circleCenter = Offset(
            centerX + (centerX - circleRadius - margin) * cos(angleInRadians),
            centerY + (centerX - circleRadius - margin) * sin(angleInRadians)
        )

        // Draw the circle with applied alpha
        drawCircle(
            color = circleColor.copy(alpha = transparency),
            radius = circleRadius,
            center = circleCenter
        )

        // Draw the number inside the circle with applied alpha
        val fontSize = circleRadius * 1.5f
        drawContext.canvas.nativeCanvas.drawText(
            number.toString(),
            circleCenter.x,
            circleCenter.y + fontSize / 3, // Adjust to vertically center the text in the circle
            Paint().apply {
                color = android.graphics.Color.BLACK
                alpha = alphaInt // Apply alpha to the Paint object
                textAlign = Paint.Align.CENTER
                textSize = fontSize
                typeface = Typeface.DEFAULT_BOLD
            }
        )
    }
}
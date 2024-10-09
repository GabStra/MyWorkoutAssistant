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
import com.gabstra.myworkoutassistant.data.getContrastRatio
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin


@Composable
fun CircleWithNumber(
    baseAngleInDegrees: Float,
    circleRadius: Float, // Sets the radius of the circle
    circleColor: Color,
    number: Int, // The number to display inside the circle
    transparency: Float = 1f // Alpha value for transparency
) {
    val textColor = if (getContrastRatio(circleColor, Color.Black) > getContrastRatio(circleColor, Color.White)) {
        android.graphics.Color.BLACK
    } else {
        android.graphics.Color.WHITE
    }

    Canvas(modifier = Modifier.fillMaxSize()) {
        val alphaInt = (transparency * 255).roundToInt().coerceIn(0, 255)

        val center = Offset(size.width / 2, size.height / 2)

        val radius = (minOf(size.width, size.height) / 2) +5f - circleRadius / 2

        val angleInRadians = Math.toRadians(baseAngleInDegrees.toDouble()).toFloat()

        // Position of the circle's center at the tip of the radius
        val circleCenter = Offset(
            x = center.x + radius * cos(angleInRadians),
            y = center.y + radius * sin(angleInRadians),
        )

        // Draw the circle with applied alpha
        drawCircle(
            color = circleColor.copy(alpha = transparency),
            radius = circleRadius,
            center = circleCenter
        )

        // Calculate the maximum font size that fits within the circle
        val paint = Paint().apply {
            color = textColor
            alpha = alphaInt // Apply alpha to the Paint object
            textAlign = Paint.Align.CENTER
            typeface = Typeface.MONOSPACE
        }

        var fontSize = circleRadius * 2f
        val textBounds = android.graphics.Rect()
        paint.textSize = fontSize
        paint.getTextBounds(number.toString(), 0, number.toString().length, textBounds)

        // Decrease font size until the text fits within the circle
        while (textBounds.width() > circleRadius * 1.1 || textBounds.height() > circleRadius * 1.1) {
            fontSize -= 1
            paint.textSize = fontSize
            paint.getTextBounds(number.toString(), 0, number.toString().length, textBounds)
        }

        // Adjust the x and y coordinates to center the text within the circle
        val textX = circleCenter.x
        val textY = circleCenter.y + textBounds.height() / 2f

        drawContext.canvas.nativeCanvas.drawText(
            number.toString(),
            textX,
            textY,
            paint
        )
    }
}
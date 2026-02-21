package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.asin
import kotlin.math.PI

@Composable
fun HeightLockedCircularProgressIndicator(
    progress: () -> Float,
    modifier: Modifier = Modifier,
    indicatorColor: Color,
    trackColor: Color,
    strokeWidth: Dp = 4.dp,
    startAngle: Float = 0f,
    endAngle: Float = 360f,
    gapSize: Dp = strokeWidth / 3f,
    keepRadiusFromHeight: Boolean = true
) {
    Canvas(modifier = modifier) {
        val strokePx = strokeWidth.toPx()
        val progressValue = progress().coerceIn(0f, 1f)
        val fullSweep = 360f - ((startAngle - endAngle) % 360f + 360f) % 360f
        if (fullSweep <= 0f) return@Canvas

        val radiusFromHeight = (size.height - strokePx).coerceAtLeast(0f) / 2f
        val radiusFromWidth = (size.width - strokePx).coerceAtLeast(0f) / 2f
        val radius = if (keepRadiusFromHeight) {
            radiusFromHeight
        } else {
            minOf(radiusFromHeight, radiusFromWidth)
        }

        val diameter = radius * 2f
        val topLeft = Offset(
            x = (size.width - diameter) / 2f,
            y = (size.height - diameter) / 2f
        )
        val arcSize = Size(diameter, diameter)
        val progressSweep = fullSweep * progressValue
        val diameterSafe = (diameter - strokePx).coerceAtLeast(1f)
        val gapSweep = ((gapSize.toPx() + strokePx) / (PI.toFloat() * diameterSafe)) * 360f

        drawSegmentArc(
            color = trackColor,
            startAngle = startAngle + progressSweep,
            sweep = fullSweep - progressSweep,
            gapSweep = gapSweep,
            topLeft = topLeft,
            size = arcSize,
            strokeWidthPx = strokePx
        )
        drawSegmentArc(
            color = indicatorColor,
            startAngle = startAngle,
            sweep = progressSweep,
            gapSweep = gapSweep,
            topLeft = topLeft,
            size = arcSize,
            strokeWidthPx = strokePx
        )
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawSegmentArc(
    color: Color,
    startAngle: Float,
    sweep: Float,
    gapSweep: Float,
    topLeft: Offset,
    size: Size,
    strokeWidthPx: Float
) {
    if (sweep <= 0f) return
    val adjustedSweep = (sweep - gapSweep).coerceAtLeast(0f)
    if (adjustedSweep <= 0f) return

    drawArc(
        color = color,
        startAngle = startAngle + (gapSweep / 2f),
        sweepAngle = adjustedSweep,
        useCenter = false,
        topLeft = topLeft,
        size = size,
        style = Stroke(width = strokeWidthPx, cap = StrokeCap.Round)
    )
}

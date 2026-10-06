package com.gabstra.myworkoutassistant.composables

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.running.formatRunningMapScaleDistance
import com.gabstra.myworkoutassistant.shared.running.niceRunningMapScaleDistance
import com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint
import kotlin.math.cos
import kotlin.math.floor

private const val MIN_ZOOM = 1f
private const val MAX_ZOOM = 5f

@Composable
internal fun WearRunningRouteMap(
    route: List<RunningRoutePoint>,
    modifier: Modifier = Modifier,
    backgroundColor: Color,
    gridColor: Color,
    routeColor: Color,
    startColor: Color,
    currentColor: Color,
    labelColor: Color,
) {
    var zoom by remember { mutableFloatStateOf(MIN_ZOOM) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    var mapSize by remember { mutableStateOf(IntSize.Zero) }

    Canvas(
        modifier = modifier
            .fillMaxWidth()
            .height(88.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(backgroundColor)
            .onSizeChanged { mapSize = it }
            .pointerInput(Unit) {
                detectTransformGestures(panZoomLock = true) { centroid, panChange, zoomChange, _ ->
                    val oldZoom = zoom
                    val newZoom = (oldZoom * zoomChange).coerceIn(MIN_ZOOM, MAX_ZOOM)
                    zoom = newZoom
                    pan = centroid - (centroid - pan) * newZoom / oldZoom
                    if (zoomChange == 1f) pan += panChange
                }
            }
            .semantics {
                contentDescription = "Zoomable live GPS route map, ${route.size} route points"
            },
    ) {
        if (route.isEmpty() || mapSize.width <= 0 || mapSize.height <= 0) return@Canvas

        val meanLatitudeRadians = Math.toRadians(route.map { it.latitude }.average())
        val projected = route.map { point ->
            Offset(
                x = (Math.toRadians(point.longitude) * cos(meanLatitudeRadians) * EARTH_RADIUS_METERS).toFloat(),
                y = (Math.toRadians(point.latitude) * EARTH_RADIUS_METERS).toFloat(),
            )
        }
        val minX = projected.minOf { it.x }
        val maxX = projected.maxOf { it.x }
        val minY = projected.minOf { it.y }
        val maxY = projected.maxOf { it.y }
        val routeWidth = (maxX - minX).coerceAtLeast(0.000001f)
        val routeHeight = (maxY - minY).coerceAtLeast(0.000001f)
        val inset = 15.dp.toPx()
        val fitScale = minOf(
            (size.width - inset * 2) / routeWidth,
            (size.height - inset * 2) / routeHeight,
        )
        val fittedWidth = routeWidth * fitScale
        val fittedHeight = routeHeight * fitScale
        val left = (size.width - fittedWidth) / 2f
        val top = (size.height - fittedHeight) / 2f
        val points = projected.map { point ->
            Offset(
                x = left + (point.x - minX) * fitScale,
                y = size.height - top - (point.y - minY) * fitScale,
            )
        }

        translate(pan.x, pan.y) {
            scale(zoom, pivot = Offset.Zero) {
                val gridStep = 36.dp.toPx()
                var x = floor((-pan.x / zoom) / gridStep) * gridStep
                while (x <= (size.width - pan.x) / zoom + gridStep) {
                    drawLine(
                        color = gridColor,
                        start = Offset(x, -pan.y / zoom - gridStep),
                        end = Offset(x, (size.height - pan.y) / zoom + gridStep),
                    )
                    x += gridStep
                }
                var y = floor((-pan.y / zoom) / gridStep) * gridStep
                while (y <= (size.height - pan.y) / zoom + gridStep) {
                    drawLine(
                        color = gridColor,
                        start = Offset(-pan.x / zoom - gridStep, y),
                        end = Offset((size.width - pan.x) / zoom + gridStep, y),
                    )
                    y += gridStep
                }
                points.zipWithNext().forEach { (start, end) ->
                    drawLine(
                        color = routeColor.copy(alpha = 0.22f),
                        start = start,
                        end = end,
                        strokeWidth = 8.dp.toPx(),
                        cap = StrokeCap.Round,
                    )
                    drawLine(
                        color = routeColor,
                        start = start,
                        end = end,
                        strokeWidth = 3.5.dp.toPx(),
                        cap = StrokeCap.Round,
                    )
                }
                drawCircle(backgroundColor, radius = 7.dp.toPx(), center = points.first())
                drawCircle(startColor, radius = 4.5.dp.toPx(), center = points.first())
                if (points.size > 1) {
                    drawCircle(backgroundColor, radius = 7.dp.toPx(), center = points.last())
                    drawCircle(currentColor, radius = 4.5.dp.toPx(), center = points.last())
                }
            }
        }

        if (route.size >= 2) {
            drawRouteScaleBar(
                zoom = zoom,
                fitScalePixelsPerMeter = fitScale,
                routeColor = routeColor,
                backgroundColor = backgroundColor,
                labelColor = labelColor,
            )
        }
    }
}

private const val EARTH_RADIUS_METERS = 6_371_000.0

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawRouteScaleBar(
    zoom: Float,
    fitScalePixelsPerMeter: Float,
    routeColor: Color,
    backgroundColor: Color,
    labelColor: Color,
) {
    val targetBarWidth = size.width * 0.22f
    val targetDistanceMeters = targetBarWidth / (fitScalePixelsPerMeter * zoom)
    val scaleDistanceMeters = niceRunningMapScaleDistance(targetDistanceMeters.toDouble())
    val barWidth = (scaleDistanceMeters * fitScalePixelsPerMeter * zoom).toFloat()
    val padding = 5.dp.toPx()
    val panelHeight = 23.dp.toPx()
    val textSize = 9.dp.toPx()
    val label = formatRunningMapScaleDistance(scaleDistanceMeters)
    val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = labelColor.toArgb()
        this.textSize = textSize
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }
    val textWidth = textPaint.measureText(label)
    val panelWidth = maxOf(barWidth, textWidth) + padding * 2
    val panelLeft = 5.dp.toPx()
    val panelTop = size.height - panelHeight - 5.dp.toPx()
    drawRoundRect(
        color = backgroundColor.copy(alpha = 0.92f),
        topLeft = Offset(panelLeft, panelTop),
        size = Size(panelWidth, panelHeight),
        cornerRadius = CornerRadius(4.dp.toPx()),
    )
    val textBaseline = panelTop + padding + textSize * 0.82f
    drawContext.canvas.nativeCanvas.drawText(
        label,
        panelLeft + padding,
        textBaseline,
        textPaint,
    )
    val barY = panelTop + panelHeight - 4.dp.toPx()
    val barStart = Offset(panelLeft + padding, barY)
    val barEnd = Offset(barStart.x + barWidth, barY)
    drawLine(routeColor, barStart, barEnd, strokeWidth = 2.dp.toPx())
    drawLine(routeColor, Offset(barStart.x, barY - 3.dp.toPx()), Offset(barStart.x, barY + 1.dp.toPx()), strokeWidth = 1.dp.toPx())
    drawLine(routeColor, Offset(barEnd.x, barY - 3.dp.toPx()), Offset(barEnd.x, barY + 1.dp.toPx()), strokeWidth = 1.dp.toPx())
}

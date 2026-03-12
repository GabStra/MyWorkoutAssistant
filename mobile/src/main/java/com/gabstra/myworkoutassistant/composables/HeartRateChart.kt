package com.gabstra.myworkoutassistant.composables

import android.os.Build
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Velocity
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisTickComponent
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberFadingEdges
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.compose.cartesian.CartesianMeasuringContext
import com.patrykandpatrick.vico.compose.cartesian.Zoom
import com.patrykandpatrick.vico.compose.cartesian.axis.Axis
import com.patrykandpatrick.vico.compose.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianLayerRangeProvider
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.data.LineCartesianLayerModel
import com.patrykandpatrick.vico.compose.cartesian.decoration.HorizontalLine
import com.patrykandpatrick.vico.compose.cartesian.layer.LineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.CandlestickCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.compose.cartesian.marker.CartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.marker.ColumnCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.compose.cartesian.marker.DefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.compose.common.DashedShape
import com.patrykandpatrick.vico.compose.common.Fill
import com.patrykandpatrick.vico.compose.common.Insets
import com.patrykandpatrick.vico.compose.common.Position

@Composable
private fun rememberHorizontalLine(
    color: Color,
    y: Double,
): HorizontalLine {
    val line = rememberLineComponent(fill = Fill(color), thickness = 1.dp, shape = DashedShape())
    return remember(y, color) {
        HorizontalLine(
            y = { y },
            line = line,
        )
    }
}

private class FixedValuesVerticalAxisItemPlacer(
    private val values: List<Double>,
    private val delegate: VerticalAxis.ItemPlacer = VerticalAxis.ItemPlacer.step(step = { 10.0 }),
) : VerticalAxis.ItemPlacer {
    override fun getShiftTopLines(context: CartesianDrawingContext): Boolean =
        delegate.getShiftTopLines(context)

    override fun getLabelValues(
        context: CartesianDrawingContext,
        axisHeight: Float,
        maxLabelHeight: Float,
        position: Axis.Position.Vertical,
    ): List<Double> = valuesInRange(context, position)

    override fun getWidthMeasurementLabelValues(
        context: CartesianMeasuringContext,
        axisHeight: Float,
        maxLabelHeight: Float,
        position: Axis.Position.Vertical,
    ): List<Double> = valuesInRange(context, position)

    override fun getHeightMeasurementLabelValues(
        context: CartesianMeasuringContext,
        position: Axis.Position.Vertical,
    ): List<Double> = valuesInRange(context, position)

    override fun getLineValues(
        context: CartesianDrawingContext,
        axisHeight: Float,
        maxLabelHeight: Float,
        position: Axis.Position.Vertical,
    ): List<Double> = valuesInRange(context, position)

    override fun getTopLayerMargin(
        context: CartesianMeasuringContext,
        verticalLabelPosition: Position.Vertical,
        maxLabelHeight: Float,
        maxLineThickness: Float,
    ): Float = delegate.getTopLayerMargin(context, verticalLabelPosition, maxLabelHeight, maxLineThickness)

    override fun getBottomLayerMargin(
        context: CartesianMeasuringContext,
        verticalLabelPosition: Position.Vertical,
        maxLabelHeight: Float,
        maxLineThickness: Float,
    ): Float = delegate.getBottomLayerMargin(context, verticalLabelPosition, maxLabelHeight, maxLineThickness)

    private fun valuesInRange(
        context: CartesianDrawingContext,
        position: Axis.Position.Vertical,
    ): List<Double> {
        val yRange = context.ranges.getYRange(position)
        return values.filter { it in yRange.minY..yRange.maxY }
    }

    private fun valuesInRange(
        context: CartesianMeasuringContext,
        position: Axis.Position.Vertical,
    ): List<Double> {
        val yRange = context.ranges.getYRange(position)
        return values.filter { it in yRange.minY..yRange.maxY }
    }
}


internal fun SpannableStringBuilder.appendCompat(
    text: CharSequence,
    what: Any,
    flags: Int,
): SpannableStringBuilder =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
        append(text, what, flags)
    } else {
        append(text, 0, text.length)
        setSpan(what, length - text.length, length, flags)
        this
    }

internal class DefaultValueFormatter(
    private val formatter: (Double) -> String,
    private val textColor: Int,
    private val colorCode: Boolean = true,
) : DefaultCartesianMarker.ValueFormatter {
    private fun SpannableStringBuilder.appendValue(y: Double, color: Color? = null) {
        if (colorCode && color != null) {
            appendCompat(
                formatter(y),
                ForegroundColorSpan(color.toArgb()),
                Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
        } else {
            append(formatter(y))
        }
    }

    private fun SpannableStringBuilder.appendTarget(target: CartesianMarker.Target, shorten: Boolean) {
        when (target) {
            is CandlestickCartesianLayerMarkerTarget -> {
                if (shorten) {
                    appendValue(target.entry.closing, target.closingColor)
                } else {
                    append("O ")
                    appendValue(target.entry.opening, target.openingColor)
                    append(", C ")
                    appendValue(target.entry.closing, target.closingColor)
                    append(", L ")
                    appendValue(target.entry.low, target.lowColor)
                    append(", H ")
                    appendValue(target.entry.high, target.highColor)
                }
            }

            is ColumnCartesianLayerMarkerTarget -> {
                val includeSum = target.columns.size > 1
                if (includeSum) {
                    appendValue(target.columns.sumOf { it.entry.y })
                    append(" (")
                }
                target.columns.forEachIndexed { index, column ->
                    appendValue(column.entry.y, column.color)
                    if (index != target.columns.lastIndex) append(", ")
                }
                if (includeSum) append(")")
            }

            is LineCartesianLayerMarkerTarget -> {
                target.points.forEachIndexed { index, point ->
                    appendValue(point.entry.y, point.color)
                    if (index != target.points.lastIndex) append(", ")
                }
            }

            else -> throw IllegalArgumentException("Unexpected `CartesianMarker.Target` implementation.")
        }
    }

    override fun format(
        context: CartesianDrawingContext,
        targets: List<CartesianMarker.Target>,
    ): CharSequence =
        SpannableStringBuilder().apply {
            targets.forEachIndexed { index, target ->
                appendTarget(target = target, shorten = targets.size > 1)
                if (index != targets.lastIndex) append(", ")
            }
        }

    override fun equals(other: Any?): Boolean =
        this === other ||
                other is DefaultValueFormatter &&
                formatter == other.formatter &&
                textColor == other.textColor &&
                colorCode == other.colorCode

    override fun hashCode(): Int = 31 * (31 * formatter.hashCode() + textColor.hashCode()) + colorCode.hashCode()
}

@Composable
fun HeartRateChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    minYBpm: Double? = null,
    zoneTickValuesBpm: List<Double>? = null,
    lineZoneIndices: List<Int>? = null,
    includeCard: Boolean = true,
) {
    val chartContent = @Composable {
        HeartRateChartContent(
            modifier = modifier,
            cartesianChartModel = cartesianChartModel,
            userAge = userAge,
            measuredMaxHeartRate = measuredMaxHeartRate,
            restingHeartRate = restingHeartRate,
            minYBpm = minYBpm,
            zoneTickValuesBpm = zoneTickValuesBpm,
            lineZoneIndices = lineZoneIndices,
        )
    }

    if (includeCard) {
        StyledCard {
            ExpandableContainer(
                isOpen = true,
                modifier = modifier,
                isExpandable = false,
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = 10.dp, top = 10.dp, end = 0.dp, bottom = 10.dp),
                        text = title,
                        textAlign = TextAlign.Start,
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleMedium,
                    )
                },
                content = {
                    chartContent()
                }
            )
        }
    } else {
        chartContent()
    }
}

@Composable
fun HeartRateChartContent(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
    minYBpm: Double? = null,
    zoneTickValuesBpm: List<Double>? = null,
    lineZoneIndices: List<Int>? = null,
    onInteractionChange: ((Boolean) -> Unit)? = null,
) {
    val chartNestedScrollConnection = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource,
            ): Offset = available

            override suspend fun onPostFling(
                consumed: Velocity,
                available: Velocity,
            ): Velocity = available
        }
    }
    val zoneAxisValues = remember(userAge, measuredMaxHeartRate, restingHeartRate, zoneTickValuesBpm) {
        zoneTickValuesBpm ?: listOf(50f, 60f, 70f, 80f, 90f, 100f).map {
            getHeartRateFromPercentage(
                it,
                userAge,
                measuredMaxHeartRate,
                restingHeartRate
            ).toDouble()
        }.distinct().sorted()
    }
    val zoneStartAxisValues = remember(zoneAxisValues) {
        if (zoneAxisValues.size > 1) zoneAxisValues.dropLast(1) else zoneAxisValues
    }

    val startAxisValueFormatter =
        CartesianValueFormatter { _, value, _ ->
            value.toInt().toString()
        }

    val textColor = MaterialTheme.colorScheme.onBackground.toArgb()
    val shapeComponent = rememberShapeComponent(Fill(Color.White), RoundedCornerShape(percent = 50))
    val marker = rememberDefaultCartesianMarker(
        valueFormatter = remember {
            DefaultValueFormatter({
                it.toInt().toString()
            }, textColor)
        },
        label = rememberTextComponent(
            style = TextStyle(color = Color.White, textAlign = TextAlign.Center),
            padding = Insets(8.dp),
        ),
        guideline = rememberAxisGuidelineComponent(Fill(MaterialTheme.colorScheme.background)),
        indicatorSize = 10.dp,
        indicator = { _ -> shapeComponent }
    )

    val bottomAxisValueFormatter =
        CartesianValueFormatter { _, value, _ ->
            formatTime((value).toInt())
        }

    val firstModel = cartesianChartModel.models.firstOrNull()
    val modelMaxY = firstModel?.maxY ?: 1.0
    val effectiveMinY = minOf(minYBpm ?: modelMaxY, zoneAxisValues.firstOrNull() ?: modelMaxY) - 2.0
    val effectiveMaxY = maxOf(modelMaxY, (zoneAxisValues.lastOrNull() ?: modelMaxY) + 2.0)

    val modelSeriesCount = (cartesianChartModel.models.firstOrNull() as? LineCartesianLayerModel)?.series?.size ?: 0
    val effectiveLineZoneIndices = if (
        lineZoneIndices != null &&
        modelSeriesCount > 0 &&
        lineZoneIndices.size == modelSeriesCount
    ) {
        lineZoneIndices
    } else {
        null
    }

    val lines = if (effectiveLineZoneIndices != null) {
        effectiveLineZoneIndices.map { zoneIndex ->
            LineCartesianLayer.rememberLine(
                fill = LineCartesianLayer.LineFill.single(Fill(colorsByZone[zoneIndex.coerceIn(0, colorsByZone.lastIndex)])),
                areaFill = null,
                pointProvider = null,
                pointConnector = LineCartesianLayer.PointConnector.Sharp,
            )
        }
    } else {
        listOf(
            LineCartesianLayer.rememberLine(
                fill = LineCartesianLayer.LineFill.single(
                    Fill(
                        Color(
                            0xFFff6700
                        )
                    )
                ),
                areaFill = null,
                pointProvider = null,
                pointConnector = LineCartesianLayer.PointConnector.cubic(),
            )
        )
    }

    CartesianChartHost(
        modifier = modifier
            .padding(10.dp)
            .nestedScroll(chartNestedScrollConnection)
            .chartTouchInterop(onInteractionChange = onInteractionChange),
        zoomState = rememberVicoZoomState(
            initialZoom = Zoom.Content,
            zoomEnabled = true
        ),
        scrollState = rememberVicoScrollState(scrollEnabled = true),
        chart = rememberCartesianChart(
            rememberLineCartesianLayer(
                LineCartesianLayer.LineProvider.series(lines),

                rangeProvider = CartesianLayerRangeProvider.fixed(
                    minY = effectiveMinY,
                    maxY = effectiveMaxY
                ),
            ),
            decorations = zoneStartAxisValues.mapIndexed { index, threshold ->
                val zoneColor = colorsByZone[(index + 1).coerceIn(0, colorsByZone.lastIndex)]
                rememberHorizontalLine(
                    color = zoneColor.copy(alpha = 0.75f),
                    y = threshold,
                )
            },
            startAxis = VerticalAxis.rememberStart(
                line = rememberAxisLineComponent(Fill(MaterialTheme.colorScheme.outlineVariant)),
                tick = rememberAxisTickComponent(Fill(MaterialTheme.colorScheme.outlineVariant)),
                guideline = null,
                valueFormatter = startAxisValueFormatter,
                itemPlacer = remember(zoneAxisValues) {
                    FixedValuesVerticalAxisItemPlacer(zoneAxisValues)
                }),
            bottomAxis = HorizontalAxis.rememberBottom(
                line = rememberAxisLineComponent(Fill(MaterialTheme.colorScheme.outlineVariant)),
                tick = rememberAxisTickComponent(Fill(MaterialTheme.colorScheme.outlineVariant)),
                guideline = null,
                valueFormatter = bottomAxisValueFormatter,
                itemPlacer = remember { HorizontalAxis.ItemPlacer.aligned(spacing = { 30 }) }),
            marker = marker,
            fadingEdges = rememberFadingEdges()
        ),
        model = cartesianChartModel,
    )
}


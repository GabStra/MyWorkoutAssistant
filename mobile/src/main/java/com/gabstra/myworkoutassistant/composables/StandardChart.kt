package com.gabstra.myworkoutassistant.composables

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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.Velocity
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisTickComponent
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberFadingEdges
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.compose.cartesian.CartesianMeasuringContext
import com.patrykandpatrick.vico.compose.cartesian.Zoom
import com.patrykandpatrick.vico.compose.cartesian.axis.Axis
import com.patrykandpatrick.vico.compose.cartesian.axis.BaseAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianLayerRangeProvider
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.layer.LineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.compose.common.Fill
import com.patrykandpatrick.vico.compose.common.Insets
import com.patrykandpatrick.vico.compose.common.Position
import com.patrykandpatrick.vico.compose.common.component.LineComponent
import com.patrykandpatrick.vico.compose.common.component.TextComponent
import com.patrykandpatrick.vico.compose.common.data.ExtraStore
import kotlin.math.abs

internal val BottomPaddedChartVerticalOffset = 10.dp
private const val ChartBottomRangePaddingFraction = 0.08
private val ChartBottomVisualPaddingFraction =
    ChartBottomRangePaddingFraction / (1.0 + ChartBottomRangePaddingFraction)

private class BottomPaddedRangeProvider(
    private val minYOverride: Double?,
    private val maxYOverride: Double?,
    private val bottomPaddingFraction: Double,
) : CartesianLayerRangeProvider {
    override fun getMinY(minY: Double, maxY: Double, extraStore: ExtraStore): Double {
        if (minYOverride != null) return minYOverride

        val range = (maxY - minY).takeIf { it > 0.0 } ?: maxOf(abs(minY), abs(maxY), 1.0)
        return minY - (range * bottomPaddingFraction)
    }

    override fun getMaxY(minY: Double, maxY: Double, extraStore: ExtraStore): Double =
        maxYOverride ?: maxY
}

internal class FixedValuesHorizontalAxisItemPlacer(
    values: List<Double>,
    private val maxVisibleLabelCount: Int = 15,
    private val delegate: HorizontalAxis.ItemPlacer = HorizontalAxis.ItemPlacer.aligned(),
) : HorizontalAxis.ItemPlacer {
    private val sortedValues = values.distinct().sorted()

    override fun getShiftExtremeLines(context: CartesianDrawingContext): Boolean = false

    override fun getFirstLabelValue(
        context: CartesianMeasuringContext,
        maxLabelWidth: Float,
    ): Double? = sortedValues.firstOrNull()

    override fun getLastLabelValue(
        context: CartesianMeasuringContext,
        maxLabelWidth: Float,
    ): Double? = sortedValues.lastOrNull()

    override fun getLabelValues(
        context: CartesianDrawingContext,
        visibleXRange: ClosedFloatingPointRange<Double>,
        fullXRange: ClosedFloatingPointRange<Double>,
        maxLabelWidth: Float,
    ): List<Double> {
        val visibleValues = valuesInRange(visibleXRange)
        if (visibleValues.isEmpty()) return emptyList()
        if (visibleValues.size <= 2) return visibleValues

        val spacingPx = context.layerDimensions.xSpacing
        val strideByWidth = if (spacingPx <= 0f) {
            1
        } else {
            kotlin.math.ceil((maxLabelWidth / spacingPx).toDouble()).toInt().coerceAtLeast(1)
        }
        val strideByCount = kotlin.math.ceil(
            visibleValues.size.toDouble() / maxVisibleLabelCount.coerceAtLeast(2)
        ).toInt().coerceAtLeast(1)
        val stride = maxOf(strideByWidth, strideByCount)

        return sortedValues.filterIndexed { index, value ->
            value in visibleXRange && index % stride == 0
        }.ifEmpty {
            visibleValues
        }
    }

    override fun getWidthMeasurementLabelValues(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.compose.cartesian.layer.CartesianLayerDimensions,
        fullXRange: ClosedFloatingPointRange<Double>,
    ): List<Double> = valuesInRange(fullXRange)

    override fun getHeightMeasurementLabelValues(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.compose.cartesian.layer.CartesianLayerDimensions,
        fullXRange: ClosedFloatingPointRange<Double>,
        maxLabelWidth: Float,
    ): List<Double> = valuesInRange(fullXRange)

    override fun getLineValues(
        context: CartesianDrawingContext,
        visibleXRange: ClosedFloatingPointRange<Double>,
        fullXRange: ClosedFloatingPointRange<Double>,
        maxLabelWidth: Float,
    ): List<Double> = valuesInRange(visibleXRange)

    override fun getStartLayerMargin(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.compose.cartesian.layer.CartesianLayerDimensions,
        tickThickness: Float,
        maxLabelWidth: Float,
    ): Float = delegate.getStartLayerMargin(context, layerDimensions, tickThickness, maxLabelWidth)

    override fun getEndLayerMargin(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.compose.cartesian.layer.CartesianLayerDimensions,
        tickThickness: Float,
        maxLabelWidth: Float,
    ): Float = delegate.getEndLayerMargin(context, layerDimensions, tickThickness, maxLabelWidth)

    private fun valuesInRange(range: ClosedFloatingPointRange<Double>): List<Double> {
        if (sortedValues.isEmpty()) return emptyList()
        val start = range.start
        val end = range.endInclusive
        return sortedValues.filter { it in start..end }
    }
}

internal class BottomPaddedStartVerticalAxis(
    line: LineComponent?,
    label: TextComponent?,
    labelRotationDegrees: Float,
    horizontalLabelPosition: VerticalAxis.HorizontalLabelPosition,
    verticalLabelPosition: Position.Vertical,
    valueFormatter: CartesianValueFormatter,
    tick: LineComponent?,
    tickLength: Dp,
    guideline: LineComponent?,
    itemPlacer: VerticalAxis.ItemPlacer,
    size: com.patrykandpatrick.vico.compose.cartesian.axis.BaseAxis.Size,
    titleComponent: TextComponent?,
    title: (ExtraStore) -> CharSequence?,
    tickPosition: BaseAxis.TickPosition,
    lineDrawingOrder: BaseAxis.LineDrawingOrder,
    private val bottomPadding: Dp,
    private val bottomPaddingFraction: Double?,
) : VerticalAxis<Axis.Position.Vertical.Start>(
    position = Axis.Position.Vertical.Start,
    line = line,
    label = label,
    labelRotationDegrees = labelRotationDegrees,
    horizontalLabelPosition = horizontalLabelPosition,
    verticalLabelPosition = verticalLabelPosition,
    valueFormatter = valueFormatter,
    tick = tick,
    tickLength = tickLength,
    guideline = guideline,
    itemPlacer = itemPlacer,
    size = size,
    titleComponent = titleComponent,
    title = title,
    tickPosition = tickPosition,
    lineDrawingOrder = lineDrawingOrder,
) {
    override fun drawUnderLayers(
        context: CartesianDrawingContext,
        axisDimensions: Map<Axis.Position, com.patrykandpatrick.vico.compose.cartesian.axis.AxisDimensions>,
    ) {
        with(context) {
            val yRange = ranges.getYRange(position)
            val maxLabelHeight = getMaxLabelHeight()
            val lineValues =
                itemPlacer.getLineValues(this, bounds.height, maxLabelHeight, position)
                    ?: itemPlacer.getLabelValues(this, bounds.height, maxLabelHeight, position)
            val bottomPaddingPx =
                (
                    bottomPaddingFraction?.let { (bounds.height * it).toFloat() }
                        ?: bottomPadding.pixels
                ).coerceIn(0f, (bounds.height - 1f).coerceAtLeast(0f))
            val effectiveBottom = bounds.bottom - bottomPaddingPx
            val effectiveHeight = (bounds.height - bottomPaddingPx).coerceAtLeast(1f)

            lineValues.forEach { lineValue ->
                val centerY =
                    effectiveBottom -
                        effectiveHeight * ((lineValue - yRange.minY) / yRange.length).toFloat() +
                        getLineCanvasYCorrection(guidelineThickness, lineValue)

                guideline
                    ?.takeIf {
                        isNotInRestrictedBounds(
                            left = layerBounds.left,
                            top = centerY - guidelineThickness / 2f,
                            right = layerBounds.right,
                            bottom = centerY + guidelineThickness / 2f,
                        )
                    }
                    ?.drawHorizontal(
                        context = context,
                        left = layerBounds.left,
                        right = layerBounds.right,
                        y = centerY,
                    )
            }

            val topExtension = if (itemPlacer.getShiftTopLines(this)) tickThickness else 0f
            val bottomExtension = tickThickness
            line?.drawVertical(
                context = context,
                x = if (isLtr) bounds.right - lineThickness / 2f else bounds.left + lineThickness / 2f,
                top = bounds.top - topExtension,
                bottom = bounds.bottom + bottomExtension,
            )
        }
    }

    override fun drawOverLayers(
        context: CartesianDrawingContext,
        axisDimensions: Map<Axis.Position, com.patrykandpatrick.vico.compose.cartesian.axis.AxisDimensions>,
    ) {
        with(context) {
            val label = label
            val labelValues =
                itemPlacer.getLabelValues(this, bounds.height, getMaxLabelHeight(), position)
            val tickLeftX = getTickLeftX()
            val tickRightX = tickLeftX + lineThickness + this.tickLength
            val labelX =
                if (areLabelsOutsideAtStartOrInsideAtEnd == isLtr) tickLeftX else tickRightX
            val yRange = ranges.getYRange(position)
            val bottomPaddingPx =
                (
                    bottomPaddingFraction?.let { (bounds.height * it).toFloat() }
                        ?: bottomPadding.pixels
                ).coerceIn(0f, (bounds.height - 1f).coerceAtLeast(0f))
            val effectiveBottom = bounds.bottom - bottomPaddingPx
            val effectiveHeight = (bounds.height - bottomPaddingPx).coerceAtLeast(1f)

            labelValues.forEach { labelValue ->
                val tickCenterY =
                    effectiveBottom -
                        effectiveHeight * ((labelValue - yRange.minY) / yRange.length).toFloat() +
                        getLineCanvasYCorrection(tickThickness, labelValue)

                tick?.drawHorizontal(
                    context = context,
                    left = tickLeftX,
                    right = tickRightX,
                    y = tickCenterY,
                )

                label ?: return@forEach
                drawLabel(
                    context = this,
                    labelComponent = label,
                    label = valueFormatter.format(this, labelValue, position),
                    labelX = labelX,
                    tickCenterY = tickCenterY,
                )
            }

            title(model.extraStore)?.let { titleText ->
                titleComponent?.draw(
                    context = this,
                    text = titleText,
                    x = if (isLtr) bounds.left else bounds.right,
                    y = bounds.center.y,
                    horizontalPosition = Position.Horizontal.End,
                    verticalPosition = Position.Vertical.Center,
                    rotationDegrees = -90f,
                    maxHeight = bounds.height.toInt(),
                )
            }
        }
    }
}

@Composable
internal fun rememberBottomPaddedStartVerticalAxis(
    line: LineComponent?,
    label: TextComponent?,
    labelRotationDegrees: Float = 0f,
    horizontalLabelPosition: VerticalAxis.HorizontalLabelPosition = VerticalAxis.HorizontalLabelPosition.Outside,
    verticalLabelPosition: Position.Vertical = Position.Vertical.Center,
    valueFormatter: CartesianValueFormatter,
    tick: LineComponent?,
    tickLength: Dp = 4.dp,
    guideline: LineComponent?,
    itemPlacer: VerticalAxis.ItemPlacer,
    size: com.patrykandpatrick.vico.compose.cartesian.axis.BaseAxis.Size,
    titleComponent: TextComponent? = null,
    title: (ExtraStore) -> CharSequence? = { null },
    tickPosition: BaseAxis.TickPosition =
        if (horizontalLabelPosition == VerticalAxis.HorizontalLabelPosition.Outside) {
            BaseAxis.TickPosition.Outside
        } else {
            BaseAxis.TickPosition.Inside
        },
    lineDrawingOrder: BaseAxis.LineDrawingOrder = BaseAxis.LineDrawingOrder.UnderLayers,
    bottomPadding: Dp,
    bottomPaddingFraction: Double? = null,
): VerticalAxis<Axis.Position.Vertical.Start> = remember(
    line,
    label,
    labelRotationDegrees,
    horizontalLabelPosition,
    verticalLabelPosition,
    valueFormatter,
    tick,
    tickLength,
    guideline,
    itemPlacer,
    size,
    titleComponent,
    title,
    tickPosition,
    lineDrawingOrder,
    bottomPadding,
    bottomPaddingFraction,
) {
    BottomPaddedStartVerticalAxis(
        line = line,
        label = label,
        labelRotationDegrees = labelRotationDegrees,
        horizontalLabelPosition = horizontalLabelPosition,
        verticalLabelPosition = verticalLabelPosition,
        valueFormatter = valueFormatter,
        tick = tick,
        tickLength = tickLength,
        guideline = guideline,
        itemPlacer = itemPlacer,
        size = size,
        titleComponent = titleComponent,
        title = title,
        tickPosition = tickPosition,
        lineDrawingOrder = lineDrawingOrder,
        bottomPadding = bottomPadding,
        bottomPaddingFraction = bottomPaddingFraction,
    )
}


@Composable
fun StandardChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    isZoomEnabled: Boolean = true,
    minValue: Double? = null,
    maxValue: Double? = null,
    markerPosition: Double? = null,
    xAxisTickValues: List<Double>? = null,
    maxVisibleXLabels: Int = 16,
    markerTextFormatter: ((Double) -> String)? = ({ it.toString() }),
    startAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() },
    bottomAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() },
    onInteractionChange: ((Boolean) -> Unit)? = null,
) {
    val onBackgroundColor = MaterialTheme.colorScheme.onBackground
    val onBackgroundColorArgb = onBackgroundColor.toArgb()
    val chartNestedScrollConnection = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource
            ): Offset {
                return available
            }

            override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
                return available
            }
        }
    }
    val shapeComponent = rememberShapeComponent(Fill(onBackgroundColor), RoundedCornerShape(percent = 50))
    val markerGuideline = rememberPressedChartGuideline()

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(
            style = TextStyle(color = onBackgroundColor, textAlign = TextAlign.Center),
            padding = Insets(8.dp),
        ),
        guideline = markerGuideline,
        indicatorSize = 10.dp,
        valueFormatter = { _, targets ->
            val target = targets.first() as LineCartesianLayerMarkerTarget
            val point = target.points.first()
            SpannableStringBuilder().apply {
                append(
                    markerTextFormatter?.invoke(point.entry.y),
                    ForegroundColorSpan(onBackgroundColorArgb),
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
                )
            }
        },
        indicator = { _ -> shapeComponent }
    )

    val firstModel = cartesianChartModel.models.firstOrNull()

    var minY = minValue ?: firstModel?.minY ?: 0.0
    var maxY = maxValue ?: firstModel?.maxY ?: 1.0

    if(minY == maxY){
        val value = minY
        minY = value.times(0.99)
        maxY = value.times(1.01)
    }

    val rangeProvider = remember(minValue, maxValue) {
        BottomPaddedRangeProvider(
            minYOverride = minValue,
            maxYOverride = maxValue,
            bottomPaddingFraction = ChartBottomRangePaddingFraction,
        )
    }
    val axisBottomPaddingFraction = if (minValue == null) ChartBottomVisualPaddingFraction else 0.0

    StyledCard{
        ExpandableContainer(
            isOpen = true,
            modifier = modifier,
            isExpandable = false,
            title = {
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 10.dp, start = 10.dp),
                    text = title,
                    textAlign = TextAlign.Start,
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleMedium,
                )
            },
            content = {
                CartesianChartHost(
                    modifier = Modifier
                        .padding(horizontal = 10.dp)
                        .padding(bottom = 10.dp)
                        .nestedScroll(chartNestedScrollConnection)
                        .chartTouchInterop(onInteractionChange = onInteractionChange),
                    zoomState = rememberVicoZoomState(
                        initialZoom = Zoom.Content,
                        zoomEnabled = isZoomEnabled
                    ),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(
                            LineCartesianLayer.LineProvider.series(
                                listOf(
                                    LineCartesianLayer.rememberLine(
                                        fill = LineCartesianLayer.LineFill.single(Fill(Color(0xFFff6700))),
                                        pointConnector =  LineCartesianLayer.PointConnector.cubic(),
                                        areaFill = null,
                                        pointProvider = null,
                                    )
                                )
                            ),
                            pointSpacing = 32.dp,
                            rangeProvider = rangeProvider,
                        ),
                        startAxis = rememberBottomPaddedStartVerticalAxis(
                            line = rememberAxisLineComponent(Fill(MaterialTheme.colorScheme.onBackground)),
                            label = rememberTextComponent(
                                style = TextStyle(
                                    color = MaterialTheme.colorScheme.onBackground,
                                    fontSize = 12.sp,
                                    textAlign = TextAlign.End,
                                ),
                                padding = Insets(4.dp, 4.dp),
                            ),
                            valueFormatter = startAxisValueFormatter,
                            itemPlacer = remember { VerticalAxis.ItemPlacer.count() },
                            tick = rememberAxisTickComponent(Fill(MaterialTheme.colorScheme.onBackground)),
                            guideline = null,
                            size = com.patrykandpatrick.vico.compose.cartesian.axis.BaseAxis.Size.Auto(),
                            bottomPadding = BottomPaddedChartVerticalOffset,
                            bottomPaddingFraction = axisBottomPaddingFraction,
                        ),
                        bottomAxis = HorizontalAxis.rememberBottom(
                            line = rememberAxisLineComponent(Fill(MaterialTheme.colorScheme.onBackground)),
                            label = rememberTextComponent(
                                style = TextStyle(
                                    color = MaterialTheme.colorScheme.onBackground,
                                    fontSize = 12.sp,
                                    textAlign = TextAlign.End,
                                ),
                                padding = Insets(4.dp, 4.dp),
                                //minWidth = TextComponent.MinWidth.fixed(20f)
                            ),
                            labelRotationDegrees = -90f,
                            valueFormatter = bottomAxisValueFormatter,
                            guideline = null,
                            tick = rememberAxisTickComponent(Fill(MaterialTheme.colorScheme.onBackground)),
                            itemPlacer = remember(xAxisTickValues, maxVisibleXLabels) {
                                if (xAxisTickValues.isNullOrEmpty()) {
                                    HorizontalAxis.ItemPlacer.aligned()
                                } else {
                                    FixedValuesHorizontalAxisItemPlacer(
                                        values = xAxisTickValues,
                                        maxVisibleLabelCount = maxVisibleXLabels,
                                    )
                                }
                            },
                        ),
                        persistentMarkers = if (markerPosition != null)  { _ ->
                            marker at markerPosition
                        } else null,
                        marker = marker,
                        fadingEdges = rememberFadingEdges()
                    ),
                    model = cartesianChartModel,
                )
            }
        )
    }
}


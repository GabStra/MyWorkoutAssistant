package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisTickComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberFadingEdges
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.fill
import com.patrykandpatrick.vico.core.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.core.cartesian.CartesianMeasuringContext
import com.patrykandpatrick.vico.core.cartesian.Zoom
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianLayerRangeProvider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.layer.LineCartesianLayer
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Insets
import com.patrykandpatrick.vico.core.common.shape.CorneredShape

private class FixedValuesHorizontalAxisItemPlacer(
    values: List<Double>,
    private val maxVisibleLabelCount: Int = 15,
    private val delegate: HorizontalAxis.ItemPlacer = HorizontalAxis.ItemPlacer.aligned(),
) : HorizontalAxis.ItemPlacer {
    private val sortedValues = values.distinct().sorted()

    override fun getShiftExtremeLines(context: CartesianDrawingContext): Boolean =
        delegate.getShiftExtremeLines(context)

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

        val labels = mutableListOf<Double>()
        for (index in visibleValues.indices step stride) {
            labels += visibleValues[index]
        }
        return labels
    }

    override fun getWidthMeasurementLabelValues(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.core.cartesian.layer.CartesianLayerDimensions,
        fullXRange: ClosedFloatingPointRange<Double>,
    ): List<Double> = valuesInRange(fullXRange)

    override fun getHeightMeasurementLabelValues(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.core.cartesian.layer.CartesianLayerDimensions,
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
        layerDimensions: com.patrykandpatrick.vico.core.cartesian.layer.CartesianLayerDimensions,
        tickThickness: Float,
        maxLabelWidth: Float,
    ): Float = delegate.getStartLayerMargin(context, layerDimensions, tickThickness, maxLabelWidth)

    override fun getEndLayerMargin(
        context: CartesianMeasuringContext,
        layerDimensions: com.patrykandpatrick.vico.core.cartesian.layer.CartesianLayerDimensions,
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
    bottomAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() }
) {
    val onBackgroundColor = MaterialTheme.colorScheme.onBackground
    val onBackgroundColorArgb = onBackgroundColor.toArgb()
    val shapeComponent =  rememberShapeComponent(fill(onBackgroundColor), CorneredShape.Pill)

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(
            color = onBackgroundColor,
            padding = Insets(8f),
            textAlignment = Layout.Alignment.ALIGN_CENTER,
        ),
        guideline =  rememberAxisGuidelineComponent(fill(onBackgroundColor)),
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

    StyledCard{
        ExpandableContainer(
            isOpen = true,
            modifier = modifier,
            isExpandable = false,
            title = {
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 10.dp),
                    text = title,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleMedium,
                )
            },
            content = {
                CartesianChartHost(
                    modifier = Modifier.padding(horizontal = 10.dp).padding(bottom = 10.dp),
                    zoomState = rememberVicoZoomState(
                        initialZoom = Zoom.Content,
                        zoomEnabled = isZoomEnabled
                    ),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(
                            LineCartesianLayer.LineProvider.series(
                                listOf(
                                    LineCartesianLayer.rememberLine(
                                        fill = LineCartesianLayer.LineFill.single(fill(Color(0xFFff6700))),
                                        pointConnector =  LineCartesianLayer.PointConnector.cubic(),
                                        areaFill = null,
                                        pointProvider = null,
                                    )
                                )
                            ),
                            rangeProvider = CartesianLayerRangeProvider.fixed(minY = minY, maxY = maxY)
                        ),
                        startAxis = VerticalAxis.rememberStart(
                            line = rememberAxisLineComponent(fill(MaterialTheme.colorScheme.onBackground)),
                            label = rememberTextComponent(
                                color = MaterialTheme.colorScheme.onBackground,
                                textSize = 12.sp,
                                padding = Insets(4f, 4f),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                            ),
                            valueFormatter = startAxisValueFormatter,
                            itemPlacer = remember { VerticalAxis.ItemPlacer.count() },
                            tick = rememberAxisTickComponent(fill(MaterialTheme.colorScheme.onBackground)),
                            guideline = null,
                        ),
                        bottomAxis = HorizontalAxis.rememberBottom(
                            line = rememberAxisLineComponent(fill(MaterialTheme.colorScheme.onBackground)),
                            label = rememberTextComponent(
                                color = MaterialTheme.colorScheme.onBackground,
                                textSize = 12.sp,
                                padding = Insets(4f, 4f),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                                //minWidth = TextComponent.MinWidth.fixed(20f)
                            ),
                            labelRotationDegrees = -90f,
                            valueFormatter = bottomAxisValueFormatter,
                            guideline = null,
                            tick = rememberAxisTickComponent(fill(MaterialTheme.colorScheme.onBackground)),
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

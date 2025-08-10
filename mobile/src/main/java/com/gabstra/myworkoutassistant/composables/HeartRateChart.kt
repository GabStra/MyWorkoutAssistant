package com.gabstra.myworkoutassistant.composables

import android.os.Build
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
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
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
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.fill
import com.patrykandpatrick.vico.compose.common.shape.dashedShape
import com.patrykandpatrick.vico.core.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.core.cartesian.Zoom
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianLayerRangeProvider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.decoration.HorizontalLine
import com.patrykandpatrick.vico.core.cartesian.layer.LineCartesianLayer
import com.patrykandpatrick.vico.core.cartesian.marker.CandlestickCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.cartesian.marker.CartesianMarker
import com.patrykandpatrick.vico.core.cartesian.marker.ColumnCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.cartesian.marker.DefaultCartesianMarker
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Insets
import com.patrykandpatrick.vico.core.common.shape.CorneredShape

@Composable
private fun rememberHorizontalLine(color: Color, y: Double): HorizontalLine {
    val fill = fill(color)
    val line = rememberLineComponent(fill = fill, thickness = 1.dp, shape = dashedShape(),)
    return remember {
        HorizontalLine(
            y = { y },
            line = line,
        )
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
    private val colorCode: Boolean = true,
) : DefaultCartesianMarker.ValueFormatter {
    private fun SpannableStringBuilder.append(y: Double, color: Int? = null) {
        if (colorCode && color != null) {
            appendCompat(
                formatter(y),
                ForegroundColorSpan(LightGray.toArgb()),
                Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
        } else {
            append(formatter(y))
        }
    }

    private fun SpannableStringBuilder.append(target: CartesianMarker.Target, shorten: Boolean) {
        when (target) {
            is CandlestickCartesianLayerMarkerTarget -> {
                if (shorten) {
                    append(target.entry.closing, target.closingColor)
                } else {
                    append("O ")
                    append(target.entry.opening, target.openingColor)
                    append(", C ")
                    append(target.entry.closing, target.closingColor)
                    append(", L ")
                    append(target.entry.low, target.lowColor)
                    append(", H ")
                    append(target.entry.high, target.highColor)
                }
            }

            is ColumnCartesianLayerMarkerTarget -> {
                val includeSum = target.columns.size > 1
                if (includeSum) {
                    append(target.columns.sumOf { it.entry.y })
                    append(" (")
                }
                target.columns.forEachIndexed { index, column ->
                    append(column.entry.y, column.color)
                    if (index != target.columns.lastIndex) append(", ")
                }
                if (includeSum) append(")")
            }

            is LineCartesianLayerMarkerTarget -> {
                target.points.forEachIndexed { index, point ->
                    append(point.entry.y, point.color)
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
                append(target = target, shorten = targets.size > 1)
                if (index != targets.lastIndex) append(", ")
            }
        }

    override fun equals(other: Any?): Boolean =
        this === other ||
                other is DefaultValueFormatter &&
                formatter == other.formatter &&
                colorCode == other.colorCode

    override fun hashCode(): Int = 31 * formatter.hashCode() + colorCode.hashCode()
}

@Composable
fun HeartRateChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    userAge: Int,
) {
    val startAxisValueFormatter =
        CartesianValueFormatter { _, value, _ ->
            getHeartRateFromPercentage(value.toFloat(),userAge).toString()
        }

    val shapeComponent = rememberShapeComponent(fill(Color.White), CorneredShape.Pill)
    val marker = rememberDefaultCartesianMarker(
        valueFormatter = remember {
            DefaultValueFormatter({
                getHeartRateFromPercentage(it.toFloat(),userAge).toString()
            })
        },
        label = rememberTextComponent(
            color = Color.White,
            padding = Insets(8f),
            textAlignment = Layout.Alignment.ALIGN_CENTER
        ),
        guideline =  rememberAxisGuidelineComponent(fill(DarkGray)),
        indicatorSize = 10.dp,
        indicator = { _ -> shapeComponent }
    )


    val bottomAxisValueFormatter =
        CartesianValueFormatter { _, value, _ ->
            formatTime((value).toInt())
        }

    StyledCard {
        ExpandableContainer(
            isOpen = true,
            modifier = modifier,
            isExpandable = false,
            title = {
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 10.dp),
                    text = title,
                    textAlign = TextAlign.Center,
                    color = LightGray,
                    style = MaterialTheme.typography.titleMedium,
                )
            },
            content = {
                CartesianChartHost(
                    modifier = Modifier.padding(10.dp),
                    zoomState = rememberVicoZoomState(
                        initialZoom = Zoom.Content,
                        zoomEnabled = true
                    ),
                    scrollState = rememberVicoScrollState(scrollEnabled = true),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(
                            LineCartesianLayer.LineProvider.series(
                                listOf(
                                    LineCartesianLayer.rememberLine(
                                        fill = LineCartesianLayer.LineFill.single(
                                            fill(
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
                            ),

                            rangeProvider = CartesianLayerRangeProvider.fixed(
                                minY = 40.0,
                                maxY = 105.0
                            ),
                        ),
                        decorations = listOf(
                            rememberHorizontalLine(colorsByZone[1].copy(alpha = 0.75f), 50.0),
                            rememberHorizontalLine(colorsByZone[2].copy(alpha = 0.75f), 60.0),
                            rememberHorizontalLine(colorsByZone[3].copy(alpha = 0.75f), 70.0),
                            rememberHorizontalLine(colorsByZone[4].copy(alpha = 0.75f), 80.0),
                            rememberHorizontalLine(colorsByZone[5].copy(alpha = 0.75f), 90.0),
                            rememberHorizontalLine(Color.Black, 100.0),
                        ),
                        startAxis = VerticalAxis.rememberStart(
                            line = rememberAxisLineComponent(fill(MediumLightGray)),
                            tick = rememberAxisTickComponent(fill(MediumLightGray)),
                            guideline = null,
                            valueFormatter = startAxisValueFormatter,
                            itemPlacer = remember { VerticalAxis.ItemPlacer.step(step = { 10.0 }) }),
                        bottomAxis = HorizontalAxis.rememberBottom(
                            line = rememberAxisLineComponent(fill(MediumLightGray)),
                            tick = rememberAxisTickComponent(fill(MediumLightGray)),
                            guideline = null,
                            valueFormatter = bottomAxisValueFormatter,
                            itemPlacer = remember { HorizontalAxis.ItemPlacer.aligned(spacing = { 30 }) }),
                        marker = marker,
                        fadingEdges = rememberFadingEdges()
                    ),
                    model = cartesianChartModel,
                )
            }
        )
    }
}
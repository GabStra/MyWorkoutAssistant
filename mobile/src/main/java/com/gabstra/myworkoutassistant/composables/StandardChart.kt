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
import com.gabstra.myworkoutassistant.ui.theme.DarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray
import com.gabstra.myworkoutassistant.ui.theme.LightGray
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

@Composable
fun StandardChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    isZoomEnabled: Boolean = true,
    minValue: Double? = null,
    maxValue: Double? = null,
    markerPosition: Float? = null,
    markerTextFormatter: ((Double) -> String)? = ({ it.toString() }),
    startAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() },
    bottomAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() }
) {
    val shapeComponent =  rememberShapeComponent(fill(LightGray), CorneredShape.Pill)

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(
            color = LightGray,
            padding = Insets(8f),
            textAlignment = Layout.Alignment.ALIGN_CENTER
        ),
        guideline =  rememberAxisGuidelineComponent(fill(DarkGray)),
        indicatorSize = 10.dp,
        valueFormatter = { _, targets ->
            val target = targets.first() as LineCartesianLayerMarkerTarget
            val point = target.points.first()
            SpannableStringBuilder().apply {
                append(
                    markerTextFormatter?.invoke(point.entry.y),
                    ForegroundColorSpan(LightGray.toArgb()),
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
                )
            }
        },
        indicator = { _ -> shapeComponent }
    )

    cartesianChartModel.models.first().minY

    var minY = minValue ?: cartesianChartModel.models.first().minY * 0.75f
    var maxY = maxValue ?: cartesianChartModel.models.first().maxY * 1.25f

    StyledCard{
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
                            line = rememberAxisLineComponent(fill(MediumGray)),
                            label = rememberTextComponent(
                                color = LightGray,
                                textSize = 12.sp,
                                padding = Insets(4f, 4f),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                            ),
                            valueFormatter = startAxisValueFormatter,
                            itemPlacer = remember { VerticalAxis.ItemPlacer.step(step = { 10.0 }) },
                            tick = rememberAxisTickComponent(fill(MediumGray)),
                            guideline = null,
                        ),
                        bottomAxis = HorizontalAxis.rememberBottom(
                            line = rememberAxisLineComponent(fill(MediumGray)),
                            label = rememberTextComponent(
                                color = LightGray,
                                textSize = 12.sp,
                                padding = Insets(4f, 4f),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                                //minWidth = TextComponent.MinWidth.fixed(20f)
                            ),
                            labelRotationDegrees = -90f,
                            valueFormatter = bottomAxisValueFormatter,
                            guideline = null,
                            tick = rememberAxisTickComponent(fill(MediumGray)),

                            ),
                        persistentMarkers = if (markerPosition != null)  { _ ->
                            marker at markerPosition.toFloat()
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

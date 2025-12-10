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
import androidx.compose.material3.MaterialTheme
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
    markerPosition: Double? = null,
    markerTextFormatter: ((Double) -> String)? = ({ it.toString() }),
    startAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() },
    bottomAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() }
) {
    val shapeComponent =  rememberShapeComponent(fill(MaterialTheme.colorScheme.onBackground), CorneredShape.Pill)

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(
            color = MaterialTheme.colorScheme.onBackground,
            padding = Insets(8f),
            textAlignment = Layout.Alignment.ALIGN_CENTER,
        ),
        guideline =  rememberAxisGuidelineComponent(fill(MaterialTheme.colorScheme.onBackground)),
        indicatorSize = 10.dp,
        valueFormatter = { _, targets ->
            val target = targets.first() as LineCartesianLayerMarkerTarget
            val point = target.points.first()
            SpannableStringBuilder().apply {
                append(
                    markerTextFormatter?.invoke(point.entry.y),
                    ForegroundColorSpan(MaterialTheme.colorScheme.onBackground.toArgb()),
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
                            line = rememberAxisLineComponent(fill(MediumMaterialTheme.colorScheme.onBackground)),
                            label = rememberTextComponent(
                                color = MaterialTheme.colorScheme.onBackground,
                                textSize = 12.sp,
                                padding = Insets(4f, 4f),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                            ),
                            valueFormatter = startAxisValueFormatter,
                            itemPlacer = remember { VerticalAxis.ItemPlacer.count() },
                            tick = rememberAxisTickComponent(fill(MediumMaterialTheme.colorScheme.onBackground)),
                            guideline = null,
                        ),
                        bottomAxis = HorizontalAxis.rememberBottom(
                            line = rememberAxisLineComponent(fill(MediumMaterialTheme.colorScheme.onBackground)),
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
                            tick = rememberAxisTickComponent(fill(MediumMaterialTheme.colorScheme.onBackground)),

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

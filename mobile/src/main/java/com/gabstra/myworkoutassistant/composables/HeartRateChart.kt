package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.fill
import com.patrykandpatrick.vico.core.cartesian.Zoom

import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis

import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianLayerRangeProvider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.decoration.HorizontalLine
import com.patrykandpatrick.vico.core.cartesian.layer.LineCartesianLayer

import com.patrykandpatrick.vico.core.common.Insets
import com.patrykandpatrick.vico.core.common.data.ExtraStore
import com.patrykandpatrick.vico.core.common.shape.CorneredShape
import kotlin.math.floor

@Composable
private fun rememberHorizontalLine(color: Color, y: Double): HorizontalLine {
    val fill = fill(color)
    val line = rememberLineComponent(fill = fill, thickness = 2.dp)
    return remember {
        HorizontalLine(
            y = { y },
            line = line,
        )
    }
}

@Composable
fun HeartRateChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    userAge: Int,
    minHeartRate: Int,
    isZoomEnabled: Boolean = true,
) {
    val shapeComponent =  rememberShapeComponent(fill(Color(0xFFff6700)), CorneredShape.Pill)
    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(
            color = Color.White.copy(alpha = .87f),
            padding = Insets(8f),
            textAlignment = Layout.Alignment.ALIGN_CENTER
        ),
        guideline = rememberAxisGuidelineComponent(),
        indicatorSize = 10.dp,
        indicator = { _ -> shapeComponent }
    )

    val bottomAxisValueFormatter =
        CartesianValueFormatter { _, value, _ ->
            formatTime((value).toInt())
        }

    DarkModeContainer(modifier,whiteOverlayAlpha = .1f) {
        Column {
            Text(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(10.dp),
                text = title,
                textAlign = TextAlign.Center,
                color = Color.White.copy(alpha = .87f),
                style = MaterialTheme.typography.titleMedium,
            )
            DarkModeContainer(whiteOverlayAlpha = .05f,isRounded = false) {
                CartesianChartHost(
                    modifier = Modifier.padding(10.dp),
                    zoomState = rememberVicoZoomState(
                        initialZoom = Zoom.Content,
                        zoomEnabled = isZoomEnabled
                    ),
                    scrollState = rememberVicoScrollState(scrollEnabled = false),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(
                            LineCartesianLayer.LineProvider.series(
                                listOf(
                                    LineCartesianLayer.rememberLine(
                                        fill = LineCartesianLayer.LineFill.single(fill(Color(0xFFff6700))),
                                        areaFill = null,
                                        pointProvider = null,
                                    )
                                )
                            ),

                            rangeProvider = CartesianLayerRangeProvider.fixed(minY = minHeartRate.toDouble(), maxY = getHeartRateFromPercentage(100f, userAge).toDouble()),
                        ),
                        decorations = listOf(
                            rememberHorizontalLine(Color.hsl(208f, 0.61f, 0.76f, .5f),getHeartRateFromPercentage(50f, userAge).toDouble()),
                            rememberHorizontalLine(Color.hsl(200f, 0.66f, 0.49f, .5f),getHeartRateFromPercentage(60f, userAge).toDouble()),
                            rememberHorizontalLine(Color.hsl(113f, 0.79f, 0.34f, .5f),getHeartRateFromPercentage(70f, userAge).toDouble()),
                            rememberHorizontalLine(Color.hsl(27f, 0.97f, 0.54f, .5f),getHeartRateFromPercentage(80f, userAge).toDouble()),
                            rememberHorizontalLine(Color.hsl(9f, 0.88f, 0.45f, .5f),getHeartRateFromPercentage(90f, userAge).toDouble()),
                            rememberHorizontalLine(MaterialTheme.colorScheme.background,getHeartRateFromPercentage(100f, userAge).toDouble()),
                        ),
                        startAxis = VerticalAxis.rememberStart(guideline = null),
                        bottomAxis = HorizontalAxis.rememberBottom(guideline = null, valueFormatter = bottomAxisValueFormatter),
                        marker = marker
                    ),
                    model = cartesianChartModel,

                )
            }
        }
    }
}
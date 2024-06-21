package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottomAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStartAxis
import com.patrykandpatrick.vico.compose.cartesian.decoration.rememberHorizontalLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberLayeredComponent
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.of
import com.patrykandpatrick.vico.core.cartesian.Zoom
import com.patrykandpatrick.vico.core.cartesian.data.AxisValueOverrider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.CartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.DefaultCartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Dimensions
import com.patrykandpatrick.vico.core.common.shape.Shape

@Composable
fun HeartRateChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    userAge: Int,
    isZoomEnabled: Boolean = false,
) {

    val indicatorFrontComponent =
        rememberShapeComponent(Shape.Pill, Color(0xFFff6700))
    val indicatorRearComponent = rememberShapeComponent(Shape.Pill, Color(0xFFff6700))
    val indicator =
        rememberLayeredComponent(
            rear = indicatorRearComponent,
            front = indicatorFrontComponent,
            padding = Dimensions.of(3.dp),
        )

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(color = Color.White, padding = Dimensions.of(8.dp), textAlignment = Layout.Alignment.ALIGN_CENTER),
        guideline = rememberAxisGuidelineComponent(),
        indicatorSize = 10.dp,
        indicator = indicator
    )

    Column(modifier = modifier) {
        Text(
            modifier = Modifier
                .fillMaxWidth(),
            text = title,
            textAlign = TextAlign.Center
        )

        CartesianChartHost(
            zoomState = rememberVicoZoomState(initialZoom = Zoom.Content, zoomEnabled = isZoomEnabled),
            scrollState = rememberVicoScrollState(scrollEnabled = false),
            chart = rememberCartesianChart(
                rememberLineCartesianLayer(axisValueOverrider = AxisValueOverrider.fixed(null,null,50f,200f)),
                decorations =
                listOf(
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(0.5f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.hsl(208f, 0.61f, 0.76f,.5f), thickness = 2.dp),
                    ),
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(0.6f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.hsl(200f, 0.66f, 0.49f,.5f), thickness = 2.dp),
                    ),
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(0.7f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.hsl(113f, 0.79f, 0.34f,.5f),thickness = 2.dp),
                    ),
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(0.8f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.hsl(27f, 0.97f, 0.54f,.5f), thickness = 2.dp),
                    ),
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(0.9f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.hsl(9f, 0.88f, 0.45f,.5f), thickness = 2.dp),
                    ),
                    rememberHorizontalLine(
                        y = { getHeartRateFromPercentage(1f,userAge).toFloat() },
                        line = rememberLineComponent(color = Color.Black, thickness = 2.dp),
                    ),
                ),
            ),
            model = cartesianChartModel,
            marker = marker,
        )
    }
}
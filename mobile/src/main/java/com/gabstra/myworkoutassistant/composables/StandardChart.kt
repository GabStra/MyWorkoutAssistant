package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottomAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStartAxis
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.component.rememberLayeredComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.of
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel.Entry
import com.patrykandpatrick.vico.core.cartesian.marker.CartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.DefaultCartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Dimensions
import com.patrykandpatrick.vico.core.common.shape.Shape

@Composable
fun StandardChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    isZoomEnabled: Boolean = false,
    markerPosition: Float,
    markerText: String? = null,
    startAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() },
    bottomAxisValueFormatter: CartesianValueFormatter = remember { CartesianValueFormatter.decimal() }
) {
    val indicatorFrontComponent =
        rememberShapeComponent(Shape.Pill, Color(0xFFff6700))
    val indicatorRearComponent = rememberShapeComponent(Shape.Pill, Color(0xFFff6700))
    val indicator =
        rememberLayeredComponent(
            rear = indicatorRearComponent,
            front = indicatorFrontComponent,
            padding = Dimensions.of(5.dp),
        )

    val marker = rememberDefaultCartesianMarker(
        label = rememberTextComponent(color = Color.White, padding = Dimensions.of(8.dp), textAlignment = Layout.Alignment.ALIGN_CENTER),
        guideline = rememberAxisGuidelineComponent(),
        indicatorSize = 10.dp,
        valueFormatter = if (markerText != null) {
            CartesianMarkerValueFormatter { context, targets ->
                val target = targets.first() as LineCartesianLayerMarkerTarget
                val point = target.points.first()
                SpannableStringBuilder().apply {
                    append(
                        markerText,
                        ForegroundColorSpan(point.color),
                        Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
                    )
                }
            }
        } else {
            remember {
                DefaultCartesianMarkerValueFormatter()
            }
        },
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
            zoomState = rememberVicoZoomState(zoomEnabled = isZoomEnabled),
            chart = rememberCartesianChart(
                rememberLineCartesianLayer(spacing = 75.dp),
                startAxis = rememberStartAxis(valueFormatter = startAxisValueFormatter),
                bottomAxis = rememberBottomAxis(valueFormatter = bottomAxisValueFormatter),
                persistentMarkers = mapOf(markerPosition.toFloat() to marker),
            ),
            model = cartesianChartModel,
            marker = marker,
        )
    }
}

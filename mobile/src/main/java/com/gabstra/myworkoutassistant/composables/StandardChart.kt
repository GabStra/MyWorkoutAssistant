package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLabelComponent
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
import com.patrykandpatrick.vico.compose.common.vicoTheme
import com.patrykandpatrick.vico.core.cartesian.HorizontalLayout
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.CartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.DefaultCartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Dimensions
import com.patrykandpatrick.vico.core.common.component.TextComponent
import com.patrykandpatrick.vico.core.common.shape.Shape

@Composable
fun StandardChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    isZoomEnabled: Boolean = true,
    markerPosition: Float? = null,
    markerTextFormatter: ((Float) -> String)? = ({ it.toString() }),
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
        label = rememberTextComponent(
            color = Color.White.copy(alpha = .87f),
            padding = Dimensions.of(8.dp),
            textAlignment = Layout.Alignment.ALIGN_CENTER
        ),
        guideline = rememberAxisGuidelineComponent(),
        indicatorSize = 10.dp,
        valueFormatter = { context, targets ->
            val target = targets.first() as LineCartesianLayerMarkerTarget
            val point = target.points.first()
            SpannableStringBuilder().apply {
                append(
                    markerTextFormatter?.invoke(point.entry.y),
                    ForegroundColorSpan(point.color),
                    Spannable.SPAN_EXCLUSIVE_EXCLUSIVE,
                )
            }
        },
        indicator = indicator
    )

    DarkModeContainer(modifier,whiteOverlayAlpha = .1f) {
        Column{
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
                    zoomState = rememberVicoZoomState(zoomEnabled = isZoomEnabled),
                    horizontalLayout = HorizontalLayout.FullWidth(
                        unscalableStartPaddingDp = 20f,
                        unscalableEndPaddingDp = 20f
                    ),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(spacing = 75.dp),
                        startAxis = rememberStartAxis(valueFormatter = startAxisValueFormatter),
                        bottomAxis = rememberBottomAxis(
                            label = rememberTextComponent(
                                color = Color.White.copy(alpha = .6f),
                                textSize = 12.sp,
                                padding = Dimensions.of(4.dp, 4.dp),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                            ),
                            labelRotationDegrees = -90f,
                            valueFormatter = bottomAxisValueFormatter
                        ),
                        persistentMarkers = if (markerPosition != null) mapOf(markerPosition.toFloat() to marker) else null,
                    ),
                    model = cartesianChartModel,
                    marker = marker,
                )
            }
        }
    }
}

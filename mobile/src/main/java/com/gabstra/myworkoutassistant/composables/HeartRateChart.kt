package com.gabstra.myworkoutassistant.composables

import android.text.Layout
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLabelComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisTickComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottomAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStartAxis
import com.patrykandpatrick.vico.compose.cartesian.decoration.rememberHorizontalLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.marker.rememberDefaultCartesianMarker
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.cartesian.segmented
import com.patrykandpatrick.vico.compose.common.component.rememberLayeredComponent
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent
import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.of
import com.patrykandpatrick.vico.compose.common.vicoTheme
import com.patrykandpatrick.vico.core.cartesian.HorizontalLayout
import com.patrykandpatrick.vico.core.cartesian.Zoom
import com.patrykandpatrick.vico.core.cartesian.axis.AxisItemPlacer
import com.patrykandpatrick.vico.core.cartesian.axis.BaseAxis
import com.patrykandpatrick.vico.core.cartesian.data.AxisValueOverrider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.CartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.DefaultCartesianMarkerValueFormatter
import com.patrykandpatrick.vico.core.cartesian.marker.LineCartesianLayerMarkerTarget
import com.patrykandpatrick.vico.core.common.Defaults
import com.patrykandpatrick.vico.core.common.Dimensions
import com.patrykandpatrick.vico.core.common.component.TextComponent
import com.patrykandpatrick.vico.core.common.shape.Shape

@Composable
fun HeartRateChart(
    modifier: Modifier = Modifier,
    cartesianChartModel: CartesianChartModel,
    title: String,
    userAge: Int,
    entriesCount: Int,
    isZoomEnabled: Boolean = true,
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
        label = rememberTextComponent(
            color = Color.White.copy(alpha = .87f),
            padding = Dimensions.of(8.dp),
            textAlignment = Layout.Alignment.ALIGN_CENTER
        ),
        guideline = rememberAxisGuidelineComponent(),
        indicatorSize = 10.dp,
        indicator = indicator
    )

    val bottomAxisValueFormatter = CartesianValueFormatter { value, _, _ ->
        formatTime((value / 2).toInt())
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
                    horizontalLayout = HorizontalLayout.FullWidth(
                        unscalableStartPaddingDp = 20f,
                        unscalableEndPaddingDp = 20f
                    ),
                    scrollState = rememberVicoScrollState(scrollEnabled = false),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(
                            axisValueOverrider = AxisValueOverrider.fixed(
                                null,
                                null,
                                50f,
                                200f
                            )
                        ),
                        decorations = listOf(
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(50f, userAge).toFloat() },
                                line = rememberLineComponent(
                                    color = Color.hsl(208f, 0.61f, 0.76f, .5f),
                                    thickness = 2.dp
                                ),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(60f, userAge).toFloat() },
                                line = rememberLineComponent(
                                    color = Color.hsl(200f, 0.66f, 0.49f, .5f),
                                    thickness = 2.dp
                                ),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(70f, userAge).toFloat() },
                                line = rememberLineComponent(
                                    color = Color.hsl(113f, 0.79f, 0.34f, .5f),
                                    thickness = 2.dp
                                ),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(80f, userAge).toFloat() },
                                line = rememberLineComponent(
                                    color = Color.hsl(27f, 0.97f, 0.54f, .5f),
                                    thickness = 2.dp
                                ),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(90f, userAge).toFloat() },
                                line = rememberLineComponent(
                                    color = Color.hsl(9f, 0.88f, 0.45f, .5f),
                                    thickness = 2.dp
                                ),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(100f, userAge).toFloat() },
                                line = rememberLineComponent(color = MaterialTheme.colorScheme.background, thickness = 2.dp),
                            ),
                        ),
                        bottomAxis = rememberBottomAxis(
                            guideline = null,
                            label = rememberTextComponent(
                                color = Color.White.copy(alpha = .6f),
                                textSize = 12.sp,
                                padding = Dimensions.of(4.dp, 4.dp),
                                textAlignment = Layout.Alignment.ALIGN_OPPOSITE,
                            ),
                            labelRotationDegrees = -90f,
                            valueFormatter = bottomAxisValueFormatter,
                            itemPlacer = remember {
                                AxisItemPlacer.Horizontal.default(
                                    spacing = 600,
                                    offset = 600
                                )
                            }
                        )
                    ),
                    model = cartesianChartModel,
                    marker = marker,
                )
            }
        }
    }
}
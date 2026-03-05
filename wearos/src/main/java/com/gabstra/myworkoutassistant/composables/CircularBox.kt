package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.Stable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.ParentDataModifier
import androidx.compose.ui.layout.SubcomposeLayout
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

@Immutable
private data class CircularBoxParentData(
    val verticalBias: Float = 0f,
    val horizontalAlignment: Alignment.Horizontal = Alignment.CenterHorizontally
)

private data class CircularBoxMeasuredChild(
    val placeable: androidx.compose.ui.layout.Placeable,
    val parentData: CircularBoxParentData,
    val dy: Float
)

@Stable
interface CircularBoxScope {
    fun Modifier.circularItem(
        verticalBias: Float = 0f,
        horizontalAlignment: Alignment.Horizontal = Alignment.CenterHorizontally
    ): Modifier
}

private object CircularBoxScopeInstance : CircularBoxScope {
    override fun Modifier.circularItem(
        verticalBias: Float,
        horizontalAlignment: Alignment.Horizontal
    ): Modifier =
        then(
            CircularItemParentDataModifier(
                verticalBias = verticalBias,
                horizontalAlignment = horizontalAlignment
            )
        )
}

private class CircularItemParentDataModifier(
    private val verticalBias: Float,
    private val horizontalAlignment: Alignment.Horizontal
) : ParentDataModifier {
    override fun Density.modifyParentData(parentData: Any?): Any {
        return CircularBoxParentData(
            verticalBias = verticalBias.coerceIn(-1f, 1f),
            horizontalAlignment = horizontalAlignment
        )
    }
}

/**
 * A circular container where each child receives a width constraint based on its vertical position.
 *
 * Child width is limited to the circle chord at the child's vertical bias. This makes children using
 * `fillMaxWidth()` naturally expand at center and retract toward top/bottom.
 */
@Composable
fun CircularBox(
    modifier: Modifier = Modifier,
    clipToCircle: Boolean = true,
    content: @Composable CircularBoxScope.() -> Unit
) {
    Layout(
        modifier = if (clipToCircle) modifier.clip(CircleShape) else modifier,
        content = { CircularBoxScopeInstance.content() }
    ) { measurables, constraints ->
        val layoutWidth = if (constraints.hasBoundedWidth) constraints.maxWidth else constraints.minWidth
        val layoutHeight = if (constraints.hasBoundedHeight) constraints.maxHeight else constraints.minHeight

        val diameter = min(layoutWidth, layoutHeight)
        val radius = diameter / 2f
        val centerY = layoutHeight / 2f

        val measuredChildren = measurables.map { measurable ->
            val parentData = (measurable.parentData as? CircularBoxParentData) ?: CircularBoxParentData()
            val dy = parentData.verticalBias * radius

            val chordSquared = (radius * radius - dy * dy).coerceAtLeast(0f)
            val maxWidthAtY = (2f * sqrt(chordSquared)).roundToInt()
                .coerceIn(0, layoutWidth)

            val placeable = measurable.measure(
                constraints.copy(
                    minWidth = 0,
                    maxWidth = maxWidthAtY,
                    minHeight = 0,
                    maxHeight = layoutHeight
                )
            )

            CircularBoxMeasuredChild(
                placeable = placeable,
                parentData = parentData,
                dy = dy
            )
        }

        layout(layoutWidth, layoutHeight) {
            measuredChildren.forEach { child ->
                val x = child.parentData.horizontalAlignment.align(
                    size = child.placeable.width,
                    space = layoutWidth,
                    layoutDirection = layoutDirection
                )

                val childCenterY = centerY + child.dy
                val y = (childCenterY - child.placeable.height / 2f).roundToInt()

                child.placeable.placeRelative(x = x, y = y)
            }
        }
    }
}

/**
 * A column-like circular container.
 *
 * Children are stacked like a regular Column and each child receives a width constraint based on
 * the circle chord at the child's vertical center. This allows `fillMaxWidth()` to automatically
 * expand near center and retract near top/bottom without per-child modifiers.
 */
@Composable
fun CircularColumn(
    modifier: Modifier = Modifier,
    verticalArrangement: Arrangement.Vertical = Arrangement.Top,
    horizontalAlignment: Alignment.Horizontal = Alignment.CenterHorizontally,
    clipToCircle: Boolean = true,
    content: @Composable () -> Unit
) {
    SubcomposeLayout(
        modifier = if (clipToCircle) modifier.clip(CircleShape) else modifier
    ) { constraints ->
        val layoutWidth = if (constraints.hasBoundedWidth) constraints.maxWidth else constraints.minWidth
        val layoutHeight = if (constraints.hasBoundedHeight) constraints.maxHeight else constraints.minHeight

        val diameter = min(layoutWidth, layoutHeight)
        val radius = diameter / 2f
        val centerY = layoutHeight / 2f

        val estimateMeasurables = subcompose(slotId = "estimate", content = content)
        val estimatePlaceables = estimateMeasurables.map { measurable ->
            measurable.measure(
                constraints.copy(
                    minWidth = 0,
                    maxWidth = diameter,
                    minHeight = 0,
                    maxHeight = layoutHeight
                )
            )
        }

        val firstHeights = IntArray(estimatePlaceables.size) { index -> estimatePlaceables[index].height }
        val firstY = IntArray(estimatePlaceables.size)
        with(verticalArrangement) {
            this@SubcomposeLayout.arrange(layoutHeight, firstHeights, firstY)
        }

        val finalMeasurables = subcompose(slotId = "final", content = content)
        val finalPlaceables = finalMeasurables.mapIndexed { index, measurable ->
            val estimatedCenterY = firstY[index] + firstHeights[index] / 2f
            val dy = estimatedCenterY - centerY
            val chordSquared = (radius * radius - dy * dy).coerceAtLeast(0f)
            val maxWidthAtY = (2f * sqrt(chordSquared)).roundToInt().coerceIn(0, layoutWidth)

            measurable.measure(
                constraints.copy(
                    minWidth = 0,
                    maxWidth = maxWidthAtY,
                    minHeight = 0,
                    maxHeight = layoutHeight
                )
            )
        }

        val secondHeights = IntArray(finalPlaceables.size) { index -> finalPlaceables[index].height }
        val finalY = IntArray(finalPlaceables.size)
        with(verticalArrangement) {
            this@SubcomposeLayout.arrange(layoutHeight, secondHeights, finalY)
        }

        layout(layoutWidth, layoutHeight) {
            finalPlaceables.forEachIndexed { index, placeable ->
                val x = horizontalAlignment.align(
                    size = placeable.width,
                    space = layoutWidth,
                    layoutDirection = layoutDirection
                )
                placeable.placeRelative(x = x, y = finalY[index])
            }
        }
    }
}

/**
 * A column-like capsule container (horizontal stadium).
 *
 * Children are stacked like a regular Column and each child receives a width constraint based on
 * the capsule width at the child's vertical center. This keeps full width in the middle band and
 * smoothly narrows near top/bottom rounded caps.
 */
@Composable
fun CapsuleColumn(
    modifier: Modifier = Modifier,
    verticalArrangement: Arrangement.Vertical = Arrangement.Top,
    horizontalAlignment: Alignment.Horizontal = Alignment.CenterHorizontally,
    clipToCapsule: Boolean = true,
    content: @Composable () -> Unit
) {
    SubcomposeLayout(
        modifier = if (clipToCapsule) modifier.clip(RoundedCornerShape(percent = 50)) else modifier
    ) { constraints ->
        val layoutWidth = if (constraints.hasBoundedWidth) constraints.maxWidth else constraints.minWidth
        val layoutHeight = if (constraints.hasBoundedHeight) constraints.maxHeight else constraints.minHeight

        val radius = layoutHeight / 2f
        val centerY = layoutHeight / 2f
        val bodyWidth = (layoutWidth - 2f * radius).coerceAtLeast(0f)

        val estimateMeasurables = subcompose(slotId = "capsuleEstimate", content = content)
        val estimatePlaceables = estimateMeasurables.map { measurable ->
            measurable.measure(
                constraints.copy(
                    minWidth = 0,
                    maxWidth = layoutWidth,
                    minHeight = 0,
                    maxHeight = layoutHeight
                )
            )
        }

        val firstHeights = IntArray(estimatePlaceables.size) { index -> estimatePlaceables[index].height }
        val firstY = IntArray(estimatePlaceables.size)
        with(verticalArrangement) {
            this@SubcomposeLayout.arrange(layoutHeight, firstHeights, firstY)
        }

        val finalMeasurables = subcompose(slotId = "capsuleFinal", content = content)
        val finalPlaceables = finalMeasurables.mapIndexed { index, measurable ->
            val estimatedCenterY = firstY[index] + firstHeights[index] / 2f
            val dy = abs(estimatedCenterY - centerY)
            val capHalfWidth = sqrt((radius * radius - dy * dy).coerceAtLeast(0f))
            val maxWidthAtY = (bodyWidth + 2f * capHalfWidth).roundToInt().coerceIn(0, layoutWidth)

            measurable.measure(
                constraints.copy(
                    minWidth = 0,
                    maxWidth = maxWidthAtY,
                    minHeight = 0,
                    maxHeight = layoutHeight
                )
            )
        }

        val secondHeights = IntArray(finalPlaceables.size) { index -> finalPlaceables[index].height }
        val finalY = IntArray(finalPlaceables.size)
        with(verticalArrangement) {
            this@SubcomposeLayout.arrange(layoutHeight, secondHeights, finalY)
        }

        layout(layoutWidth, layoutHeight) {
            finalPlaceables.forEachIndexed { index, placeable ->
                val x = horizontalAlignment.align(
                    size = placeable.width,
                    space = layoutWidth,
                    layoutDirection = layoutDirection
                )
                placeable.placeRelative(x = x, y = finalY[index])
            }
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun CircularBoxPreview() {
    MaterialTheme(colorScheme = darkScheme, typography = baseline) {
        CircularBox(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
        ) {
            Box(
                modifier = Modifier
                    .circularItem(verticalBias = -0.65f)
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.error)
            )
            Box(
                modifier = Modifier
                    .circularItem(verticalBias = 0f)
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.primary)
            )
            Box(
                modifier = Modifier
                    .circularItem(verticalBias = 0.65f)
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.secondary)
            )
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun CircularColumnPreview() {
    MaterialTheme(colorScheme = darkScheme, typography = baseline) {
        CircularColumn(
            modifier = Modifier
                .fillMaxSize()
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.onError)
                .padding(horizontal = 8.dp),
            verticalArrangement = Arrangement.Top
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.error)
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.primary),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "CENTER",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(22.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.secondary)
            )
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun CapsuleColumnPreview() {
    MaterialTheme(colorScheme = darkScheme, typography = baseline) {
        CapsuleColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 8.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.SpaceEvenly
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(20.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.error)
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(20.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.primary),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "CAPSULE",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(20.dp)
                    .clip(RoundedCornerShape(percent = 50))
                    .background(MaterialTheme.colorScheme.secondary)
            )
        }
    }
}

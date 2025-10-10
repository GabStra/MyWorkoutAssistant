package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp

class CircularEndsPillShape(
    private val edgeRadius: Dp? = null,      // optional fixed circle radius
    private val straightWidth: Dp? = null    // width of the center rectangle (dp)
) : Shape {

    override fun createOutline(
        size: androidx.compose.ui.geometry.Size,
        layoutDirection: androidx.compose.ui.unit.LayoutDirection,
        density: Density
    ): Outline {
        val h = size.height
        val cy = h / 2f
        val straightPx = straightWidth?.let { with(density) { it.toPx() } }

        // If radius not provided, derive from straightWidth (or default to h/2)
        val r = edgeRadius?.let { with(density) { it.toPx() } } ?: run {
            straightPx?.let { ((size.width - it) / 2f) } ?: (h / 2f)
        }.coerceAtLeast(0f).coerceAtMost(h / 2f)

        // Actual straight segment after clamping
        val straight = (size.width - 2f * r).coerceAtLeast(0f)

        // Center the straight segment
        val leftX = (size.width - straight) / 2f
        val rightX = leftX + straight

        val path = Path().apply {
            // middle rectangle
            addRect(Rect(leftX, 0f, rightX, h))
            // left circle (center at leftX)
            addOval(Rect(leftX - r, 0f, leftX + r, h))
            // right circle (center at rightX)
            addOval(Rect(rightX - r, 0f, rightX + r, h))
        }
        return Outline.Generic(path)
    }
}
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.withTransform
import com.gabstra.myworkoutassistant.shared.MaleMusclePathProvider
import com.gabstra.myworkoutassistant.shared.MuscleGroup

enum class MuscleViewMode {
    FRONT_ONLY,
    BACK_ONLY,
    BOTH
}

@Composable
fun MuscleHeatMap(
    modifier: Modifier = Modifier,
    activeMuscles: Set<MuscleGroup>,
    secondaryMuscles: Set<MuscleGroup> = emptySet(),
    viewMode: MuscleViewMode = MuscleViewMode.BOTH, // Default to showing both
    highlightColor: Color = Color(0xFFFF8C00), // Orange
    secondaryHighlightColor: Color = Color(0xFFFF8C00).copy(alpha = 0.6f), // Lighter orange
    baseColor: Color = Color(0xFFF0E0D6),      // Flesh/Pale
    outlineColor: Color = Color.Black
) {
    // 1. Load Data
    val frontPaths = remember { MaleMusclePathProvider.getFrontMusclePaths() }
    val backPaths = remember { MaleMusclePathProvider.getBackMusclePaths() }
    val outlineFront = remember { MaleMusclePathProvider.BODY_OUTLINE_FRONT }
    val outlineBack = remember { MaleMusclePathProvider.BODY_OUTLINE_BACK }

    // 2. Define Viewport Constants
    val virtualHeight = 1530f

    // Width for a single body view (with margins)
    val singleBodyWidth = 750f
    // Width for the full double body view
    val fullDoubleBodyWidth = 1450f

    // Center X coordinates for specific targets (based on SVG data)
    val centerOfFront = 360f
    val centerOfBack = 1085f
    val centerOfBoth = 725f // Middle of the total width

    // 3. Determine "Camera" Settings based on Mode
    val (virtualWidth, targetCenterX) = when (viewMode) {
        MuscleViewMode.FRONT_ONLY -> Pair(singleBodyWidth, centerOfFront)
        MuscleViewMode.BACK_ONLY -> Pair(singleBodyWidth, centerOfBack)
        MuscleViewMode.BOTH -> Pair(fullDoubleBodyWidth, centerOfBoth)
    }

    val targetCenterY = 765f // Middle of height

    Canvas(modifier = modifier) {
        // 4. Calculate Scale
        // Fit the chosen virtual width into the available screen width
        val scaleX = size.width / virtualWidth
        val scaleY = size.height / virtualHeight
        val scale = minOf(scaleX, scaleY)

        withTransform({
            // Center the canvas
            translate(left = size.width / 2f, top = size.height / 2f)
            // Apply Zoom
            scale(scale, pivot = Offset.Zero)
            // Move camera to specific target (Front, Back, or Middle)
            translate(left = -targetCenterX, top = -targetCenterY)
        }) {

           // 5. Draw Front (If applicable)
            if (viewMode == MuscleViewMode.FRONT_ONLY || viewMode == MuscleViewMode.BOTH) {
                // Base
                drawPath(path = outlineFront, color = baseColor)
                // Secondary muscles first (so they don't obscure primary)
                frontPaths.forEach { (muscle, path) ->
                    if (secondaryMuscles.contains(muscle) && !activeMuscles.contains(muscle)) {
                        drawPath(path = path, color = secondaryHighlightColor)
                        drawPath(path = path, color = outlineColor, style = Stroke(width = 1f/scale))
                    }
                }
                // Primary muscles
                frontPaths.forEach { (muscle, path) ->
                    if (activeMuscles.contains(muscle)) {
                        drawPath(path = path, color = highlightColor)
                        drawPath(path = path, color = outlineColor, style = Stroke(width = 1f/scale))
                    }
                }
            }

            // 6. Draw Back (If applicable)
            if (viewMode == MuscleViewMode.BACK_ONLY || viewMode == MuscleViewMode.BOTH) {
                // Base
                drawPath(path = outlineBack, color = baseColor)
                // Secondary muscles first (so they don't obscure primary)
                backPaths.forEach { (muscle, path) ->
                    if (secondaryMuscles.contains(muscle) && !activeMuscles.contains(muscle)) {
                        drawPath(path = path, color = secondaryHighlightColor)
                        drawPath(path = path, color = outlineColor, style = Stroke(width = 1f/scale))
                    }
                }
                // Primary muscles
                backPaths.forEach { (muscle, path) ->
                    if (activeMuscles.contains(muscle)) {
                        drawPath(path = path, color = highlightColor)
                        drawPath(path = path, color = outlineColor, style = Stroke(width = 1f/scale))
                    }
                }
            }
        }
    }
}


package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.MusclePathProvider
import com.gabstra.myworkoutassistant.shared.Orange

@Composable
fun MuscleHeatMap(
    modifier: Modifier = Modifier,
    activeMuscles: Set<MuscleGroup>,
    highlightColor: Color = Orange, // Red
    baseColor: Color = LightGray, // Pale Pink/Flesh
    outlineColor: Color = Color.Black
) {
    // Load paths once
    val musclePaths = remember { MusclePathProvider.getMusclePaths() }

    // Our virtual grid includes the front (0-100) and back (120-220).
    // Total virtual width = ~230f. Total virtual height = ~260f.
    val virtualWidth = 230f
    val virtualHeight = 260f

    Canvas(modifier = modifier.fillMaxSize().padding(8.dp)) {
        // Calculate scaling to fit the Watch screen
        val scaleX = size.width / virtualWidth
        val scaleY = size.height / virtualHeight
        val scale = minOf(scaleX, scaleY) * 0.9f // 0.9f for a little margin

        // Center the drawing
        val translateX = (size.width - (virtualWidth * scale)) / 2f
        val translateY = (size.height - (virtualHeight * scale)) / 2f

        translate(left = translateX, top = translateY) {
            scale(scale, pivot = Offset.Zero) {

                // Draw Head (Decoration only - not a muscle)
                drawCircle(color = baseColor, center = Offset(50f, 25f), radius = 15f) // Front Head
                drawCircle(color = outlineColor, center = Offset(50f, 25f), radius = 15f, style = Stroke(1.5f))

                drawCircle(color = baseColor, center = Offset(170f, 25f), radius = 15f) // Back Head (120+50)
                drawCircle(color = outlineColor, center = Offset(170f, 25f), radius = 15f, style = Stroke(1.5f))

                // Draw all muscles
                musclePaths.forEach { (muscle, path) ->
                    val isActive = activeMuscles.contains(muscle)
                    val fillColor = if (isActive) highlightColor else baseColor

                    // 1. Fill
                    drawPath(
                        path = path,
                        color = fillColor
                    )

                    // 2. Outline
                    drawPath(
                        path = path,
                        color = outlineColor,
                        style = Stroke(width = 2f) // Black border
                    )
                }
            }
        }
    }
}
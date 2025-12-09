package com.gabstra.myworkoutassistant.composables

import android.graphics.RectF
import android.graphics.Region
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.MusclePathProvider
import com.gabstra.myworkoutassistant.shared.Orange
import kotlin.math.roundToInt

enum class BodyView {
    FRONT,
    BACK
}

fun Path.contains(offset: Offset): Boolean {
    // 1. Convert Compose Path to Android native Path
    val androidPath = this.asAndroidPath()

    // 2. Create a Region to check for containment
    val rectF = RectF()
    androidPath.computeBounds(rectF, true)

    val region = Region()
    region.setPath(
        androidPath,
        Region(
            rectF.left.toInt(),
            rectF.top.toInt(),
            rectF.right.toInt(),
            rectF.bottom.toInt()
        )
    )

    // 3. Check if point is inside
    return region.contains(offset.x.roundToInt(), offset.y.roundToInt())
}

@Composable
fun InteractiveMuscleHeatMap(
    modifier: Modifier = Modifier,
    selectedMuscles: Set<MuscleGroup>,
    onMuscleToggled: (MuscleGroup) -> Unit,
    currentView: BodyView,
    highlightColor: Color = Orange,
    baseColor: Color = LightGray,
    outlineColor: Color = Color.Black
) {
    // Load paths once
    val musclePaths = remember { MusclePathProvider.getMusclePaths() }
    
    // Filter muscles based on current view
    val frontMuscles = setOf(
        MuscleGroup.TRAPEZIUS_FRONT,   
        MuscleGroup.ANTERIOR_DELTOIDS,
        MuscleGroup.MIDDLE_DELTOIDS,   
        MuscleGroup.PECTORALS,
        MuscleGroup.SERRATUS_ANTERIOR,
        MuscleGroup.ABDOMINALS,
        MuscleGroup.OBLIQUES,
        MuscleGroup.BICEPS,
        MuscleGroup.FOREARMS,
        MuscleGroup.ADDUCTORS,         
        MuscleGroup.QUADRICEPS,
        MuscleGroup.TIBIALIS
    )

    val backMuscles = setOf(
        MuscleGroup.TRAPEZIUS,         
        MuscleGroup.POSTERIOR_DELTOIDS,
        MuscleGroup.LATISSIMUS,
        MuscleGroup.TRICEPS,
        MuscleGroup.ERECTORS,
        MuscleGroup.GLUTES,
        MuscleGroup.ABDUCTORS,        
        MuscleGroup.HAMSTRINGS,
        MuscleGroup.CALVES
    )
    
    val visibleMuscles = if (currentView == BodyView.FRONT) frontMuscles else backMuscles
    
    // Virtual dimensions for the current view
    val virtualWidth = if (currentView == BodyView.FRONT) 100f else 100f
    val virtualHeight = 260f
    val backOffsetX = 120f // Offset for back muscles
    
    Box(modifier = modifier) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(300.dp)
                .pointerInput(Unit) {
                    detectTapGestures { tapOffset ->
                        // Transform tap coordinates to virtual coordinates
                        val scaleX = size.width / virtualWidth
                        val scaleY = size.height / virtualHeight
                        val scale = minOf(scaleX, scaleY) * 0.9f
                        
                        val translateX = (size.width - (virtualWidth * scale)) / 2f
                        val translateY = (size.height - (virtualHeight * scale)) / 2f
                        
                        // Convert tap coordinates to virtual coordinates
                        val virtualX = (tapOffset.x - translateX) / scale
                        val virtualY = (tapOffset.y - translateY) / scale
                        
                        // For back view, we need to add the offset to match the path coordinates
                        // For front view, paths are in 0-100 range, so use virtualX directly
                        val checkX = if (currentView == BodyView.BACK) {
                            virtualX + backOffsetX
                        } else {
                            virtualX
                        }
                        val checkPoint = Offset(checkX, virtualY)
                        
                        // Check each muscle path in reverse order (last drawn = top)
                        // to handle overlapping muscles correctly
                        val musclesInView = musclePaths.entries
                            .filter { (muscle, _) -> visibleMuscles.contains(muscle) }
                            .reversed()
                        
                        for ((muscle, path) in musclesInView) {
                            if (path.contains(checkPoint)) {
                                onMuscleToggled(muscle)
                                break
                            }
                        }
                    }
                }
        ) {
            // Calculate scaling to fit the canvas
            val scaleX = size.width / virtualWidth
            val scaleY = size.height / virtualHeight
            val scale = minOf(scaleX, scaleY) * 0.9f
            
            // Center the drawing
            val translateX = (size.width - (virtualWidth * scale)) / 2f
            val translateY = (size.height - (virtualHeight * scale)) / 2f
            
            translate(left = translateX, top = translateY) {
                scale(scale, pivot = Offset.Zero) {
                    if (currentView == BodyView.BACK) {
                        // For back view, translate the drawing to account for the offset
                        translate(left = -backOffsetX, top = 0f) {
                            // Draw Head (Decoration only - not a muscle)
                            drawCircle(color = baseColor, center = Offset(50f + backOffsetX, 25f), radius = 15f)
                            drawCircle(color = outlineColor, center = Offset(50f + backOffsetX, 25f), radius = 15f, style = Stroke(1.5f))
                            
                            // Draw visible muscles
                            musclePaths.forEach { (muscle, path) ->
                                if (!visibleMuscles.contains(muscle)) return@forEach
                                
                                val isSelected = selectedMuscles.contains(muscle)
                                val fillColor = if (isSelected) highlightColor else baseColor
                                
                                // 1. Fill
                                drawPath(
                                    path = path,
                                    color = fillColor
                                )
                                
                                // 2. Outline
                                drawPath(
                                    path = path,
                                    color = outlineColor,
                                    style = Stroke(width = 2f)
                                )
                            }
                        }
                    } else {
                        // For front view, draw normally
                        // Draw Head (Decoration only - not a muscle)
                        drawCircle(color = baseColor, center = Offset(50f, 25f), radius = 15f)
                        drawCircle(color = outlineColor, center = Offset(50f, 25f), radius = 15f, style = Stroke(1.5f))
                        
                        // Draw visible muscles
                        musclePaths.forEach { (muscle, path) ->
                            if (!visibleMuscles.contains(muscle)) return@forEach
                            
                            val isSelected = selectedMuscles.contains(muscle)
                            val fillColor = if (isSelected) highlightColor else baseColor
                            
                            // 1. Fill
                            drawPath(
                                path = path,
                                color = fillColor
                            )
                            
                            // 2. Outline
                            drawPath(
                                path = path,
                                color = outlineColor,
                                style = Stroke(width = 2f)
                            )
                        }
                    }
                }
            }
        }
    }
}


package com.gabstra.myworkoutassistant.composables

import android.graphics.RectF
import android.graphics.Region
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import com.gabstra.myworkoutassistant.shared.MaleMusclePathProvider
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.MuscleHeatMapBackground
import com.gabstra.myworkoutassistant.shared.PrimaryMuscleGroupColor
import com.gabstra.myworkoutassistant.shared.SecondaryMuscleGroupColor
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
    selectedSecondaryMuscles: Set<MuscleGroup> = emptySet(),
    onMuscleToggled: (MuscleGroup) -> Unit,
    onSecondaryMuscleToggled: ((MuscleGroup) -> Unit)? = null,
    currentView: BodyView,
    highlightColor: Color = PrimaryMuscleGroupColor,
    secondaryHighlightColor: Color = SecondaryMuscleGroupColor,
    baseColor: Color = MuscleHeatMapBackground,
) {
    // Load paths once
    val frontPaths = remember { MaleMusclePathProvider.getFrontMusclePaths() }
    val backPaths = remember { MaleMusclePathProvider.getBackMusclePaths() }
    val outlineFront = remember { MaleMusclePathProvider.BODY_OUTLINE_FRONT }
    val outlineBack = remember { MaleMusclePathProvider.BODY_OUTLINE_BACK }

    // Define Viewport Constants
    val virtualHeight = 1450f

    // Width for a single body view (with margins)
    val singleBodyWidth = 750f

    // Center X coordinates for specific targets (based on SVG data)
    // These are the actual centers of each view in the SVG coordinate system
    val centerOfFront = 360f
    val centerOfBack = 1085f

    // Determine "Camera" Settings based on View
    // Use the actual SVG center coordinates, but ensure both views use the same virtual width
    // for consistent scaling and alignment
    val virtualWidth = singleBodyWidth
    val targetCenterX = when (currentView) {
        BodyView.FRONT -> centerOfFront
        BodyView.BACK -> centerOfBack
    }

    val targetCenterY = 765f // Middle of height
    
    val aspectRatio = virtualWidth / virtualHeight

    Box(modifier = modifier) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(aspectRatio)
                .pointerInput(currentView, frontPaths, backPaths) {
                    detectTapGestures { tapOffset ->
                        // Calculate the same transformation as in drawing
                        // Use scaleX to fill full width horizontally
                        val scaleX = size.width / virtualWidth
                        val scaleY = size.height / virtualHeight
                        val scale = scaleX // Use horizontal scale to fill width
                        
                        // Reverse the transformation pipeline
                        // 1. Start from screen coordinates
                        // 2. Translate to center
                        val centeredX = tapOffset.x - size.width / 2f
                        val centeredY = tapOffset.y - size.height / 2f
                        
                        // 3. Scale back
                        val scaledX = centeredX / scale
                        val scaledY = centeredY / scale
                        
                        // 4. Translate to target center
                        val virtualX = scaledX + targetCenterX
                        val virtualY = scaledY + targetCenterY
                        
                        val checkPoint = Offset(virtualX, virtualY)
                        
                        // Get the appropriate path map based on current view
                        val pathsToCheck = if (currentView == BodyView.FRONT) {
                            frontPaths.entries.reversed()
                        } else {
                            backPaths.entries.reversed()
                        }
                        
                        // Check each muscle path in reverse order (last drawn = top)
                        // to handle overlapping muscles correctly
                        for ((muscle, path) in pathsToCheck) {
                            if (path.contains(checkPoint)) {
                                // Check if it's a secondary muscle first
                                if (selectedSecondaryMuscles.contains(muscle) && onSecondaryMuscleToggled != null) {
                                    onSecondaryMuscleToggled(muscle)
                                } else {
                                    onMuscleToggled(muscle)
                                }
                                break
                            }
                        }
                    }
                }
        ) {
            // Calculate Scale
            // Use scaleX to fill the full available width horizontally
            val scaleX = size.width / virtualWidth
            val scaleY = size.height / virtualHeight
            val scale = scaleX // Use horizontal scale to fill width

            clipRect {
                withTransform({
                    // Center the canvas
                    translate(left = size.width / 2f, top = size.height / 2f)
                    // Apply Zoom
                    scale(scale, pivot = Offset.Zero)
                    // Move camera to specific target (Front or Back)
                    translate(left = -targetCenterX, top = -targetCenterY)
                }) {
                    // Draw Front (If applicable)
                    if (currentView == BodyView.FRONT) {
                        // Base
                        drawPath(path = outlineFront, color = baseColor)
                        // Muscles
                        frontPaths.forEach { (muscle, path) ->
                            val isPrimarySelected = selectedMuscles.contains(muscle)
                            val isSecondarySelected = selectedSecondaryMuscles.contains(muscle) && !isPrimarySelected
                            val fillColor = when {
                                isPrimarySelected -> highlightColor
                                isSecondarySelected -> secondaryHighlightColor
                                else -> baseColor
                            }

                            drawPath(path = path, color = fillColor)
                        }
                    }

                    // Draw Back (If applicable)
                    if (currentView == BodyView.BACK) {
                        // Base
                        drawPath(path = outlineBack, color = baseColor)
                        // Muscles
                        backPaths.forEach { (muscle, path) ->
                            val isPrimarySelected = selectedMuscles.contains(muscle)
                            val isSecondarySelected = selectedSecondaryMuscles.contains(muscle) && !isPrimarySelected
                            val fillColor = when {
                                isPrimarySelected -> highlightColor
                                isSecondarySelected -> secondaryHighlightColor
                                else -> baseColor
                            }

                            drawPath(path = path, color = fillColor)
                        }
                    }
                }
            }
        }
    }
}


package com.gabstra.myworkoutassistant.composables

import android.graphics.RectF
import android.graphics.Region
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import com.gabstra.myworkoutassistant.shared.MaleMusclePathProvider
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.MuscleHeatMapBackground
import com.gabstra.myworkoutassistant.shared.PrimaryMuscleGroupColor
import com.gabstra.myworkoutassistant.shared.SecondaryMuscleGroupColor
import kotlin.math.floor
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

private const val CONTENT_WIDTH = 1450f
private const val CONTENT_HEIGHT = 1450f
private const val GRID_STEP = 100f
private const val MIN_SCALE = 0.5f
private const val MAX_SCALE = 4f

@Composable
fun ZoomableMuscleHeatMap(
    modifier: Modifier = Modifier,
    selectedMuscles: Set<MuscleGroup>,
    selectedSecondaryMuscles: Set<MuscleGroup> = emptySet(),
    onMuscleToggled: (MuscleGroup) -> Unit,
    onSecondaryMuscleToggled: ((MuscleGroup) -> Unit)? = null,
    highlightColor: Color = PrimaryMuscleGroupColor,
    secondaryHighlightColor: Color = SecondaryMuscleGroupColor,
    baseColor: Color = MuscleHeatMapBackground,
    gridColor: Color? = null,
    resetTrigger: Int = 0,
) {
    val frontPaths = remember { MaleMusclePathProvider.getFrontMusclePaths() }
    val backPaths = remember { MaleMusclePathProvider.getBackMusclePaths() }
    val outlineFront = remember { MaleMusclePathProvider.BODY_OUTLINE_FRONT }
    val outlineBack = remember { MaleMusclePathProvider.BODY_OUTLINE_BACK }

    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    var layoutSize by remember { mutableStateOf(IntSize.Zero) }
    var initialized by remember { mutableStateOf(false) }

    fun fitScaleAndOffset(size: IntSize): Pair<Float, Offset> {
        if (size.width <= 0 || size.height <= 0) return scale to offset
        val fitScale = minOf(
            size.width / CONTENT_WIDTH,
            size.height / CONTENT_HEIGHT
        )
        val fitOffset = Offset(
            size.width / 2f - (CONTENT_WIDTH / 2f) * fitScale,
            size.height / 2f - (CONTENT_HEIGHT / 2f) * fitScale
        )
        return fitScale to fitOffset
    }

    LaunchedEffect(resetTrigger) {
        if (resetTrigger > 0 && layoutSize.width > 0 && layoutSize.height > 0) {
            val (fitScale, fitOffset) = fitScaleAndOffset(layoutSize)
            scale = fitScale
            offset = fitOffset
        }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .aspectRatio(CONTENT_WIDTH / CONTENT_HEIGHT)
            .onSizeChanged { size ->
                layoutSize = IntSize(size.width, size.height)
                if (!initialized && size.width > 0 && size.height > 0) {
                    val (fitScale, fitOffset) = fitScaleAndOffset(IntSize(size.width, size.height))
                    scale = fitScale
                    offset = fitOffset
                    initialized = true
                }
            }
            .pointerInput(Unit) {
                detectTransformGestures(panZoomLock = true) { centroid, pan, zoom, _ ->
                    val scaleOld = scale
                    val scaleNew = (scale * zoom).coerceIn(MIN_SCALE, MAX_SCALE)
                    scale = scaleNew
                    offset = centroid - (centroid - offset) * scaleNew / scaleOld
                    if (zoom == 1f) {
                        offset += pan
                    }
                }
            }
            .pointerInput(scale, offset) {
                detectTapGestures { tapOffset ->
                    val contentX = (tapOffset.x - offset.x) / scale
                    val contentY = (tapOffset.y - offset.y) / scale
                    val checkPoint = Offset(contentX, contentY)

                    val pathsToCheck = frontPaths.entries.reversed() + backPaths.entries.reversed()
                    for ((muscle, path) in pathsToCheck) {
                        if (path.contains(checkPoint)) {
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
        val gridColorResolved = gridColor ?: MaterialTheme.colorScheme.outline.copy(alpha = 0.45f)
        Canvas(modifier = Modifier.fillMaxSize()) {
            clipRect {
                withTransform({
                    translate(left = offset.x, top = offset.y)
                    scale(scale, pivot = Offset.Zero)
                }) {
                    // Grid (behind figures)
                    val visibleMinX = (-offset.x) / scale
                    val visibleMaxX = (size.width - offset.x) / scale
                    val visibleMinY = (-offset.y) / scale
                    val visibleMaxY = (size.height - offset.y) / scale

                    val xStart = floor(visibleMinX / GRID_STEP) * GRID_STEP
                    val yStart = floor(visibleMinY / GRID_STEP) * GRID_STEP
                    val xEnd = visibleMaxX + GRID_STEP
                    val yEnd = visibleMaxY + GRID_STEP

                    var x = xStart
                    while (x <= xEnd) {
                        drawLine(
                            color = gridColorResolved,
                            start = Offset(x, visibleMinY - GRID_STEP),
                            end = Offset(x, yEnd)
                        )
                        x += GRID_STEP
                    }
                    var y = yStart
                    while (y <= yEnd) {
                        drawLine(
                            color = gridColorResolved,
                            start = Offset(visibleMinX - GRID_STEP, y),
                            end = Offset(xEnd, y)
                        )
                        y += GRID_STEP
                    }

                    // Front outline + muscles
                    drawPath(path = outlineFront, color = baseColor)
                    frontPaths.forEach { (muscle, path) ->
                        val isPrimarySelected = selectedMuscles.contains(muscle)
                        val isSecondarySelected =
                            selectedSecondaryMuscles.contains(muscle) && !isPrimarySelected
                        val fillColor = when {
                            isPrimarySelected -> highlightColor
                            isSecondarySelected -> secondaryHighlightColor
                            else -> baseColor
                        }
                        drawPath(path = path, color = fillColor)
                    }

                    // Back outline + muscles
                    drawPath(path = outlineBack, color = baseColor)
                    backPaths.forEach { (muscle, path) ->
                        val isPrimarySelected = selectedMuscles.contains(muscle)
                        val isSecondarySelected =
                            selectedSecondaryMuscles.contains(muscle) && !isPrimarySelected
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



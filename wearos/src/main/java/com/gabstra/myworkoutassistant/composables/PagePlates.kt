package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.delay
import kotlin.math.sqrt

private fun Double.compact(): String {
    val s = String.format("%.2f", this).replace(',', '.')
    return s.trimEnd('0').trimEnd('.')
}

@SuppressLint("DefaultLocale")
@Composable
fun PagePlates(
    updatedState: WorkoutState.Set,
    equipment: WeightLoadedEquipment?,
    hapticsViewModel: HapticsViewModel
) {
    var headerMarqueeEnabled by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            text = "Loading Guide",
            style = MaterialTheme.typography.titleSmall,
            textAlign = TextAlign.Center
        )

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "NOT AVAILABLE",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center
            )
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                val previousSideWeightTotal =
                    remember(updatedState.plateChangeResult!!.previousPlates) {
                        updatedState.plateChangeResult!!.previousPlates.sum().round(2)
                    }
                val currentSideWeightTotal =
                    remember(updatedState.plateChangeResult!!.currentPlates) {
                        updatedState.plateChangeResult!!.currentPlates.sum().round(2)
                    }

                val previousWeightTotal = remember(
                    equipment.barWeight,
                    previousSideWeightTotal
                ) { (equipment.barWeight + (previousSideWeightTotal * 2)).round(2) }
                val currentWeightTotal = remember(
                    equipment.barWeight,
                    currentSideWeightTotal
                ) { (equipment.barWeight + (currentSideWeightTotal * 2)).round(2) }

                if (previousSideWeightTotal.isEqualTo(currentSideWeightTotal) || previousSideWeightTotal == 0.0) {
                    val topLine = buildAnnotatedString {
                        fun pipe() {
                            withStyle(
                                SpanStyle(
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(" • ")
                            }
                        }

                        append("Σ ${formatWeight(currentWeightTotal)}")
                        pipe()
                        append("Bar ${formatWeight(equipment.barWeight)}")
                    }

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        modifier = Modifier
                            .clickable {
                                headerMarqueeEnabled = !headerMarqueeEnabled
                                hapticsViewModel.doGentleVibration()
                            }
                            .then(
                                if (headerMarqueeEnabled)
                                    Modifier.basicMarquee(iterations = Int.MAX_VALUE)
                                else
                                    Modifier
                            )
                    )
                } else {
                    val topLine = buildAnnotatedString {
                        fun pipe() {
                            withStyle(
                                SpanStyle(
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(" • ")
                            }
                        }

                        append("Σ ${formatWeight(previousWeightTotal)}")
                        append(" → ")
                        append("${formatWeight(currentWeightTotal)}")
                        pipe()
                        append("Bar ${formatWeight(equipment.barWeight)}")
                    }

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        modifier = Modifier
                            .clickable {
                                headerMarqueeEnabled = !headerMarqueeEnabled
                                hapticsViewModel.doGentleVibration()
                            }
                            .then(
                                if (headerMarqueeEnabled)
                                    Modifier.basicMarquee(iterations = Int.MAX_VALUE)
                                else
                                    Modifier
                            )
                    )
                }
            }

            // Visual barbell representation with animation
            val plateChangeResult = updatedState.plateChangeResult!!
            val steps = plateChangeResult.change.steps

            // Index of the current step being animated (or -1 when idle)
            var currentStepIndex by remember(plateChangeResult) { mutableIntStateOf(-1) }

            // We keep track of the *actual* plates currently shown on the bar.
            // This lets us always start the animation from the current state instead of
            // reconstructing everything from an implicit empty bar or looping forever.
            var animatedPlates by remember(plateChangeResult) {
                mutableStateOf(plateChangeResult.previousPlates.sortedDescending())
            }
            
            // Track which specific plate instance is currently being added or removed
            // We need to identify which instance among multiple plates of the same weight
            val activePlateInfo = remember(currentStepIndex, steps, animatedPlates) {
                if (currentStepIndex >= 0 && currentStepIndex < steps.size) {
                    val step = steps[currentStepIndex]
                    
                    // Calculate plates state before current step
                    val platesBeforeStep = if (currentStepIndex > 0) {
                        val before = plateChangeResult.previousPlates.toMutableList()
                        for (i in 0 until currentStepIndex) {
                            val s = steps[i]
                            when (s.action) {
                                PlateCalculator.Companion.Action.ADD -> before.add(s.weight)
                                PlateCalculator.Companion.Action.REMOVE -> before.remove(s.weight)
                            }
                        }
                        before.sortedDescending()
                    } else {
                        plateChangeResult.previousPlates.sortedDescending()
                    }
                    
                    // Count how many plates of this weight exist before the current step
                    val countBefore = platesBeforeStep.count { it == step.weight }
                    
                    // For ADD: the new plate will be at position countBefore in the sorted list of same-weight plates
                    // For REMOVE: we remove the plate from the end (outermost), which is the last instance
                    val instanceIndex = when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> countBefore // New plate will be at this index (0-indexed)
                        PlateCalculator.Companion.Action.REMOVE -> {
                            // For REMOVE, the algorithm removes from the end (outermost)
                            // In sorted descending order, this is the last instance of that weight
                            // If countBefore is 2 (instances 0 and 1), we remove instance 1 (the last one)
                            countBefore - 1
                        }
                    }
                    
                    Triple(step.weight, step.action, instanceIndex)
                } else {
                    null
                }
            }
            
            // Animate the plate changes
            LaunchedEffect(plateChangeResult) {
                // If there are no steps we just show the current configuration and do not animate.
                if (steps.isEmpty()) {
                    currentStepIndex = -1
                    animatedPlates = plateChangeResult.currentPlates.sortedDescending()
                    return@LaunchedEffect
                }

                // Start from the *current* bar configuration for this transition.
                // This is the configuration the user should already have on the barbell.
                animatedPlates = plateChangeResult.previousPlates.sortedDescending()
                currentStepIndex = -1

                // Small initial pause so the user can see the starting point.
                delay(500)

                // Walk the sequence of physical steps exactly once, applying the
                // delta to the currently drawn plates instead of restarting from empty.
                for (stepIndex in steps.indices) {
                    val step = steps[stepIndex]
                    currentStepIndex = stepIndex

                    // Apply this step to the current animated plates.
                    animatedPlates = animatedPlates.toMutableList().also { currentPlates ->
                        when (step.action) {
                            PlateCalculator.Companion.Action.ADD -> {
                                currentPlates.add(step.weight)
                            }

                            PlateCalculator.Companion.Action.REMOVE -> {
                                // Remove one instance of this plate, matching the physical action
                                // (outermost plate of that weight). Since the list is sorted
                                // descending, any instance is visually equivalent.
                                currentPlates.remove(step.weight)
                            }
                        }
                    }.sortedDescending()

                    // Give time for the highlight / alpha animation and for the user to see the step.
                    delay(900)
                }

                // After the last step, show the final configuration and clear the highlight.
                animatedPlates = plateChangeResult.currentPlates.sortedDescending()
                currentStepIndex = -1
            }
            
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
            ) {
                BarbellVisualization(
                    plates = animatedPlates,
                    barbell = equipment,
                    activePlateInfo = activePlateInfo,
                    modifier = Modifier.fillMaxSize()
                )
            }
        }
    }
}

@Composable
private fun BarbellVisualization(
    plates: List<Double>,
    barbell: Barbell,
    activePlateInfo: Triple<Double, PlateCalculator.Companion.Action, Int>? = null, // weight, action, instanceIndex
    modifier: Modifier = Modifier
) {

    // plateData matches the order of sortedPlates, so indices align
    val plateData = remember(plates, barbell.availablePlates) {
        plates.sortedDescending().map { weight ->
            val plate = barbell.availablePlates.find { it.weight == weight }
            PlateData(
                weight = weight,
                thickness = plate?.thickness ?: 30.0
            )
        }
    }

    val barLength = barbell.barLength.toFloat()
    // Total logical thickness of all plates currently on the sleeve (in the same unit as barLength)
    val totalThickness = plateData.sumOf { it.thickness }.toFloat()
    // Extra logical length reserved beyond the outermost plate so we always show a bit of empty sleeve.
    // This is expressed as a fraction of the sleeve length per side and capped at non‑negative.
    val extraLogicalOffset = (barLength * 0.15f).coerceAtLeast(0f)

    val maxPlateWeight = remember(plateData) {
        plateData.maxOfOrNull { it.weight } ?: 25.0
    }

    val barbellColor = MaterialTheme.colorScheme.onBackground
    val defaultPlateColor = MaterialTheme.colorScheme.primary
    val borderColor = MaterialTheme.colorScheme.background

    val labelColor = MaterialTheme.colorScheme.onBackground
    
    // Determine color and alpha for each plate based on animation state
    // Only highlight the specific instance being modified, not all plates of the same weight
    val sortedPlates = plates.sortedDescending()
    
    // Calculate which plate indices should be highlighted (based on instance position among same-weight plates)
    val highlightedPlateIndices = remember(sortedPlates, activePlateInfo) {
        if (activePlateInfo == null) {
            emptySet<Int>()
        } else {
            val (targetWeight, _, instanceIndex) = activePlateInfo
            sortedPlates.mapIndexedNotNull { index, plateWeight ->
                if (plateWeight == targetWeight) {
                    // Count how many plates of this weight come before this one (0-indexed)
                    val instanceCount = sortedPlates.subList(0, index + 1).count { it == targetWeight } - 1
                    if (instanceCount == instanceIndex) index else null
                } else {
                    null
                }
            }.toSet()
        }
    }
    
    // Animate alpha for active plates
    // For ADD: fade in (target 1.0), for REMOVE: fade out (target 0.4)
    val targetAlphaForActive = when (activePlateInfo?.second) {
        PlateCalculator.Companion.Action.ADD -> 1f
        PlateCalculator.Companion.Action.REMOVE -> 0.4f
        null -> 1f
    }
    
    // Use the active plate info as a key to reset animation when plate changes
    val animationKey = activePlateInfo?.let { "${it.first}-${it.second}-${it.third}" } ?: "none"
    
    val animatedAlpha = animateFloatAsState(
        targetValue = targetAlphaForActive,
        animationSpec = tween(durationMillis = 400),
        label = "plate-alpha-$animationKey"
    )

    val labelTextSize = MaterialTheme.typography.bodySmall.fontSize

    Canvas(modifier = modifier) {
        val canvasWidth = size.width
        val canvasHeight = size.height
        val centerX = canvasWidth / 2f
        val centerY = canvasHeight / 2f

        // --- 1. SETUP PAINT & METRICS ---
        val textSizePx = labelTextSize.toPx()
        val textPaint = android.graphics.Paint().apply {
            color = labelColor.toArgb()
            textSize = textSizePx
            textAlign = android.graphics.Paint.Align.CENTER
            isAntiAlias = true
        }

        val fontMetrics = textPaint.fontMetrics
        val textHeight = fontMetrics.descent - fontMetrics.ascent

        val textToPlatePadding = 4.dp.toPx()

        // --- CHANGE HERE: Increased padding from 2.dp to 12.dp ---
        // This forces labels to jump to the next stack level if they are
        // horizontally closer than 12dp.
        val labelCollisionPadding = 12.dp.toPx()

        val rowSpacing = 2.dp.toPx() // Optional: add a tiny bit of vertical spacing between text rows

        // Barbell Geometry
        val shaftLength = 20.dp.toPx()
        val stopperWidth = 5.dp.toPx()
        val spacing = 0.dp.toPx()
        val paddingEnd = 0.dp.toPx()

        val sleeveX = shaftLength + spacing + stopperWidth + spacing
        val sleeveWidth = canvasWidth - sleeveX - paddingEnd
        // Dynamically scale the logical sleeve length so plates use more of the visible width.
        // We base this on the total plate thickness plus a small offset, but never exceed
        // the physical sleeve length per side (barLength).
        val logicalUsedLength = if (totalThickness > 0f) {
            val desired = totalThickness + extraLogicalOffset
            if (barLength > 0f) {
                desired.coerceAtMost(barLength)
            } else {
                desired
            }
        } else {
            // If there are no plates, fall back to showing the whole physical sleeve if known,
            // otherwise just map 1:1 to the canvas sleeve width.
            if (barLength > 0f) barLength else sleeveWidth
        }.coerceAtLeast(1f)

        val scaleFactor = sleeveWidth / logicalUsedLength

        // --- HELPER FUNCTION ---
        fun drawRoundedBlock(
            topLeft: Offset,
            size: Size,
            cornerRadiusPx: Float,
            fillColor: androidx.compose.ui.graphics.Color,
            strokeColor: androidx.compose.ui.graphics.Color? = null,
            strokeWidthPx: Float = 0f
        ) {
            val rect = androidx.compose.ui.geometry.Rect(offset = topLeft, size = size)
            val cornerRadius = CornerRadius(cornerRadiusPx, cornerRadiusPx)

            val roundRect = androidx.compose.ui.geometry.RoundRect(
                rect = rect,
                topLeft = cornerRadius,
                topRight = cornerRadius,
                bottomRight = cornerRadius,
                bottomLeft = cornerRadius
            )

            val path = Path().apply { addRoundRect(roundRect) }

            drawPath(path = path, color = fillColor)

            if (strokeColor != null && strokeWidthPx > 0f) {
                drawPath(
                    path = path,
                    color = strokeColor,
                    style = Stroke(width = strokeWidthPx)
                )
            }
        }

        // --- 2. PASS 1: SIMULATION ---
        var simCurrentX = sleeveX
        val maxLabelStacks = 4 // Increased max stacks slightly to accommodate more spreading
        val topStackRightX = FloatArray(maxLabelStacks) { -1f }
        val bottomStackRightX = FloatArray(maxLabelStacks) { -1f }

        var maxStackUsedTop = 0
        var maxStackUsedBottom = 0

        plateData.forEach { plateInfo ->
            val scaledThickness = plateInfo.thickness.toFloat() * scaleFactor
            val plateWidth = scaledThickness.coerceAtLeast(4.dp.toPx()).coerceAtMost(sleeveX + sleeveWidth - simCurrentX)
            val plateCenterX = simCurrentX + plateWidth / 2f

            val weightText = plateInfo.weight.compact()
            val labelWidth = textPaint.measureText(weightText)
            val labelLeft = plateCenterX - labelWidth / 2f
            val labelRight = plateCenterX + labelWidth / 2f

            // Collision Logic
            var bestTopStackIdx = -1
            for (i in 0 until maxLabelStacks) {
                // Determine if this stack level has enough space (including the new larger padding)
                if (labelLeft > topStackRightX[i] + labelCollisionPadding) {
                    bestTopStackIdx = i
                    break
                }
            }

            var bestBottomStackIdx = -1
            for (i in 0 until maxLabelStacks) {
                if (labelLeft > bottomStackRightX[i] + labelCollisionPadding) {
                    bestBottomStackIdx = i
                    break
                }
            }

            // Logic to balance top vs bottom
            val isTop = when {
                bestTopStackIdx == -1 && bestBottomStackIdx == -1 -> true // Default to top if both full (overflow)
                bestTopStackIdx != -1 && bestBottomStackIdx == -1 -> true
                bestTopStackIdx == -1 && bestBottomStackIdx != -1 -> false
                else -> bestTopStackIdx <= bestBottomStackIdx // Pick the smaller stack index
            }

            val chosenStackIdx = if (isTop)
                bestTopStackIdx.coerceAtLeast(0)
            else
                bestBottomStackIdx.coerceAtLeast(0)

            if (isTop) {
                if (chosenStackIdx < maxLabelStacks) topStackRightX[chosenStackIdx] = labelRight
                maxStackUsedTop = maxOf(maxStackUsedTop, chosenStackIdx + 1)
            } else {
                if (chosenStackIdx < maxLabelStacks) bottomStackRightX[chosenStackIdx] = labelRight
                maxStackUsedBottom = maxOf(maxStackUsedBottom, chosenStackIdx + 1)
            }

            simCurrentX += plateWidth
        }

        // --- 3. CALCULATE BOUNDARIES ---
        val stacksNeeded = maxOf(maxStackUsedTop, maxStackUsedBottom).coerceAtLeast(1)
        val totalTextReserve = textToPlatePadding +
                (stacksNeeded * textHeight) +
                ((stacksNeeded - 1) * rowSpacing)

        val maxAvailablePlateHeight = (canvasHeight - (totalTextReserve * 2)).coerceAtLeast(10f)

        val globalPlateTopY = centerY - (maxAvailablePlateHeight / 2f)
        val globalPlateBottomY = centerY + (maxAvailablePlateHeight / 2f)

        // --- 4. PASS 2: DRAWING ---
        val sleeveHeight = maxAvailablePlateHeight * 0.15f
        val sleeveY = centerY - (sleeveHeight / 2f)
        val stopperHeight = sleeveHeight * 3f
        val stopperY = centerY - (stopperHeight / 2f)
        val barbellCornerRadius = 3.dp.toPx()

        // Draw Barbell parts
        drawRoundedBlock(
            topLeft = Offset(0f, sleeveY),
            size = Size(shaftLength+stopperWidth+sleeveWidth, sleeveHeight),
            cornerRadiusPx = barbellCornerRadius,
            fillColor = barbellColor
        )
        drawRoundedBlock(
            topLeft = Offset(shaftLength + spacing, stopperY),
            size = Size(stopperWidth, stopperHeight),
            cornerRadiusPx = barbellCornerRadius,
            fillColor = barbellColor
        )

        // Reset for drawing pass
        topStackRightX.fill(-1f)
        bottomStackRightX.fill(-1f)
        var currentX = sleeveX

        val plateBorderWidth = 1.5.dp.toPx()
        val plateCornerRadius = 3.dp.toPx()

        plateData.forEachIndexed { plateIndex, plateInfo ->
            val scaledThickness = plateInfo.thickness.toFloat() * scaleFactor
            val plateWidth = scaledThickness.coerceAtLeast(4.dp.toPx()).coerceAtMost(sleeveX + sleeveWidth - currentX)

            val minHeightRatio = 0.3f
            val weightRatio = sqrt(
                (plateInfo.weight.toFloat() / maxPlateWeight.toFloat()).coerceIn(0f, 1f)
            )
            val plateHeight = maxAvailablePlateHeight * (minHeightRatio + (1f - minHeightRatio) * weightRatio)

            val localPlateY = centerY - (plateHeight / 2f)
            val localPlateTopY = localPlateY
            val localPlateBottomY = localPlateY + plateHeight

            // Get color and alpha for this specific plate instance
            val isHighlighted = highlightedPlateIndices.contains(plateIndex)
            val plateColor = if (isHighlighted && activePlateInfo != null) {
                when (activePlateInfo.second) {
                    PlateCalculator.Companion.Action.ADD -> Green
                    PlateCalculator.Companion.Action.REMOVE -> Red
                }
            } else {
                defaultPlateColor
            }
            val plateAlpha = if (isHighlighted) animatedAlpha.value else 1f

            // Draw Plate with color and alpha
            drawRoundedBlock(
                topLeft = Offset(currentX, localPlateY),
                size = Size(plateWidth, plateHeight),
                cornerRadiusPx = plateCornerRadius,
                fillColor = plateColor.copy(alpha = plateAlpha),
                strokeColor = borderColor.copy(alpha = plateAlpha),
                strokeWidthPx = plateBorderWidth
            )

            // Draw Text
            val plateCenterX = currentX + plateWidth / 2f
            val weightText = plateInfo.weight.compact()
            val labelWidth = textPaint.measureText(weightText)
            val labelLeft = plateCenterX - labelWidth / 2f
            val labelRight = plateCenterX + labelWidth / 2f

            // Recalculate stack logic (Must match simulation pass logic EXACTLY)
            var bestTopStackIdx = -1
            for (i in 0 until maxLabelStacks) {
                if (labelLeft > topStackRightX[i] + labelCollisionPadding) {
                    bestTopStackIdx = i
                    break
                }
            }
            var bestBottomStackIdx = -1
            for (i in 0 until maxLabelStacks) {
                if (labelLeft > bottomStackRightX[i] + labelCollisionPadding) {
                    bestBottomStackIdx = i
                    break
                }
            }
            val isTop = when {
                bestTopStackIdx == -1 && bestBottomStackIdx == -1 -> true
                bestTopStackIdx != -1 && bestBottomStackIdx == -1 -> true
                bestTopStackIdx == -1 && bestBottomStackIdx != -1 -> false
                else -> bestTopStackIdx <= bestBottomStackIdx
            }
            val chosenStackIdx = if (isTop) bestTopStackIdx.coerceAtLeast(0) else bestBottomStackIdx.coerceAtLeast(0)

            if (isTop && chosenStackIdx < maxLabelStacks) topStackRightX[chosenStackIdx] = labelRight
            else if (!isTop && chosenStackIdx < maxLabelStacks) bottomStackRightX[chosenStackIdx] = labelRight

            val stackOffset = chosenStackIdx * (textHeight + rowSpacing)

            // Draw text and guidelines
            val textBaseline: Float
            val lineStartY: Float
            val lineEndY: Float

            if (isTop) {
                val textBoxTop = globalPlateTopY - textToPlatePadding - stackOffset - textHeight
                textBaseline = textBoxTop - fontMetrics.ascent
                lineStartY = textBaseline + fontMetrics.descent
                lineEndY = localPlateTopY
            } else {
                val textBoxTop = globalPlateBottomY + textToPlatePadding + stackOffset
                textBaseline = textBoxTop - fontMetrics.ascent
                lineStartY = localPlateBottomY
                lineEndY = textBoxTop
            }

            drawContext.canvas.nativeCanvas.drawText(weightText, plateCenterX, textBaseline, textPaint)

            if (kotlin.math.abs(lineEndY - lineStartY) > 2.dp.toPx()) {
                val dashPath = Path().apply {
                    moveTo(plateCenterX, lineStartY)
                    lineTo(plateCenterX, lineEndY)
                }
                drawPath(
                    path = dashPath,
                    color = labelColor.copy(alpha = 0.5f),
                    style = Stroke(
                        width = 1.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(5f, 5f), 0f)
                    )
                )
            }

            currentX += plateWidth
        }
    }
}

private data class PlateData(
    val weight: Double,
    val thickness: Double
)
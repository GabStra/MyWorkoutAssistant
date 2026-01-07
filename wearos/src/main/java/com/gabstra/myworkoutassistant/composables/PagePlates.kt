package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
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
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LighterGray
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
                .padding(horizontal = 30.dp),
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
                    val baseStyle = MaterialTheme.typography.bodySmall
                    val topLine = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append("Tot: ")
                        }
                        append(formatWeight(equipment.barWeight))
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append(" + ")
                        }
                        append(formatWeight(currentSideWeightTotal))
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append(" × 2 = ")
                        }
                        append(formatWeight(currentWeightTotal))
                    }

                    Text(
                        text = topLine,
                        style = baseStyle,
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
                    val baseStyle = MaterialTheme.typography.bodySmall
                    val topLine = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append("Tot: ")
                        }
                        append(formatWeight(equipment.barWeight))
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append(" + ")
                        }
                        append(formatWeight(currentSideWeightTotal))
                        withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                            append(" × 2 = ")
                        }
                        append(formatWeight(currentWeightTotal))
                    }

                    Text(
                        text = topLine,
                        style = baseStyle,
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
            val allSteps = plateChangeResult.change.steps

            // Filter out no-op steps that don't result in any visual change
            val effectiveSteps = remember(allSteps, plateChangeResult.previousPlates) {
                val filtered = mutableListOf<PlateCalculator.Companion.PlateStep>()
                val workingPlates = plateChangeResult.previousPlates.toMutableList()

                allSteps.forEach { step ->
                    val platesBefore = workingPlates.sortedDescending().toList()

                    // Apply the step
                    when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> workingPlates.add(step.weight)
                        PlateCalculator.Companion.Action.REMOVE -> workingPlates.remove(step.weight)
                    }

                    val platesAfter = workingPlates.sortedDescending().toList()

                    // Only include the step if it actually changed the plate configuration
                    if (platesBefore != platesAfter) {
                        filtered.add(step)
                    }
                }

                filtered
            }

            val steps = effectiveSteps

            // Index of the current step being animated (or -1 when idle, or steps.size for final state)
            var currentStepIndex by remember(plateChangeResult) { mutableIntStateOf(-1) }

            // We keep track of the *actual* plates currently shown on the bar.
            // This lets us always start the animation from the current state instead of
            // reconstructing everything from an implicit empty bar or looping forever.
            var animatedPlates by remember(plateChangeResult) {
                mutableStateOf(plateChangeResult.previousPlates.sortedDescending())
            }

            // Compute the maximum total plate thickness encountered across all configurations
            // in this transition (previous → all intermediate steps → current). This value
            // is used to determine the logical sleeve length, so scaling remains stable for
            // the "widest" configuration seen in the animation.
            val maxLogicalThickness = remember(plateChangeResult, equipment.availablePlates) {
                // Helper to compute total thickness for a given per-side plate configuration.
                fun totalThicknessFor(plates: List<Double>): Double {
                    return plates.sumOf { w ->
                        equipment.availablePlates.find { it.weight == w }?.thickness ?: 30.0
                    }
                }

                var maxThickness = totalThicknessFor(plateChangeResult.previousPlates)
                val workingPlates = plateChangeResult.previousPlates.toMutableList()

                steps.forEach { step ->
                    when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> workingPlates.add(step.weight)
                        PlateCalculator.Companion.Action.REMOVE -> workingPlates.remove(step.weight)
                    }
                    val t = totalThicknessFor(workingPlates)
                    if (t > maxThickness) {
                        maxThickness = t
                    }
                }

                // Ensure we also consider the final target configuration explicitly.
                val finalThickness = totalThicknessFor(plateChangeResult.currentPlates)
                if (finalThickness > maxThickness) {
                    maxThickness = finalThickness
                }

                maxThickness.toFloat()
            }

            // Track which plate instances were added during the entire transition sequence
            // This allows us to keep them green throughout the animation
            val addedPlateInstances = remember(steps, plateChangeResult.previousPlates) {
                val addedInstances = mutableSetOf<Pair<Double, Int>>() // (weight, instanceIndex)
                val workingPlates = plateChangeResult.previousPlates.toMutableList()

                steps.forEach { step ->
                    if (step.action == PlateCalculator.Companion.Action.ADD) {
                        // Calculate plates state before this ADD step
                        val platesBefore = workingPlates.sortedDescending()

                        // Count how many plates of this weight exist before adding
                        val countBefore = platesBefore.count { it == step.weight }

                        // The new plate will be at instance index countBefore (0-indexed)
                        addedInstances.add(Pair(step.weight, countBefore))
                    }

                    // Apply the step to working plates for next iteration
                    when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> workingPlates.add(step.weight)
                        PlateCalculator.Companion.Action.REMOVE -> workingPlates.remove(step.weight)
                    }
                }

                addedInstances
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
                    // If countBefore is 2 (instances 0 and 1), we remove instance 1 (the last one)
                    val instanceIndex = when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> countBefore // New plate will be at this index (0-indexed)
                        PlateCalculator.Companion.Action.REMOVE -> {
                            // For REMOVE, the algorithm removes from the end (outermost)
                            // In sorted descending order, this is the last instance of that weight
                            countBefore - 1
                        }
                    }

                    Triple(step.weight, step.action, instanceIndex)
                } else {
                    null
                }
            }

            // Calculate plates state before current step for highlighting purposes
            // This is needed for REMOVE actions where the plate is already removed from animatedPlates
            // For final state (currentStepIndex == steps.size), use null since we don't need before state
            val platesBeforeCurrentStep = remember(currentStepIndex, steps, plateChangeResult.previousPlates) {
                if (currentStepIndex >= 0 && currentStepIndex < steps.size) {
                    if (currentStepIndex > 0) {
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

                // Continuously loop the full physical transition from previousPlates → currentPlates.
                // The starting configuration for every loop is always previousPlates (never an
                // artificial empty bar), so the user repeatedly sees the exact sequence of
                // plate changes needed for this transition.
                while (true) {
                    // Start from the previous bar configuration for this transition.
                    animatedPlates = plateChangeResult.previousPlates.sortedDescending()

                    // Walk the sequence of physical steps, applying the
                    // delta to the currently drawn plates.
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
                        delay(1000)
                    }

                    // After the last step, show the final configuration with all plates in primary color
                    animatedPlates = plateChangeResult.currentPlates.sortedDescending()
                    currentStepIndex = steps.size // Special value to indicate final state

                    // Show final state with all plates in primary color
                    delay(1000)

                    // Pause before restarting the animation loop
                    delay(1000)
                }
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
            ) {
                BarbellVisualization(
                    plates = animatedPlates,
                    barbell = equipment,
                    activePlateInfo = activePlateInfo,
                    addedPlateInstances = addedPlateInstances,
                    maxLogicalThickness = maxLogicalThickness,
                    platesBeforeCurrentStep = platesBeforeCurrentStep,
                    currentStepIndex = currentStepIndex,
                    totalSteps = steps.size,
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
    addedPlateInstances: Set<Pair<Double, Int>> = emptySet(), // Set of (weight, instanceIndex) for plates that were added
    maxLogicalThickness: Float? = null,
    platesBeforeCurrentStep: List<Double>? = null, // Plates state before current step (for REMOVE highlighting)
    currentStepIndex: Int = -1, // Current step index (-1 idle, steps.size for final state)
    totalSteps: Int = 0, // Total number of steps
    modifier: Modifier = Modifier
) {

    // For REMOVE actions, use platesBeforeCurrentStep so the plate being removed is still drawn and can be highlighted
    // For ADD actions, use the current plates (the plate being added is already in the list)
    val platesForDrawing = remember(plates, platesBeforeCurrentStep, activePlateInfo) {
        if (activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE && platesBeforeCurrentStep != null) {
            // Use the before state which includes the plate being removed
            platesBeforeCurrentStep.sortedDescending()
        } else {
            plates.sortedDescending()
        }
    }

    // plateData matches the order of platesForDrawing, so indices align
    val plateData = remember(platesForDrawing, barbell.availablePlates) {
        platesForDrawing.map { weight ->
            val plate = barbell.availablePlates.find { it.weight == weight }
            PlateData(
                weight = weight,
                thickness = plate?.thickness ?: 30.0
            )
        }
    }

    val isFinalState = (currentStepIndex == totalSteps) || (totalSteps == 0)

    val sleeveLength = barbell.sleeveLength.toFloat()
    // Total logical thickness of the *current* plates on the sleeve (in the same unit as sleeveLength)
    val currentTotalThickness = plateData.sumOf { it.thickness }.toFloat()
    // Extra logical length reserved beyond the outermost plate so we always show a bit of empty sleeve.
    // This is expressed as a fraction of the sleeve length per side and capped at non‑negative.
    val extraLogicalOffset = (sleeveLength * 0.15f).coerceAtLeast(0f)

    val maxPlateWeight = remember(plateData) {
        plateData.maxOfOrNull { it.weight } ?: 25.0
    }


    val defaultColor = MaterialTheme.colorScheme.onBackground
    val finalStatePlateColor = MaterialTheme.colorScheme.primary
    val borderColor = MaterialTheme.colorScheme.background
    val labelColor = MaterialTheme.colorScheme.onBackground
    val defaultPlateColor = MaterialTheme.colorScheme.onBackground

    // 2. Determine Barbell Color
    // If we are in the final state AND the bar is empty, color the bar Primary.
    // Otherwise, keep it the default color.
    val barbellColor = if (isFinalState && platesForDrawing.isEmpty()) {
        finalStatePlateColor
    } else {
        defaultColor
    }

    // Determine color and alpha for each plate based on animation state
    // Only highlight the specific instance being modified, not all plates of the same weight
    // Use platesForDrawing which includes the removed plate for REMOVE actions
    val sortedPlatesForHighlighting = platesForDrawing

    // Calculate which plate indices should be highlighted (based on instance position among same-weight plates)
    // In final state, no plates should be highlighted
    val highlightedPlateIndices = remember(sortedPlatesForHighlighting, activePlateInfo, isFinalState) {
        if (isFinalState || activePlateInfo == null) {
            emptySet<Int>()
        } else {
            val (targetWeight, _, instanceIndex) = activePlateInfo
            sortedPlatesForHighlighting.mapIndexedNotNull { index, plateWeight ->
                if (plateWeight == targetWeight) {
                    // Count how many plates of this weight come before this one (0-indexed)
                    val instanceCount = sortedPlatesForHighlighting.subList(0, index + 1).count { it == targetWeight } - 1
                    if (instanceCount == instanceIndex) index else null
                } else {
                    null
                }
            }.toSet()
        }
    }

    // Calculate which plate indices were previously added (for persistent green coloring)
    // In final state, no plates should be marked as previously added (they all use primary)
    val previouslyAddedPlateIndices = remember(platesForDrawing, addedPlateInstances, isFinalState) {
        if (isFinalState) {
            emptySet<Int>()
        } else {
            platesForDrawing.mapIndexedNotNull { index, plateWeight ->
                // Count how many plates of this weight come before this one (0-indexed)
                val instanceCount = platesForDrawing.subList(0, index + 1).count { it == plateWeight } - 1
                if (addedPlateInstances.contains(Pair(plateWeight, instanceCount))) {
                    index
                } else {
                    null
                }
            }.toSet()
        }
    }

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
        val labelCollisionPadding = 2.dp.toPx()

        val rowSpacing = 2.dp.toPx() // Optional: add a tiny bit of vertical spacing between text rows

        // Barbell Geometry
        val shaftLength = 20.dp.toPx()
        val stopperWidth = 5.dp.toPx()
        val spacing = 0.dp.toPx()
        val paddingEnd = 0.dp.toPx()

        val sleeveX = shaftLength + spacing + stopperWidth + spacing
        val sleeveWidth = canvasWidth - sleeveX - paddingEnd
        // Dynamically scale the logical sleeve length so plates use more of the visible width.
        // We base this on the maximum total thickness encountered across all configurations in
        // the animation (if provided), plus a small offset, but never exceed the physical sleeve
        // length per side (sleeveLength).
        val baseThickness = (maxLogicalThickness ?: currentTotalThickness).coerceAtLeast(0f)
        val logicalUsedLength = if (baseThickness > 0f) {
            val desired = baseThickness + extraLogicalOffset
            if (sleeveLength > 0f) {
                desired.coerceAtMost(sleeveLength)
            } else {
                desired
            }
        } else {
            // If there are no plates, fall back to showing the whole physical sleeve if known,
            // otherwise just map 1:1 to the canvas sleeve width.
            if (sleeveLength > 0f) sleeveLength else sleeveWidth
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
        val stacksNeeded = if (plateData.isEmpty()) {
            0
        } else {
            maxOf(maxStackUsedTop, maxStackUsedBottom).coerceAtLeast(1)
        }

        // MODIFICATION START: Strictly reserve 0 space if no stacks are needed
        val totalTextReserve = if (stacksNeeded > 0) {
            textToPlatePadding +
                    (stacksNeeded * textHeight) +
                    ((stacksNeeded - 1).coerceAtLeast(0) * rowSpacing)
        } else {
            0f
        }
        // MODIFICATION END

        val maxAvailablePlateHeight = (canvasHeight - (totalTextReserve * 2)).coerceAtLeast(10f)

        val globalPlateTopY = centerY - (maxAvailablePlateHeight / 2f)
        val globalPlateBottomY = centerY + (maxAvailablePlateHeight / 2f)

        // --- 4. PASS 2: DRAWING ---

        // 1. Proportions (Key to fixing the "Sword" look)
        // Shaft = Thinner (60%), Sleeve = Standard (100%), Collar = Stopper (150%)
        val sleeveDiameter = maxAvailablePlateHeight * 0.15f
        val shaftDiameter = sleeveDiameter * 0.6f
        val collarDiameter = sleeveDiameter * 1.5f

        val sleeveY = centerY - (sleeveDiameter / 2f)
        val shaftY = centerY - (shaftDiameter / 2f)
        val collarY = centerY - (collarDiameter / 2f)

        val barbellCornerRadius = 2.dp.toPx()

        // 2. Draw Barbell Anatomy

        // A. SHAFT: The "Vertical Break" Effect
        // We draw two pieces: a small starting block, a gap, then the rest.
        val breakWidth = 3.dp.toPx()  // Width of the first "dash"
        val breakGap = 2.dp.toPx()    // Width of the empty space
        val mainShaftStart = breakWidth + breakGap

        // Piece 1: The small detached start
        drawRoundedBlock(
            topLeft = Offset(0f, shaftY),
            size = Size(breakWidth, shaftDiameter),
            cornerRadiusPx = 0f, // Slight roundness
            fillColor = barbellColor.copy(alpha = 0.5f) // Slightly dimmer to imply distance
        )

        // Piece 2: The main shaft connecting to the collar
        drawRoundedBlock(
            topLeft = Offset(mainShaftStart, shaftY),
            size = Size(shaftLength - mainShaftStart, shaftDiameter),
            cornerRadiusPx = 0f, // Flat left edge facing the gap
            fillColor = barbellColor
        )

        // B. COLLAR (The Stopper)
        drawRoundedBlock(
            topLeft = Offset(shaftLength, collarY),
            size = Size(stopperWidth, collarDiameter),
            cornerRadiusPx = barbellCornerRadius,
            fillColor = barbellColor
        )

        // C. SLEEVE (No end cap, flat right edge)
        drawRoundedBlock(
            topLeft = Offset(sleeveX, sleeveY),
            size = Size(sleeveWidth, sleeveDiameter),
            cornerRadiusPx = 0f,
            fillColor = barbellColor
        )

        // Reset for drawing plates
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
            val wasPreviouslyAdded = previouslyAddedPlateIndices.contains(plateIndex)

            val plateColor = when {
                // Final state: all plates use primary color (this should be the only case in final state)
                isFinalState -> finalStatePlateColor
                // Currently active plate being added - green with animation
                isHighlighted && activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.ADD -> Green
                // Currently active plate being removed - red with animation
                isHighlighted && activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE -> Red
                // Previously added plate (not currently active) - stay green
                wasPreviouslyAdded -> Green
                // Default color for plates that weren't added (onBackground)
                else -> defaultPlateColor
            }

            // All plates use full opacity (no fade animation)
            val plateAlpha = 1f

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
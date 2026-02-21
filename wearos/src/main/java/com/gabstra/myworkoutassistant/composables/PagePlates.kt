package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
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
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlin.math.sqrt

private fun Double.compact(): String {
    val s = String.format("%.2f", this).replace(',', '.')
    return s.trimEnd('0').trimEnd('.')
}

/**
 * Computes the rightmost X (in px) that plate labels will use when laid out with the same
 * geometry and collision logic as [BarbellVisualization]. Used to set content width so
 * horizontal scroll is only enabled when labels actually overflow the viewport.
 */
private fun computeRequiredLabelRightEdgePx(
    plateData: List<PlateData>,
    viewportWidthPx: Float,
    sleeveLength: Float,
    extraLogicalOffset: Float,
    maxLogicalThickness: Float?,
    currentTotalThickness: Float,
    density: Density,
    labelTextSizePx: Float
): Float {
    if (plateData.isEmpty()) return viewportWidthPx
    val shaftLength = with(density) { 20.dp.toPx() }
    val stopperWidth = with(density) { 5.dp.toPx() }
    val spacing = with(density) { 0.dp.toPx() }
    val paddingEnd = with(density) { 0.dp.toPx() }
    val sleeveX = shaftLength + spacing + stopperWidth + spacing
    val sleeveWidth = viewportWidthPx - sleeveX - paddingEnd
    val baseThickness = (maxLogicalThickness ?: currentTotalThickness).coerceAtLeast(0f)
    val logicalUsedLength = if (baseThickness > 0f) {
        val desired = baseThickness + extraLogicalOffset
        if (sleeveLength > 0f) desired.coerceAtMost(sleeveLength) else desired
    } else {
        if (sleeveLength > 0f) sleeveLength else sleeveWidth
    }.coerceAtLeast(1f)
    val scaleFactor = sleeveWidth / logicalUsedLength
    val labelCollisionPadding = with(density) { 6.dp.toPx() }
    val minPlateWidthPx = with(density) { 4.dp.toPx() }
    val maxPlateWeight = plateData.maxOfOrNull { it.weight } ?: 25.0
    val textPaint = android.graphics.Paint().apply {
        textSize = labelTextSizePx
        isAntiAlias = true
    }
    var topRowRightX = sleeveX - labelCollisionPadding
    var bottomRowRightX = sleeveX - labelCollisionPadding
    var currentX = sleeveX
    val unboundedMaxLabelCenterX = 1e6f
    plateData.forEachIndexed { plateIndex, plateInfo ->
        val scaledThickness = plateInfo.thickness.toFloat() * scaleFactor
        val plateWidth = scaledThickness.coerceAtLeast(minPlateWidthPx).coerceAtMost(sleeveX + sleeveWidth - currentX)
        val plateCenterX = currentX + plateWidth / 2f
        val weightText = plateInfo.weight.compact()
        val labelWidth = textPaint.measureText(weightText)
        val minLabelCenterX = sleeveX + (labelWidth / 2f)
        val maxLabelCenterX = unboundedMaxLabelCenterX
        val isTop = plateIndex % 2 == 0
        val rowRightX = if (isTop) topRowRightX else bottomRowRightX
        val desiredCenterX = plateCenterX.coerceIn(minLabelCenterX, maxLabelCenterX)
        val desiredLeft = desiredCenterX - (labelWidth / 2f)
        val adjustedCenterX = if (desiredLeft > rowRightX + labelCollisionPadding) {
            desiredCenterX
        } else {
            (rowRightX + labelCollisionPadding + (labelWidth / 2f)).coerceAtMost(maxLabelCenterX)
        }
        val adjustedRight = adjustedCenterX + (labelWidth / 2f)
        if (isTop) topRowRightX = adjustedRight else bottomRowRightX = adjustedRight
        currentX += plateWidth
    }
    return maxOf(topRowRightX, bottomRowRightX)
}

@SuppressLint("DefaultLocale")
@Composable
fun PagePlates(
    updatedState: WorkoutState.Set,
    equipment: WeightLoadedEquipment?,
    hapticsViewModel: HapticsViewModel,
    viewModel: AppViewModel
) {
    val isRecalculating by viewModel.isPlateRecalculationInProgress.collectAsState()

    // Show loading screen during recalculation
    if (isRecalculating) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator()
            Spacer(Modifier.height(8.dp))
            LoadingText(baseText = "Loading")
        }
        return
    }

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
            style = workoutPagerTitleTextStyle(),
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
                        withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray, fontWeight = FontWeight.Normal)) {
                            append("Tot: ")
                            append(formatWeight(equipment.barWeight))
                            if (currentSideWeightTotal != 0.0) {
                                append(" + (")
                                append(formatWeight(currentSideWeightTotal))
                                append(" × 2) = ")
                                append(formatWeight(currentWeightTotal))
                            }
                        }
                    }

                    FadingText(
                        text = topLine,
                        style = baseStyle.copy(fontWeight = FontWeight.Normal),
                        color = MediumLighterGray,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .clickable {
                                hapticsViewModel.doGentleVibration()
                            }
                    )
                } else {
                    val baseStyle = MaterialTheme.typography.bodySmall
                    val topLine = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray, fontWeight = FontWeight.Normal)) {
                            append("Tot: ")
                            append(formatWeight(equipment.barWeight))
                            if (currentSideWeightTotal != 0.0) {
                                append(" + (")
                                append(formatWeight(currentSideWeightTotal))
                                append(" × 2) = ")
                                append(formatWeight(currentWeightTotal))
                            }
                        }
                    }

                    FadingText(
                        text = topLine,
                        style = baseStyle.copy(fontWeight = FontWeight.Normal),
                        color = MediumLighterGray,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .clickable {
                                hapticsViewModel.doGentleVibration()
                            }
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

            // Build lists of plates to remove and to add (with instance index). Plates that
            // appear in both are "shuffled" (removed then re-added). Track step indices for each.
            val (shuffledPlates, removeStepIndex, addStepIndex) = remember(steps, plateChangeResult.previousPlates) {
                val toRemove = mutableSetOf<Pair<Double, Int>>()
                val toAdd = mutableSetOf<Pair<Double, Int>>()
                val removeStep = mutableMapOf<Pair<Double, Int>, Int>()
                val addStep = mutableMapOf<Pair<Double, Int>, Int>()
                val working = plateChangeResult.previousPlates.toMutableList()

                steps.forEachIndexed { stepIdx, step ->
                    val platesBefore = working.sortedDescending()
                    val countBefore = platesBefore.count { it == step.weight }

                    when (step.action) {
                        PlateCalculator.Companion.Action.REMOVE -> {
                            val instanceIdx = countBefore - 1
                            val key = Pair(step.weight, instanceIdx)
                            toRemove.add(key)
                            removeStep[key] = stepIdx
                        }
                        PlateCalculator.Companion.Action.ADD -> {
                            val instanceIdx = countBefore
                            val key = Pair(step.weight, instanceIdx)
                            toAdd.add(key)
                            addStep[key] = stepIdx
                        }
                    }
                    when (step.action) {
                        PlateCalculator.Companion.Action.ADD -> working.add(step.weight)
                        PlateCalculator.Companion.Action.REMOVE -> working.remove(step.weight)
                    }
                }
                val shuffled = toRemove.intersect(toAdd)
                Triple(shuffled, removeStep, addStep)
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

            BoxWithConstraints(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
            ) {
                val viewportWidth = maxWidth
                val density = LocalDensity.current
                val viewportWidthPx = with(density) { viewportWidth.toPx() }
                val labelTextSizePx = with(density) { MaterialTheme.typography.bodySmall.fontSize.toPx() }
                val labelRightPaddingPx = with(density) { 4.dp.toPx() }
                val platesForDrawing = remember(animatedPlates, platesBeforeCurrentStep, activePlateInfo) {
                    if (activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE && platesBeforeCurrentStep != null) {
                        platesBeforeCurrentStep.sortedDescending()
                    } else {
                        animatedPlates.sortedDescending()
                    }
                }
                val plateDataForWidth = remember(platesForDrawing, equipment.availablePlates) {
                    platesForDrawing.map { weight ->
                        val plate = equipment.availablePlates.find { it.weight == weight }
                        PlateData(weight = weight, thickness = plate?.thickness ?: 30.0)
                    }
                }
                val sleeveLength = equipment.sleeveLength.toFloat()
                val currentTotalThickness = plateDataForWidth.sumOf { it.thickness }.toFloat()
                val extraLogicalOffset = (sleeveLength * 0.15f).coerceAtLeast(0f)
                val requiredLabelRightPx = computeRequiredLabelRightEdgePx(
                    plateData = plateDataForWidth,
                    viewportWidthPx = viewportWidthPx,
                    sleeveLength = sleeveLength,
                    extraLogicalOffset = extraLogicalOffset,
                    maxLogicalThickness = maxLogicalThickness,
                    currentTotalThickness = currentTotalThickness,
                    density = density,
                    labelTextSizePx = labelTextSizePx
                )
                val contentWidthPx = maxOf(viewportWidthPx, requiredLabelRightPx + labelRightPaddingPx)
                val contentWidth = with(density) { contentWidthPx.toDp() }
                val scrollState = rememberScrollState()
                Box(
                    modifier = Modifier
                        .horizontalScroll(scrollState)
                        .width(contentWidth)
                        .fillMaxHeight()
                ) {
                    BarbellVisualization(
                        plates = animatedPlates,
                        barbell = equipment,
                        activePlateInfo = activePlateInfo,
                        shuffledPlates = shuffledPlates,
                        addStepIndex = addStepIndex,
                        maxLogicalThickness = maxLogicalThickness,
                        platesBeforeCurrentStep = platesBeforeCurrentStep,
                        previousPlates = plateChangeResult.previousPlates.sortedDescending(),
                        currentStepIndex = currentStepIndex,
                        totalSteps = steps.size,
                        viewportWidth = viewportWidth,
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }
    }
}

@Composable
private fun BarbellVisualization(
    plates: List<Double>,
    barbell: Barbell,
    activePlateInfo: Triple<Double, PlateCalculator.Companion.Action, Int>? = null, // weight, action, instanceIndex
    shuffledPlates: Set<Pair<Double, Int>> = emptySet(), // Plates that appear in both remove and add lists
    addStepIndex: Map<Pair<Double, Int>, Int> = emptyMap(), // Step index when each shuffled plate is re-added
    maxLogicalThickness: Float? = null,
    platesBeforeCurrentStep: List<Double>? = null, // Plates state before current step (for REMOVE highlighting)
    previousPlates: List<Double>? = null, // Initial previous plate configuration (for unchanged plate coloring)
    currentStepIndex: Int = -1, // Current step index (-1 idle, steps.size for final state)
    totalSteps: Int = 0, // Total number of steps
    viewportWidth: Dp? = null, // When set, bar and plates use this width; labels use full canvas (content) width
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

    // Shuffled plates (in both remove and add lists): green once re-added (currentStepIndex >= addStepIndex).
    // Red while being removed is handled by activePlateInfo / highlightedPlateIndices.
    // Calculate instance indices based on platesForDrawing to match how they were calculated when building
    // the shuffled set. platesForDrawing already has the correct state (includes plate being removed during
    // REMOVE actions, includes plate being added during ADD actions).
    val shuffledReAddedPlateIndices = remember(platesForDrawing, shuffledPlates, addStepIndex, currentStepIndex, isFinalState) {
        if (isFinalState) {
            emptySet<Int>()
        } else {
            platesForDrawing.mapIndexedNotNull { index, plateWeight ->
                // Calculate instance index the same way as when building shuffled plates
                // For ADD actions, instanceIdx = countBefore (number of plates of this weight before adding)
                // This equals the count of plates of this weight up to and including this plate minus 1 (0-indexed)
                val instanceIdx = platesForDrawing.subList(0, index + 1).count { it == plateWeight } - 1
                val key = Pair(plateWeight, instanceIdx)
                
                // Check if this plate is shuffled and has been re-added
                if (shuffledPlates.contains(key) && currentStepIndex >= (addStepIndex[key] ?: -1)) {
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
        val labelCollisionPadding = 6.dp.toPx()


        // Barbell Geometry
        val shaftLength = 20.dp.toPx()
        val stopperWidth = 5.dp.toPx()
        val spacing = 0.dp.toPx()
        val paddingEnd = 0.dp.toPx()

        val sleeveX = shaftLength + spacing + stopperWidth + spacing
        // When viewportWidth is set (scrollable layout), bar and plates use viewport width; labels use full canvas width.
        val viewportWidthPx = viewportWidth?.toPx()
        val sleeveWidth = (viewportWidthPx ?: canvasWidth) - sleeveX - paddingEnd
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

        // --- 2. CALCULATE BOUNDARIES ---
        val totalTextReserve = if (plateData.isNotEmpty()) {
            textToPlatePadding + textHeight
        } else {
            0f
        }

        val maxAvailablePlateHeight = (canvasHeight - (totalTextReserve * 2)).coerceAtLeast(10f)

        val globalPlateTopY = centerY - (maxAvailablePlateHeight / 2f)
        val globalPlateBottomY = centerY + (maxAvailablePlateHeight / 2f)

        // --- 3. DRAWING ---

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
        var topRowRightX = sleeveX - labelCollisionPadding
        var bottomRowRightX = sleeveX - labelCollisionPadding
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
            val isShuffledReAdded = shuffledReAddedPlateIndices.contains(plateIndex)

            val plateColor = when {
                // Final state: all plates use primary color (this should be the only case in final state)
                isFinalState -> finalStatePlateColor
                // Currently active plate being added - green with animation
                isHighlighted && activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.ADD -> Green
                // Currently active plate being removed - red with animation
                isHighlighted && activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE -> Red
                // Shuffled plate that has been re-added (in both remove and add lists) - green
                isShuffledReAdded -> Green
                // Default color for other plates (onBackground)
                else -> defaultPlateColor
            }

            // All plates use full opacity (no fade animation)
            val plateAlpha = 1f

            // Draw Text
            val plateCenterX = currentX + plateWidth / 2f
            val weightText = plateInfo.weight.compact()
            val labelWidth = textPaint.measureText(weightText)
            val minLabelCenterX = sleeveX + (labelWidth / 2f)
            val labelRightPaddingPx = 4.dp.toPx()
            val maxLabelCenterX = canvasWidth - (labelWidth / 2f) - labelRightPaddingPx

            val preferredIsTop = plateIndex % 2 == 0
            val isTop = preferredIsTop

            val rowRightX = if (isTop) topRowRightX else bottomRowRightX
            val desiredCenterX = plateCenterX.coerceIn(minLabelCenterX, maxLabelCenterX)
            val desiredLeft = desiredCenterX - (labelWidth / 2f)

            val adjustedCenterX = if (desiredLeft > rowRightX + labelCollisionPadding) {
                desiredCenterX
            } else {
                (rowRightX + labelCollisionPadding + (labelWidth / 2f)).coerceAtMost(maxLabelCenterX)
            }

            val adjustedRight = adjustedCenterX + (labelWidth / 2f)
            if (isTop) {
                topRowRightX = adjustedRight
            } else {
                bottomRowRightX = adjustedRight
            }

            // Draw text and guidelines
            val textBaseline: Float
            val labelAnchorY: Float
            val plateCenterY = localPlateY + (plateHeight / 2f)

            if (isTop) {
                val textBoxTop = globalPlateTopY - textToPlatePadding - textHeight
                textBaseline = textBoxTop - fontMetrics.ascent
                labelAnchorY = textBaseline + fontMetrics.descent
            } else {
                val textBoxTop = globalPlateBottomY + textToPlatePadding
                textBaseline = textBoxTop - fontMetrics.ascent
                labelAnchorY = textBoxTop
            }

            val dashPath = Path().apply {
                moveTo(plateCenterX, plateCenterY)
                lineTo(adjustedCenterX, labelAnchorY)
            }
            drawPath(
                path = dashPath,
                color = labelColor.copy(alpha = 0.5f),
                style = Stroke(
                    width = 1.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(5f, 5f), 0f)
                )
            )

            // Draw Plate with color and alpha
            drawRoundedBlock(
                topLeft = Offset(currentX, localPlateY),
                size = Size(plateWidth, plateHeight),
                cornerRadiusPx = plateCornerRadius,
                fillColor = plateColor.copy(alpha = plateAlpha),
                strokeColor = borderColor.copy(alpha = plateAlpha),
                strokeWidthPx = plateBorderWidth
            )

            drawContext.canvas.nativeCanvas.drawText(weightText, adjustedCenterX, textBaseline, textPaint)

            currentX += plateWidth
        }
    }
}

private data class PlateData(
    val weight: Double,
    val thickness: Double
)

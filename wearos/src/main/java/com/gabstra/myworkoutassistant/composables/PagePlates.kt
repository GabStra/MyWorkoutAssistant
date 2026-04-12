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
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlin.math.sqrt
import java.util.UUID

private fun Double.compact(): String {
    val s = String.format("%.2f", this).replace(',', '.')
    return s.trimEnd('0').trimEnd('.')
}

private const val StopperViewportAnchorFraction = 0.44f
private const val BarbellEndPaddingDp = 12

private data class LabelBoundsPx(
    val left: Float,
    val right: Float
) {
    val width: Float get() = (right - left).coerceAtLeast(0f)
    val center: Float get() = left + (width / 2f)
}

private fun computeBarbellStartX(
    viewportWidthPx: Float,
    density: Density
): Float {
    val shaftLength = with(density) { 20.dp.toPx() }
    val stopperWidth = with(density) { 5.dp.toPx() }
    val targetStopperCenterX = viewportWidthPx * StopperViewportAnchorFraction
    return (targetStopperCenterX - shaftLength - (stopperWidth / 2f)).coerceAtLeast(0f)
}

/**
 * Computes the rightmost X (in px) that plate labels will use when laid out with the same
 * geometry and collision logic as [BarbellVisualization]. Used to set content width so
 * horizontal scroll is only enabled when labels actually overflow the viewport.
 */
private fun computeLabelBoundsPx(
    plateData: List<PlateData>,
    canvasWidthPx: Float,
    viewportWidthPx: Float,
    sleeveLength: Float,
    extraLogicalOffset: Float,
    maxLogicalThickness: Float?,
    currentTotalThickness: Float,
    density: Density,
    labelTextSizePx: Float
): LabelBoundsPx {
    val shaftLength = with(density) { 20.dp.toPx() }
    val stopperWidth = with(density) { 5.dp.toPx() }
    val spacing = with(density) { 0.dp.toPx() }
    val paddingEnd = with(density) { BarbellEndPaddingDp.dp.toPx() }
    val barbellStartX = computeBarbellStartX(viewportWidthPx = viewportWidthPx, density = density)
    val sleeveX = barbellStartX + shaftLength + spacing + stopperWidth + spacing
    val sleeveWidth = canvasWidthPx - sleeveX - paddingEnd
    val logicalUsedLength = if (sleeveLength > 0f) sleeveLength else sleeveWidth
    val scaleFactor = sleeveWidth / logicalUsedLength.coerceAtLeast(1f)
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
    var minLeftX = Float.POSITIVE_INFINITY
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
        minLeftX = minOf(minLeftX, adjustedCenterX - (labelWidth / 2f))
        val adjustedRight = adjustedCenterX + (labelWidth / 2f)
        if (isTop) topRowRightX = adjustedRight else bottomRowRightX = adjustedRight
        currentX += plateWidth
    }
    if (plateData.isEmpty()) {
        return LabelBoundsPx(left = sleeveX, right = sleeveX)
    }
    return LabelBoundsPx(
        left = minLeftX.coerceAtMost(maxOf(topRowRightX, bottomRowRightX)),
        right = maxOf(topRowRightX, bottomRowRightX)
    )
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

    PagePlatesContent(
        updatedState = updatedState,
        equipment = equipment,
        onHeaderTap = { hapticsViewModel.doGentleVibration() }
    )
}

@SuppressLint("DefaultLocale")
@Composable
private fun PagePlatesContent(
    updatedState: WorkoutState.Set,
    equipment: WeightLoadedEquipment?,
    onHeaderTap: () -> Unit = {},
    animateSteps: Boolean = true
) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 30.dp),
            text = "Barbell guide",
            style =  MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
            textAlign = TextAlign.Center
        )

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "Not available",
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
                    val secondaryTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                    val topLine = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
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

                    ScalableFadingText(
                        text = topLine,
                        style = baseStyle.copy(fontWeight = FontWeight.Normal),
                        color = secondaryTextColor,
                    )
                } else {
                    val baseStyle = MaterialTheme.typography.bodySmall
                    val secondaryTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                    val topLine = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
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

                    ScalableFadingText(
                        text = topLine,
                        style = baseStyle.copy(fontWeight = FontWeight.Normal),
                        color = secondaryTextColor
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

            val allPlateConfigurations = remember(steps, plateChangeResult.previousPlates, plateChangeResult.currentPlates) {
                buildList {
                    val workingPlates = plateChangeResult.previousPlates.sortedDescending().toMutableList()
                    add(workingPlates.toList())
                    steps.forEach { step ->
                        when (step.action) {
                            PlateCalculator.Companion.Action.ADD -> workingPlates.add(step.weight)
                            PlateCalculator.Companion.Action.REMOVE -> workingPlates.remove(step.weight)
                        }
                        add(workingPlates.sortedDescending())
                    }
                    if (isEmpty() || last() != plateChangeResult.currentPlates.sortedDescending()) {
                        add(plateChangeResult.currentPlates.sortedDescending())
                    }
                }
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
            LaunchedEffect(plateChangeResult, animateSteps) {
                if (!animateSteps) {
                    animatedPlates = plateChangeResult.currentPlates.sortedDescending()
                    currentStepIndex = steps.size
                    return@LaunchedEffect
                }

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
                val barbellStartPx = remember(viewportWidthPx, density) {
                    computeBarbellStartX(
                        viewportWidthPx = viewportWidthPx,
                        density = density
                    )
                }
                val platesForDrawing = remember(animatedPlates, platesBeforeCurrentStep, activePlateInfo) {
                    if (activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE && platesBeforeCurrentStep != null) {
                        platesBeforeCurrentStep.sortedDescending()
                    } else {
                        animatedPlates.sortedDescending()
                    }
                }
                val plateDataForWidth = remember(allPlateConfigurations, equipment.availablePlates) {
                    allPlateConfigurations.map { plateConfiguration ->
                        plateConfiguration.map { weight ->
                            val plate = equipment.availablePlates.find { it.weight == weight }
                            PlateData(weight = weight, thickness = plate?.thickness ?: 30.0)
                        }
                    }
                }
                val sleeveLength = equipment.sleeveLength.toFloat()
                val extraLogicalOffset = (sleeveLength * 0.15f).coerceAtLeast(0f)
                val minimumContentWidthPx = viewportWidthPx + barbellStartPx
                val labelBoundsAcrossConfigurations = remember(
                    plateDataForWidth,
                    minimumContentWidthPx,
                    viewportWidthPx,
                    sleeveLength,
                    extraLogicalOffset,
                    maxLogicalThickness,
                    density,
                    labelTextSizePx
                ) {
                    plateDataForWidth.map { plateData ->
                        computeLabelBoundsPx(
                            plateData = plateData,
                            canvasWidthPx = minimumContentWidthPx,
                            viewportWidthPx = viewportWidthPx,
                            sleeveLength = sleeveLength,
                            extraLogicalOffset = extraLogicalOffset,
                            maxLogicalThickness = maxLogicalThickness,
                            currentTotalThickness = plateData.sumOf { it.thickness }.toFloat(),
                            density = density,
                            labelTextSizePx = labelTextSizePx
                        )
                    }
                }
                val widestLabelBounds = remember(labelBoundsAcrossConfigurations) {
                    labelBoundsAcrossConfigurations.maxByOrNull { it.width }
                        ?: LabelBoundsPx(left = 0f, right = viewportWidthPx)
                }
                val contentWidthPx = maxOf(
                    minimumContentWidthPx,
                    widestLabelBounds.right + labelRightPaddingPx
                )
                val contentWidth = with(density) { contentWidthPx.toDp() }
                val maxScrollPx = (contentWidthPx - viewportWidthPx).coerceAtLeast(0f)
                val labelOverflowPx = (widestLabelBounds.right + labelRightPaddingPx - viewportWidthPx)
                    .coerceAtLeast(0f)
                val canPanHorizontally = labelOverflowPx > 0f
                val horizontalPanNestedScrollConnection = remember {
                    object : NestedScrollConnection {
                        override fun onPostScroll(
                            consumed: Offset,
                            available: Offset,
                            source: NestedScrollSource
                        ): Offset {
                            return available
                        }

                        override suspend fun onPostFling(
                            consumed: Velocity,
                            available: Velocity
                        ): Velocity {
                            return available
                        }
                    }
                }
                val initialScrollTargetPx = remember(widestLabelBounds, viewportWidthPx, maxScrollPx) {
                    (widestLabelBounds.center - (viewportWidthPx / 2f))
                        .coerceIn(0f, maxScrollPx)
                        .toInt()
                }
                val scrollState = rememberScrollState()
                LaunchedEffect(plateChangeResult, contentWidthPx, initialScrollTargetPx) {
                    scrollState.scrollTo(initialScrollTargetPx)
                }
                Box(
                    modifier = Modifier
                        .nestedScroll(horizontalPanNestedScrollConnection)
                        .horizontalScroll(
                            state = scrollState,
                            enabled = canPanHorizontally
                        )
                        .fillMaxWidth()
                        .fillMaxHeight()
                ) {
                    Box(
                        modifier = Modifier
                            .width(contentWidth)
                            .fillMaxHeight()
                    ) {
                        BarbellVisualization(
                            plates = animatedPlates,
                            barbell = equipment,
                            activePlateInfo = activePlateInfo,
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
}

@Composable
private fun BarbellVisualization(
    plates: List<Double>,
    barbell: Barbell,
    activePlateInfo: Triple<Double, PlateCalculator.Companion.Action, Int>? = null, // weight, action, instanceIndex
    maxLogicalThickness: Float? = null,
    platesBeforeCurrentStep: List<Double>? = null, // Plates state before current step (for REMOVE highlighting)
    previousPlates: List<Double>? = null, // Initial previous plate configuration used as the color baseline
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
    // This is expressed as a fraction of the sleeve length per side and capped at non-negative.
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

    // Green should mean "this position now has a different plate than the initial configuration",
    // not "this plate happened to be removed and re-added during the sequence".
    val newlyAddedPlateIndices = remember(platesForDrawing, previousPlates, isFinalState) {
        if (isFinalState) {
            emptySet<Int>()
        } else {
            platesForDrawing.mapIndexedNotNull { index, plateWeight ->
                if (previousPlates?.getOrNull(index) != plateWeight) {
                    index
                } else {
                    null
                }
            }.toSet()
        }
    }

    val labelTextSize = MaterialTheme.typography.labelMedium.fontSize

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
        val paddingEnd = BarbellEndPaddingDp.dp.toPx()

        val viewportWidthPx = viewportWidth?.toPx()
        val barbellStartX = computeBarbellStartX(
            viewportWidthPx = viewportWidthPx ?: canvasWidth,
            density = this
        )
        val shaftStartX = barbellStartX
        val stopperX = shaftStartX + shaftLength
        val sleeveX = stopperX + spacing + stopperWidth + spacing
        val sleeveWidth = canvasWidth - sleeveX - paddingEnd
        // Scale against the full physical sleeve length so plate thickness remains proportional.
        val logicalUsedLength = if (sleeveLength > 0f) sleeveLength else sleeveWidth
        val scaleFactor = sleeveWidth / logicalUsedLength.coerceAtLeast(1f)

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
        // Shaft = Thinner (50%), Sleeve = Standard (100%), Collar = Stopper (150%)
        val sleeveDiameter = maxAvailablePlateHeight * 0.2f
        val shaftDiameter = sleeveDiameter * 0.5f
        val collarDiameter = sleeveDiameter * 1.5f

        val sleeveY = centerY - (sleeveDiameter / 2f)
        val shaftY = centerY - (shaftDiameter / 2f)
        val collarY = centerY - (collarDiameter / 2f)

        val barbellCornerRadius = 2.dp.toPx()

        // 2. Draw Barbell Anatomy

        // A. SHAFT
        drawRoundedBlock(
            topLeft = Offset(0f, shaftY),
            size = Size(stopperX, shaftDiameter),
            cornerRadiusPx = 0f,
            fillColor = barbellColor
        )

        // B. COLLAR (The Stopper)
        drawRoundedBlock(
            topLeft = Offset(stopperX, collarY),
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

        plateData.forEachIndexed { plateIndex, plateInfo ->
            val scaledThickness = plateInfo.thickness.toFloat() * scaleFactor
            val plateWidth = scaledThickness
                .coerceAtLeast(4.dp.toPx())
                .coerceAtMost(sleeveX + sleeveWidth - currentX)

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
            val isNewAtThisPosition = newlyAddedPlateIndices.contains(plateIndex)

            val plateColor = when {
                // Final state: all plates use primary color (this should be the only case in final state)
                isFinalState -> finalStatePlateColor
                // Currently active plate being removed - red with animation
                isHighlighted && activePlateInfo != null && activePlateInfo.second == PlateCalculator.Companion.Action.REMOVE -> Red
                // Green marks positions that now contain a new plate relative to the starting configuration.
                isNewAtThisPosition -> Green
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

            // Draw plate as a capsule (rectangle with semi-circular ends).
            val plateCornerRadius = (plateWidth / 2f).coerceAtMost(plateHeight / 2f)
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

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun PagePlatesPreview() {
    val previewBarbell = Barbell(
        id = UUID.randomUUID(),
        name = "Preview Barbell",
        availablePlates = listOf(
            Plate(20.0, 20.0),
            Plate(20.0, 20.0),
            Plate(10.0, 15.0),
            Plate(10.0, 15.0),
            Plate(5.0, 10.0),
            Plate(5.0, 10.0),
            Plate(2.5, 5.0),
            Plate(2.5, 5.0)
        ),
        sleeveLength = 200,
        barWeight = 20.0
    )
    val previewPlateChangeResult = PlateCalculator.Companion.PlateChangeResult(
        change = PlateCalculator.Companion.PlateChange(
            from = 60.0,
            to = 100.0,
            steps = listOf(
                PlateCalculator.Companion.PlateStep(
                    action = PlateCalculator.Companion.Action.ADD,
                    weight = 10.0
                ),
                PlateCalculator.Companion.PlateStep(
                    action = PlateCalculator.Companion.Action.ADD,
                    weight = 10.0
                )
            )
        ),
        previousPlates = listOf(20.0),
        currentPlates = listOf(20.0, 10.0)
    )
    val previewSetDataState = remember {
        mutableStateOf(
            WeightSetData(
                actualReps = 5,
                actualWeight = 100.0,
                volume = 500.0,
                subCategory = SetSubCategory.WorkSet
            ) as SetData
        )
    }
    val previewState = WorkoutState.Set(
        exerciseId = UUID.randomUUID(),
        set = WeightSet(
            id = UUID.randomUUID(),
            reps = 5,
            weight = 100.0,
            subCategory = SetSubCategory.WorkSet
        ),
        setIndex = 0u,
        previousSetData = null,
        currentSetDataState = previewSetDataState,
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        plateChangeResult = previewPlateChangeResult,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = previewBarbell.id
    )

    MyWorkoutAssistantTheme {
        PagePlatesContent(
            updatedState = previewState,
            equipment = previewBarbell,
            animateSteps = false
        )
    }
}

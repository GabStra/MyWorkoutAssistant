package com.gabstra.myworkoutassistant.workout

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlin.math.sqrt

private val MobileMinPlateWidth = 8.dp
private val MobileMaxPlateWidth = 20.dp

@SuppressLint("DefaultLocale")
@Composable
fun PagePlates(updatedState: WorkoutState.Set, equipment: WeightLoadedEquipment?) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp),
            text = "Barbell guide",
            style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(5.dp))

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "Not available",
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center
            )
        } else {
            val plateChangeResult = updatedState.plateChangeResult!!
            val targetSideWeight = remember(plateChangeResult.currentPlates) {
                plateChangeResult.currentPlates.sum()
            }
            val targetWeight = remember(targetSideWeight, equipment.barWeight) {
                equipment.barWeight + targetSideWeight * 2
            }
            Text(
                text = "Target ${formatWeight(targetWeight)}",
                modifier = Modifier
                    .fillMaxWidth()
                    .height(28.dp),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center,
                maxLines = 1,
            )
            Spacer(modifier = Modifier.height(5.dp))
            val steps = remember(plateChangeResult) { navigableMobilePlateSteps(plateChangeResult) }
            var selectedStepIndex by remember(plateChangeResult) { mutableIntStateOf(0) }
            LaunchedEffect(plateChangeResult) { selectedStepIndex = 0 }
            val selectedStep = steps.getOrNull(selectedStepIndex)
            val platesBeforeStep = remember(plateChangeResult, steps, selectedStepIndex) {
                if (selectedStep != null) {
                    applyMobilePlateSteps(plateChangeResult.previousPlates, steps, selectedStepIndex)
                } else {
                    null
                }
            }
            val displayedPlates = remember(plateChangeResult, steps, selectedStepIndex) {
                if (selectedStep != null) {
                    applyMobilePlateSteps(plateChangeResult.previousPlates, steps, selectedStepIndex + 1)
                } else {
                    plateChangeResult.currentPlates.sortedDescending()
                }
            }
            val highlightedIndices = remember(platesBeforeStep, selectedStep) {
                if (platesBeforeStep != null && selectedStep != null) {
                    highlightedMobilePlateIndices(platesBeforeStep, selectedStep)
                } else {
                    emptySet()
                }
            }
            val maxLogicalThickness = remember(plateChangeResult, steps, equipment.availablePlates) {
                fun thicknessOf(plates: List<Double>): Float = plates.sumOf { weight ->
                    equipment.availablePlates.firstOrNull { it.weight == weight }?.thickness ?: 30.0
                }.toFloat()

                (0..steps.size).maxOf { appliedStepCount ->
                    thicknessOf(
                        applyMobilePlateSteps(
                            previousPlates = plateChangeResult.previousPlates,
                            steps = steps,
                            stepCount = appliedStepCount,
                        )
                    )
                }.coerceAtLeast(thicknessOf(plateChangeResult.currentPlates))
            }
            BarbellVisualization(
                plates = displayedPlates,
                barbell = equipment,
                activeStep = selectedStep,
                platesBeforeStep = platesBeforeStep,
                highlightedPlateIndices = highlightedIndices,
                previousPlates = plateChangeResult.previousPlates,
                isFinalState = steps.isEmpty(),
                maxLogicalThickness = maxLogicalThickness,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(190.dp)
                    .padding(horizontal = 12.dp),
            )

            if (steps.isEmpty()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 16.dp, top = 12.dp, end = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.Outlined.CheckCircle,
                        contentDescription = null,
                        modifier = Modifier.size(20.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "Barbell already loaded",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                if (steps.size == 1) {
                    Spacer(modifier = Modifier.height(16.dp))
                }
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .padding(horizontal = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (steps.size > 1) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            IconButton(
                                enabled = selectedStepIndex > 0,
                                onClick = { selectedStepIndex -= 1 },
                                modifier = Modifier.size(56.dp),
                            ) {
                                Icon(
                                    modifier = Modifier.size(32.dp),
                                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                    contentDescription = "Previous plate step",
                                )
                            }
                            Text(
                                text = "STEP ${selectedStepIndex + 1}/${steps.size}",
                                style = MaterialTheme.typography.titleMedium.copy(
                                    fontSize = 18.sp,
                                    lineHeight = 22.sp,
                                    fontWeight = FontWeight.SemiBold,
                                ),
                                textAlign = TextAlign.Center,
                            )
                            IconButton(
                                enabled = selectedStepIndex < steps.lastIndex,
                                onClick = { selectedStepIndex += 1 },
                                modifier = Modifier.size(56.dp),
                            ) {
                                Icon(
                                    modifier = Modifier.size(32.dp),
                                    imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                                    contentDescription = "Next plate step",
                                )
                            }
                        }
                    }
                    selectedStep?.let { step ->
                        val isAddStep = step.action == PlateCalculator.Companion.Action.ADD
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .weight(1f)
                                .verticalScroll(rememberScrollState()),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            step.weights.forEach { weight ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(MaterialTheme.shapes.extraLarge)
                                        .background(
                                            if (isAddStep) {
                                                Green.copy(alpha = 0.22f)
                                            } else {
                                                Red.copy(alpha = 0.22f)
                                            }
                                        )
                                        .padding(vertical = 8.dp, horizontal = 16.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = if (isAddStep) "+" else "−",
                                        modifier = Modifier.weight(1f),
                                        style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                                        color = if (isAddStep) Green else Red,
                                        textAlign = TextAlign.End,
                                    )
                                    Text(
                                        text = "${formatPlateWeight(weight)} kg",
                                        modifier = Modifier.weight(2f),
                                        style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                                        color = MaterialTheme.colorScheme.onBackground,
                                        textAlign = TextAlign.Center,
                                    )
                                    Spacer(modifier = Modifier.weight(1f))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private data class MobilePlateUiStep(
    val action: PlateCalculator.Companion.Action,
    val weights: List<Double>,
)

private fun applyPhysicalMobilePlateStep(
    plates: MutableList<Double>,
    step: PlateCalculator.Companion.PlateStep,
) {
    when (step.action) {
        PlateCalculator.Companion.Action.ADD -> plates.add(step.weight)
        PlateCalculator.Companion.Action.REMOVE -> {
            plates.sortDescending()
            if (plates.lastOrNull() == step.weight) plates.removeAt(plates.lastIndex)
            else plates.remove(step.weight)
        }
    }
    plates.sortDescending()
}

private fun navigableMobilePlateSteps(
    result: PlateCalculator.Companion.PlateChangeResult,
): List<MobilePlateUiStep> {
    val effectiveSteps = mutableListOf<PlateCalculator.Companion.PlateStep>()
    val filteringStack = result.previousPlates.sortedDescending().toMutableList()
    result.change.steps.forEach { step ->
        val before = filteringStack.toList()
        applyPhysicalMobilePlateStep(filteringStack, step)
        if (before != filteringStack) effectiveSteps += step
    }

    val groupedSteps = mutableListOf<MobilePlateUiStep>()
    val workingStack = result.previousPlates.sortedDescending().toMutableList()
    var index = 0
    while (index < effectiveSteps.size) {
        val action = effectiveSteps[index].action
        val weights = mutableListOf<Double>()
        var lastAddedIndex: Int? = null
        while (index < effectiveSteps.size && effectiveSteps[index].action == action) {
            val step = effectiveSteps[index]
            val canJoin = when (action) {
                PlateCalculator.Companion.Action.REMOVE ->
                    weights.isEmpty() || workingStack.lastOrNull() == step.weight
                PlateCalculator.Companion.Action.ADD -> {
                    if (weights.isEmpty() || lastAddedIndex == null) {
                        true
                    } else {
                        val after = (workingStack + step.weight).sortedDescending()
                        kotlin.math.abs(after.indexOfLast { it == step.weight } - lastAddedIndex) == 1
                    }
                }
            }
            if (!canJoin) break
            weights += step.weight
            applyPhysicalMobilePlateStep(workingStack, step)
            if (action == PlateCalculator.Companion.Action.ADD) {
                lastAddedIndex = workingStack.indexOfLast { it == step.weight }
            }
            index++
        }
        if (weights.isNotEmpty()) groupedSteps += MobilePlateUiStep(action, weights)
    }
    return groupedSteps
}

private fun applyMobilePlateSteps(
    previousPlates: List<Double>,
    steps: List<MobilePlateUiStep>,
    stepCount: Int,
): List<Double> {
    val working = previousPlates.sortedDescending().toMutableList()
    steps.take(stepCount).forEach { step ->
        step.weights.forEach { weight ->
            when (step.action) {
                PlateCalculator.Companion.Action.ADD -> working.add(weight)
                PlateCalculator.Companion.Action.REMOVE -> {
                    working.sortDescending()
                    if (working.lastOrNull() == weight) working.removeAt(working.lastIndex)
                    else working.remove(weight)
                }
            }
        }
        working.sortDescending()
    }
    return working
}

private fun highlightedMobilePlateIndices(
    platesBeforeStep: List<Double>,
    step: MobilePlateUiStep,
): Set<Int> {
    return when (step.action) {
        PlateCalculator.Companion.Action.REMOVE -> {
            val working = platesBeforeStep.sortedDescending().toMutableList()
            buildSet {
                step.weights.forEach { weight ->
                    if (working.lastOrNull() == weight) {
                        add(working.lastIndex)
                        working.removeAt(working.lastIndex)
                    }
                }
            }
        }
        PlateCalculator.Companion.Action.ADD -> {
            val after = applyMobilePlateSteps(
                previousPlates = platesBeforeStep,
                steps = listOf(step),
                stepCount = 1,
            )
            val remainingBefore = platesBeforeStep.toMutableList()
            buildSet {
                after.forEachIndexed { index, weight ->
                    if (!remainingBefore.remove(weight)) add(index)
                }
            }
        }
    }
}

@Composable
private fun BarbellVisualization(
    plates: List<Double>,
    barbell: Barbell,
    activeStep: MobilePlateUiStep?,
    platesBeforeStep: List<Double>?,
    highlightedPlateIndices: Set<Int>,
    previousPlates: List<Double>,
    isFinalState: Boolean,
    maxLogicalThickness: Float,
    modifier: Modifier = Modifier,
) {
    val sortedPlates = remember(plates, platesBeforeStep, activeStep) {
        if (activeStep?.action == PlateCalculator.Companion.Action.REMOVE && platesBeforeStep != null) {
            platesBeforeStep.sortedDescending()
        } else {
            plates.sortedDescending()
        }
    }
    val plateDetails = remember(sortedPlates, barbell.availablePlates) {
        sortedPlates.map { weight ->
            weight to (barbell.availablePlates.firstOrNull { it.weight == weight }?.thickness ?: 30.0)
        }
    }
    val barColor = if (plateDetails.isEmpty()) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onBackground
    }
    val finalPlateColor = MaterialTheme.colorScheme.primary
    val defaultPlateColor = MaterialTheme.colorScheme.onBackground
    val outlineColor = MaterialTheme.colorScheme.background
    val labelColor = MaterialTheme.colorScheme.onBackground
    val labelTextSize = 20.sp

    Canvas(modifier = modifier.graphicsLayer()) {
        val centerY = size.height / 2f
        val textPaint = android.graphics.Paint().apply {
            color = labelColor.toArgb()
            textSize = labelTextSize.toPx()
            textAlign = android.graphics.Paint.Align.CENTER
            isAntiAlias = true
        }
        val fontMetrics = textPaint.fontMetrics
        val textHeight = fontMetrics.descent - fontMetrics.ascent
        val textToPlatePadding = 4.dp.toPx()
        val labelCollisionPadding = 6.dp.toPx()
        val collarWidth = 10.dp.toPx()
        val sleeveEndPadding = 12.dp.toPx()
        val labelReserve = if (plateDetails.isNotEmpty()) textToPlatePadding + textHeight else 0f
        val maxAvailablePlateHeight = (size.height - labelReserve * 2f).coerceAtLeast(10f)
        val sleeveHeight = maxAvailablePlateHeight * 0.2f
        val shaftHeight = sleeveHeight * 0.5f
        val collarHeight = sleeveHeight * 1.5f

        val totalThickness = maxLogicalThickness.coerceAtLeast(1f)
        val physicalSleeveLength = barbell.sleeveLength.toFloat()
        val emptySleeveAllowance = totalThickness * 0.2f
        val displayedSleeveLength = if (physicalSleeveLength > 0f) {
            (totalThickness + emptySleeveAllowance).coerceIn(1f, physicalSleeveLength)
        } else {
            totalThickness
        }

        fun renderedPlateWidths(sleeveWidth: Float): List<Float> {
            val scale = sleeveWidth / displayedSleeveLength.coerceAtLeast(1f)
            var remainingWidth = sleeveWidth
            return plateDetails.map { (_, thickness) ->
                (thickness.toFloat() * scale)
                    .coerceIn(MobileMinPlateWidth.toPx(), MobileMaxPlateWidth.toPx())
                    .coerceAtMost(remainingWidth)
                    .also { remainingWidth = (remainingWidth - it).coerceAtLeast(0f) }
            }
        }

        var sleeveStart = size.width * 0.44f + collarWidth / 2f
        repeat(2) {
            val availableSleeveWidth = (size.width - sleeveStart - sleeveEndPadding).coerceAtLeast(0f)
            val plateStackWidth = renderedPlateWidths(availableSleeveWidth).sum()
            if (plateStackWidth > 0f) {
                sleeveStart = (size.width - plateStackWidth) / 2f
            }
        }
        val collarStart = sleeveStart - collarWidth
        val sleeveWidth = (size.width - sleeveStart - sleeveEndPadding).coerceAtLeast(0f)
        val renderedWidths = renderedPlateWidths(sleeveWidth)

        drawRect(
            color = barColor,
            topLeft = androidx.compose.ui.geometry.Offset(0f, centerY - shaftHeight / 2f),
            size = androidx.compose.ui.geometry.Size(collarStart, shaftHeight),
        )
        drawRoundRect(
            color = barColor,
            topLeft = androidx.compose.ui.geometry.Offset(collarStart, centerY - collarHeight / 2f),
            size = androidx.compose.ui.geometry.Size(collarWidth, collarHeight),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()),
        )
        drawRect(
            color = barColor,
            topLeft = androidx.compose.ui.geometry.Offset(sleeveStart, centerY - sleeveHeight / 2f),
            size = androidx.compose.ui.geometry.Size(sleeveWidth, sleeveHeight),
        )

        if (plateDetails.isEmpty()) return@Canvas

        val maxWeight = plateDetails.maxOf { it.first }.coerceAtLeast(1.0)
        var x = sleeveStart
        var topLabelRight = Float.NEGATIVE_INFINITY
        var bottomLabelRight = Float.NEGATIVE_INFINITY
        val globalPlateTop = centerY - maxAvailablePlateHeight / 2f
        val globalPlateBottom = centerY + maxAvailablePlateHeight / 2f

        plateDetails.forEachIndexed { index, (weight, _) ->
            val width = renderedWidths[index]
            val weightRatio = sqrt((weight / maxWeight).toFloat().coerceIn(0f, 1f))
            val height = maxAvailablePlateHeight * (0.3f + 0.7f * weightRatio)
            val topLeft = androidx.compose.ui.geometry.Offset(x, centerY - height / 2f)
            val plateSize = androidx.compose.ui.geometry.Size(width, height)
            val radius = androidx.compose.ui.geometry.CornerRadius(
                (width / 2f).coerceAtMost(height / 2f)
            )
            val isHighlighted = highlightedPlateIndices.contains(index)
            val isNewAtThisPosition = !isFinalState && previousPlates.getOrNull(index) != weight
            val plateColor = when {
                isFinalState -> finalPlateColor
                isHighlighted && activeStep?.action == PlateCalculator.Companion.Action.REMOVE -> Red
                isHighlighted && activeStep?.action == PlateCalculator.Companion.Action.ADD -> Green
                isNewAtThisPosition -> Green
                else -> defaultPlateColor
            }
            val label = formatPlateWeight(weight)
            val labelWidth = textPaint.measureText(label)
            val plateCenterX = x + width / 2f
            val isTopLabel = index % 2 == 0
            val previousRight = if (isTopLabel) topLabelRight else bottomLabelRight
            val labelCenterX = maxOf(
                plateCenterX,
                previousRight + labelCollisionPadding + labelWidth / 2f,
            ).coerceAtMost(size.width - labelWidth / 2f - 4.dp.toPx())
            if (isTopLabel) topLabelRight = labelCenterX + labelWidth / 2f
            else bottomLabelRight = labelCenterX + labelWidth / 2f

            val textBaseline = if (isTopLabel) {
                globalPlateTop - textToPlatePadding - textHeight - fontMetrics.ascent
            } else {
                globalPlateBottom + textToPlatePadding - fontMetrics.ascent
            }
            val lineEndY = if (isTopLabel) {
                textBaseline + fontMetrics.descent
            } else {
                globalPlateBottom + textToPlatePadding
            }
            val guide = Path().apply {
                moveTo(plateCenterX, centerY)
                lineTo(labelCenterX, lineEndY)
            }
            drawPath(
                path = guide,
                color = labelColor.copy(alpha = 0.5f),
                style = Stroke(
                    width = 1.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(5f, 5f)),
                ),
            )
            drawRoundRect(plateColor, topLeft, plateSize, radius)
            drawRoundRect(
                color = outlineColor,
                topLeft = topLeft,
                size = plateSize,
                cornerRadius = radius,
                style = Stroke(width = 1.5.dp.toPx()),
            )
            drawIntoCanvas { canvas ->
                canvas.nativeCanvas.drawText(label, labelCenterX, textBaseline, textPaint)
            }
            x += width
        }
    }
}

private fun formatPlateWeight(weight: Double): String =
    if (weight % 1.0 == 0.0) weight.toInt().toString()
    else weight.toString().trimEnd('0').trimEnd('.')



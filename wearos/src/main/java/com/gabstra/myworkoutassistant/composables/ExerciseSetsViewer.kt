package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.Yellow
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.display.ExerciseSetDisplayRow
import com.gabstra.myworkoutassistant.shared.workout.display.buildExerciseSetDisplayRows
import com.gabstra.myworkoutassistant.shared.workout.display.buildSupersetSetDisplayRows
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutRestRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutSetDisplayIdentifier
import com.gabstra.myworkoutassistant.shared.workout.display.findDisplayRowIndex
import com.gabstra.myworkoutassistant.shared.workout.display.setLikeIdOrNull
import com.gabstra.myworkoutassistant.shared.workout.display.toExerciseSetDisplayRowOrNull
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

enum class ProgressState { PAST, CURRENT, FUTURE }

internal fun buildSetIdentifier(
    viewModel: AppViewModel,
    exerciseId: UUID,
    setState: WorkoutState.Set,
): String? = buildWorkoutSetDisplayIdentifier(viewModel, exerciseId, setState)

internal fun buildUnilateralSideBadge(
    sideIndex: UInt?,
    intraSetTotal: UInt?,
): String? = buildUnilateralSideLabel(sideIndex, intraSetTotal)

internal fun resolveExerciseSetsScrollTargetIndex(
    viewModel: AppViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    stateToMatch: WorkoutState?,
    firstSetListItemIndex: Int,
): Int? {
    val supersetId = viewModel.supersetIdByExerciseId[exercise.id]
    val displayRows = if (supersetId != null) {
        buildSupersetSetDisplayRows(viewModel = viewModel, supersetId = supersetId)
    } else {
        buildExerciseSetDisplayRows(viewModel = viewModel, exerciseId = exercise.id)
    }
    if (displayRows.isEmpty()) return null

    val setIndex = stateToMatch?.let {
        findDisplayRowIndex(
            displayRows = displayRows,
            stateToMatch = it,
            fallbackSetId = currentSet.id
        )
    } ?: 0
    return (firstSetListItemIndex + setIndex).coerceAtLeast(firstSetListItemIndex)
}

internal data class SetTrendIndicator(
    val glyph: String,
    val color: Color,
)

internal fun buildSetTrendIndicator(setState: WorkoutState.Set): SetTrendIndicator? {
    return when (compareSets(setState.historicalSetData, setState.currentSetData)) {
        SetComparison.BETTER -> SetTrendIndicator(glyph = "↑", color = Green)
        SetComparison.WORSE -> SetTrendIndicator(glyph = "↓", color = Red)
        SetComparison.MIXED -> SetTrendIndicator(glyph = "~", color = Yellow)
        SetComparison.EQUAL -> null
    }
}

internal fun resolveSetTrendIndicator(setState: WorkoutState.Set): SetTrendIndicator? {
    val isWorkSet = when (val set = setState.set) {
        is WeightSet -> set.subCategory == SetSubCategory.WorkSet
        is com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet ->
            set.subCategory == SetSubCategory.WorkSet
        else -> false
    }
    if (!isWorkSet) return null
    return buildSetTrendIndicator(setState)
}

internal fun userEditedTrendForWeight(setState: WorkoutState.Set): SetTrendIndicator? {
    val previousSetData = setState.previousSetData ?: return null
    val currentSetData = setState.currentSetData
    return when {
        previousSetData is WeightSetData && currentSetData is WeightSetData -> {
            when {
                currentSetData.actualWeight > previousSetData.actualWeight ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.actualWeight < previousSetData.actualWeight ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        previousSetData is BodyWeightSetData && currentSetData is BodyWeightSetData -> {
            when {
                currentSetData.additionalWeight > previousSetData.additionalWeight ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.additionalWeight < previousSetData.additionalWeight ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> null
    }
}

internal fun userEditedTrendForReps(setState: WorkoutState.Set): SetTrendIndicator? {
    val previousSetData = setState.previousSetData ?: return null
    val currentSetData = setState.currentSetData
    return when {
        previousSetData is WeightSetData && currentSetData is WeightSetData -> {
            when {
                currentSetData.actualReps > previousSetData.actualReps ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.actualReps < previousSetData.actualReps ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        previousSetData is BodyWeightSetData && currentSetData is BodyWeightSetData -> {
            when {
                currentSetData.actualReps > previousSetData.actualReps ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.actualReps < previousSetData.actualReps ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> null
    }
}

internal fun userEditedTrendForTime(setState: WorkoutState.Set): SetTrendIndicator? {
    val previousSetData = setState.previousSetData ?: return null
    val currentSetData = setState.currentSetData
    return when {
        previousSetData is TimedDurationSetData && currentSetData is TimedDurationSetData -> {
            when {
                currentSetData.startTimer > previousSetData.startTimer ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.startTimer < previousSetData.startTimer ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        previousSetData is EnduranceSetData && currentSetData is EnduranceSetData -> {
            when {
                currentSetData.startTimer > previousSetData.startTimer ->
                    SetTrendIndicator(glyph = "↑", color = Green)
                currentSetData.startTimer < previousSetData.startTimer ->
                    SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> null
    }
}

private fun isWorkSet(setState: WorkoutState.Set): Boolean = when (val set = setState.set) {
    is WeightSet -> set.subCategory == SetSubCategory.WorkSet
    is com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet ->
        set.subCategory == SetSubCategory.WorkSet
    else -> false
}

internal fun trendForWeight(setState: WorkoutState.Set): SetTrendIndicator? {
    if (!isWorkSet(setState)) return null
    val prev = setState.historicalSetData ?: return null
    val curr = setState.currentSetData
    when {
        curr is WeightSetData && prev is WeightSetData -> {
            return when {
                curr.actualWeight > prev.actualWeight -> SetTrendIndicator(glyph = "↑", color = Green)
                curr.actualWeight < prev.actualWeight -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        curr is BodyWeightSetData && prev is BodyWeightSetData -> {
            return when {
                curr.getWeight() > prev.getWeight() -> SetTrendIndicator(glyph = "↑", color = Green)
                curr.getWeight() < prev.getWeight() -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> return null
    }
}

internal fun trendForReps(setState: WorkoutState.Set): SetTrendIndicator? {
    if (!isWorkSet(setState)) return null
    val prev = setState.historicalSetData ?: return null
    val curr = setState.currentSetData
    when {
        curr is WeightSetData && prev is WeightSetData -> {
            return when {
                curr.actualReps > prev.actualReps -> SetTrendIndicator(glyph = "↑", color = Green)
                curr.actualReps < prev.actualReps -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        curr is BodyWeightSetData && prev is BodyWeightSetData -> {
            return when {
                curr.actualReps > prev.actualReps -> SetTrendIndicator(glyph = "↑", color = Green)
                curr.actualReps < prev.actualReps -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> return null
    }
}

internal fun trendForTime(setState: WorkoutState.Set): SetTrendIndicator? {
    val prev = setState.historicalSetData ?: return null
    val curr = setState.currentSetData
    when {
        curr is TimedDurationSetData && prev is TimedDurationSetData -> {
            val beforeDuration = prev.endTimer - prev.startTimer
            val afterDuration = curr.endTimer - curr.startTimer
            return when {
                afterDuration > beforeDuration -> SetTrendIndicator(glyph = "↑", color = Green)
                afterDuration < beforeDuration -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        curr is EnduranceSetData && prev is EnduranceSetData -> {
            val beforeDuration = prev.endTimer - prev.startTimer
            val afterDuration = curr.endTimer - curr.startTimer
            return when {
                afterDuration > beforeDuration -> SetTrendIndicator(glyph = "↑", color = Green)
                afterDuration < beforeDuration -> SetTrendIndicator(glyph = "↓", color = Red)
                else -> null
            }
        }
        else -> return null
    }
}

@Composable
internal fun ExerciseSetsTableHeader(
    modifier: Modifier = Modifier,
    useWeightHeader: Boolean,
) {
    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    if (useWeightHeader) {
        Row(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = 2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = "SET",
                style = headerStyle,
                textAlign = TextAlign.Center
            )
            Text(
                modifier = Modifier.weight(2f),
                text = "WEIGHT (KG)",
                style = headerStyle,
                textAlign = TextAlign.Center
            )
            Text(
                modifier = Modifier.weight(1f),
                text = "REPS",
                style = headerStyle,
                textAlign = TextAlign.Center
            )
        }
    } else {
        Row(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = 2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = "SET",
                style = headerStyle,
                textAlign = TextAlign.Center
            )
            Text(
                modifier = Modifier.weight(3f),
                text = "TIME (HH:MM:SS)",
                style = headerStyle,
                textAlign = TextAlign.Center
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: AppViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    setIdentifier: String? = null,
    sideBadge: String? = null,
    index: Int?,
    isCurrentSet: Boolean,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    hasUnconfirmedLoadSelectionForExercise: Boolean = false,
){
    val itemStyle = MaterialTheme.typography.numeralSmall

    val equipment = setState.equipmentId?.let { viewModel.getEquipmentById(it) }
    val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(setState.set)
    val isPendingCalibration = CalibrationHelper.shouldShowPendingCalibrationForWorkSet(
        setState = setState,
        hasUnconfirmedLoadSelectionForExercise
    )
    val shouldHideCalibrationExecutionWeight = CalibrationHelper.shouldHideCalibrationExecutionWeight(
        setState = setState,
        hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
    )

    Box(
        modifier = modifier,
    ){
        val rowSetContentDescription = when {
            !setIdentifier.isNullOrBlank() && !sideBadge.isNullOrBlank() -> "$setIdentifier$sideBadge"
            !setIdentifier.isNullOrBlank() -> setIdentifier
            !sideBadge.isNullOrBlank() -> sideBadge
            else -> null
        }
        Row(
            modifier = Modifier.fillMaxSize()
                .padding(2.5.dp)
                .then(
                    rowSetContentDescription?.let { contentDescription ->
                        Modifier.semantics(mergeDescendants = false) {
                            this.contentDescription = contentDescription
                        }
                    } ?: Modifier
                ),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val baseSetDisplayText = rowSetContentDescription ?: ""
            ScalableFadingText(
                modifier = Modifier
                    .weight(1f)
                    .then(
                        if (!setIdentifier.isNullOrBlank()) {
                            Modifier.semantics(mergeDescendants = false) {
                                contentDescription = setIdentifier
                            }
                        } else Modifier
                    ),
                text = baseSetDisplayText,
                style = itemStyle,
                color = textColor
            )

            when (setState.currentSetData) {
                is WeightSetData -> {
                    val weightSetData = (setState.currentSetData as WeightSetData)

                    val weightText = equipment?.formatWeight(weightSetData.actualWeight) ?: "-"
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> "TBD"
                        isCalibrationSet && setState.isCalibrationSet -> weightText
                        isPendingCalibration -> "TBD"
                        else -> weightText
                    }

                    Row(
                        modifier = Modifier.weight(2f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = displayWeightText,
                            style = itemStyle,
                            color = textColor,
                        )
                    }
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = "${weightSetData.actualReps}",
                            style = itemStyle,
                            color = textColor,
                        )
                    }
                }

                is BodyWeightSetData -> {
                    val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)

                    val baseWeightText = if(equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                        equipment.formatWeight(bodyWeightSetData.additionalWeight)
                    }else {
                        "BW"
                    }
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> "TBD"
                        isCalibrationSet && setState.isCalibrationSet && equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> baseWeightText
                        isPendingCalibration -> "TBD"
                        else -> baseWeightText
                    }

                    Row(
                        modifier = Modifier.weight(2f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = displayWeightText,
                            style = itemStyle,
                            color = textColor
                        )
                    }
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = "${bodyWeightSetData.actualReps}",
                            style = itemStyle,
                            color = textColor
                        )
                    }
                }

                is TimedDurationSetData -> {
                    val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                    Row(
                        modifier = Modifier.weight(3f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = FormatTime(timedDurationSetData.startTimer / 1000),
                            style = itemStyle,
                            color = textColor
                        )
                    }
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    Row(
                        modifier = Modifier.weight(3f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ScalableFadingText(
                            text = FormatTime(enduranceSetData.startTimer / 1000),
                            style = itemStyle,
                            color = textColor
                        )
                    }
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }
    }
}

@Composable
private fun CenteredLabelRow(
    modifier: Modifier,
    text: String,
    textColor: Color,
) {
    val itemStyle = MaterialTheme.typography.numeralSmall
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 2.5.dp, horizontal = 5.dp),
        contentAlignment = Alignment.Center
    ) {
        ScalableText(
            text = text,
            color = textColor,
            style = itemStyle,
        )
    }
}

fun TransformingLazyColumnScope.ExerciseSetsViewer(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    transformationSpec: TransformationSpec,
    stateToMatch: WorkoutState?,
    progressState: ProgressState = ProgressState.CURRENT,
){
    val supersetId = viewModel.supersetIdByExerciseId[exercise.id]
    val displayRows = if (supersetId != null) {
        buildSupersetSetDisplayRows(viewModel = viewModel, supersetId = supersetId)
    } else {
        buildExerciseSetDisplayRows(viewModel = viewModel, exerciseId = exercise.id)
    }

    val setIndex = stateToMatch?.let {
        findDisplayRowIndex(
            displayRows = displayRows,
            stateToMatch = it,
            fallbackSetId = currentSet.id
        )
    } ?: 0

    val unilateralSideBadgeByRowIndex = displayRows.mapIndexedNotNull { rowIndex, displayRow ->
        val setRow = displayRow as? ExerciseSetDisplayRow.SetRow ?: return@mapIndexedNotNull null
        val intraSetTotal = setRow.state.intraSetTotal?.toInt() ?: return@mapIndexedNotNull null
        if (!setRow.state.isUnilateral) return@mapIndexedNotNull null
        val sideIndex = displayRows
            .subList(0, rowIndex + 1)
            .count { row ->
                row is ExerciseSetDisplayRow.SetRow && row.state.set.id == setRow.state.set.id
            }
            .coerceIn(1, intraSetTotal)
        val sideBadge = buildUnilateralSideLabel(
            sideIndex = sideIndex.toUInt(),
            intraSetTotal = intraSetTotal.toUInt()
        ) ?: return@mapIndexedNotNull null
        rowIndex to sideBadge
    }.toMap()

    val exerciseIdsForLoadFlag: Set<UUID> = displayRows.mapNotNull { row ->
        (row as? ExerciseSetDisplayRow.SetRow)?.state?.exerciseId
    }.toSet()

    val hasUnconfirmedLoadByExerciseId: Map<UUID, Boolean> =
        if (exerciseIdsForLoadFlag.isEmpty()) {
            emptyMap()
        } else {
            exerciseIdsForLoadFlag.associateWith { exerciseId ->
                CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
                    allWorkoutStates = viewModel.allWorkoutStates,
                    exerciseId = exerciseId
                )
            }
        }

    val scrollKey = supersetId ?: exercise.id

    @Composable
    fun MeasuredSetTableRow(
        displayRow: ExerciseSetDisplayRow,
        rowIndex: Int,
    ) {
        val currentExercisePendingColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
        val borderColor = when (progressState) {
            ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
            ProgressState.CURRENT -> when {
                rowIndex == setIndex -> Orange
                rowIndex < setIndex -> MaterialTheme.colorScheme.primary
                else -> currentExercisePendingColor
            }
            ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val textColor = borderColor

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(25.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            val shape = RoundedCornerShape(25)

            val rowModifier = Modifier
                .height(25.dp)
                //.padding(bottom = 2.5.dp)
                .border(BorderStroke(1.dp, borderColor), shape)
                //.background(backgroundColor, shape)

            when (displayRow) {
                is ExerciseSetDisplayRow.SetRow -> SetTableRow(
                    modifier = rowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = displayRow.state,
                    setIdentifier = buildSetIdentifier(
                        viewModel = viewModel,
                        exerciseId = displayRow.state.exerciseId,
                        setState = displayRow.state
                    ),
                    sideBadge = unilateralSideBadgeByRowIndex[rowIndex],
                    index = rowIndex,
                    isCurrentSet = rowIndex == setIndex,
                    textColor = textColor,
                    hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadByExerciseId[displayRow.state.exerciseId]
                        ?: false
                )
                is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = "SET LOAD",
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.RestRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = buildWorkoutRestRowLabel(displayRow.state),
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.CalibrationRIRRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = "SET RIR",
                    textColor = textColor
                )
            }
        }
    }

    items(
        items = displayRows.withIndex().toList(),
        key = { indexedRow ->
            val row = indexedRow.value
            buildString {
                append(row::class.simpleName ?: "row")
                append(":")
                append(row.setLikeIdOrNull()?.toString() ?: "no-set")
                append(":")
                append(indexedRow.index)
            }
        }
    ) { indexedRow ->
        val rowIndex = indexedRow.index
        val displayRow = indexedRow.value
        val rowModifier = Modifier
            .fillMaxWidth()
            .transformedHeight(this, transformationSpec)
            .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } }

        Box(
            modifier = rowModifier,
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier.graphicsLayer {
                    with(transformationSpec) { applyContentTransformation(scrollProgress) }
                }
            ) {
                MeasuredSetTableRow(displayRow = displayRow, rowIndex = rowIndex)
            }
        }
    }
}

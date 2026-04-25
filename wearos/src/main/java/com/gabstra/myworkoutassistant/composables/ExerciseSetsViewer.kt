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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material3.LocalTextConfiguration
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

private fun trendPreferHigher(current: Int, previous: Int): SetTrendIndicator? = when {
    current > previous -> SetTrendIndicator(glyph = "↑", color = Green)
    current < previous -> SetTrendIndicator(glyph = "↓", color = Red)
    else -> null
}

private fun trendPreferHigher(current: Double, previous: Double): SetTrendIndicator? = when {
    current > previous -> SetTrendIndicator(glyph = "↑", color = Green)
    current < previous -> SetTrendIndicator(glyph = "↓", color = Red)
    else -> null
}

@Composable
private fun ExerciseSetRowFadingCell(
    text: String,
    hideSetListRowText: Boolean,
    style: TextStyle,
    color: Color,
    modifier: Modifier = Modifier,
) {
    if (hideSetListRowText) {
        Box(modifier = modifier)
    } else {
        ScalableFadingText(
            modifier = modifier,
            text = text,
            style = style,
            color = color,
        )
    }
}

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
        previousSetData is WeightSetData && currentSetData is WeightSetData ->
            trendPreferHigher(currentSetData.actualWeight, previousSetData.actualWeight)
        previousSetData is BodyWeightSetData && currentSetData is BodyWeightSetData ->
            trendPreferHigher(currentSetData.additionalWeight, previousSetData.additionalWeight)
        else -> null
    }
}

internal fun userEditedTrendForReps(setState: WorkoutState.Set): SetTrendIndicator? {
    val previousSetData = setState.previousSetData ?: return null
    val currentSetData = setState.currentSetData
    return when {
        previousSetData is WeightSetData && currentSetData is WeightSetData ->
            trendPreferHigher(currentSetData.actualReps, previousSetData.actualReps)
        previousSetData is BodyWeightSetData && currentSetData is BodyWeightSetData ->
            trendPreferHigher(currentSetData.actualReps, previousSetData.actualReps)
        else -> null
    }
}

internal fun userEditedTrendForTime(setState: WorkoutState.Set): SetTrendIndicator? {
    val previousSetData = setState.previousSetData ?: return null
    val currentSetData = setState.currentSetData
    return when {
        previousSetData is TimedDurationSetData && currentSetData is TimedDurationSetData ->
            trendPreferHigher(currentSetData.startTimer, previousSetData.startTimer)
        previousSetData is EnduranceSetData && currentSetData is EnduranceSetData ->
            trendPreferHigher(currentSetData.startTimer, previousSetData.startTimer)
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
    return when {
        curr is WeightSetData && prev is WeightSetData ->
            trendPreferHigher(curr.actualWeight, prev.actualWeight)
        curr is BodyWeightSetData && prev is BodyWeightSetData ->
            trendPreferHigher(curr.getWeight(), prev.getWeight())
        else -> null
    }
}

internal fun trendForReps(setState: WorkoutState.Set): SetTrendIndicator? {
    if (!isWorkSet(setState)) return null
    val prev = setState.historicalSetData ?: return null
    val curr = setState.currentSetData
    return when {
        curr is WeightSetData && prev is WeightSetData ->
            trendPreferHigher(curr.actualReps, prev.actualReps)
        curr is BodyWeightSetData && prev is BodyWeightSetData ->
            trendPreferHigher(curr.actualReps, prev.actualReps)
        else -> null
    }
}

internal fun trendForTime(setState: WorkoutState.Set): SetTrendIndicator? {
    val prev = setState.historicalSetData ?: return null
    val curr = setState.currentSetData
    return when {
        curr is TimedDurationSetData && prev is TimedDurationSetData -> {
            val beforeDuration = prev.endTimer - prev.startTimer
            val afterDuration = curr.endTimer - curr.startTimer
            trendPreferHigher(afterDuration, beforeDuration)
        }
        curr is EnduranceSetData && prev is EnduranceSetData -> {
            val beforeDuration = prev.endTimer - prev.startTimer
            val afterDuration = curr.endTimer - curr.startTimer
            trendPreferHigher(afterDuration, beforeDuration)
        }
        else -> null
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
    hideSetListRowText: Boolean = false,
) {
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
            ExerciseSetRowFadingCell(
                text = baseSetDisplayText,
                hideSetListRowText = hideSetListRowText,
                style = itemStyle,
                color = textColor,
                modifier = Modifier
                    .weight(1f)
                    .then(
                        if (!setIdentifier.isNullOrBlank()) {
                            Modifier.semantics(mergeDescendants = false) {
                                contentDescription = setIdentifier
                            }
                        } else Modifier
                    ),
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
                        ExerciseSetRowFadingCell(
                            text = displayWeightText,
                            hideSetListRowText = hideSetListRowText,
                            style = itemStyle,
                            color = textColor,
                        )
                    }
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ExerciseSetRowFadingCell(
                            text = "${weightSetData.actualReps}",
                            hideSetListRowText = hideSetListRowText,
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
                        ExerciseSetRowFadingCell(
                            text = displayWeightText,
                            hideSetListRowText = hideSetListRowText,
                            style = itemStyle,
                            color = textColor,
                        )
                    }
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(2.5.dp,Alignment.CenterHorizontally)
                    ) {
                        ExerciseSetRowFadingCell(
                            text = "${bodyWeightSetData.actualReps}",
                            hideSetListRowText = hideSetListRowText,
                            style = itemStyle,
                            color = textColor,
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
                        ExerciseSetRowFadingCell(
                            text = FormatTime(timedDurationSetData.startTimer / 1000),
                            hideSetListRowText = hideSetListRowText,
                            style = itemStyle,
                            color = textColor,
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
                        ExerciseSetRowFadingCell(
                            text = FormatTime(enduranceSetData.startTimer / 1000),
                            hideSetListRowText = hideSetListRowText,
                            style = itemStyle,
                            color = textColor,
                        )
                    }
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }
    }
}

@Composable
private fun FastPageExercisesSetTableRow(
    rowModel: PageExercisesRowModel,
    fittedRow: PageExercisesFittedRow?,
    enableFadingText: Boolean,
    hideSetListRowText: Boolean,
    modifier: Modifier = Modifier,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
) {
    val itemStyle = MaterialTheme.typography.numeralSmall

    Row(
        modifier = modifier
            .padding(2.5.dp)
            .then(
                rowModel.semanticsLabel?.let { contentDescription ->
                    Modifier.semantics(mergeDescendants = false) {
                        this.contentDescription = contentDescription
                    }
                } ?: Modifier
            ),
        verticalAlignment = Alignment.CenterVertically
    ) {
        FastPageExercisesCellText(
            modifier = Modifier
                .weight(1f)
                .height(fittedRow?.setText?.containerHeight ?: PageExercisesSetRowInnerHeight)
                .then(
                    if (!rowModel.setIdentifier.isNullOrBlank()) {
                        Modifier.semantics(mergeDescendants = false) {
                            contentDescription = rowModel.setIdentifier
                        }
                    } else {
                        Modifier
                    }
                ),
            text = rowModel.setText.orEmpty(),
            fittedText = fittedRow?.setText,
            enableFadingText = enableFadingText,
            color = textColor,
            style = itemStyle,
            hideSetListRowText = hideSetListRowText,
        )

        FastPageExercisesCellText(
            modifier = Modifier
                .weight(rowModel.valueWeight)
                .height(fittedRow?.valueText?.containerHeight ?: PageExercisesSetRowInnerHeight),
            text = rowModel.valueText.orEmpty(),
            fittedText = fittedRow?.valueText,
            enableFadingText = enableFadingText,
            color = textColor,
            style = itemStyle,
            hideSetListRowText = hideSetListRowText,
        )
        rowModel.repsText?.let { repsText ->
            FastPageExercisesCellText(
                modifier = Modifier
                    .weight(1f)
                    .height(fittedRow?.repsText?.containerHeight ?: PageExercisesSetRowInnerHeight),
                text = repsText,
                fittedText = fittedRow?.repsText,
                enableFadingText = enableFadingText,
                color = textColor,
                style = itemStyle,
                hideSetListRowText = hideSetListRowText,
            )
        }
    }
}

@Composable
private fun FastPageExercisesCellText(
    text: String,
    fittedText: PageExercisesFittedTextCell?,
    enableFadingText: Boolean,
    color: Color,
    style: TextStyle,
    hideSetListRowText: Boolean,
    modifier: Modifier = Modifier,
) {
    if (fittedText != null && !hideSetListRowText) {
        FastFittedFadingTextCell(
            fittedText = fittedText,
            enableFadingText = enableFadingText,
            color = color,
            style = style,
            modifier = modifier,
        )
    } else {
        ExerciseSetRowFadingCell(
            text = text,
            hideSetListRowText = hideSetListRowText,
            style = style,
            color = color,
            modifier = modifier,
        )
    }
}

@Composable
private fun CenteredLabelRow(
    modifier: Modifier,
    text: String,
    fittedText: PageExercisesFittedTextCell?,
    textColor: Color,
    hideSetListRowText: Boolean,
) {
    val itemStyle = MaterialTheme.typography.numeralSmall
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 2.5.dp, horizontal = 5.dp),
        contentAlignment = Alignment.Center
    ) {
        if (!hideSetListRowText && fittedText != null) {
            FastFittedTextCell(
                fittedText = fittedText,
                color = textColor,
                style = itemStyle,
            )
        } else if (!hideSetListRowText) {
            ScalableText(
                text = text,
                color = textColor,
                style = itemStyle,
            )
        }
    }
}

private val PageExercisesSetRowHeight = 25.dp
private val PageExercisesSetRowPadding = 2.5.dp
private val PageExercisesSetRowInnerHeight = PageExercisesSetRowHeight - PageExercisesSetRowPadding * 2
private val PageExercisesCenteredRowHorizontalPadding = 5.dp
private val PageExercisesCenteredRowVerticalPadding = 2.5.dp

@Immutable
internal data class PageExercisesFittedTextCell(
    val text: String,
    val fontSize: TextUnit,
    val inkWidth: Dp,
    val containerWidth: Dp,
    val containerHeight: Dp,
    val overflows: Boolean,
)

@Immutable
internal data class PageExercisesFittedRow(
    val key: String,
    val setText: PageExercisesFittedTextCell? = null,
    val valueText: PageExercisesFittedTextCell? = null,
    val repsText: PageExercisesFittedTextCell? = null,
    val centeredText: PageExercisesFittedTextCell? = null,
)

@Immutable
internal data class PageExercisesFittedRows(
    val preparedRows: PageExercisesPreparedRows,
    val rowsByKey: Map<String, PageExercisesFittedRow>,
)

private data class PageExercisesTextFitKey(
    val text: String,
    val widthPx: Int,
    val heightPx: Int,
)

@Composable
internal fun rememberPageExercisesFittedRows(
    preparedRows: PageExercisesPreparedRows?,
    rowMaxWidth: Dp,
    rowMaxHeight: Dp = PageExercisesSetRowHeight,
): PageExercisesFittedRows? {
    if (preparedRows == null) return null

    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()
    val itemStyle = MaterialTheme.typography.numeralSmall
    val baseStyle = remember(itemStyle) { pageExercisesBaseTextStyle(itemStyle) }
    val densityValue = density.density
    val fontScale = density.fontScale

    return remember(
        preparedRows,
        rowMaxWidth,
        rowMaxHeight,
        baseStyle,
        densityValue,
        fontScale,
    ) {
        buildPageExercisesFittedRows(
            preparedRows = preparedRows,
            rowMaxWidth = rowMaxWidth,
            rowMaxHeight = rowMaxHeight,
            baseStyle = baseStyle,
            textMeasurer = textMeasurer,
            density = density,
        )
    }
}

internal fun buildPageExercisesFittedRows(
    preparedRows: PageExercisesPreparedRows,
    rowMaxWidth: Dp,
    rowMaxHeight: Dp,
    baseStyle: TextStyle,
    textMeasurer: TextMeasurer,
    density: Density,
): PageExercisesFittedRows {
    val cache = mutableMapOf<PageExercisesTextFitKey, PageExercisesFittedTextCell>()
    val setInnerWidth = (rowMaxWidth - PageExercisesSetRowPadding * 2).coerceAtLeast(0.dp)
    val setInnerHeight = (rowMaxHeight - PageExercisesSetRowPadding * 2).coerceAtLeast(0.dp)
    val centeredWidth = (rowMaxWidth - PageExercisesCenteredRowHorizontalPadding * 2).coerceAtLeast(0.dp)
    val centeredHeight = (rowMaxHeight - PageExercisesCenteredRowVerticalPadding * 2).coerceAtLeast(0.dp)

    val rows = preparedRows.rowModels.associate { rowModel ->
        val fittedRow = when (rowModel.contentType) {
            PageExercisesRowContentType.Set -> {
                val hasReps = rowModel.repsText != null
                val totalWeight = 1f + rowModel.valueWeight + if (hasReps) 1f else 0f
                val setTextWidth = setInnerWidth * (1f / totalWeight)
                val valueTextWidth = setInnerWidth * (rowModel.valueWeight / totalWeight)
                val repsTextWidth = setInnerWidth * (1f / totalWeight)

                PageExercisesFittedRow(
                    key = rowModel.key,
                    setText = fitPageExercisesTextCell(
                        text = rowModel.setText.orEmpty(),
                        containerWidth = setTextWidth,
                        containerHeight = setInnerHeight,
                        baseStyle = baseStyle,
                        textMeasurer = textMeasurer,
                        density = density,
                        cache = cache,
                    ),
                    valueText = fitPageExercisesTextCell(
                        text = rowModel.valueText.orEmpty(),
                        containerWidth = valueTextWidth,
                        containerHeight = setInnerHeight,
                        baseStyle = baseStyle,
                        textMeasurer = textMeasurer,
                        density = density,
                        cache = cache,
                    ),
                    repsText = rowModel.repsText?.let { repsText ->
                        fitPageExercisesTextCell(
                            text = repsText,
                            containerWidth = repsTextWidth,
                            containerHeight = setInnerHeight,
                            baseStyle = baseStyle,
                            textMeasurer = textMeasurer,
                            density = density,
                            cache = cache,
                        )
                    },
                )
            }
            PageExercisesRowContentType.CalibrationLoad,
            PageExercisesRowContentType.Rest,
            PageExercisesRowContentType.CalibrationRir -> PageExercisesFittedRow(
                key = rowModel.key,
                centeredText = fitPageExercisesTextCell(
                    text = rowModel.centeredText.orEmpty(),
                    containerWidth = centeredWidth,
                    containerHeight = centeredHeight,
                    baseStyle = baseStyle,
                    textMeasurer = textMeasurer,
                    density = density,
                    cache = cache,
                ),
            )
        }

        rowModel.key to fittedRow
    }

    return PageExercisesFittedRows(
        preparedRows = preparedRows,
        rowsByKey = rows,
    )
}

private fun fitPageExercisesTextCell(
    text: String,
    containerWidth: Dp,
    containerHeight: Dp,
    baseStyle: TextStyle,
    textMeasurer: TextMeasurer,
    density: Density,
    cache: MutableMap<PageExercisesTextFitKey, PageExercisesFittedTextCell>,
): PageExercisesFittedTextCell {
    val widthPx = with(density) { containerWidth.toPx() }.toInt().coerceAtLeast(0)
    val heightPx = with(density) { containerHeight.toPx() }.toInt().coerceAtLeast(0)
    val key = PageExercisesTextFitKey(
        text = text,
        widthPx = widthPx,
        heightPx = heightPx,
    )

    return cache.getOrPut(key) {
        val layout = measureScalableSingleLineLayout(
            measurer = textMeasurer,
            text = AnnotatedString(text),
            maxWidthPx = widthPx.toFloat(),
            maxHeightPx = heightPx.toFloat(),
            baseStyle = baseStyle,
            minTextSize = 12.sp,
            scaleDownOnly = true,
            density = density,
        )
        val inkWidthPx = with(density) { layout.widthDp.toPx() }

        PageExercisesFittedTextCell(
            text = text,
            fontSize = layout.fontSize,
            inkWidth = layout.widthDp,
            containerWidth = containerWidth,
            containerHeight = containerHeight,
            overflows = inkWidthPx > widthPx + 0.5f,
        )
    }
}

private fun pageExercisesBaseTextStyle(style: TextStyle): TextStyle {
    return style.copy(
        platformStyle = PlatformTextStyle(includeFontPadding = false),
        lineHeightStyle = LineHeightStyle(
            alignment = LineHeightStyle.Alignment.Center,
            trim = LineHeightStyle.Trim.Both
        )
    )
}

@Composable
private fun FastFittedTextCell(
    fittedText: PageExercisesFittedTextCell,
    color: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    FastFittedTextCellContent(
        fittedText = fittedText,
        color = color,
        style = style,
        modifier = modifier,
        fadeOverflow = false,
    )
}

@Composable
private fun FastFittedFadingTextCell(
    fittedText: PageExercisesFittedTextCell,
    enableFadingText: Boolean,
    color: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    FastFittedTextCellContent(
        fittedText = fittedText,
        enableFadingText = enableFadingText,
        color = color,
        style = style,
        modifier = modifier,
        fadeOverflow = true,
    )
}

@Composable
private fun FastFittedTextCellContent(
    fittedText: PageExercisesFittedTextCell,
    enableFadingText: Boolean = false,
    color: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
    fadeOverflow: Boolean,
) {
    if (fadeOverflow && fittedText.overflows && enableFadingText) {
        MarqueeFittedTextCell(
            fittedText = fittedText,
            color = color,
            style = style,
            modifier = modifier,
        )
    } else {
        PlainFittedTextCell(
            fittedText = fittedText,
            color = color,
            style = style,
            modifier = modifier,
        )
    }
}

@Composable
private fun MarqueeFittedTextCell(
    fittedText: PageExercisesFittedTextCell,
    color: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    val baseStyle = remember(style) { pageExercisesBaseTextStyle(style) }
    val marqueeState = rememberTrackableMarqueeState()
    val fadeColor = MaterialTheme.colorScheme.background

    Box(
        modifier = modifier
            .width(fittedText.containerWidth)
            .height(fittedText.containerHeight)
            .clipToBounds(),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier.graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = fittedText.text,
                style = baseStyle.copy(fontSize = fittedText.fontSize, color = color),
                color = Color.Unspecified,
                maxLines = 1,
                textAlign = TextAlign.Center,
                overflow = LocalTextConfiguration.current.overflow,
                modifier = Modifier
                    .trackableMarquee(
                        state = marqueeState,
                        iterations = Int.MAX_VALUE,
                        edgeFadeWidth = 12.dp,
                        edgeFadeColor = fadeColor,
                    )
                    .width(fittedText.inkWidth),
            )
        }
    }
}

@Composable
private fun PlainFittedTextCell(
    fittedText: PageExercisesFittedTextCell,
    color: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    val baseStyle = remember(style) { pageExercisesBaseTextStyle(style) }

    Box(
        modifier = modifier
            .width(fittedText.containerWidth)
            .height(fittedText.containerHeight)
            .clipToBounds(),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = fittedText.text,
            style = baseStyle.copy(fontSize = fittedText.fontSize, color = color),
            color = Color.Unspecified,
            maxLines = 1,
            textAlign = TextAlign.Center,
            overflow = LocalTextConfiguration.current.overflow,
            modifier = Modifier.width(fittedText.inkWidth),
        )
    }
}

internal enum class PageExercisesRowContentType {
    Set,
    Rest,
    CalibrationLoad,
    CalibrationRir
}

@Immutable
internal data class PageExercisesPreparedRows(
    val rowModels: List<PageExercisesRowModel>,
    val setIndex: Int
)

@Immutable
internal data class PageExercisesRowModel(
    val rowIndex: Int,
    val key: String,
    val contentType: PageExercisesRowContentType,
    val setIdentifier: String? = null,
    val semanticsLabel: String? = null,
    val setText: String? = null,
    val valueText: String? = null,
    val repsText: String? = null,
    val valueWeight: Float = 3f,
    val centeredText: String? = null
)

private data class PageExercisesSetRowTexts(
    val valueText: String,
    val repsText: String?,
    val valueWeight: Float
)

internal fun buildPageExercisesPreparedRows(
    viewModel: AppViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    stateToMatch: WorkoutState?,
): PageExercisesPreparedRows {
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
    val unilateralSideBadgeByRowIndex = buildUnilateralSideBadgeByRowIndex(displayRows)
    val hasUnconfirmedLoadByExerciseId = buildHasUnconfirmedLoadByExerciseId(viewModel, displayRows)

    return PageExercisesPreparedRows(
        rowModels = displayRows.mapIndexed { rowIndex, displayRow ->
            buildPageExercisesRowModel(
                viewModel = viewModel,
                displayRow = displayRow,
                rowIndex = rowIndex,
                sideBadge = unilateralSideBadgeByRowIndex[rowIndex],
                hasUnconfirmedLoadSelectionForExercise = (displayRow as? ExerciseSetDisplayRow.SetRow)
                    ?.state
                    ?.exerciseId
                    ?.let { hasUnconfirmedLoadByExerciseId[it] }
                    ?: false
            )
        },
        setIndex = setIndex
    )
}

private fun buildUnilateralSideBadgeByRowIndex(
    displayRows: List<ExerciseSetDisplayRow>,
): Map<Int, String> {
    return displayRows.mapIndexedNotNull { rowIndex, displayRow ->
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
}

private fun buildHasUnconfirmedLoadByExerciseId(
    viewModel: AppViewModel,
    displayRows: List<ExerciseSetDisplayRow>,
): Map<UUID, Boolean> {
    val exerciseIdsForLoadFlag = displayRows.mapNotNull { row ->
        (row as? ExerciseSetDisplayRow.SetRow)?.state?.exerciseId
    }.toSet()
    return if (exerciseIdsForLoadFlag.isEmpty()) {
        emptyMap()
    } else {
        exerciseIdsForLoadFlag.associateWith { exerciseId ->
            CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
                allWorkoutStates = viewModel.allWorkoutStates,
                exerciseId = exerciseId
            )
        }
    }
}

private fun buildPageExercisesRowModel(
    viewModel: AppViewModel,
    displayRow: ExerciseSetDisplayRow,
    rowIndex: Int,
    sideBadge: String?,
    hasUnconfirmedLoadSelectionForExercise: Boolean,
): PageExercisesRowModel {
    return when (displayRow) {
        is ExerciseSetDisplayRow.SetRow -> {
            val setState = displayRow.state
            val setIdentifier = buildSetIdentifier(
                viewModel = viewModel,
                exerciseId = setState.exerciseId,
                setState = setState
            )
            val rowSetContentDescription = when {
                !setIdentifier.isNullOrBlank() && !sideBadge.isNullOrBlank() -> "$setIdentifier$sideBadge"
                !setIdentifier.isNullOrBlank() -> setIdentifier
                !sideBadge.isNullOrBlank() -> sideBadge
                else -> null
            }
            val rowTexts = buildPageExercisesSetRowTexts(
                viewModel = viewModel,
                setState = setState,
                hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
            )

            PageExercisesRowModel(
                rowIndex = rowIndex,
                key = buildPageExercisesRowKey(displayRow, rowIndex),
                contentType = PageExercisesRowContentType.Set,
                setIdentifier = setIdentifier,
                semanticsLabel = rowSetContentDescription,
                setText = rowSetContentDescription.orEmpty(),
                valueText = rowTexts.valueText,
                repsText = rowTexts.repsText,
                valueWeight = rowTexts.valueWeight
            )
        }

        is ExerciseSetDisplayRow.RestRow -> PageExercisesRowModel(
            rowIndex = rowIndex,
            key = buildPageExercisesRowKey(displayRow, rowIndex),
            contentType = PageExercisesRowContentType.Rest,
            centeredText = buildWorkoutRestRowLabel(displayRow.state)
        )

        is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> PageExercisesRowModel(
            rowIndex = rowIndex,
            key = buildPageExercisesRowKey(displayRow, rowIndex),
            contentType = PageExercisesRowContentType.CalibrationLoad,
            centeredText = "SET LOAD"
        )

        is ExerciseSetDisplayRow.CalibrationRIRRow -> PageExercisesRowModel(
            rowIndex = rowIndex,
            key = buildPageExercisesRowKey(displayRow, rowIndex),
            contentType = PageExercisesRowContentType.CalibrationRir,
            centeredText = "SET RIR"
        )
    }
}

private fun buildPageExercisesSetRowTexts(
    viewModel: AppViewModel,
    setState: WorkoutState.Set,
    hasUnconfirmedLoadSelectionForExercise: Boolean,
): PageExercisesSetRowTexts {
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

    return when (val currentSetData = setState.currentSetData) {
        is WeightSetData -> {
            val weightText = equipment?.formatWeight(currentSetData.actualWeight) ?: "-"
            val displayWeightText = when {
                shouldHideCalibrationExecutionWeight -> "TBD"
                isCalibrationSet && setState.isCalibrationSet -> weightText
                isPendingCalibration -> "TBD"
                else -> weightText
            }
            PageExercisesSetRowTexts(
                valueText = displayWeightText,
                repsText = currentSetData.actualReps.toString(),
                valueWeight = 2f
            )
        }

        is BodyWeightSetData -> {
            val baseWeightText = if (equipment != null && currentSetData.additionalWeight != 0.0) {
                equipment.formatWeight(currentSetData.additionalWeight)
            } else {
                "BW"
            }
            val displayWeightText = when {
                shouldHideCalibrationExecutionWeight -> "TBD"
                isCalibrationSet && setState.isCalibrationSet && equipment != null && currentSetData.additionalWeight != 0.0 -> baseWeightText
                isPendingCalibration -> "TBD"
                else -> baseWeightText
            }
            PageExercisesSetRowTexts(
                valueText = displayWeightText,
                repsText = currentSetData.actualReps.toString(),
                valueWeight = 2f
            )
        }

        is TimedDurationSetData -> PageExercisesSetRowTexts(
            valueText = FormatTime(currentSetData.startTimer / 1000),
            repsText = null,
            valueWeight = 3f
        )

        is EnduranceSetData -> PageExercisesSetRowTexts(
            valueText = FormatTime(currentSetData.startTimer / 1000),
            repsText = null,
            valueWeight = 3f
        )

        else -> throw RuntimeException("Unsupported set type")
    }
}

private fun buildPageExercisesRowKey(row: ExerciseSetDisplayRow, rowIndex: Int): String {
    return buildString {
        append(row::class.simpleName ?: "row")
        append(":")
        append(row.setLikeIdOrNull()?.toString() ?: "no-set")
        append(":")
        append(rowIndex)
    }
}

internal fun TransformingLazyColumnScope.ExerciseSetsViewer(
    viewModel: AppViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    transformationSpec: TransformationSpec,
    stateToMatch: WorkoutState?,
    progressState: ProgressState = ProgressState.CURRENT,
    preparedRows: PageExercisesPreparedRows? = null,
    fittedRows: PageExercisesFittedRows? = null,
    enableFadingText: Boolean = true,
    hideSetListRowText: Boolean = false,
) {
    val rows = fittedRows?.preparedRows ?: preparedRows ?: buildPageExercisesPreparedRows(
        viewModel = viewModel,
        exercise = exercise,
        currentSet = currentSet,
        stateToMatch = stateToMatch
    )
    val setIndex = rows.setIndex

    @Composable
    fun MeasuredSetTableRow(
        rowModel: PageExercisesRowModel,
    ) {
        val currentExercisePendingColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
        val borderColor = when (progressState) {
            ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
            ProgressState.CURRENT -> when {
                rowModel.rowIndex == setIndex -> Orange
                rowModel.rowIndex < setIndex -> MaterialTheme.colorScheme.primary
                else -> currentExercisePendingColor
            }
            ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val rowModifier = Modifier
            .fillMaxWidth()
            .height(25.dp)
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(25))

        when (rowModel.contentType) {
            PageExercisesRowContentType.Set -> FastPageExercisesSetTableRow(
                rowModel = rowModel,
                fittedRow = fittedRows?.rowsByKey?.get(rowModel.key),
                enableFadingText = enableFadingText,
                hideSetListRowText = hideSetListRowText,
                modifier = rowModifier,
                textColor = borderColor
            )
            PageExercisesRowContentType.CalibrationLoad -> CenteredLabelRow(
                modifier = rowModifier,
                text = rowModel.centeredText.orEmpty(),
                fittedText = fittedRows?.rowsByKey?.get(rowModel.key)?.centeredText,
                textColor = borderColor,
                hideSetListRowText = hideSetListRowText,
            )
            PageExercisesRowContentType.Rest -> CenteredLabelRow(
                modifier = rowModifier,
                text = rowModel.centeredText.orEmpty(),
                fittedText = fittedRows?.rowsByKey?.get(rowModel.key)?.centeredText,
                textColor = borderColor,
                hideSetListRowText = hideSetListRowText,
            )
            PageExercisesRowContentType.CalibrationRir -> CenteredLabelRow(
                modifier = rowModifier,
                text = rowModel.centeredText.orEmpty(),
                fittedText = fittedRows?.rowsByKey?.get(rowModel.key)?.centeredText,
                textColor = borderColor,
                hideSetListRowText = hideSetListRowText,
            )
        }
    }

    items(
        items = rows.rowModels,
        key = { rowModel -> rowModel.key },
        contentType = { rowModel -> rowModel.contentType }
    ) { rowModel ->
        val rowModifier = Modifier
            .fillMaxWidth()
            .transformedHeight(this, transformationSpec)
            .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } }

        Box(
            modifier = rowModifier,
            contentAlignment = Alignment.Center
        ) {
            MeasuredSetTableRow(rowModel = rowModel)
        }
    }
}

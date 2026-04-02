package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set as WorkoutSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workout.display.ExerciseSetDisplayRow
import com.gabstra.myworkoutassistant.shared.workout.display.buildExerciseSetDisplayRows
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutRestRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutSetDisplayIdentifier
import com.gabstra.myworkoutassistant.shared.workout.display.findDisplayRowIndex
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

fun FormatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    setIdentifier: String? = null,
    sideBadge: String? = null,
    index: Int?,
    isCurrentSet: Boolean,
    markAsDone: Boolean,
    color: Color = MaterialTheme.colorScheme.onBackground,
    weightTextColor: Color? = null,
    isFutureExercise: Boolean = false,
    hasUnconfirmedLoadSelectionForExercise: Boolean = false,
) {
    val equipment = setState.equipmentId?.let { viewModel.getEquipmentById(it) }

    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.displayLarge.copy(fontWeight = FontWeight.Bold) }

    val actualWeightTextColor = weightTextColor ?: color

    val isCalibrationSet = when (val set = setState.set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

    val isPendingCalibration = CalibrationHelper.shouldShowPendingCalibrationForWorkSet(
        setState = setState,
        hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
    )
    val shouldHideCalibrationExecutionWeight = CalibrationHelper.shouldHideCalibrationExecutionWeight(
        setState = setState,
        hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
    )

    val rowSetContentDescription = when {
        !setIdentifier.isNullOrBlank() && !sideBadge.isNullOrBlank() -> "$setIdentifier$sideBadge"
        !setIdentifier.isNullOrBlank() -> setIdentifier
        !sideBadge.isNullOrBlank() -> sideBadge
        else -> null
    }
    val baseSetDisplayText = rowSetContentDescription ?: ""

    Box(
        modifier = modifier,
    ) {
        Row(
            modifier = Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ScalableText(
                modifier = Modifier.weight(1f),
                text = baseSetDisplayText,
                style = itemStyle,
                textAlign = TextAlign.Center,
                color = color
            )

            when (setState.currentSetData) {
                is WeightSetData -> {
                    val weightSetData = (setState.currentSetData as WeightSetData)
                    val weightText = equipment?.formatWeight(weightSetData.actualWeight) ?: "-"
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> CalibrationUiLabels.Tbd
                        isCalibrationSet -> weightText
                        isPendingCalibration -> CalibrationUiLabels.Tbd
                        else -> weightText
                    }
                    ScalableText(
                        modifier = Modifier.weight(2f),
                        text = displayWeightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = actualWeightTextColor
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "${weightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = color
                    )
                }

                is BodyWeightSetData -> {
                    val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                    val baseWeightText = if (equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                        equipment.formatWeight(bodyWeightSetData.additionalWeight)
                    } else {
                        "BW"
                    }
                    val weightText = when {
                        shouldHideCalibrationExecutionWeight -> CalibrationUiLabels.Tbd
                        isCalibrationSet && equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> baseWeightText
                        isPendingCalibration -> CalibrationUiLabels.Tbd
                        else -> baseWeightText
                    }

                    ScalableText(
                        modifier = Modifier.weight(2f),
                        text = weightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = actualWeightTextColor
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "${bodyWeightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = color
                    )
                }

                is TimedDurationSetData -> {
                    val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                    ScalableText(
                        modifier = Modifier.weight(3f),
                        text = FormatTime(timedDurationSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = color
                    )
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    ScalableText(
                        modifier = Modifier.weight(3f),
                        text = FormatTime(enduranceSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = color
                    )
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }

        if (markAsDone) {
            HorizontalDivider(
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(horizontal = 5.dp),
                color = color
            )
        }
    }
}

@Composable
private fun CenteredLabelRow(
    modifier: Modifier,
    text: String,
    textColor: Color,
) {
    val itemStyle = MaterialTheme.typography.displayLarge.copy(fontWeight = FontWeight.Bold)
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(1.dp),
        contentAlignment = Alignment.Center
    ) {
        ScalableText(
            text = text,
            style = itemStyle,
            textAlign = TextAlign.Center,
            color = textColor
        )
    }
}

@Composable
fun ExerciseSetsViewer(
    modifier: Modifier = Modifier,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    currentSet: WorkoutSet,
    customColor: Color? = null,
    customBorderColor: Color? = null,
    customTextColor: Color? = null,
    customMarkAsDone: Boolean? = null,
    overrideSetIndex: Int? = null,
    isFutureExercise: Boolean = false,
) {
    val displayRows: List<ExerciseSetDisplayRow> = remember(exercise.id, viewModel.allWorkoutStates.size) {
        buildExerciseSetDisplayRows(viewModel = viewModel, exerciseId = exercise.id)
    }

    val currentWorkoutState by viewModel.workoutState.collectAsState()
    val setIndex = overrideSetIndex ?: findDisplayRowIndex(
        displayRows = displayRows,
        stateToMatch = currentWorkoutState,
        fallbackSetId = currentSet.id
    )

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
            exerciseIdsForLoadFlag.associateWith { exerciseId: UUID ->
                CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
                    allWorkoutStates = viewModel.allWorkoutStates,
                    exerciseId = exerciseId
                )
            }
        }

    val headerStyle = MaterialTheme.typography.bodySmall

    val scrollState = rememberScrollState()
    val density = LocalDensity.current

    val itemHeightDp = 30.0.dp

    LaunchedEffect(exercise.id) {
        scrollState.animateScrollTo(0)
    }

    LaunchedEffect(setIndex, exercise.id) {
        if (setIndex in displayRows.indices) {
            val scrollPosition = with(density) { (setIndex * itemHeightDp.toPx()).toInt() }
            scrollState.animateScrollTo(scrollPosition)
        } else {
            scrollState.animateScrollTo(0)
        }
    }

    @Composable
    fun MeasuredSetTableRow(
        displayRow: ExerciseSetDisplayRow,
        rowIndex: Int,
        isFutureExerciseParam: Boolean = isFutureExercise,
    ) {
        val isDone = customMarkAsDone ?: (rowIndex < setIndex)
        val setStateForThisRow = (displayRow as? ExerciseSetDisplayRow.SetRow)?.state
        val shouldUseCalibrationExecutionColors =
            setStateForThisRow?.isCalibrationSet == true &&
                customBorderColor == null &&
                customTextColor == null &&
                customColor == null
        val calibrationExecutionColor = if (isDone) {
            Green
        } else {
            Green.copy(alpha = 0.35f)
        }
        val backgroundColor = if (rowIndex == setIndex) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.surfaceVariant
        }

        val borderColor = when {
            shouldUseCalibrationExecutionColors -> calibrationExecutionColor
            else -> customBorderColor ?: customColor
        }

        val textColor = when {
            shouldUseCalibrationExecutionColors -> calibrationExecutionColor
            else -> customTextColor ?: customColor ?: when {
                rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
                rowIndex == setIndex -> MaterialTheme.colorScheme.onPrimary
                else -> MaterialTheme.colorScheme.onBackground
            }
        }

        val weightTextColor = when {
            shouldUseCalibrationExecutionColors -> calibrationExecutionColor
            else -> customTextColor ?: customColor ?: when {
                rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
                rowIndex == setIndex -> MaterialTheme.colorScheme.onPrimary
                else -> MaterialTheme.colorScheme.onBackground
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(30.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val rowModifier = Modifier
                .fillMaxWidth()
                .height(27.5.dp)
                .padding(bottom = 2.5.dp)
                .clip(MaterialTheme.shapes.extraLarge)
                .then(
                    if (borderColor != null) {
                        Modifier.border(BorderStroke(1.dp, borderColor), MaterialTheme.shapes.extraLarge)
                    } else {
                        Modifier
                    }
                )
                .background(backgroundColor)

            when (displayRow) {
                is ExerciseSetDisplayRow.SetRow -> SetTableRow(
                    modifier = rowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = displayRow.state,
                    setIdentifier = buildWorkoutSetDisplayIdentifier(
                        viewModel = viewModel,
                        exerciseId = displayRow.state.exerciseId,
                        setState = displayRow.state
                    ),
                    sideBadge = unilateralSideBadgeByRowIndex[rowIndex],
                    index = rowIndex,
                    isCurrentSet = rowIndex == setIndex,
                    markAsDone = isDone,
                    color = textColor,
                    weightTextColor = weightTextColor,
                    isFutureExercise = isFutureExerciseParam,
                    hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadByExerciseId[displayRow.state.exerciseId]
                        ?: false
                )
                is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = CalibrationUiLabels.SelectLoad,
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.CalibrationRIRRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = CalibrationUiLabels.SetRir,
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.RestRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = buildWorkoutRestRowLabel(displayRow.state),
                    textColor = textColor
                )
            }
        }
    }

    val prototypeItem = @Composable {
        val firstRow = displayRows.firstOrNull()
        if (firstRow != null) {
            MeasuredSetTableRow(displayRow = firstRow, rowIndex = 0)
        }
    }

    Column(modifier = modifier) {
        if (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            Row(
                modifier = Modifier
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

            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                prototypeItem = { prototypeItem() }
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalScroll(scrollState)
                ) {
                    displayRows.forEachIndexed { index, displayRow ->
                        MeasuredSetTableRow(displayRow, index)
                    }
                }
            }
        }

        if (exercise.exerciseType == ExerciseType.COUNTUP || exercise.exerciseType == ExerciseType.COUNTDOWN) {
            Row(
                modifier = Modifier
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
            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                prototypeItem = { prototypeItem() }
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalScroll(scrollState)
                ) {
                    displayRows.forEachIndexed { index, displayRow ->
                        MeasuredSetTableRow(displayRow, index)
                    }
                }
            }
        }
    }
}

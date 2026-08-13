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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumGray
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
import com.gabstra.myworkoutassistant.shared.workout.display.buildSupersetSetDisplayRows
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutRestRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutSetDisplayIdentifier
import com.gabstra.myworkoutassistant.shared.workout.display.buildSupersetAwareRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.resolveSupersetExercisePrefix
import com.gabstra.myworkoutassistant.shared.workout.display.findDisplayRowIndex
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.Locale
import java.util.UUID

fun FormatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format(Locale.US, "%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format(Locale.US, "%02d:%02d", minutes, remainingSeconds)
    }
}

@Composable
fun SetTableRow(
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    setIdentifier: String? = null,
    sideBadge: String? = null,
    color: Color = MaterialTheme.colorScheme.onBackground,
    weightTextColor: Color? = null,
    hasUnconfirmedLoadSelectionForExercise: Boolean = false,
) {
    val equipment = setState.equipmentId?.let { viewModel.getEquipmentById(it) }

    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.headlineMedium.copy(fontWeight = FontWeight.Bold) }

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

    }
}

private enum class MobileProgressState { PAST, CURRENT, FUTURE }

@Composable
private fun mobileProgressRowAccentColor(
    progressState: MobileProgressState,
    rowIndex: Int,
    currentRowIndex: Int,
): Color {
    val completedColor = MaterialTheme.colorScheme.onBackground
    return when (progressState) {
        MobileProgressState.PAST -> completedColor
        MobileProgressState.CURRENT -> when {
            rowIndex == currentRowIndex -> MaterialTheme.colorScheme.primary
            rowIndex < currentRowIndex -> completedColor
            else -> MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
        }
        // Wear maps surfaceContainerHigh to MediumGray. Mobile intentionally uses a
        // darker value for that token globally, so use the shared Wear row color here.
        MobileProgressState.FUTURE -> MediumGray
    }
}

@Composable
private fun CenteredLabelRow(
    modifier: Modifier,
    text: String,
    textColor: Color,
) {
    val itemStyle = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold)
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
    val supersetId = viewModel.supersetIdByExerciseId[exercise.id]
    val displayRows: List<ExerciseSetDisplayRow> = remember(exercise.id, supersetId, viewModel.allWorkoutStates.size) {
        if (supersetId != null) {
            buildSupersetSetDisplayRows(viewModel = viewModel, supersetId = supersetId)
        } else {
            buildExerciseSetDisplayRows(viewModel = viewModel, exerciseId = exercise.id)
        }
    }

    val currentWorkoutState by viewModel.workoutState.collectAsState()
    val setIndex = overrideSetIndex ?: findDisplayRowIndex(
        displayRows = displayRows,
        stateToMatch = currentWorkoutState,
        fallbackSetId = currentSet.id
    )

    val unilateralSideBadgeByRowIndex = remember(displayRows) {
        displayRows.mapIndexedNotNull { rowIndex, displayRow ->
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

    val exerciseIdsForLoadFlag: Set<UUID> = remember(displayRows) {
        displayRows.mapNotNull { row ->
            (row as? ExerciseSetDisplayRow.SetRow)?.state?.exerciseId
        }.toSet()
    }

    val hasUnconfirmedLoadByExerciseId: Map<UUID, Boolean> = remember(
        exerciseIdsForLoadFlag,
        viewModel.allWorkoutStates.size,
    ) {
        exerciseIdsForLoadFlag.associateWith { exerciseId ->
            CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
                allWorkoutStates = viewModel.allWorkoutStates,
                exerciseId = exerciseId
            )
        }
    }

    val headerStyle = MaterialTheme.typography.titleMedium.copy(lineHeight = 20.sp)

    val density = LocalDensity.current

    val itemHeightDp = 46.dp
    val rowHeightDp = 42.dp
    val targetScrollPosition = if (setIndex in displayRows.indices) {
        with(density) { (setIndex * itemHeightDp.toPx()).toInt() }
    } else {
        0
    }
    val scrollState = key(exercise.id) {
        rememberScrollState(initial = targetScrollPosition)
    }

    val progressState = when {
        customMarkAsDone == true -> MobileProgressState.PAST
        isFutureExercise || customMarkAsDone == false -> MobileProgressState.FUTURE
        else -> MobileProgressState.CURRENT
    }

    LaunchedEffect(setIndex, exercise.id) {
        if (scrollState.value != targetScrollPosition) {
            scrollState.scrollTo(targetScrollPosition)
        }
    }

    @Composable
    fun MeasuredSetTableRow(
        displayRow: ExerciseSetDisplayRow,
        rowIndex: Int,
    ) {
        val rowAccentColor = mobileProgressRowAccentColor(
            progressState = progressState,
            rowIndex = rowIndex,
            currentRowIndex = setIndex,
        )
        val borderColor = customBorderColor ?: customColor ?: rowAccentColor
        val textColor = customTextColor ?: customColor ?: rowAccentColor
        val weightTextColor = textColor

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(itemHeightDp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val rowModifier = Modifier
                .fillMaxWidth()
                .height(rowHeightDp)
                .clip(MaterialTheme.shapes.extraLarge)
                .background(MaterialTheme.colorScheme.background)
                .border(BorderStroke(1.dp, borderColor), MaterialTheme.shapes.extraLarge)

            when (displayRow) {
                is ExerciseSetDisplayRow.SetRow -> SetTableRow(
                    modifier = rowModifier,
                    viewModel = viewModel,
                    setState = displayRow.state,
                    setIdentifier = buildWorkoutSetDisplayIdentifier(
                        viewModel = viewModel,
                        exerciseId = displayRow.state.exerciseId,
                        setState = displayRow.state
                    ),
                    sideBadge = unilateralSideBadgeByRowIndex[rowIndex],
                    color = textColor,
                    weightTextColor = weightTextColor,
                    hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadByExerciseId[displayRow.state.exerciseId]
                        ?: false
                )
                is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = buildSupersetAwareRowLabel(
                        supersetPrefix = resolveSupersetExercisePrefix(
                            viewModel = viewModel,
                            exerciseId = displayRow.state.exerciseId,
                        ),
                        label = "SELECT LOAD",
                    ),
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.CalibrationRIRRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = buildSupersetAwareRowLabel(
                        supersetPrefix = resolveSupersetExercisePrefix(
                            viewModel = viewModel,
                            exerciseId = displayRow.state.exerciseId,
                        ),
                        label = "SET RIR",
                    ),
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

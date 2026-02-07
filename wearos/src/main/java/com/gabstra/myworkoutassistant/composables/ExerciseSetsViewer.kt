package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

/**
 * Display model for one row in the exercise set viewer. Each row corresponds to one state
 * from the exercise's container in the workout state machine.
 */
sealed class ExerciseSetDisplayRow {
    data class SetRow(val state: WorkoutState.Set) : ExerciseSetDisplayRow()
    data class CalibrationLoadSelectRow(val state: WorkoutState.CalibrationLoadSelection) : ExerciseSetDisplayRow()
    data class CalibrationRIRRow(val state: WorkoutState.CalibrationRIRSelection) : ExerciseSetDisplayRow()

    fun workoutState(): WorkoutState = when (this) {
        is SetRow -> state
        is CalibrationLoadSelectRow -> state
        is CalibrationRIRRow -> state
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: AppViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    isCurrentSet: Boolean,
    markAsDone: Boolean,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    hasUnconfirmedLoadSelectionForExercise: Boolean = false,
){
    val itemStyle = MaterialTheme.typography.numeralSmall

    val equipment = setState.equipment
    val exercise = viewModel.exercisesById[setState.exerciseId]
    val isCalibrationEnabled = exercise?.requiresLoadCalibration ?: false

    val isWarmupSet = CalibrationHelper.isWarmupSet(setState.set)
    val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(setState.set)
    val isPendingCalibration = CalibrationHelper.shouldShowPendingCalibrationForWorkSet(
        setState,
        isCalibrationEnabled,
        isWarmupSet,
        isCalibrationSet,
        hasUnconfirmedLoadSelectionForExercise
    )
    val shouldHideCalibrationExecutionWeight = CalibrationHelper.shouldHideCalibrationExecutionWeight(
        setState = setState,
        isCalibrationSetBySubCategory = isCalibrationSet,
        hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
    )

    Box(
        modifier = modifier,
    ){
        Row(
            modifier = Modifier.fillMaxSize()
                .padding(1.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            when (setState.currentSetData) {
                is WeightSetData -> {
                    val weightSetData = (setState.currentSetData as WeightSetData)
                    val previousWeightSetData = (setState.previousSetData as WeightSetData)

                    val weightTextColor = when {
                        weightSetData.actualWeight == previousWeightSetData.actualWeight -> textColor
                        weightSetData.actualWeight < previousWeightSetData.actualWeight  -> Red
                        else -> Green
                    }

                    val repsTextColor = when {
                        weightSetData.actualReps == previousWeightSetData.actualReps -> textColor
                        weightSetData.actualReps < previousWeightSetData.actualReps  -> Red
                        else -> Green
                    }

                    val weightText = equipment!!.formatWeight(weightSetData.actualWeight)
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> "TBD"
                        isCalibrationSet && setState.isCalibrationSet -> "$weightText (Cal)"
                        isPendingCalibration -> "TBD"
                        else -> weightText
                    }
                    val weightColor = weightTextColor

                    ScalableFadingText(
                        modifier = Modifier.weight(2f),
                        text = displayWeightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = weightColor,
                    )
                    ScalableFadingText(
                        modifier = Modifier.weight(1f),
                        text = "${weightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = repsTextColor,
                    )
                }

                is BodyWeightSetData -> {
                    val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                    val previousBodyWeightSetData = (setState.previousSetData as BodyWeightSetData)

                    val baseWeightText = if(setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                        setState.equipment!!.formatWeight(bodyWeightSetData.additionalWeight)
                    }else {
                        "BW"
                    }
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> "TBD"
                        isCalibrationSet && setState.isCalibrationSet && setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> "$baseWeightText (Cal)"
                        isPendingCalibration -> "TBD"
                        else -> baseWeightText
                    }

                    val weightTextColor = when {
                        bodyWeightSetData.additionalWeight == previousBodyWeightSetData.additionalWeight -> textColor
                        bodyWeightSetData.additionalWeight < previousBodyWeightSetData.additionalWeight  -> Red
                        else -> Green
                    }
                    val weightColor = weightTextColor

                    val repsTextColor = when {
                        bodyWeightSetData.actualReps == previousBodyWeightSetData.actualReps -> textColor
                        bodyWeightSetData.actualReps < previousBodyWeightSetData.actualReps  -> Red
                        else -> Green
                    }

                    ScalableFadingText(
                        modifier = Modifier.weight(2f),
                        text = displayWeightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = weightColor
                    )
                    ScalableFadingText(
                        modifier = Modifier.weight(1f),
                        text = "${bodyWeightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = repsTextColor
                    )
                }

                is TimedDurationSetData -> {
                    val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                    ScalableFadingText(
                        modifier = Modifier.weight(1f),
                        text = FormatTime(timedDurationSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    ScalableFadingText(
                        modifier = Modifier.weight(1f),
                        text = FormatTime(enduranceSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }

        if(markAsDone){
            Spacer(
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxWidth()
                    .padding(horizontal = 2.5.dp)
                    .height(2.dp)
                    .background(textColor)
                    .clip(RoundedCornerShape(50))
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
    val itemStyle = MaterialTheme.typography.numeralSmall
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(1.dp),
        contentAlignment = Alignment.Center
    ) {
        ScalableFadingText(
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
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    customMarkAsDone: Boolean? = null,
    customBorderColor: Color? = null,
    customBackgroundColor: Color? = null,
    customTextColor: Color? = null,
    overrideSetIndex: Int? = null,
    currentWorkoutStateOverride: WorkoutState? = null,
){
    val exerciseStates = viewModel.getStatesForExercise(exercise.id)
        .filter { it !is WorkoutState.Rest }
    val displayRows: List<ExerciseSetDisplayRow> = exerciseStates.map { state ->
        when (state) {
            is WorkoutState.Set -> ExerciseSetDisplayRow.SetRow(state)
            is WorkoutState.CalibrationLoadSelection ->
                if (state.isLoadConfirmed) null else ExerciseSetDisplayRow.CalibrationLoadSelectRow(state)
            is WorkoutState.CalibrationRIRSelection -> ExerciseSetDisplayRow.CalibrationRIRRow(state)
            else -> null
        }
    }.filterNotNull()

    val currentWorkoutState by viewModel.workoutState.collectAsState()
    val hasUnconfirmedLoadSelectionForExercise = CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
        allWorkoutStates = viewModel.allWorkoutStates,
        exerciseId = exercise.id
    )

    val stateToMatch = currentWorkoutStateOverride ?: currentWorkoutState
    val setIndex = overrideSetIndex
        ?: displayRows.indexOfFirst { it.workoutState() === stateToMatch }.takeIf { it >= 0 }
        ?: displayRows.indexOfFirst { row ->
            (row as? ExerciseSetDisplayRow.SetRow)?.state?.set?.id == currentSet.id
        }.takeIf { it >= 0 }
        ?: 0

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()
    val density = LocalDensity.current

    val itemHeightDp = 27.5.dp

    // Reset scroll position immediately when exercise changes
    LaunchedEffect(exercise.id) {
        scrollState.animateScrollTo(0)
    }

    // Scroll to current set when it changes
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
    ) {
        val isWarmupSetRow = when (displayRow) {
            is ExerciseSetDisplayRow.SetRow -> CalibrationHelper.isWarmupSet(displayRow.state.set)
            else -> false
        }

        val borderColor = customBorderColor ?: when {
            rowIndex == setIndex -> Orange
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
            else -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val backgroundColor = customBackgroundColor ?: MaterialTheme.colorScheme.background

        val textColor = customTextColor ?: when {
            rowIndex == setIndex -> Orange
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
            else -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(27.5.dp)
                .padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val shape = RoundedCornerShape(25)

            val rowModifier = Modifier
                .height(25.dp)
                .padding(bottom = 2.5.dp)
                .then(
                    if (isWarmupSetRow) {
                        Modifier.dashedBorder(
                            strokeWidth = 1.dp,
                            color = borderColor,
                            shape = shape,
                            onInterval = 4.dp,
                            offInterval = 4.dp
                        )
                    } else {
                        Modifier.border(BorderStroke(1.dp, borderColor), shape)
                    }
                )
                .background(backgroundColor, shape)

            when (displayRow) {
                is ExerciseSetDisplayRow.SetRow -> SetTableRow(
                    modifier = rowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = displayRow.state,
                    index = rowIndex,
                    isCurrentSet = rowIndex == setIndex,
                    markAsDone = false,
                    textColor = textColor,
                    hasUnconfirmedLoadSelectionForExercise = hasUnconfirmedLoadSelectionForExercise
                )
                is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = "Select Load",
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.CalibrationRIRRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = "Set RIR",
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

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.5.dp)
    ) {
        if (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
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
                    .weight(1f) // Fills remaining vertical space
                    .fillMaxWidth(), // Still need to fill width
                prototypeItem = { prototypeItem() } // Pass the item for measurement
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalColumnScrollbar(scrollState = scrollState)
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
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "TIME (HH:MM:SS)",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
            }
            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f) // Fills remaining vertical space
                    .fillMaxWidth(), // Still need to fill width
                prototypeItem = { prototypeItem() } // Pass the item for measurement
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalColumnScrollbar(scrollState = scrollState)
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

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
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise


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
    isFutureExercise: Boolean = false,
){
    val itemStyle = MaterialTheme.typography.numeralSmall

    val equipment = setState.equipment
    val exercise = viewModel.exercisesById[setState.exerciseId]
    val isCalibrationEnabled = exercise?.requiresLoadCalibration ?: false

    val isWarmupSet = when(val set = setState.set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
        else -> false
    }
    
    val isCalibrationSet = when(val set = setState.set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }
    
    val calibrationContext by viewModel.calibrationContext.collectAsState(initial = null)
    val isPendingCalibration = CalibrationHelper.isPendingCalibration(
        setState,
        calibrationContext,
        isCalibrationEnabled,
        isWarmupSet,
        isCalibrationSet,
        isFutureExercise
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
                        isCalibrationSet -> "$weightText (Cal)"
                        isPendingCalibration -> "Pending"
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
                    val weightText = when {
                        isCalibrationSet && setState.isCalibrationSet && setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> "$baseWeightText (Cal)"
                        isPendingCalibration && setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> "$baseWeightText (Pending)"
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
                        text = weightText,
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
    isFutureExercise: Boolean = false,
){
    val exerciseSetStates = viewModel.getAllExerciseWorkoutStates(exercise.id)
        .filter { it.set !is RestSet }
        .filterNot { it.shouldIgnoreCalibration() }
        .distinctBy { it.set.id }
    val exerciseSetIds = exerciseSetStates.map { it.set.id }
    val setIndex = overrideSetIndex ?: exerciseSetIds.indexOf(currentSet.id)

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
        if (setIndex != -1 && setIndex < exerciseSetStates.size) {
            val scrollPosition = with(density) { (setIndex * itemHeightDp.toPx()).toInt() }
            scrollState.animateScrollTo(scrollPosition)
        } else {
            scrollState.animateScrollTo(0)
        }
    }

    @Composable
    fun MeasuredSetTableRow(
        setStateForThisRow:  WorkoutState.Set,
        rowIndex: Int,
        isFutureExerciseParam: Boolean = isFutureExercise,
    ) {
        val isWarmupSetRow = when(val set = setStateForThisRow.set) {
            is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
            is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
            else -> false
        }

        // When custom colors are provided, enforce them for ALL sets (previous, current, future)
        // This is used when viewing previous or future exercises
        // When null, use default logic that distinguishes between previous/current/future sets within the exercise
        val borderColor = customBorderColor ?: when {
            rowIndex == setIndex -> Orange // Current set: orange border
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground // Previous set: onBackground border
            else -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val backgroundColor = customBackgroundColor ?: MaterialTheme.colorScheme.background // All sets: black background

        val textColor = customTextColor ?: when {
            rowIndex == setIndex -> Orange // Current set: orange text
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground // Previous set: onBackground text
            else -> MaterialTheme.colorScheme.surfaceContainerHigh // Future set: surfaceContainerHigh (MediumLightGray)
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
                        // Warmup sets: use dashed border
                        Modifier.dashedBorder(
                            strokeWidth = 1.dp,
                            color = borderColor,
                            shape = shape,
                            onInterval = 4.dp,
                            offInterval = 4.dp
                        )
                    } else {
                        // Normal sets: use solid border
                        Modifier.border(BorderStroke(1.dp, borderColor), shape)
                    }
                )
                .background(backgroundColor, shape)

            SetTableRow(
                modifier = rowModifier,
                hapticsViewModel = hapticsViewModel,
                viewModel = viewModel,
                setState = setStateForThisRow,
                index = rowIndex,
                isCurrentSet = rowIndex == setIndex,
                markAsDone = false,
                textColor = textColor,
                isFutureExercise = isFutureExerciseParam
            )
        }
    }

    val prototypeItem = @Composable {
        MeasuredSetTableRow(setStateForThisRow = exerciseSetStates[0], rowIndex = 0)
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
                    exerciseSetStates.forEachIndexed { index, setState ->
                        MeasuredSetTableRow(setState, index)
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
                    exerciseSetStates.forEachIndexed { index, setState ->
                        MeasuredSetTableRow(setState, index)
                    }
                }
            }
        }
    }
}

private fun WorkoutState.Set.shouldIgnoreCalibration(): Boolean {
    val isCalibrationSet = when (val workoutSet = set) {
        is BodyWeightSet -> workoutSet.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> workoutSet.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

    // Ignore calibration set if it's not in execution state (i.e., if we're in LoadSelection or RIRSelection states)
    // With new state types, calibration sets are only shown when isCalibrationSet == true (execution state)
    return isCalibrationSet && !this.isCalibrationSet
}

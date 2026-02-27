package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
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
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

enum class ProgressState { PAST, CURRENT, FUTURE }

/**
 * Display model for one row in the exercise set viewer. Each row corresponds to one state
 * from the exercise's container in the workout state machine.
 */
sealed class ExerciseSetDisplayRow {
    data class SetRow(val state: WorkoutState.Set) : ExerciseSetDisplayRow()
    data class RestRow(val state: WorkoutState.Rest) : ExerciseSetDisplayRow()
    data class CalibrationLoadSelectRow(val state: WorkoutState.CalibrationLoadSelection) : ExerciseSetDisplayRow()
    data class CalibrationRIRRow(val state: WorkoutState.CalibrationRIRSelection) : ExerciseSetDisplayRow()

    fun workoutState(): WorkoutState = when (this) {
        is SetRow -> state
        is RestRow -> state
        is CalibrationLoadSelectRow -> state
        is CalibrationRIRRow -> state
    }
}

internal fun buildExerciseSetDisplayRows(
    viewModel: AppViewModel,
    exerciseId: UUID,
): List<ExerciseSetDisplayRow> {
    return viewModel.getStatesForExercise(exerciseId).mapNotNull { state ->
        when (state) {
            is WorkoutState.Set -> ExerciseSetDisplayRow.SetRow(state)
            is WorkoutState.Rest -> ExerciseSetDisplayRow.RestRow(state)
            is WorkoutState.CalibrationLoadSelection ->
                if (state.isLoadConfirmed) null else ExerciseSetDisplayRow.CalibrationLoadSelectRow(state)
            is WorkoutState.CalibrationRIRSelection -> ExerciseSetDisplayRow.CalibrationRIRRow(state)
            is WorkoutState.AutoRegulationRIRSelection -> null
            else -> null
        }
    }
}

internal fun buildSupersetSetDisplayRows(
    viewModel: AppViewModel,
    supersetId: UUID,
): List<ExerciseSetDisplayRow> {
    return viewModel.getStatesForSuperset(supersetId).mapNotNull { state ->
        when (state) {
            is WorkoutState.Set -> ExerciseSetDisplayRow.SetRow(state)
            is WorkoutState.Rest -> ExerciseSetDisplayRow.RestRow(state)
            is WorkoutState.CalibrationLoadSelection ->
                if (state.isLoadConfirmed) null else ExerciseSetDisplayRow.CalibrationLoadSelectRow(state)
            is WorkoutState.CalibrationRIRSelection -> ExerciseSetDisplayRow.CalibrationRIRRow(state)
            is WorkoutState.AutoRegulationRIRSelection -> null
            else -> null
        }
    }
}

internal fun ExerciseSetDisplayRow.setLikeIdOrNull(): UUID? = when (this) {
    is ExerciseSetDisplayRow.SetRow -> state.set.id
    is ExerciseSetDisplayRow.RestRow -> state.set.id
    is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> state.calibrationSet.id
    is ExerciseSetDisplayRow.CalibrationRIRRow -> state.calibrationSet.id
}

internal fun findDisplayRowIndex(
    displayRows: List<ExerciseSetDisplayRow>,
    stateToMatch: WorkoutState,
    fallbackSetId: UUID?,
): Int {
    val byReference = displayRows.indexOfFirst { it.workoutState() === stateToMatch }
    if (byReference >= 0) return byReference

    if (fallbackSetId != null) {
        val bySetId = displayRows.indexOfFirst { it.setLikeIdOrNull() == fallbackSetId }
        if (bySetId >= 0) return bySetId
    }

    return 0
}

private fun toSupersetLetter(index: Int): String {
    if (index < 0) return ""
    var value = index
    val builder = StringBuilder()
    do {
        val remainder = value % 26
        builder.append(('A'.code + remainder).toChar())
        value = (value / 26) - 1
    } while (value >= 0)
    return builder.reverse().toString()
}

private fun buildSetIdentifier(
    viewModel: AppViewModel,
    exerciseId: UUID,
    setState: WorkoutState.Set,
): String? {
    val (current, _) = viewModel.getSetCounterForExercise(exerciseId, setState) ?: return null

    val supersetPrefix = viewModel.supersetIdByExerciseId[exerciseId]
        ?.let { supersetId -> viewModel.exercisesBySupersetId[supersetId] }
        ?.indexOfFirst { it.id == exerciseId }
        ?.takeIf { it >= 0 }
        ?.let(::toSupersetLetter)

    val baseIdentifier = if (supersetPrefix != null) {
        "$supersetPrefix$current"
    } else {
        current.toString()
    }

    return when {
        CalibrationHelper.isWarmupSet(setState.set) -> "W$baseIdentifier"
        else -> baseIdentifier
    }
}

private fun buildRestLabel(restState: WorkoutState.Rest): String {
    val seconds = (restState.set as? RestSet)?.timeInSeconds ?: 0
    return "REST ${FormatTime(seconds)}"
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
        Row(
            modifier = Modifier.fillMaxSize()
                .padding(2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val setDisplayText = when {
                !setIdentifier.isNullOrBlank() && !sideBadge.isNullOrBlank() -> "$setIdentifier$sideBadge"
                !setIdentifier.isNullOrBlank() -> setIdentifier!!
                !sideBadge.isNullOrBlank() -> sideBadge
                else -> ""
            }
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
                text = setDisplayText,
                style = itemStyle,
                textAlign = TextAlign.Center,
                color = textColor
            )

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

                    val weightText = equipment?.formatWeight(weightSetData.actualWeight) ?: "-"
                    val displayWeightText = when {
                        shouldHideCalibrationExecutionWeight -> "TBD"
                        isCalibrationSet && setState.isCalibrationSet -> weightText
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
                        modifier = Modifier.weight(3f),
                        text = FormatTime(timedDurationSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    ScalableFadingText(
                        modifier = Modifier.weight(3f),
                        text = FormatTime(enduranceSetData.startTimer / 1000),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
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
            .fillMaxSize()
            .padding(2.dp),
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
    progressState: ProgressState = ProgressState.CURRENT,
    customBackgroundColor: Color? = null,
    overrideSetIndex: Int? = null,
    currentWorkoutStateOverride: WorkoutState? = null,
){
    val supersetId = viewModel.supersetIdByExerciseId[exercise.id]
    val displayRows = if (supersetId != null) {
        buildSupersetSetDisplayRows(viewModel = viewModel, supersetId = supersetId)
    } else {
        buildExerciseSetDisplayRows(viewModel = viewModel, exerciseId = exercise.id)
    }

    val currentWorkoutState by viewModel.workoutState.collectAsState()

    val stateToMatch = currentWorkoutStateOverride ?: currentWorkoutState
    val setIndex = if (supersetId != null) {
        findDisplayRowIndex(
            displayRows = displayRows,
            stateToMatch = stateToMatch,
            fallbackSetId = currentSet.id
        )
    } else {
        overrideSetIndex ?: findDisplayRowIndex(
            displayRows = displayRows,
            stateToMatch = stateToMatch,
            fallbackSetId = currentSet.id
        )
    }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()
    val density = LocalDensity.current

    val itemHeightDp = 27.5.dp
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
        val sideBadge = when (sideIndex) {
            1 -> "①"
            2 -> "②"
            else -> "($sideIndex/$intraSetTotal)"
        }
        rowIndex to sideBadge
    }.toMap()

    val scrollKey = if (supersetId != null) supersetId else exercise.id

    // Reset scroll position immediately when exercise/superset changes
    LaunchedEffect(scrollKey) {
        scrollState.animateScrollTo(0)
    }

    // Scroll to current set when it changes
    LaunchedEffect(setIndex, scrollKey) {
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
        val borderColor = when (progressState) {
            ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
            ProgressState.CURRENT -> when {
                rowIndex == setIndex -> Orange
                rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
                else -> MaterialTheme.colorScheme.surfaceContainerHigh
            }
            ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val backgroundColor = customBackgroundColor ?: MaterialTheme.colorScheme.background

        val textColor = when (progressState) {
            ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
            ProgressState.CURRENT -> when {
                rowIndex == setIndex -> Orange
                rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
                else -> MaterialTheme.colorScheme.surfaceContainerHigh
            }
            ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        val markAsDone = when (progressState) {
            ProgressState.PAST -> true
            ProgressState.CURRENT -> rowIndex < setIndex
            ProgressState.FUTURE -> false
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
                    setIdentifier = buildSetIdentifier(
                        viewModel = viewModel,
                        exerciseId = displayRow.state.exerciseId,
                        setState = displayRow.state
                    ),
                    sideBadge = unilateralSideBadgeByRowIndex[rowIndex],
                    index = rowIndex,
                    isCurrentSet = rowIndex == setIndex,
                    textColor = textColor,
                    hasUnconfirmedLoadSelectionForExercise = CalibrationHelper.hasUnconfirmedLoadSelectionForExercise(
                        allWorkoutStates = viewModel.allWorkoutStates,
                        exerciseId = displayRow.state.exerciseId
                    )
                )
                is ExerciseSetDisplayRow.CalibrationLoadSelectRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = "SET LOAD",
                    textColor = textColor
                )
                is ExerciseSetDisplayRow.RestRow -> CenteredLabelRow(
                    modifier = rowModifier,
                    text = buildRestLabel(displayRow.state),
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

    val prototypeItem = @Composable {
        val firstRow = displayRows.firstOrNull()
        if (firstRow != null) {
            MeasuredSetTableRow(displayRow = firstRow, rowIndex = 0)
        }
    }

    val hasWeightRows = displayRows.any { row ->
        (row as? ExerciseSetDisplayRow.SetRow)?.state?.currentSetData?.let { data ->
            data is WeightSetData || data is BodyWeightSetData
        } ?: false
    }
    val useWeightHeader = if (supersetId != null) hasWeightRows else (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)

    Column(
        modifier = modifier.semantics { contentDescription = "Exercise sets viewer" },
        verticalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        if (useWeightHeader) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
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
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
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

        DynamicHeightColumn(
            modifier = Modifier
                .height(100.dp) // Fills remaining vertical space
                .fillMaxWidth()
                .clipToBounds(), // Still need to fill width
            prototypeItem = { prototypeItem() } // Pass the item for measurement
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalColumnScrollbar(scrollState = scrollState)
                    .verticalScroll(scrollState)
            ) {
                displayRows.forEachIndexed { index, setState ->
                    MeasuredSetTableRow(setState, index)
                }
            }
        }
    }
}

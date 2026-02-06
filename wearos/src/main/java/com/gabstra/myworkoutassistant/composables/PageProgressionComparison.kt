package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class SetComparison {
    BETTER, EQUAL, WORSE, MIXED
}

fun compareSets(beforeSetData: SetData?, afterSetData: SetData?): SetComparison {
    if (beforeSetData == null || afterSetData == null) {
        return SetComparison.EQUAL
    }

    return when {
        beforeSetData is WeightSetData && afterSetData is WeightSetData -> {
            val beforeReps = beforeSetData.actualReps
            val beforeWeight = beforeSetData.actualWeight
            val afterReps = afterSetData.actualReps
            val afterWeight = afterSetData.actualWeight

            when {
                afterReps == beforeReps && afterWeight == beforeWeight -> SetComparison.EQUAL
                (afterWeight > beforeWeight && afterReps < beforeReps) ||
                        (afterWeight < beforeWeight && afterReps > beforeReps) -> SetComparison.MIXED
                (afterWeight == beforeWeight && afterReps > beforeReps) ||
                        (afterReps == beforeReps && afterWeight > beforeWeight) ||
                        (afterReps > beforeReps && afterWeight > beforeWeight) -> SetComparison.BETTER

                else -> SetComparison.WORSE
            }
        }

        beforeSetData is BodyWeightSetData && afterSetData is BodyWeightSetData -> {
            val beforeReps = beforeSetData.actualReps
            val beforeWeight = beforeSetData.getWeight()
            val afterReps = afterSetData.actualReps
            val afterWeight = afterSetData.getWeight()

            when {
                afterReps == beforeReps && afterWeight == beforeWeight -> SetComparison.EQUAL
                (afterWeight > beforeWeight && afterReps < beforeReps) ||
                        (afterWeight < beforeWeight && afterReps > beforeReps) -> SetComparison.MIXED
                (afterWeight == beforeWeight && afterReps > beforeReps) ||
                        (afterReps == beforeReps && afterWeight > beforeWeight) ||
                        (afterReps > beforeReps && afterWeight > beforeWeight) -> SetComparison.BETTER

                else -> SetComparison.WORSE
            }
        }

        beforeSetData is EnduranceSetData && afterSetData is EnduranceSetData -> {
            val beforeDuration = beforeSetData.endTimer - beforeSetData.startTimer
            val afterDuration = afterSetData.endTimer - afterSetData.startTimer

            when {
                afterDuration == beforeDuration -> SetComparison.EQUAL
                afterDuration > beforeDuration -> SetComparison.BETTER
                else -> SetComparison.WORSE
            }
        }

        beforeSetData is TimedDurationSetData && afterSetData is TimedDurationSetData -> {
            val beforeDuration = beforeSetData.endTimer - beforeSetData.startTimer
            val afterDuration = afterSetData.endTimer - afterSetData.startTimer

            when {
                afterDuration == beforeDuration -> SetComparison.EQUAL
                afterDuration > beforeDuration -> SetComparison.BETTER
                else -> SetComparison.WORSE
            }
        }

        else -> SetComparison.EQUAL
    }
}

fun calculateSetDifference(
    beforeSetData: SetData?,
    afterSetData: SetData?,
    equipment: Equipment?
): String {
    if (beforeSetData == null || afterSetData == null) {
        return "Equal"
    }

    return when {
        beforeSetData is WeightSetData && afterSetData is WeightSetData -> {
            val weightDiff = afterSetData.actualWeight - beforeSetData.actualWeight
            val repsDiff = afterSetData.actualReps - beforeSetData.actualReps

            val parts = mutableListOf<String>()
            if (weightDiff != 0.0 && equipment is WeightLoadedEquipment) {
                val sign = if (weightDiff > 0) "+" else ""
                parts.add("$sign${equipment.formatWeight(weightDiff)} kg")
            }
            if (repsDiff != 0) {
                val sign = if (repsDiff > 0) "+" else ""
                parts.add("$sign$repsDiff reps")
            }

            if (parts.isEmpty()) "Equal" else parts.joinToString(", ")
        }

        beforeSetData is BodyWeightSetData && afterSetData is BodyWeightSetData -> {
            val weightDiff = afterSetData.getWeight() - beforeSetData.getWeight()
            val repsDiff = afterSetData.actualReps - beforeSetData.actualReps

            val parts = mutableListOf<String>()
            if (weightDiff != 0.0 && equipment is WeightLoadedEquipment) {
                val sign = if (weightDiff > 0) "+" else ""
                parts.add("$sign${equipment.formatWeight(weightDiff)} kg")
            }
            if (repsDiff != 0) {
                val sign = if (repsDiff > 0) "+" else ""
                parts.add("$sign$repsDiff reps")
            }

            if (parts.isEmpty()) "Equal" else parts.joinToString(" - ")
        }

        beforeSetData is EnduranceSetData && afterSetData is EnduranceSetData -> {
            val beforeDuration = (beforeSetData.endTimer - beforeSetData.startTimer) / 1000
            val afterDuration = (afterSetData.endTimer - afterSetData.startTimer) / 1000
            val durationDiff = afterDuration - beforeDuration

            if (durationDiff == 0) {
                "Equal"
            } else {
                val sign = if (durationDiff > 0) "+" else ""
                "$sign${FormatTime(durationDiff.toInt())}"
            }
        }

        beforeSetData is TimedDurationSetData && afterSetData is TimedDurationSetData -> {
            val beforeDuration = (beforeSetData.endTimer - beforeSetData.startTimer) / 1000
            val afterDuration = (afterSetData.endTimer - afterSetData.startTimer) / 1000
            val durationDiff = afterDuration - beforeDuration

            if (durationDiff == 0) {
                "Equal"
            } else {
                val sign = if (durationDiff > 0) "+" else ""
                "$sign${FormatTime(durationDiff.toInt())}"
            }
        }

        else -> "Equal"
    }
}

private fun isWorkSet(set: com.gabstra.myworkoutassistant.shared.sets.Set): Boolean = when (set) {
    is RestSet -> false
    is WeightSet -> set.subCategory == SetSubCategory.WorkSet
    is BodyWeightSet -> set.subCategory == SetSubCategory.WorkSet
    is EnduranceSet, is TimedDurationSet -> true
}

@Composable
fun PlaceholderSetRow(
    modifier: Modifier = Modifier,
    exercise: Exercise,
    textColor: Color = MaterialTheme.colorScheme.onBackground
) {
    val itemStyle = MaterialTheme.typography.numeralSmall

    Box(modifier = modifier) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Spacer(modifier = Modifier.width(18.dp))
            when (exercise.exerciseType) {
                ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT -> {
                    ScalableText(
                        modifier = Modifier.weight(2f),
                        text = "-",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "-",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                }

                ExerciseType.COUNTUP, ExerciseType.COUNTDOWN -> {
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "-",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                    Spacer(modifier = Modifier.width(18.dp))
                }

                else -> {
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "-",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                    Spacer(modifier = Modifier.width(18.dp))
                }
            }
        }
    }
}

@Composable
fun PageProgressionComparison(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    state: WorkoutState.Set,
    isPageVisible: Boolean = true
) {
    val progressionData = remember(exercise.id) {
        viewModel.exerciseProgressionByExerciseId[exercise.id]
    }

    val progressionState = progressionData?.second
    val isRetry = progressionState == ProgressionState.RETRY

    // Memoize previous set states - only compute once per exercise
    val previousSetStates = remember(exercise.id) {
        mutableStateOf<List<WorkoutState.Set>>(emptyList())
    }
    val scope = rememberWearCoroutineScope()
    
    // Track loading state - initialize to true when page becomes visible
    // Will be set to false immediately if data already exists
    var isLoading by remember(exercise.id, isPageVisible) {
        mutableStateOf(isPageVisible)
    }

    // Get previous sets from lastSessionWorkout - only when page is visible and data is not already loaded
    LaunchedEffect(exercise.id, isPageVisible) {
        if (!isPageVisible) {
            isLoading = false
            return@LaunchedEffect
        }
        
        // If data is already loaded for this exercise, no need to reload
        if (previousSetStates.value.isNotEmpty()) {
            isLoading = false
            return@LaunchedEffect
        }
        
        isLoading = true
        scope.launch {
            withContext(Dispatchers.IO) {
                val lastSessionWorkout = viewModel.lastSessionWorkout
                if (lastSessionWorkout != null) {
                    val lastSessionExercise =
                        (lastSessionWorkout.workoutComponents.filterIsInstance<Exercise>() +
                                lastSessionWorkout.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                                    .flatMap { it.exercises })
                            .find { it.id == exercise.id }

                    if (lastSessionExercise != null) {
                        val states = viewModel.createStatesFromExercise(lastSessionExercise)
                        previousSetStates.value = states.filterIsInstance<WorkoutState.Set>()
                            .filter { isWorkSet(it.set) }
                            .distinctBy { it.set.id }
                    }
                }
            }
            isLoading = false
        }
    }

    // Get progression sets from current exercise states (work sets only)
    val progressionSetStates = remember(exercise.id) {
        viewModel.getAllExerciseWorkoutStates(exercise.id)
            .filter { isWorkSet(it.set) }
            .distinctBy { it.set.id }
    }

    // Current work-set index (for comparison row and "Set: X/Y")
    val setIndex = remember(state.set.id, progressionSetStates) {
        progressionSetStates.indexOfFirst { it.set.id == state.set.id }.takeIf { it >= 0 } ?: 0
    }

    // Set index state for navigation
    var currentSetIndex by remember(exercise.id, setIndex) { mutableIntStateOf(setIndex) }
    val maxSets by remember(previousSetStates.value.size, progressionSetStates.size) {
        derivedStateOf {
            maxOf(previousSetStates.value.size, progressionSetStates.size)
        }
    }

    // Reset index when exercise or setIndex changes
    LaunchedEffect(exercise.id, setIndex) {
        currentSetIndex = setIndex
    }

    val colorScheme = MaterialTheme.colorScheme

    // Show loading screen until data is ready or when page is not visible
    if (isLoading || !isPageVisible) {
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
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // Title
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 5.dp),
            text = "Session Comparison",
            style = MaterialTheme.typography.titleSmall.copy(
                fontWeight = FontWeight.Bold
            ),
            textAlign = TextAlign.Center
        )

        // Set number indicator (combined with Repeat and Plateau Detected if applicable)
        if (maxSets > 0) {
            val baseStyle = MaterialTheme.typography.bodySmall
            val setIndicatorText = remember(isRetry, currentSetIndex, maxSets, baseStyle) {
                buildAnnotatedString {
                    withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray, fontWeight = FontWeight.Thin)) {
                        fun pipe() {
                            withStyle(baseStyle.toSpanStyle().copy(fontWeight = FontWeight.Thin)) {
                                append(" | ")
                            }
                        }
                        if (isRetry) {
                            withStyle(baseStyle.toSpanStyle().copy(fontWeight = FontWeight.Bold)) {
                                append("Repeat")
                            }
                            pipe()
                        }
                        append("Set: ${currentSetIndex + 1}/$maxSets")
                    }
                }
            }

            Text(
                text = setIndicatorText,
                style = baseStyle,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp)
            )
        }

        // Calculate comparison data - use derivedStateOf for performance
        val beforeSetData by remember(currentSetIndex, previousSetStates.value) {
            derivedStateOf {
                if (currentSetIndex < previousSetStates.value.size) {
                    previousSetStates.value[currentSetIndex].currentSetData
                } else null
            }
        }

        val afterSetData by remember(currentSetIndex, setIndex, state.currentSetData, state.set, progressionSetStates) {
            derivedStateOf {
                if (currentSetIndex == setIndex) {
                    // Use the current state's set data only when it's a work set; otherwise use work set data so comparison is work set vs work set
                    if (isWorkSet(state.set)) state.currentSetData
                    else progressionSetStates.getOrNull(currentSetIndex)?.currentSetData
                } else if (currentSetIndex < progressionSetStates.size) {
                    progressionSetStates[currentSetIndex].currentSetData
                } else null
            }
        }

        val beforeSetState by remember(currentSetIndex, previousSetStates.value) {
            derivedStateOf {
                if (currentSetIndex < previousSetStates.value.size) {
                    previousSetStates.value[currentSetIndex]
                } else null
            }
        }

        val afterSetState by remember(currentSetIndex, setIndex, state, state.set, progressionSetStates) {
            derivedStateOf {
                if (currentSetIndex == setIndex) {
                    // Use the current state only when it's a work set; otherwise use work set state so comparison is work set vs work set
                    if (isWorkSet(state.set)) state
                    else progressionSetStates.getOrNull(currentSetIndex)
                } else if (currentSetIndex < progressionSetStates.size) {
                    progressionSetStates[currentSetIndex]
                } else null
            }
        }

        val comparison by remember(beforeSetData, afterSetData) {
            derivedStateOf {
                compareSets(beforeSetData, afterSetData)
            }
        }

        val differenceText by remember(beforeSetData, afterSetData, afterSetState?.equipment, beforeSetState?.equipment) {
            derivedStateOf {
                calculateSetDifference(
                    beforeSetData,
                    afterSetData,
                    afterSetState?.equipment ?: beforeSetState?.equipment
                )
            }
        }

        val rowIndex = currentSetIndex
        val borderColor by remember(currentSetIndex, setIndex, colorScheme.outline, colorScheme.onBackground) {
            derivedStateOf {
                when {
                    rowIndex == setIndex -> Orange // Current set: orange border
                    rowIndex < setIndex -> colorScheme.onBackground // Previous set: onBackground border
                    else -> colorScheme.surfaceContainerHigh // Future set: subtle outline
                }
            }
        }
        val backgroundColor by remember(currentSetIndex, setIndex, colorScheme.background) {
            derivedStateOf {
                colorScheme.background // All sets: black background
            }
        }
        val textColor by remember(currentSetIndex, setIndex, colorScheme.surfaceContainerHigh) {
            derivedStateOf {
                when {
                    rowIndex == setIndex -> Orange // Current set: orange text
                    rowIndex < setIndex -> colorScheme.onBackground // Previous set: onBackground text
                    else -> colorScheme.surfaceContainerHigh // Future set: surfaceContainerHigh (MediumLightGray)
                }
            }
        }
        val shape = remember { RoundedCornerShape(25) }

        // Previous set row or placeholder
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(27.5.dp)
                .padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val isPreviousWarmupSet = if (currentSetIndex < previousSetStates.value.size) {
                when(val set = previousSetStates.value[currentSetIndex].set) {
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    else -> false
                }
            } else false

            val previousRowModifier = Modifier
                .fillMaxSize()
                .height(25.dp)
                .padding(bottom = 2.5.dp)
                .then(
                    if (isPreviousWarmupSet) {
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
                .clip(shape)

            if (currentSetIndex < previousSetStates.value.size) {
                SetTableRow(
                    modifier = previousRowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = previousSetStates.value[currentSetIndex],
                    index = currentSetIndex,
                    isCurrentSet = false,
                    markAsDone = false,
                    textColor = textColor
                )
            } else {
                Box(modifier = previousRowModifier) {
                    PlaceholderSetRow(
                        modifier = Modifier.fillMaxSize().padding(3.dp),
                        exercise = exercise,
                        textColor = textColor
                    )
                }
            }
        }

        // Comparison section
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 2.5.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            val comparisonColor by remember(comparison, colorScheme.onBackground, colorScheme.tertiary) {
                derivedStateOf {
                    when (comparison) {
                        SetComparison.BETTER -> Green
                        SetComparison.WORSE -> Red
                        SetComparison.EQUAL -> colorScheme.onBackground
                        SetComparison.MIXED -> colorScheme.tertiary
                    }
                }
            }

            when (comparison) {
                SetComparison.EQUAL -> {
                    Icon(
                        imageVector = Icons.Filled.DragHandle,
                        contentDescription = null,
                        modifier = Modifier
                            .width(20.dp)
                            .height(20.dp),
                        tint = MaterialTheme.colorScheme.onBackground
                    )
                }

                SetComparison.BETTER -> {
                    Icon(
                        imageVector = Icons.Filled.ArrowUpward,
                        contentDescription = null,
                        modifier = Modifier
                            .width(20.dp)
                            .height(20.dp),
                        tint = Green
                    )
                }

                SetComparison.WORSE -> {
                    Icon(
                        imageVector = Icons.Filled.ArrowDownward,
                        contentDescription = null,
                        modifier = Modifier
                            .width(20.dp)
                            .height(20.dp),
                        tint = Red
                    )
                }

                SetComparison.MIXED -> {
                    Icon(
                        imageVector = Icons.Filled.SwapVert,
                        contentDescription = null,
                        modifier = Modifier
                            .width(20.dp)
                            .height(20.dp),
                        tint = MaterialTheme.colorScheme.tertiary
                    )
                }
            }

            Spacer(modifier = Modifier.width(5.dp))

            ScalableText(
                text = differenceText,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = comparisonColor
            )
        }

        // Current set row or placeholder
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(27.5.dp)
                .padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val isCurrentWarmupSet = if (currentSetIndex < progressionSetStates.size) {
                when(val set = progressionSetStates[currentSetIndex].set) {
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    else -> false
                }
            } else false

            val currentRowModifier = Modifier
                .fillMaxSize()
                .height(25.dp)
                .padding(bottom = 2.5.dp)
                .then(
                    if (isCurrentWarmupSet) {
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
                .clip(shape)

            if (currentSetIndex < progressionSetStates.size) {
                SetTableRow(
                    modifier = currentRowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = progressionSetStates[currentSetIndex],
                    index = currentSetIndex,
                    isCurrentSet = false,
                    markAsDone = false,
                    textColor = textColor
                )
            } else {
                Box(modifier = currentRowModifier) {
                    PlaceholderSetRow(
                        modifier = Modifier.fillMaxSize().padding(3.dp),
                        exercise = exercise,
                        textColor = textColor
                    )
                }
            }
        }
    }

    // Edge click navigation overlay
    Row(
        modifier = Modifier.fillMaxSize(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Row(
            modifier = Modifier
                .fillMaxHeight()
                .weight(1f)
                .clickable(
                    enabled = currentSetIndex > 0
                ) {
                    hapticsViewModel.doGentleVibration()
                    currentSetIndex--
                }
                .then(if (maxSets > 1) Modifier else Modifier.alpha(0f)),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            // Left edge - clickable for previous set
        }
        Spacer(
            modifier = Modifier
                .fillMaxHeight()
                .weight(1f)
        )
        Row(
            modifier = Modifier
                .fillMaxHeight()
                .weight(1f)
                .clickable(
                    enabled = currentSetIndex < maxSets - 1
                ) {
                    hapticsViewModel.doGentleVibration()
                    currentSetIndex++
                }
                .then(if (maxSets > 1) Modifier else Modifier.alpha(0f)),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            // Right edge - clickable for next set
        }
    }

}



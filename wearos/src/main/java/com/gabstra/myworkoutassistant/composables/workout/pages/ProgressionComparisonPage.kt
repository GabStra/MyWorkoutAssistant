package com.gabstra.myworkoutassistant.composables.workout.pages

import com.gabstra.myworkoutassistant.composables.*

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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
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
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private fun isWorkSet(set: com.gabstra.myworkoutassistant.shared.sets.Set): Boolean = when (set) {
    is RestSet -> false
    is WeightSet -> set.subCategory == SetSubCategory.WorkSet
    is BodyWeightSet -> set.subCategory == SetSubCategory.WorkSet
    is EnduranceSet, is TimedDurationSet -> true
}

internal fun canCompareProgressionSetData(before: SetData?, after: SetData?): Boolean = when {
    before is WeightSetData && after is WeightSetData -> true
    before is BodyWeightSetData && after is BodyWeightSetData -> true
    before is EnduranceSetData && after is EnduranceSetData -> true
    before is TimedDurationSetData && after is TimedDurationSetData -> true
    else -> false
}

internal fun buildHistoricalComparisonStates(
    templateStates: List<WorkoutState.Set>,
    histories: List<SetHistory>,
): List<WorkoutState.Set> {
    val templateStateBySetId = templateStates.associateBy { it.set.id }
    return histories.mapNotNull { history ->
        templateStateBySetId[history.setId]?.copy(
            previousSetData = null,
            currentSetDataState = mutableStateOf(history.setData),
            historicalSetData = history.setData,
            hasNoHistory = false,
            startTime = history.startTime,
            skipped = history.skipped,
            equipmentId = history.equipmentIdSnapshot
                ?: templateStateBySetId[history.setId]?.equipmentId,
            hasBeenExecuted = true,
        )
    }
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
                        color = textColor
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "-",
                        style = itemStyle,
                        color = textColor
                    )
                }

                ExerciseType.COUNTUP, ExerciseType.COUNTDOWN -> {
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "-",
                        style = itemStyle,
                        color = textColor
                    )
                    Spacer(modifier = Modifier.width(18.dp))
                }

            }
        }
    }
}

@Composable
fun ProgressionComparisonPage(
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
    val progressionContextLabel = when (progressionState) {
        ProgressionState.PROGRESS -> "Progress"
        ProgressionState.RETRY -> "Repeat"
        ProgressionState.DELOAD -> "Deload"
        ProgressionState.FAILED -> "Failed"
        null -> null
    }

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
                        val templateStates = viewModel.createStatesFromExercise(lastSessionExercise)
                            .filterIsInstance<WorkoutState.Set>()
                            .filter { isWorkSet(it.set) }
                            .distinctBy { it.set.id }
                        previousSetStates.value = buildHistoricalComparisonStates(
                            templateStates = templateStates,
                            histories = viewModel.getAllSetHistoriesByExerciseId(exercise.id),
                        )
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
            style = workoutPagerTitleTextStyle(),
            textAlign = TextAlign.Center
        )

        // Set number indicator (combined with Repeat and Plateau Detected if applicable)
        if (maxSets > 0) {
            val baseStyle = MaterialTheme.typography.bodySmall
            val secondaryTextColor = MaterialTheme.colorScheme.onSurfaceVariant
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (progressionContextLabel != null) {
                    Text(
                        text = progressionContextLabel,
                        style = baseStyle,
                        color = secondaryTextColor
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                }
                Text(
                    text = "Set: ${currentSetIndex + 1}/$maxSets",
                    style = baseStyle,
                    color = secondaryTextColor
                )
            }
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

        val plannedNextSet = if (progressionState == ProgressionState.PROGRESS) {
            progressionData
                .first
                .sets
                .getOrNull(currentSetIndex)
                ?.let { SimpleSet(it.weight, it.reps) }
        } else {
            null
        }

        val setDifference by remember(
            beforeSetData,
            afterSetData,
            afterSetState?.equipmentId,
            beforeSetState?.equipmentId,
            plannedNextSet,
        ) {
            derivedStateOf {
                val afterEquipment = afterSetState?.equipmentId?.let { viewModel.getEquipmentById(it) }
                val beforeEquipment = beforeSetState?.equipmentId?.let { viewModel.getEquipmentById(it) }
                calculateSetDifference(
                    beforeSetData,
                    afterSetData,
                    afterEquipment ?: beforeEquipment,
                    plannedNextSet = plannedNextSet,
                )
            }
        }
        val differenceText = setDifference.displayText
        val comparison = setDifference.comparison
        val hasCompletedCurrentSessionSet =
            currentSetIndex < setIndex || afterSetState?.hasBeenExecuted == true
        val hasValidComparison =
            hasCompletedCurrentSessionSet &&
                canCompareProgressionSetData(beforeSetData, afterSetData)

        val rowAccentColor = progressRowAccentColor(
            progressState = ProgressState.CURRENT,
            rowIndex = currentSetIndex,
            currentRowIndex = setIndex,
        )
        val previousRowAccentColor = colorScheme.onBackground
        val shape = remember { RoundedCornerShape(25) }

        // Previous set row or placeholder
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(25.dp)
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val previousRowModifier = Modifier
                .fillMaxSize()
                .border(BorderStroke(1.dp, previousRowAccentColor), shape)
                .background(colorScheme.background, shape)
                .clip(shape)

            if (currentSetIndex < previousSetStates.value.size) {
                SetTableRow(
                    modifier = previousRowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = previousSetStates.value[currentSetIndex],
                    setIdentifier = buildSetIdentifier(
                        viewModel = viewModel,
                        exerciseId = exercise.id,
                        setState = previousSetStates.value[currentSetIndex],
                    ),
                    index = currentSetIndex,
                    isCurrentSet = false,
                    textColor = previousRowAccentColor
                )
            } else {
                Box(modifier = previousRowModifier) {
                    PlaceholderSetRow(
                        modifier = Modifier.fillMaxSize().padding(3.dp),
                        exercise = exercise,
                        textColor = previousRowAccentColor
                    )
                }
            }
        }

        // Comparison section
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(30.dp)
                .padding(horizontal = 20.dp, vertical = 5.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            val comparisonColor = if (hasValidComparison) {
                colorForSetComparisonSummary(comparison)
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            }

            if (hasValidComparison) {
                SetComparisonDeltaIcon(comparison = comparison, iconSize = 20.dp)
                Spacer(modifier = Modifier.width(5.dp))
            }

            ScalableText(
                text = if (hasValidComparison) differenceText else "Not available",
                style = MaterialTheme.typography.bodySmall,
                color = comparisonColor
            )
        }

        // Current set row or placeholder
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(25.dp)
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val currentRowModifier = Modifier
                .fillMaxSize()
                .border(BorderStroke(1.dp, rowAccentColor), shape)
                .background(colorScheme.background, shape)
                .clip(shape)

            if (currentSetIndex < progressionSetStates.size) {
                SetTableRow(
                    modifier = currentRowModifier,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                    setState = progressionSetStates[currentSetIndex],
                    setIdentifier = buildSetIdentifier(
                        viewModel = viewModel,
                        exerciseId = exercise.id,
                        setState = progressionSetStates[currentSetIndex],
                    ),
                    index = currentSetIndex,
                    isCurrentSet = false,
                    textColor = rowAccentColor
                )
            } else {
                Box(modifier = currentRowModifier) {
                    PlaceholderSetRow(
                        modifier = Modifier.fillMaxSize().padding(3.dp),
                        exercise = exercise,
                        textColor = rowAccentColor
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

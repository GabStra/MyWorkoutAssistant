package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.composables.CircularEndsPillShape
import com.gabstra.myworkoutassistant.composables.ControlButtonsVertical
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PageNotes
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.PageProgressionComparison
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.composables.TimeViewer
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
private fun RestTimerBlock(
    set: RestSet,
    state: WorkoutState.Rest,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    onTimerEnd: () -> Unit,
    skipConfirmAction: androidx.compose.runtime.MutableState<(() -> Unit)?>,
    restartTimerAction: androidx.compose.runtime.MutableState<(() -> Unit)?>,
    isEditModeState: androidx.compose.runtime.MutableState<Boolean>,
) {
    val scope = rememberWearCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose { timerJob?.cancel() }
    }

    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var amountToWait by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var currentSecondsFreeze by remember { mutableIntStateOf(0) }
    var amountToWaitFreeze by remember { mutableIntStateOf(0) }
    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var hasBeenStartedOnce by remember { mutableStateOf(false) }
    val isPaused by viewModel.isPaused

    isEditModeState.value = isTimerInEditMode

    fun computeProgress(): Float {
        return if (isTimerInEditMode) {
            currentSecondsFreeze.toFloat() / amountToWaitFreeze.toFloat()
        } else {
            currentSeconds.toFloat() / amountToWait.toFloat()
        }
    }
    val indicatorProgress = remember { mutableFloatStateOf(computeProgress()) }
    LaunchedEffect(currentSeconds, amountToWait, currentSecondsFreeze, amountToWaitFreeze, isTimerInEditMode) {
        indicatorProgress.floatValue = computeProgress()
    }

    val updateInteractionTime = { lastInteractionTime = System.currentTimeMillis() }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            amountToWait -= 5
            amountToWaitFreeze = amountToWait
            currentSeconds = newTimerValue
            currentSecondsFreeze = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        amountToWait += 5
        amountToWaitFreeze = amountToWait
        currentSeconds = newTimerValue
        currentSecondsFreeze = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (currentSeconds > 0) {
                val now = LocalDateTime.now()
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())
                currentSeconds -= 1
                if (currentSeconds == 5) viewModel.lightScreenUp()
                currentSetData = currentSetData.copy(endTimer = currentSeconds)
            }
            state.currentSetData = currentSetData.copy(endTimer = 0)
            hapticsViewModel.doHardVibrationWithBeep()
            onTimerEnd()
        }
        if (!hasBeenStartedOnce) hasBeenStartedOnce = true
    }

    skipConfirmAction.value = {
        state.currentSetData = currentSetData.copy(endTimer = currentSeconds)
        viewModel.closeCustomDialog()
        onTimerEnd()
    }
    restartTimerAction.value = { startTimerJob() }

    LaunchedEffect(currentSetData) { state.currentSetData = currentSetData }
    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                isTimerInEditMode = false
            }
            delay(1000)
        }
    }
    LaunchedEffect(set.id) {
        delay(500)
        if (!isTimerInEditMode) {
            startTimerJob()
        }
        if (state.startTime == null) state.startTime = LocalDateTime.now()
    }
    LaunchedEffect(isPaused, isTimerInEditMode) {
        if (!hasBeenStartedOnce) return@LaunchedEffect
        if (isPaused || isTimerInEditMode) timerJob?.takeIf { it.isActive }?.cancel()
        else if (timerJob?.isActive != true) startTimerJob()
    }

    val timerTextStyle = MaterialTheme.typography.numeralSmall

    @Composable
    fun textComposable(seconds: Int, modifier: Modifier = Modifier, style: TextStyle = timerTextStyle) {
        Row(
            modifier = modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClick = {
                        currentSecondsFreeze = currentSeconds
                        amountToWaitFreeze = amountToWait
                        state.currentSetData = currentSetData.copy(endTimer = currentSeconds)
                        isTimerInEditMode = !isTimerInEditMode
                        updateInteractionTime()
                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {}
                ),
                seconds = seconds,
                style = style,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }
    }

    AnimatedContent(
        targetState = isTimerInEditMode,
        transitionSpec = { fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500)) },
        label = ""
    ) { updatedState ->
        if (updatedState) {
            Box(
                modifier = Modifier.fillMaxSize().padding(vertical = 20.dp, horizontal = 35.dp),
                contentAlignment = Alignment.Center
            ) {
                ControlButtonsVertical(
                    modifier = Modifier.fillMaxSize().clickable(interactionSource = null, indication = null) { updateInteractionTime() },
                    onMinusTap = { onMinusClick() },
                    onMinusLongPress = { onMinusClick() },
                    onPlusTap = { onPlusClick() },
                    onPlusLongPress = { onPlusClick() },
                    onCloseClick = { isTimerInEditMode = false },
                    content = { textComposable(seconds = currentSecondsFreeze) }
                )
            }
        } else {
            Box(modifier = Modifier.fillMaxSize())
        }
    }

    Box(
        modifier = Modifier.fillMaxSize().semantics { contentDescription = SetValueSemantics.RestSetTypeDescription },
        contentAlignment = Alignment.Center
    ) {
        val primaryColor = MaterialTheme.colorScheme.primary
        val trackColor = remember(primaryColor) { primaryColor.copy(alpha = 0.35f) }
        CircularProgressIndicator(
            progress = { indicatorProgress.floatValue },
            modifier = Modifier.fillMaxSize().padding(10.dp),
            colors = ProgressIndicatorDefaults.colors(indicatorColor = primaryColor, trackColor = trackColor),
            strokeWidth = 4.dp,
            startAngle = 125f,
            endAngle = 235f,
        )
        textComposable(
            seconds = if (isTimerInEditMode) currentSecondsFreeze else currentSeconds,
            modifier = Modifier.align(Alignment.BottomCenter),
            style = MaterialTheme.typography.labelMedium
        )
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    onBeforeGoHome: (() -> Unit)? = null,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
    navController: NavController,
) {
    val set = state.set as RestSet
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()
    val skipConfirmAction = remember { mutableStateOf<(() -> Unit)?>(null) }
    val restartTimerAction = remember { mutableStateOf<(() -> Unit)?>(null) }
    val isEditModeState = remember { mutableStateOf(false) }

    val exerciseIdFromNext = when (val n = state.nextState) {
        is WorkoutState.Set -> n.exerciseId
        is WorkoutState.CalibrationLoadSelection -> n.exerciseId
        is WorkoutState.CalibrationRIRSelection -> n.exerciseId
        else -> state.exerciseId
    }
    val exercise = remember(exerciseIdFromNext) {
        val exerciseId = exerciseIdFromNext
        if (exerciseId != null) viewModel.exercisesById[exerciseId]!!
        else viewModel.exercisesById.values.firstOrNull() ?: throw IllegalStateException("No exercises available")
    }
    val equipment = remember(exercise) { exercise.equipmentId?.let { viewModel.getEquipmentById(it) } }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null && equipment.type == EquipmentType.BARBELL &&
            equipment.name.contains("barbell", ignoreCase = true) &&
            (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }
    val showProgressionComparisonPage = remember(exercise) {
        !exercise.requiresLoadCalibration &&
            viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
            viewModel.lastSessionWorkout != null &&
            ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>().flatMap { it.exercises }).any { it.id == exercise.id })
    }
    val showNotesPage = remember(exercise) { exercise.notes.isNotEmpty() }

    val pageTypes = remember(showPlatesPage, showProgressionComparisonPage, showNotesPage) {
        mutableListOf<PageType>().apply {
            add(PageType.BUTTONS)
            add(PageType.EXERCISES)
            if (showPlatesPage) add(PageType.PLATES)
            if (showProgressionComparisonPage) add(PageType.PROGRESSION_COMPARISON)
            if (showNotesPage) add(PageType.NOTES)
        }
    }
    val exercisesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.EXERCISES) }
    val platesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.PLATES) }
    val progressionComparisonPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.PROGRESSION_COMPARISON) }

    val pagerState = rememberPagerState(initialPage = exercisesPageIndex, pageCount = { pageTypes.size })
    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }
    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex
        if (isOnPlatesPage) viewModel.setDimming(false)
        else viewModel.reEvaluateDimmingForCurrentState()
        if (pagerState.currentPage != exercisesPageIndex) selectedExercise = exercise
    }

    Box(modifier = Modifier.fillMaxSize()) {
        if (!isEditModeState.value) {
            Box(
                modifier = Modifier.fillMaxSize().padding(horizontal = 22.5.dp, vertical = 30.dp).clip(CircularEndsPillShape(straightWidth = 50.dp))
            ) {
                CustomHorizontalPager(modifier = Modifier.fillMaxSize(), pagerState = pagerState) { pageIndex ->
                    val pageType = pageTypes[pageIndex]
                    Box(modifier = Modifier.fillMaxSize().padding(horizontal = 15.dp)) {
                        when (pageType) {
                            PageType.PLATES -> {
                                val setStateForPlates = (state.nextState as? WorkoutState.Set) ?: viewModel.getFirstSetStateAfterCurrent()
                                if (setStateForPlates != null) PagePlates(setStateForPlates, equipment, hapticsViewModel, viewModel)
                            }
                            PageType.EXERCISE_DETAIL -> {}
                            PageType.EXERCISES -> {
                                val nextState = state.nextState
                                if (nextState != null) {
                                    PageExercises(
                                        selectedExercise = selectedExercise,
                                        workoutState = nextState,
                                        viewModel = viewModel,
                                        hapticsViewModel = hapticsViewModel,
                                        currentExercise = exercise,
                                        exerciseOrSupersetIds = exerciseOrSupersetIds,
                                        onExerciseSelected = { selectedExercise = it }
                                    )
                                }
                            }
                            PageType.BUTTONS -> {
                                val setStateForButtons = (state.nextState as? WorkoutState.Set) ?: viewModel.getFirstSetStateAfterCurrent()
                                if (setStateForButtons != null) {
                                    PageButtons(setStateForButtons, viewModel, hapticsViewModel, navController, onBeforeGoHome)
                                }
                            }
                            PageType.NOTES -> PageNotes(exercise.notes)
                            PageType.PROGRESSION_COMPARISON -> {
                                val setStateForProgression = (state.nextState as? WorkoutState.Set) ?: viewModel.getFirstSetStateAfterCurrent()
                                if (setStateForProgression != null) {
                                    key(pageType, pageIndex) {
                                        PageProgressionComparison(
                                            viewModel = viewModel,
                                            hapticsViewModel = hapticsViewModel,
                                            exercise = exercise,
                                            state = setStateForProgression,
                                            isPageVisible = pagerState.currentPage == progressionComparisonPageIndex
                                        )
                                    }
                                }
                            }
                            PageType.MUSCLES -> {}
                            PageType.MOVEMENT_ANIMATION -> {}
                        }
                    }
                }
            }
        }

        RestTimerBlock(
            set = set,
            state = state,
            viewModel = viewModel,
            hapticsViewModel = hapticsViewModel,
            onTimerEnd = onTimerEnd,
            skipConfirmAction = skipConfirmAction,
            restartTimerAction = restartTimerAction,
            isEditModeState = isEditModeState,
        )

        val nextState = state.nextState
        if (nextState != null && !isEditModeState.value) {
            ExerciseIndicator(
                viewModel,
                currentStateOverride = nextState,
                selectedExerciseId = selectedExercise.id
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip Rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            skipConfirmAction.value?.invoke()
        },
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.closeCustomDialog()
            restartTimerAction.value?.invoke()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
            restartTimerAction.value?.invoke()
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) viewModel.setDimming(false)
            else viewModel.reEvaluateDimmingForCurrentState()
        }
    )
}


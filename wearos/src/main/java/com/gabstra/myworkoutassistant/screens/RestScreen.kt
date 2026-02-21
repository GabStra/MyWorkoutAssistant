package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
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
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.composables.WorkoutPagerPageSafeAreaPadding
import com.gabstra.myworkoutassistant.composables.overlayVisualScale
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.delay
import java.time.LocalDateTime

private enum class RestHorizontalPage {
    BUTTONS,
    PLATES,
    REST_TIMER,
    PROGRESSION_COMPARISON,
    NOTES,
    EXERCISES
}

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
    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.endTimer) }
    var amountToWait by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var isTimerInEditMode by remember { mutableStateOf(false) }
    var wasTimerRunningBeforeEditMode by remember(set.id) { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val isPaused by viewModel.isPaused

    isEditModeState.value = isTimerInEditMode

    fun registerRestTimer() {
        if (state.startTime == null) {
            state.startTime = LocalDateTime.now()
                .minusSeconds((amountToWait - currentSeconds).coerceAtLeast(0).toLong())
        }
        if (!viewModel.workoutTimerService.isTimerRegistered(set.id) && currentSeconds > 0) {
            viewModel.workoutTimerService.registerTimer(
                state = state,
                callbacks = WorkoutTimerService.TimerCallbacks(
                    onTimerEnd = {
                        hapticsViewModel.doHardVibrationWithBeep()
                        onTimerEnd()
                    },
                    onTimerEnabled = {},
                    onTimerDisabled = {}
                )
            )
        }
    }

    fun unregisterRestTimer() {
        if (viewModel.workoutTimerService.isTimerRegistered(set.id)) {
            viewModel.workoutTimerService.unregisterTimer(set.id)
        }
    }

    fun computeProgress(): Float {
        if (amountToWait <= 0) return 0f
        return currentSeconds.toFloat() / amountToWait.toFloat()
    }
    val indicatorProgress = remember { mutableFloatStateOf(computeProgress()) }
    LaunchedEffect(currentSeconds, amountToWait) {
        indicatorProgress.floatValue = computeProgress()
    }

    val updateInteractionTime = { lastInteractionTime = System.currentTimeMillis() }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            amountToWait -= 5
            currentSeconds = newTimerValue
            hapticsViewModel.doGentleVibration()
            currentSetData = currentSetData.copy(endTimer = currentSeconds)
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        amountToWait += 5
        currentSeconds = newTimerValue
        hapticsViewModel.doGentleVibration()
        currentSetData = currentSetData.copy(endTimer = currentSeconds)
        updateInteractionTime()
    }

    fun setTimerEditMode(enabled: Boolean) {
        if (isTimerInEditMode == enabled) return
        isTimerInEditMode = enabled
        if (enabled) {
            wasTimerRunningBeforeEditMode = viewModel.workoutTimerService.isTimerRegistered(set.id)
            currentSetData = currentSetData.copy(startTimer = amountToWait, endTimer = currentSeconds)
            state.currentSetData = currentSetData
            unregisterRestTimer()
            updateInteractionTime()
        } else if (!isPaused && wasTimerRunningBeforeEditMode && currentSeconds > 0) {
            currentSetData = currentSetData.copy(startTimer = amountToWait, endTimer = currentSeconds)
            state.currentSetData = currentSetData
            state.startTime = LocalDateTime.now()
                .minusSeconds((amountToWait - currentSeconds).coerceAtLeast(0).toLong())
            registerRestTimer()
            wasTimerRunningBeforeEditMode = false
        }
    }

    skipConfirmAction.value = {
        unregisterRestTimer()
        state.currentSetData = currentSetData.copy(endTimer = currentSeconds)
        viewModel.closeCustomDialog()
        onTimerEnd()
    }
    restartTimerAction.value = {
        setTimerEditMode(false)
        if (!isPaused && currentSeconds > 0) {
            state.startTime = LocalDateTime.now()
                .minusSeconds((amountToWait - currentSeconds).coerceAtLeast(0).toLong())
            registerRestTimer()
        }
    }

    LaunchedEffect(state.currentSetData) {
        val latest = state.currentSetData as? RestSetData ?: return@LaunchedEffect
        currentSetData = latest
        if (!isTimerInEditMode) {
            currentSeconds = latest.endTimer
            amountToWait = latest.startTimer
        }
        if (latest.endTimer == 5) {
            viewModel.lightScreenUp()
        }
    }
    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                setTimerEditMode(false)
            }
            delay(1000)
        }
    }
    LaunchedEffect(set.id, isPaused, isTimerInEditMode, currentSeconds, amountToWait) {
        if (isPaused || isTimerInEditMode || currentSeconds <= 0) {
            unregisterRestTimer()
        } else {
            state.currentSetData = currentSetData.copy(startTimer = amountToWait, endTimer = currentSeconds)
            registerRestTimer()
        }
    }

    val timerTextStyle = MaterialTheme.typography.numeralSmall
    val timerHeaderStyle = MaterialTheme.typography.bodyExtraSmall

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
                        setTimerEditMode(!isTimerInEditMode)
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

    if (isTimerInEditMode) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(vertical = 20.dp, horizontal = 35.dp),
            contentAlignment = Alignment.Center
        ) {
            ControlButtonsVertical(
                modifier = Modifier
                    .fillMaxSize()
                    .clickable(interactionSource = null, indication = null) { updateInteractionTime() },
                onMinusTap = { onMinusClick() },
                onMinusLongPress = { onMinusClick() },
                onPlusTap = { onPlusClick() },
                onPlusLongPress = { onPlusClick() },
                onCloseClick = { setTimerEditMode(false) },
                content = { textComposable(seconds = currentSeconds) }
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = SetValueSemantics.RestSetTypeDescription },
        contentAlignment = Alignment.Center
    ) {
        val primaryColor = MaterialTheme.colorScheme.primary
        CircularProgressIndicator(
            progress = { indicatorProgress.floatValue },
            modifier = Modifier.fillMaxSize().padding(10.dp),
            colors = ProgressIndicatorDefaults.colors(
                indicatorColor = primaryColor,
                trackColor = MediumDarkGray
            ),
            strokeWidth = 4.dp,
            startAngle = 130f,
            endAngle = 230f,
        )
        if (!isTimerInEditMode) {
            Column(
                modifier = Modifier.align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                androidx.wear.compose.material3.Text(
                    text = "REST TIMER",
                    style = timerHeaderStyle,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Spacer(modifier = Modifier.height(5.dp))
                textComposable(seconds = currentSeconds)
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    onBeforeGoHome: (() -> Unit)? = null,
    onTimerEnd: () -> Unit,
    navController: NavController,
) {
    val set = state.set as RestSet
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()
    val skipConfirmAction = remember { mutableStateOf<(() -> Unit)?>(null) }
    val restartTimerAction = remember { mutableStateOf<(() -> Unit)?>(null) }
    val isEditModeState = remember { mutableStateOf(false) }

    val exerciseIdFromNext = when (val next = state.nextState) {
        is WorkoutState.Set -> next.exerciseId
        is WorkoutState.CalibrationLoadSelection -> next.exerciseId
        is WorkoutState.CalibrationRIRSelection -> next.exerciseId
        else -> state.exerciseId
    }
    val exercise = remember(exerciseIdFromNext) {
        val exerciseId = exerciseIdFromNext
        if (exerciseId != null) {
            viewModel.exercisesById[exerciseId]!!
        } else {
            viewModel.exercisesById.values.firstOrNull()
                ?: throw IllegalStateException("No exercises available")
        }
    }
    val equipment = remember(exercise) { exercise.equipmentId?.let { viewModel.getEquipmentById(it) } }
    val showPlatesPage = remember(exercise, equipment) {
        equipment != null &&
            equipment.type == EquipmentType.BARBELL &&
            equipment.name.contains("barbell", ignoreCase = true) &&
            (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }
    val showProgressionComparisonPage = remember(exercise) {
        !exercise.requiresLoadCalibration &&
            viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
            viewModel.lastSessionWorkout != null &&
            ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                viewModel.lastSessionWorkout!!.workoutComponents
                    .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                    .flatMap { it.exercises }).any { it.id == exercise.id })
    }
    val showNotesPage = remember(exercise) { exercise.notes.isNotEmpty() }

    val horizontalPageTypes = remember(showPlatesPage, showProgressionComparisonPage, showNotesPage) {
        mutableListOf<RestHorizontalPage>().apply {
            add(RestHorizontalPage.BUTTONS)
            if (showPlatesPage) add(RestHorizontalPage.PLATES)
            add(RestHorizontalPage.REST_TIMER)
            if (showProgressionComparisonPage) add(RestHorizontalPage.PROGRESSION_COMPARISON)
            if (showNotesPage) add(RestHorizontalPage.NOTES)
            add(RestHorizontalPage.EXERCISES)
        }
    }

    val restTimerPageIndex = remember(horizontalPageTypes) {
        horizontalPageTypes.indexOf(RestHorizontalPage.REST_TIMER)
    }
    val restPlatesPageIndex = remember(horizontalPageTypes) {
        horizontalPageTypes.indexOf(RestHorizontalPage.PLATES)
    }
    val restProgressionPageIndex = remember(horizontalPageTypes) {
        horizontalPageTypes.indexOf(RestHorizontalPage.PROGRESSION_COMPARISON)
    }
    val exercisesPageIndex = remember(horizontalPageTypes) {
        horizontalPageTypes.indexOf(RestHorizontalPage.EXERCISES)
    }

    val horizontalPagerState = rememberPagerState(
        initialPage = restTimerPageIndex,
        pageCount = { horizontalPageTypes.size }
    )
    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }
    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull {
                if (viewModel.supersetIdByExerciseId.containsKey(it)) {
                    viewModel.supersetIdByExerciseId[it]
                } else {
                    it
                }
            }
            .distinct()
    }
    val setStateForPages = remember(state.nextState) {
        (state.nextState as? WorkoutState.Set) ?: viewModel.getFirstSetStateAfterCurrent()
    }
    val nextState = state.nextState

    LaunchedEffect(set.id) {
        if (horizontalPagerState.currentPage != restTimerPageIndex) {
            horizontalPagerState.scrollToPage(restTimerPageIndex)
        }
    }

    LaunchedEffect(horizontalPagerState.currentPage) {
        val isOnRestPlatesPage = restPlatesPageIndex >= 0 &&
            horizontalPagerState.currentPage == restPlatesPageIndex
        if (isOnRestPlatesPage) viewModel.setDimming(false) else viewModel.reEvaluateDimmingForCurrentState()

        if (horizontalPagerState.currentPage != exercisesPageIndex) {
            selectedExercise = exercise
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        CustomHorizontalPager(
            modifier = Modifier.fillMaxSize(),
            pagerState = horizontalPagerState,
            userScrollEnabled = !isEditModeState.value,
            pageOverlay = { pageIndex ->
                if (horizontalPageTypes[pageIndex] == RestHorizontalPage.REST_TIMER && nextState != null) {
                    ExerciseIndicator(
                        viewModel = viewModel,
                        modifier = Modifier.fillMaxSize()
                            .overlayVisualScale(WorkoutPagerLayoutTokens.ExerciseIndicatorVisualScale),
                        currentStateOverride = state,
                        selectedExerciseId = selectedExercise.id
                    )
                }
            }
        ) { pageIndex ->
            val pageModifier = Modifier
                .fillMaxSize()
                .padding(WorkoutPagerPageSafeAreaPadding)
                .clipToBounds()
            when (horizontalPageTypes[pageIndex]) {
                RestHorizontalPage.BUTTONS -> {
                    if (setStateForPages != null) {
                        Box(modifier = pageModifier) {
                            PageButtons(setStateForPages, viewModel, hapticsViewModel, navController, onBeforeGoHome)
                        }
                    }
                }

                RestHorizontalPage.PLATES -> {
                    if (setStateForPages != null && equipment != null) {
                        Box(modifier = pageModifier) {
                            PagePlates(setStateForPages, equipment, hapticsViewModel, viewModel)
                        }
                    }
                }

                RestHorizontalPage.REST_TIMER -> {
                    Box(modifier = pageModifier, contentAlignment = Alignment.Center) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(horizontal = WorkoutPagerLayoutTokens.OverlayContentHorizontalPadding)
                        ) {
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
                        }
                    }
                }

                RestHorizontalPage.PROGRESSION_COMPARISON -> {
                    if (setStateForPages != null) {
                        Box(modifier = pageModifier) {
                            PageProgressionComparison(
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = exercise,
                                state = setStateForPages,
                                isPageVisible = horizontalPagerState.currentPage == restProgressionPageIndex &&
                                    !horizontalPagerState.isScrollInProgress
                            )
                        }
                    }
                }

                RestHorizontalPage.NOTES -> {
                    Box(modifier = pageModifier) {
                        PageNotes(exercise.notes)
                    }
                }

                RestHorizontalPage.EXERCISES -> {
                    if (nextState != null) {
                        Box(modifier = pageModifier) {
                            PageExercises(
                                selectedExercise = selectedExercise,
                                workoutState = state,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                currentExercise = exercise,
                                exerciseOrSupersetIds = exerciseOrSupersetIds,
                                onExerciseSelected = { selectedExercise = it }
                            )
                        }
                    }
                }
            }
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

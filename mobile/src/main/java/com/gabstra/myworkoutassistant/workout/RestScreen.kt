package com.gabstra.myworkoutassistant.workout


import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutSetDisplayIdentifier
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.util.UUID

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
private fun RestTimerBlock(
    set: RestSet,
    state: WorkoutState.Rest,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    onTimerEnd: () -> Unit,
    skipConfirmAction: androidx.compose.runtime.MutableState<(() -> Unit)?>,
    restartTimerAction: androidx.compose.runtime.MutableState<(() -> Unit)?>,
    nextExerciseName: String,
    nextSetState: WorkoutState.Set?,
) {
    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.endTimer) }
    var amountToWait by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var currentSecondsFreeze by remember { mutableIntStateOf(0) }
    var amountToWaitFreeze by remember { mutableIntStateOf(0) }
    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val timerUiState by viewModel.workoutTimerService.timerUiState(set.id).collectAsState(initial = null)
    val isPaused by viewModel.isPaused

    val indicatorProgress = remember(currentSeconds, amountToWait, currentSecondsFreeze, amountToWaitFreeze, isTimerInEditMode) {
        if (isTimerInEditMode) {
            currentSecondsFreeze.toFloat() / amountToWaitFreeze.toFloat()
        } else {
            currentSeconds.toFloat() / amountToWait.toFloat()
        }
    }

    val updateInteractionTime = { lastInteractionTime = System.currentTimeMillis() }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            amountToWait = amountToWait - 5
            amountToWaitFreeze = amountToWait
            currentSeconds = newTimerValue
            currentSecondsFreeze = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        amountToWait = amountToWait + 5
        amountToWaitFreeze = amountToWait
        currentSeconds = newTimerValue
        currentSecondsFreeze = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

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
                    onTimerDisabled = {},
                )
            )
        }
    }

    fun unregisterRestTimer() {
        if (viewModel.workoutTimerService.isTimerRegistered(set.id)) {
            viewModel.workoutTimerService.unregisterTimer(set.id)
        }
    }

    skipConfirmAction.value = {
        unregisterRestTimer()
        state.currentSetData = currentSetData.copy(endTimer = currentSeconds)
        viewModel.closeCustomDialog()
        onTimerEnd()
    }
    restartTimerAction.value = {
        if (!isPaused && currentSeconds > 0) registerRestTimer()
    }

    LaunchedEffect(state.currentSetData) {
        val latest = state.currentSetData as? RestSetData ?: return@LaunchedEffect
        currentSetData = latest
        if (!isTimerInEditMode) {
            currentSeconds = latest.endTimer
            amountToWait = latest.startTimer
        }
        if (latest.endTimer == 5) viewModel.lightScreenUp()
    }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000)
        }
    }

    LaunchedEffect(set.id, isPaused, isTimerInEditMode) {
        if (state.startTime == null && currentSeconds <= 0) {
            currentSeconds = currentSetData.startTimer
            amountToWait = currentSetData.startTimer
            currentSetData = currentSetData.copy(endTimer = currentSeconds)
            state.currentSetData = currentSetData
        }
        if (isPaused || isTimerInEditMode || currentSeconds <= 0) {
            unregisterRestTimer()
        } else {
            state.currentSetData = currentSetData.copy(
                startTimer = amountToWait,
                endTimer = currentSeconds,
            )
            registerRestTimer()
        }
    }

    @Composable
    fun textComposable(seconds: Int, modifier: Modifier = Modifier, style: TextStyle = MaterialTheme.typography.bodySmall) {
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
                        isTimerInEditMode = !isTimerInEditMode
                        updateInteractionTime()
                        hapticsViewModel.doGentleVibration()
                    },
                    onDoubleClick = {}
                ),
                seconds = if (isTimerInEditMode) seconds else (timerUiState?.displaySeconds ?: seconds),
                style = style,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }
    }

    Row(modifier = Modifier.fillMaxWidth()) {
        AnimatedContent(
            modifier = Modifier.fillMaxSize(),
            targetState = isTimerInEditMode,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            },
            label = ""
        ) { updatedState ->
            if (updatedState) {
                ControlButtonsVertical(
                    modifier = Modifier.fillMaxSize().clickable(interactionSource = null, indication = null) { updateInteractionTime() },
                    onMinusTap = { onMinusClick() },
                    onMinusLongPress = { onMinusClick() },
                    onPlusTap = { onPlusClick() },
                    onPlusLongPress = { onPlusClick() },
                    isResetEnabled = currentSecondsFreeze != currentSetData.startTimer,
                    onCloseClick = { isTimerInEditMode = false },
                    onResetClick = {
                        currentSeconds = currentSetData.startTimer
                        amountToWait = currentSetData.startTimer
                        currentSecondsFreeze = currentSetData.startTimer
                        amountToWaitFreeze = currentSetData.startTimer
                        updateInteractionTime()
                        hapticsViewModel.doGentleVibration()
                    },
                    content = {
                        textComposable(seconds = currentSecondsFreeze, style = MaterialTheme.typography.displaySmall.copy(fontWeight = W700))
                    }
                )
            } else {
                Column(
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = "REST",
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onBackground,
                    )
                    textComposable(
                        seconds = currentSeconds,
                        style = MaterialTheme.typography.displayLarge.copy(fontWeight = W700)
                    )
                    androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(20.dp))
                    Text(
                        text = "UP NEXT",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        text = nextExerciseName,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp),
                        style = MaterialTheme.typography.headlineMedium.copy(fontWeight = W700),
                        color = MaterialTheme.colorScheme.onBackground,
                        textAlign = TextAlign.Center,
                        maxLines = 2,
                    )
                    if (nextSetState != null) {
                        androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(12.dp))
                        UpcomingSetPreview(
                            viewModel = viewModel,
                            setState = nextSetState,
                        )
                    }
                    androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(24.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        AppPrimaryButton(
                            text = "Skip",
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.openCustomDialog()
                                viewModel.lightScreenUp()
                            }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun UpcomingSetPreview(
    viewModel: WorkoutViewModel,
    setState: WorkoutState.Set,
) {
    val previewColor: Color = MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)
    val sideBadge = if (setState.isUnilateral) {
        buildUnilateralSideLabel(
            sideIndex = viewModel.getUnilateralSideIndex(setState),
            intraSetTotal = setState.intraSetTotal,
        )
    } else {
        null
    }

    SetTableRow(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp)
            .height(46.dp)
            .clip(MaterialTheme.shapes.extraLarge)
            .border(BorderStroke(1.dp, previewColor), MaterialTheme.shapes.extraLarge),
        viewModel = viewModel,
        setState = setState,
        setIdentifier = buildWorkoutSetDisplayIdentifier(
            viewModel = viewModel,
            exerciseId = setState.exerciseId,
            setState = setState,
        ),
        sideBadge = sideBadge,
        color = previewColor,
        weightTextColor = previewColor,
    )
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
fun RestScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
    onLeaveWorkout: () -> Unit = {},
    onRestTimerPageVisibilityChanged: (Boolean) -> Unit = {},
) {
    val set = state.set as RestSet
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()

    val skipConfirmAction = remember { mutableStateOf<(() -> Unit)?>(null) }
    val restartTimerAction = remember { mutableStateOf<(() -> Unit)?>(null) }

    val exerciseIdFromNext = when (val n = state.nextState) {
        is WorkoutState.Set -> n.exerciseId
        is WorkoutState.CalibrationLoadSelection -> n.exerciseId
        is WorkoutState.CalibrationRIRSelection -> n.exerciseId
        else -> state.exerciseId
    }
    val exercise = remember(exerciseIdFromNext, state.exerciseId, viewModel.exercisesById) {
        val eid = exerciseIdFromNext ?: state.exerciseId
        eid?.let(viewModel.exercisesById::get)
            ?: viewModel.exercisesById.values.firstOrNull()
    } ?: return
    val equipment = remember(exercise) {
        exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null
            && equipment.type == EquipmentType.BARBELL
            && equipment.name.contains("barbell", ignoreCase = true)
            && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }

    val pageTypes = remember(showPlatesPage) {
        mutableListOf<PageType>().apply {
            add(PageType.BUTTONS)
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.REST_TIMER)
            add(PageType.EXERCISES)
        }
    }

    val exercisesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.EXERCISES) }
    val restTimerPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.REST_TIMER) }
    val platesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.PLATES) }

    val pagerState = rememberPagerState(initialPage = restTimerPageIndex, pageCount = { pageTypes.size })
    var selectedExerciseId by remember { mutableStateOf<UUID?>(null) }
    val nextSetState = (state.nextState as? WorkoutState.Set)
        ?: viewModel.getFirstSetStateAfterCurrent()

    LaunchedEffect(set.id) {
        if (pagerState.currentPage != restTimerPageIndex) {
            pagerState.scrollToPage(restTimerPageIndex)
        }
    }

    LaunchedEffect(pagerState.currentPage) {
        onRestTimerPageVisibilityChanged(pagerState.currentPage == restTimerPageIndex)
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex
        if (isOnPlatesPage) viewModel.setDimming(false)
        else viewModel.reEvaluateDimmingForCurrentState()
        if (pagerState.currentPage != exercisesPageIndex) selectedExerciseId = null
    }

    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose { onRestTimerPageVisibilityChanged(true) }
    }

    CustomHorizontalPager(
        modifier = Modifier.fillMaxSize(),
        pagerState = pagerState,
        pageLabel = { index -> pageTypes[index].restPageLabel() },
    ) { pageIndex ->
            val pageType = pageTypes[pageIndex]

            when (pageType) {
                PageType.PLATES -> {
                    val setStateForPlates = nextSetState
                    if (setStateForPlates != null) {
                        PagePlates(setStateForPlates, equipment)
                    }
                }
                PageType.EXERCISE_DETAIL -> {}
                PageType.REST_TIMER -> {
                    RestTimerBlock(
                        set = set,
                        state = state,
                        viewModel = viewModel,
                        hapticsViewModel = hapticsViewModel,
                        onTimerEnd = onTimerEnd,
                        skipConfirmAction = skipConfirmAction,
                        restartTimerAction = restartTimerAction,
                        nextExerciseName = exercise.name,
                        nextSetState = nextSetState,
                    )
                }
                PageType.EXERCISES -> {
                    val setStateForExercises = nextSetState
                    if (setStateForExercises != null) {
                        PageExercises(
                            workoutState = setStateForExercises,
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel,
                            currentExercise = exercise,
                            onExerciseSelected = {
                                selectedExerciseId = it
                            }
                        )
                    }
                }

                PageType.BUTTONS -> {
                    val setStateForButtons = nextSetState
                    if (setStateForButtons != null) {
                        PageButtons(
                            setStateForButtons,
                            viewModel,
                            hapticsViewModel,
                            onLeaveWorkout = onLeaveWorkout
                        )
                    }
                }

                PageType.NOTES -> {}
                PageType.MUSCLES -> {}
                PageType.INFO -> {}
                PageType.MOVEMENT -> {}
            }
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip rest",
        message = "Move on to the next set now?",
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
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

private fun PageType.restPageLabel(): String = when (this) {
    PageType.BUTTONS -> "Workout controls"
    PageType.PLATES -> "Next barbell setup"
    PageType.REST_TIMER -> "Rest timer"
    PageType.EXERCISES -> "Workout steps"
    else -> name.lowercase().replaceFirstChar { it.uppercase() }
}



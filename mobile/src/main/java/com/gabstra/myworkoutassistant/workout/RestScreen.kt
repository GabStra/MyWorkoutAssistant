package com.gabstra.myworkoutassistant.workout


import android.os.SystemClock
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
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
) {
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            timerJob?.cancel()
        }
    }

    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var amountToWait by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }
    var currentSecondsFreeze by remember { mutableIntStateOf(0) }
    var amountToWaitFreeze by remember { mutableIntStateOf(0) }
    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var hasBeenStartedOnce by remember { mutableStateOf(false) }

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

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            var nextExecutionTime = ((SystemClock.elapsedRealtime() / 1000) + 1) * 1000
            while (currentSeconds > 0) {
                val waitTime = (nextExecutionTime - SystemClock.elapsedRealtime()).coerceAtLeast(0)
                delay(waitTime)
                currentSeconds -= 1
                if (currentSeconds == 5) viewModel.lightScreenUp()
                currentSetData = currentSetData.copy(endTimer = currentSeconds)
                nextExecutionTime += 1000
            }
            state.currentSetData = currentSetData.copy(endTimer = 0)
            hapticsViewModel.doHardVibration()
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

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000)
        }
    }

    LaunchedEffect(set.id) {
        delay(500)
        startTimerJob()
        if (state.startTime == null) {
            state.startTime = LocalDateTime.now()
        }
    }

    val isPaused by viewModel.isPaused
    LaunchedEffect(isPaused) {
        if (!hasBeenStartedOnce) return@LaunchedEffect
        if (isPaused) {
            timerJob?.takeIf { it.isActive }?.cancel()
        } else {
            if (timerJob?.isActive != true) startTimerJob()
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
                seconds = seconds,
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
                    content = {
                        textComposable(seconds = currentSecondsFreeze, style = MaterialTheme.typography.displaySmall.copy(fontWeight = W700))
                    }
                )
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(5.dp, alignment = Alignment.CenterVertically)) {
                    textComposable(
                        seconds = if (isTimerInEditMode) currentSecondsFreeze else currentSeconds,
                        style = MaterialTheme.typography.displayLarge.copy(fontWeight = W700)
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Button(
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.openCustomDialog()
                                viewModel.lightScreenUp()
                            }
                        ) {
                            Text(text = "Skip", textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
fun RestScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
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
    val exercise = remember(exerciseIdFromNext, state.exerciseId) {
        val eid = exerciseIdFromNext ?: state.exerciseId
        if (eid != null) viewModel.exercisesById[eid]!!
        else viewModel.exercisesById.values.firstOrNull() ?: throw IllegalStateException("No exercises available")
    }
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
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISES)
            add(PageType.BUTTONS)
        }
    }

    val exercisesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.EXERCISES) }
    val exerciseDetailPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.EXERCISES) }
    val platesPageIndex = remember(pageTypes) { pageTypes.indexOf(PageType.PLATES) }

    val pagerState = rememberPagerState(initialPage = exerciseDetailPageIndex, pageCount = { pageTypes.size })
    var selectedExerciseId by remember { mutableStateOf<UUID?>(null) }

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex
        if (isOnPlatesPage) viewModel.setDimming(false)
        else viewModel.reEvaluateDimmingForCurrentState()
        if (pagerState.currentPage != exercisesPageIndex) selectedExerciseId = null
    }

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        RestTimerBlock(
            set = set,
            state = state,
            viewModel = viewModel,
            hapticsViewModel = hapticsViewModel,
            onTimerEnd = onTimerEnd,
            skipConfirmAction = skipConfirmAction,
            restartTimerAction = restartTimerAction,
        )

        CustomHorizontalPager(
            modifier = Modifier
                .weight(2f)
                .fillMaxWidth(),
            pagerState = pagerState,
        ) { pageIndex ->
            val pageType = pageTypes[pageIndex]

            when (pageType) {
                PageType.PLATES -> {
                    val setStateForPlates = (state.nextState as? WorkoutState.Set)
                        ?: viewModel.getFirstSetStateAfterCurrent()
                    if (setStateForPlates != null) {
                        PagePlates(setStateForPlates, equipment)
                    }
                }
                PageType.EXERCISE_DETAIL -> {}
                PageType.EXERCISES -> {
                    val setStateForExercises = (state.nextState as? WorkoutState.Set)
                        ?: viewModel.getFirstSetStateAfterCurrent()
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
                    val setStateForButtons = (state.nextState as? WorkoutState.Set)
                        ?: viewModel.getFirstSetStateAfterCurrent()
                    if (setStateForButtons != null) {
                        PageButtons(
                            setStateForButtons,
                            viewModel,
                            hapticsViewModel
                        )
                    }
                }

                PageType.NOTES -> {}
                PageType.MUSCLES -> {}
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


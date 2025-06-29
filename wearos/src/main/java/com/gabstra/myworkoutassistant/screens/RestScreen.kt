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
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.composables.ControlButtonsVertical
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.horologist.compose.layout.fillMaxRectangle
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import java.time.LocalDateTime

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
) {
    val set = state.set as RestSet

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }
    var goBackJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            timerJob?.cancel()
            goBackJob?.cancel()
        }
    }

    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }

    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = remember(state.nextStateSets.first().exerciseId) {
        viewModel.exercisesById[state.nextStateSets.first().exerciseId]!!
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

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES).coerceAtLeast(0)
    }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    fun restartGoBack() {
        goBackJob?.cancel()
        goBackJob = scope.launch {
            delay(10000)
            if(pagerState.currentPage != exerciseDetailPageIndex) {
                pagerState.scrollToPage(exerciseDetailPageIndex)
            }
        }
    }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000) // Check every second
        }
    }

    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer - 5)
            currentSeconds = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer + 5)
        currentSeconds = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            // Calculate the next second boundary
            var nextExecutionTime = System.currentTimeMillis() + 1000
            nextExecutionTime = (nextExecutionTime / 1000) * 1000 // Round to next second boundary

            while (currentSeconds > 0) {
                val currentTime = System.currentTimeMillis()
                val waitTime = maxOf(0, nextExecutionTime - currentTime)

                delay(waitTime) // Wait until next second boundary

                currentSeconds -= 1

                currentSetData = currentSetData.copy(
                    endTimer = currentSeconds
                )

                nextExecutionTime += 1000 // Schedule next second
            }

            state.currentSetData = currentSetData.copy(
                endTimer = 0
            )
            goBackJob?.cancel()
            hapticsViewModel.doHardVibrationWithBeep()
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
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
        if (!hasBeenStartedOnce) {
            return@LaunchedEffect
        }

        if (isPaused) {
            timerJob?.takeIf { it.isActive }?.cancel()
        } else {
            if (timerJob?.isActive != true) {
                startTimerJob()
            }
        }
    }

    val textComposable = @Composable {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 50.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            ScalableText(
                modifier = Modifier
                    .fillMaxWidth()
                    .combinedClickable(
                        onClick = {
                        },
                        onLongClick = {
                            isTimerInEditMode = !isTimerInEditMode
                            updateInteractionTime()
                            hapticsViewModel.doGentleVibration()
                        },
                        onDoubleClick = {}
                    ),
                text = FormatTime(currentSeconds),
                style = MaterialTheme.typography.display2.copy(fontWeight = FontWeight.Bold),
            )
        }
    }

    AnimatedContent(
        targetState = isTimerInEditMode,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { updatedState ->
        if (updatedState) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .circleMask(15.dp),
                contentAlignment = Alignment.Center
            ) {
                ControlButtonsVertical(
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(
                            interactionSource = null,
                            indication = null
                        ) {
                            updateInteractionTime()
                        },
                    onMinusTap = { onMinusClick() },
                    onMinusLongPress = { onMinusClick() },
                    onPlusTap = { onPlusClick() },
                    onPlusLongPress = { onPlusClick() },
                    content = {
                        textComposable()
                    }
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .circleMask(15.dp)
                    .fillMaxRectangle(),
                contentAlignment = Alignment.Center
            ) {
                CustomHorizontalPager(
                    modifier = Modifier
                        .fillMaxSize()
                        .pointerInput(Unit) {
                            awaitPointerEventScope {
                                while (true) {
                                    val event = awaitPointerEvent()
                                    if (event.changes.any { it.pressed }) {
                                        restartGoBack()
                                    }
                                }
                            }
                        },
                    pagerState = pagerState,
                ) { pageIndex ->
                    val pageType = pageTypes[pageIndex]
                    when (pageType) {
                        PageType.PLATES -> PagePlates(state.nextStateSets.first(), equipment)
                        PageType.EXERCISE_DETAIL -> {}
                        PageType.EXERCISES -> {
                            Column(
                                verticalArrangement = Arrangement.spacedBy(5.dp),
                                horizontalAlignment = Alignment.CenterHorizontally
                            ) {
                                textComposable()
                                PageExercises(
                                    state.nextStateSets.first(),
                                    viewModel,
                                    hapticsViewModel,
                                    exercise
                                )
                            }
                        }
                        PageType.BUTTONS -> PageButtons(state.nextStateSets.first(), viewModel,hapticsViewModel)
                        PageType.NOTES -> TODO()
                    }
                }
            }
        }
    }


    Box(
        modifier = Modifier
            .fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            modifier = Modifier.fillMaxSize(),
            viewModel,
            state.nextStateSets.first()
        )

        hearthRateChart()
    }

    LaunchedEffect(Unit) {
        snapshotFlow { showSkipDialog }
            .drop(1)
            .collect { isDialogShown ->
                if (isDialogShown) {
                    viewModel.lightScreenPermanently()
                } else {
                    viewModel.restoreScreenDimmingState()
                }
            }
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip Rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            state.currentSetData = currentSetData.copy(
                endTimer = currentSeconds
            )
            hapticsViewModel.doGentleVibration()
            onTimerEnd()
            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.closeCustomDialog()
            startTimerJob()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
            startTimerJob()
        },
        holdTimeInMillis = 1000
    )
}

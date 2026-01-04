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
fun RestScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
) {
    val set = state.set as RestSet

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

    val indicatorProgress = remember(currentSeconds,amountToWait,currentSecondsFreeze,amountToWaitFreeze,isTimerInEditMode) {
        if(isTimerInEditMode){
            currentSecondsFreeze.toFloat() / amountToWaitFreeze.toFloat()
        }else{
            currentSeconds.toFloat() / amountToWait.toFloat()
        }
    }


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

    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PLATES)
    }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    var selectedExerciseId by remember { mutableStateOf<UUID?>(null) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }


    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        if(pagerState.currentPage != exercisesPageIndex){
            selectedExerciseId = null
        }
    }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            amountToWait = amountToWait - 5
            amountToWaitFreeze = amountToWait

            //currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer - 5)
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
        //currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer + 5)
        currentSeconds = newTimerValue
        currentSecondsFreeze = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            // Calculate the next second boundary
            var nextExecutionTime = ((SystemClock.elapsedRealtime() / 1000) + 1) * 1000 // round UP
            while (currentSeconds > 0) {
                val waitTime = (nextExecutionTime - SystemClock.elapsedRealtime()).coerceAtLeast(0)
                delay(waitTime)

                currentSeconds -= 1

                if(currentSeconds == 5){
                    viewModel.lightScreenUp()
                }

                currentSetData = currentSetData.copy(
                    endTimer = currentSeconds
                )

                nextExecutionTime += 1000 // Schedule next second
            }

            state.currentSetData = currentSetData.copy(
                endTimer = 0
            )
            hapticsViewModel.doHardVibration()
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 2000) {
                isTimerInEditMode = false
            }
            delay(1000) // Check every second
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

    @Composable
    fun textComposable(seconds:Int,modifier: Modifier = Modifier, style: TextStyle = MaterialTheme.typography.bodySmall){
        Row(
            modifier = modifier
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier
                    .combinedClickable(
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

    Column(
        modifier = Modifier
        .fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ){
        Row(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        )
        {
            AnimatedContent(
                modifier = Modifier.fillMaxSize(),
                targetState = isTimerInEditMode,
                transitionSpec = {
                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
                }, label = ""
            ) { updatedState ->
                if (updatedState) {
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
                            textComposable(seconds = currentSecondsFreeze, style = MaterialTheme.typography.displaySmall.copy(fontWeight = W700))
                        }
                    )
                } else {

                    Column(verticalArrangement = Arrangement.spacedBy(5.dp,alignment = Alignment.CenterVertically)) {
                        textComposable(
                            seconds = if(isTimerInEditMode) currentSecondsFreeze else currentSeconds,
                            style = MaterialTheme.typography.displayLarge.copy(fontWeight = W700)
                        )

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ){
                            Button(
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    viewModel.openCustomDialog()
                                    viewModel.lightScreenUp()
                                },
                            ) {
                                Text(
                                    text = "Skip",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                            }
                        }
                    }
                }
            }
        }

        CustomHorizontalPager(
            modifier = Modifier
                .weight(2f)
                .fillMaxWidth(),
            pagerState = pagerState,
        ) { pageIndex ->
            val pageType = pageTypes[pageIndex]

            when (pageType) {
                PageType.PLATES -> PagePlates(state.nextStateSets.first(), equipment)
                PageType.EXERCISE_DETAIL -> {}
                PageType.EXERCISES -> {
                    PageExercises(
                        state.nextStateSets.first(),
                        viewModel,
                        hapticsViewModel,
                        exercise,
                        onExerciseSelected = {
                            selectedExerciseId = it
                        }
                    )
                }

                PageType.BUTTONS ->  PageButtons(
                    state.nextStateSets.first(),
                    viewModel,
                    hapticsViewModel
                )

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


package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable;
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.ControlButtonsVertical
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.TimedDurationSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.VibrateTwiceAndBeep
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Job

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NextExerciseInfo(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
) {
    val exerciseIndex = viewModel.setsByExerciseId.keys.indexOf(state.exerciseId)
    val exerciseCount = viewModel.setsByExerciseId.keys.count()

    val exercise = viewModel.exercisesById[state.exerciseId]!!
    val exerciseSets = exercise.sets.filter { it !is RestSet }

    val setIndex = exerciseSets.indexOf(state.set)

    var marqueeEnabled by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxHeight()
            .width(190.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        val text = if(exerciseSets.count() != 1) {
            "${exerciseIndex + 1}/${exerciseCount} - ${setIndex + 1}/${exerciseSets.count()}"
        } else {
            "${exerciseIndex + 1}/${exerciseCount}"
        }

        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Next: $text",
            style = MaterialTheme.typography.title3.copy(fontSize = MaterialTheme.typography.title3.fontSize * 0.625f),
            textAlign = TextAlign.Center
        )

        Box(modifier = Modifier
            .width(140.dp)
            .clickable { marqueeEnabled = !marqueeEnabled }
            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = exercise.name,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.title3,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }

        when (state.set) {
            is WeightSet -> WeightSetDataViewerMinimal(
                state.currentSetData as WeightSetData
            )

            is BodyWeightSet -> BodyWeightSetDataViewerMinimal(
                state.currentSetData as BodyWeightSetData
            )

            is TimedDurationSet -> TimedDurationSetDataViewerMinimal(
                state.currentSetData as TimedDurationSetData
            )

            is EnduranceSet -> EnduranceSetDataViewerMinimal(
                state.currentSetData as EnduranceSetData
            )

            is RestSet -> {
                throw RuntimeException("RestSet should not be here")
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
) {
    val set = state.set as RestSet

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }

    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }
    var showSkipDialog by remember { mutableStateOf(false) }

    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
    val nextWorkoutStateSet = if (nextWorkoutState is WorkoutState.Set) {
        nextWorkoutState as WorkoutState.Set
    } else {
        null
    }
    
    val pagerState = rememberPagerState(
        initialPage = 0,
        pageCount = {
            3
        })

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

    val progress = currentSeconds.toFloat() / currentSetData.startTimer.toFloat()

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 5000) {
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
            VibrateGentle(context)
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer + 5)
        currentSeconds = newTimerValue
        VibrateGentle(context)
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (currentSeconds > 0) {
                delay(1000) // Update every sec.
                currentSeconds -= 1

                currentSetData = currentSetData.copy(
                    endTimer = currentSeconds
                )
            }

            state.currentSetData = currentSetData.copy(
                endTimer = 0
            )
            VibrateTwiceAndBeep(context)
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(set.id) {
        delay(500)
        startTimerJob()
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
                .padding(horizontal = 20.dp),
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
                            VibrateGentle(context)
                        },
                        onDoubleClick = {}
                    ),
                text = FormatTime(currentSeconds),
                style = MaterialTheme.typography.display2,
            )
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier
            .fillMaxSize()
            .padding(25.dp)
    ) {
        if (isTimerInEditMode && nextWorkoutStateSet!=null) {
            ControlButtonsVertical(
                modifier = Modifier
                    .wrapContentSize()
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
        } else {
            if (nextWorkoutStateSet != null) {
                Column(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    textComposable()
                    val nextExercise = viewModel.exercisesById[nextWorkoutStateSet.exerciseId]!!
                    CustomHorizontalPager(
                        modifier = Modifier
                            .fillMaxSize(),
                        pagerState = pagerState,
                        userScrollEnabled = true
                    ) { page ->
                        when (page) {
                            0 -> {
                                NextExerciseInfo(viewModel, nextWorkoutStateSet)
                            }
                            1 -> {
                                Box {
                                    Text(
                                        modifier = Modifier.fillMaxSize(),
                                        text = "Notes",
                                        style = MaterialTheme.typography.body1,
                                        textAlign = TextAlign.Center
                                    )
                                    val scrollState = rememberScrollState()
                                    val notes = nextExercise.notes
                                    Box(
                                        modifier = Modifier.fillMaxSize()
                                    ) {
                                        Row {
                                            Column(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(0.dp, 25.dp, 0.dp, 25.dp)
                                                    .verticalScroll(scrollState)
                                            ) {
                                                Text(
                                                    text = notes.ifEmpty { "NOT AVAILABLE" },
                                                    modifier = Modifier.fillMaxWidth(),
                                                    style = MaterialTheme.typography.body1,
                                                    textAlign = TextAlign.Center
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                            2 ->
                                Box(
                                    modifier = Modifier.fillMaxSize()
                                ) {
                                    ButtonWithText(
                                        text = "Skip",
                                        onClick = {
                                            if (timerJob?.isActive != true) return@ButtonWithText

                                            VibrateGentle(context)
                                            timerJob?.cancel()
                                            showSkipDialog = true
                                        },
                                    )
                                }
                        }
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
        CircularProgressIndicator(
            progress = progress,
            modifier = Modifier.fillMaxSize(),
            startAngle = -60f,
            endAngle = 65f,
            strokeWidth = 4.dp,
            indicatorColor = MaterialTheme.colors.primary,
            trackColor = MaterialTheme.colors.background
        )

        hearthRateChart()
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            state.currentSetData = currentSetData.copy(
                endTimer =  currentSeconds
            )
            onTimerEnd()
            showSkipDialog = false
        },
        handleNoClick = {
            VibrateGentle(context)
            showSkipDialog = false
            startTimerJob()
        },
        handleOnAutomaticClose = {},
        holdTimeInMillis = 1000
    )
}


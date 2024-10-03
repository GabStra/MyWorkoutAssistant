package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewerMinimal
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
import com.gabstra.myworkoutassistant.data.VibrateAndBeep
import com.gabstra.myworkoutassistant.data.VibrateOnce
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
    val exerciseIndex = viewModel.setsByExerciseId.keys.indexOf(state.execiseId)
    val exerciseCount = viewModel.setsByExerciseId.keys.count()

    val exercise = viewModel.exercisesById[state.execiseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it === state.set }

    var marqueeEnabled by remember { mutableStateOf(false) }


    Column(
        modifier = Modifier
            .size(160.dp, 190.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
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

        if (exerciseSets.count() != 1) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "Exercise: ${exerciseIndex + 1}/${exerciseCount}",
                    style = MaterialTheme.typography.caption2
                )
                Spacer(modifier = Modifier.width(5.dp))
                Text(
                    text = "Set: ${setIndex + 1}/${exerciseSets.count()}",
                    style = MaterialTheme.typography.caption2
                )
            }
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

    var currentSetData by remember { mutableStateOf(state.currentSetData as RestSetData) }
    var isTimerInEditMode by remember { mutableStateOf(false) }
    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }

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

    var currentSeconds by remember(state.set.id) { mutableIntStateOf(currentSetData.startTimer) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }

    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    var showSkipDialog by remember { mutableStateOf(false) }

    val context = LocalContext.current

    val pagerState = rememberPagerState(
        initialPage = 0,
        pageCount = {
            2
        })

    fun onMinusClick() {
        if (currentSetData.startTimer > 5) {
            val newTimerValue = currentSetData.startTimer - 5
            currentSetData = currentSetData.copy(startTimer = newTimerValue)
            currentSeconds = newTimerValue
            VibrateOnce(context)
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSetData.startTimer + 5
        currentSetData = currentSetData.copy(startTimer = newTimerValue)
        currentSeconds = newTimerValue
        VibrateOnce(context)
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

                if (currentSeconds in 1..3) {
                    VibrateAndBeep(context)
                }
            }

            currentSetData = currentSetData.copy(
                endTimer = 0
            )

            state.currentSetData = currentSetData
            VibrateTwiceAndBeep(context)
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
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

    LaunchedEffect(set) {
        delay(500)
        startTimerJob()
    }

    val progress = (currentSeconds.toFloat() / (currentSetData.startTimer))

    val textComposable = @Composable {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
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
                            VibrateOnce(context)
                        },
                        onDoubleClick = {
                            if(timerJob?.isActive == true){
                                VibrateOnce(context)
                                timerJob?.cancel()
                                showSkipDialog = true
                            }
                        }
                    ),
                text = FormatTime(currentSeconds),
                style = MaterialTheme.typography.display2,
            )
        }
    }

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.fillMaxSize()
    ) {
        if (isTimerInEditMode) {
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
            textComposable()
            val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
            val nextWorkoutStateSet = if (nextWorkoutState is WorkoutState.Set) {
                nextWorkoutState as WorkoutState.Set
            } else {
                null
            }

            if (nextWorkoutStateSet != null) {
                val nextExercise = viewModel.exercisesById[nextWorkoutStateSet.execiseId]!!
                CustomHorizontalPager(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(5.dp, 70.dp, 5.dp, 0.dp),
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
                                                .padding(20.dp, 25.dp, 20.dp, 25.dp)
                                                .verticalScroll(scrollState)
                                        ) {
                                            Text(
                                                text = notes.ifEmpty { "NOT AVAILABLE" },
                                                modifier = Modifier.fillMaxWidth(),
                                                style = MaterialTheme.typography.body1,
                                                textAlign = TextAlign.Start
                                            )
                                        }
                                    }
                                }
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
            endAngle = 70f,
            strokeWidth = 4.dp,
            indicatorColor = MaterialTheme.colors.primary,
            trackColor = Color.DarkGray
        )

        hearthRateChart()
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateOnce(context)
            currentSetData = currentSetData.copy(
                endTimer =  currentSeconds
            )
            onTimerEnd()
            showSkipDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showSkipDialog = false
            startTimerJob()
        },
        handleOnAutomaticClose = {},
        holdTimeInMillis = 1000
    )
}


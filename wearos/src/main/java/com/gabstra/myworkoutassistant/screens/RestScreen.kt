package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.ControlButtonsVertical
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.ExerciseInfo
import com.gabstra.myworkoutassistant.composable.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDateTime
import java.util.UUID


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
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()

    val pagerState = rememberPagerState(
        initialPage = 0,
        pageCount = {
            2
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
            VibrateTwice(context)
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(set.id) {
        delay(500)
        startTimerJob()

        if(state.startTime == null){
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
                .padding(horizontal = 55.dp),
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(5.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        if (isTimerInEditMode) {
            ControlButtonsVertical(
                modifier = Modifier
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
        } else{
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                textComposable()
                ExerciseInfo(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 10.dp),
                    viewModel,
                    state.nextStateSets
                )
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
            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            VibrateGentle(context)
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


@Preview(
    device = Devices.WEAR_OS_LARGE_ROUND,
    backgroundColor = 0xFF000000,
    showBackground = true
)
@Composable
fun RestScreenPreview() {
    val viewModel = remember { FakeAppViewModel() }
    val restState = viewModel.createFakeRestState()
    
    RestScreen(
        viewModel = viewModel,
        state = restState,
        hearthRateChart = { },
        onTimerEnd = { }
    )
}

private val upcomingExerciseId = UUID.randomUUID()
private val upcomingSetId = UUID.randomUUID()

// Fake classes for preview
private class FakeAppViewModel : AppViewModel() {
    fun createFakeRestState(): WorkoutState.Rest {
        val restSet = RestSet(
            id = UUID.randomUUID(),
            timeInSeconds =90,
            isRestPause = false
        )
        val restSetData = RestSetData(startTimer = 60, endTimer = 60)

        return WorkoutState.Rest(
            set = restSet,
            currentSetData = restSetData,
            nextStateSets = listOf(
                WorkoutState.Set(
                    set = WeightSet(
                        id = upcomingSetId,
                        weight = 100.0,
                        reps = 10
                    ),
                    exerciseId = upcomingExerciseId,
                    startTime = null,
                    currentSetData = WeightSetData(
                        actualWeight = 100.0,
                        actualReps = 10,
                        volume = 1000.0
                    ),
                    previousSetData = null,
                    plateChangeResult = null,
                    order = 1u,
                    hasNoHistory = true,
                    skipped = false,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    currentBodyWeight = 65.0,
                    streak = 1,
                    isDeloading = false,
                    lastSessionVolume = 1000.0,
                    expectedProgress = null
                )
            ),
            order = 1u,
            exerciseId = UUID.randomUUID(),
            startTime = LocalDateTime.now()
        )
    }

    override val allWorkoutStates: MutableList<WorkoutState> = mutableListOf(
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = UUID.randomUUID(),
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = UUID.randomUUID(),
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = UUID.randomUUID(),
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        )
    )

    override val exercisesById = mutableMapOf<UUID, Exercise>().apply {
        put(upcomingExerciseId, Exercise(
            id = upcomingExerciseId,
            name = "Bench Press",
            equipmentId = null,
            notes = "Sample exercise",
            exerciseType = ExerciseType.WEIGHT,
            sets = listOf(
                WeightSet(
                    id = upcomingSetId,
                    weight = 100.0,
                    reps = 10
                ),
                WeightSet(
                    id = UUID.randomUUID(),
                    weight = 100.0,
                    reps = 10
                )
            ),
            enabled = true,
            doNotStoreHistory = false,
            minLoadPercent = 0.6,
            maxLoadPercent = .8,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            bodyWeightPercentage = null
        )
        )
    }
    
    override val isPaused = mutableStateOf(false)
    override val isCustomDialogOpen = MutableStateFlow(false)
}

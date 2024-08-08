package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable;
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.TimedDurationSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.PlayBeep
import com.gabstra.myworkoutassistant.data.PlayNBeeps
import com.gabstra.myworkoutassistant.data.VibrateAndBeep
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.VibrateShortImpulseAndBeep
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Job

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NextExerciseInfo(
    viewModel: AppViewModel,
    state: WorkoutState.Set
){
    val exerciseIndex = viewModel.setsByExercise.keys.indexOf(state.parentExercise)
    val exerciseCount = viewModel.setsByExercise.keys.count()

    val exerciseSets = state.parentExercise.sets

    val setIndex =  exerciseSets.indexOfFirst { it === state.set }

    Column(
        modifier = Modifier
            .size(160.dp, 190.dp)
            .padding(top = 70.dp),
        verticalArrangement = Arrangement.Top,
        horizontalAlignment = Alignment.CenterHorizontally,
    ){
        Column(
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
        ){
            Text(
                    modifier = Modifier
                        .basicMarquee(iterations = Int.MAX_VALUE),
                    text = state.parentExercise.name,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                )
            Spacer(modifier = Modifier.height(5.dp))
            if(exerciseSets.count()!=1){
                Text( text="${exerciseIndex+1}/${exerciseCount} - ${setIndex+1}/${exerciseSets.count()}",style = MaterialTheme.typography.body1)
            }
            Spacer(modifier = Modifier.height(5.dp))
            when(state.set){
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
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit
) {
    val totalSeconds = state.restTimeInSec;
    var currentMillis by remember { mutableIntStateOf(totalSeconds * 1000) }

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

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {

            while (currentMillis > 0) {
                delay(1000) // Update every sec.
                currentMillis -= 1000

                if (currentMillis in 1..3000)
                    VibrateAndBeep(context)
            }

            VibrateShortImpulseAndBeep(context)
            viewModel.goToNextState()
        }


        if(!hasBeenStartedOnce){
            hasBeenStartedOnce = true
        }
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(isPaused) {
        if(!hasBeenStartedOnce){
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

    LaunchedEffect(totalSeconds) {
        delay(500)
        startTimerJob()
    }

    val progress = (currentMillis.toFloat() / (totalSeconds * 1000))

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp),
        contentAlignment = Alignment.TopCenter
    ) {
        val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
        val nextWorkoutStateSet = nextWorkoutState as WorkoutState.Set
        CustomHorizontalPager(
            modifier = Modifier
                .fillMaxSize(),
            pagerState = pagerState,
            userScrollEnabled = true
        ){ page ->
            when(page){
                0 -> {
                    NextExerciseInfo(viewModel,nextWorkoutStateSet)
                }
                1 -> {
                    Box(modifier = Modifier
                        .fillMaxSize()
                        .padding(5.dp, 60.dp, 5.dp, 0.dp)){
                        Text(
                            modifier = Modifier.fillMaxSize(),
                            text = "Notes",
                            style = MaterialTheme.typography.body1,
                            textAlign = TextAlign.Center
                        )
                        val scrollState = rememberScrollState()
                        val notes = nextWorkoutStateSet.parentExercise.notes
                        Box(
                            modifier = Modifier.fillMaxSize()
                        ) {
                            Row{
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(20.dp, 25.dp, 20.dp, 25.dp)
                                        .verticalScroll(scrollState)
                                ) {
                                    Text(
                                        text = notes.ifEmpty { "No notes available" },
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

        Box(
            modifier = Modifier
                .size(160.dp, 90.dp)
                .padding(0.dp, 20.dp),
            contentAlignment = Alignment.TopCenter
        ){
            Text(
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClick = {
                        VibrateOnce(context)
                        timerJob?.cancel()
                        showSkipDialog = true
                    }
                ),
                text = FormatTime(currentMillis / 1000),
                style = MaterialTheme.typography.display3,
            )
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
            startAngle = -70f,
            endAngle = 70f,
            strokeWidth = 4.dp,
            indicatorColor = MaterialTheme.colors.primary
        )

        hearthRateChart()
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.goToNextState()
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


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
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable;
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
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
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewer
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.EnduranceSetDataViewerMinimal
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.composable.LoadingText
import com.gabstra.myworkoutassistant.composable.TimedDurationSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewer
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewerMinimal
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.VibrateShortImpulse
import com.gabstra.myworkoutassistant.data.getFirstExercise
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet

import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NextExerciseInfo(
    viewModel: AppViewModel,
    state: WorkoutState.Set
){
    val workout by viewModel.selectedWorkout
    val sets = remember(state){
        getFirstExercise(state.parents).sets
    }
    val setIndex = remember(state) {
        sets.indexOfFirst { it === state.set }
    }

    Column(
        modifier = Modifier
            .size(160.dp, 190.dp)
            .padding(top = 75.dp),
        verticalArrangement = Arrangement.Top,
        horizontalAlignment = Alignment.CenterHorizontally,
    ){
        Column(
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
        ){
            Text(text = "Up Next",style = MaterialTheme.typography.body1)
            Spacer(modifier = Modifier.height(5.dp))
            Text(
                    modifier = Modifier
                        .basicMarquee(),
                    text = state.exerciseName,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                )
            if(sets.count()!=1){
                Text( text="${setIndex+1}/${sets.count()}",style = MaterialTheme.typography.body1)
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

           //TODO Show info based on set type
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Rest
) {
    val totalSeconds = state.restTimeInSec;
    var currentMillis by remember { mutableIntStateOf(totalSeconds * 1000) }
    val context = LocalContext.current

    LaunchedEffect(key1 = totalSeconds) {
        delay(500)
        while (currentMillis > 0) {
            delay(1000) // Update every 18 milliseconds.
            currentMillis -= 1000
        }

        VibrateShortImpulse(context);
        viewModel.goToNextState()
    }

    val progress = (currentMillis.toFloat() / (totalSeconds * 1000))

    Box(
        modifier = Modifier
            .fillMaxSize()
            .combinedClickable(
                onClick = {},
                onLongClick = {
                    VibrateOnce(context);
                    viewModel.goToNextState()
                }
            ),
        contentAlignment = Alignment.TopCenter
    ) {
        CircularProgressIndicator(
            progress = progress,
            modifier = Modifier.fillMaxSize(),
            startAngle = 290f,
            endAngle = 250f,
            strokeWidth = 4.dp,
            indicatorColor = MaterialTheme.colors.primary
        )

        Box(
            modifier = Modifier
                .size(160.dp, 90.dp)
                .padding(0.dp, 30.dp),
            contentAlignment = Alignment.TopCenter
        ){
            Text(
                text = FormatTime(currentMillis / 1000),
                style = MaterialTheme.typography.display3,
            )
        }

        val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
        when(nextWorkoutState){
            is WorkoutState.Set -> {
                val state = nextWorkoutState as WorkoutState.Set
                NextExerciseInfo(viewModel,state)
            }
            else -> {}
        }
    }
}


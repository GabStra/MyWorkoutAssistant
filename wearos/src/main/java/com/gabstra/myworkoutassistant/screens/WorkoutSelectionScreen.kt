package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.SendToMobile
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import  androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.Icon
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.shared.Workout
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Calendar

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutListItem(workout: Workout, onItemClick: () -> Unit) {
    Chip(
        colors = ChipDefaults.chipColors(backgroundColor = Color.DarkGray),
        label = {
            Text(
                text = workout.name,
                modifier = Modifier.basicMarquee(initialDelayMillis = 5000),
                style = MaterialTheme.typography.body2
            )
        },
        secondaryLabel = {
            Text(
                text = workout.description,
                modifier = Modifier.basicMarquee(initialDelayMillis = 5000),
                style = MaterialTheme.typography.caption3,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        },
        onClick = { onItemClick() },
        modifier = Modifier
            .size(150.dp, 50.dp)
            .padding(2.dp),
    )
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun MissingAgeSettingMessage(
    dataClient: DataClient,
    viewModel: AppViewModel,
    appHelper: WearDataLayerAppHelper,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "Please set your age in the app on your phone",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.caption1,
        )
        Spacer(modifier = Modifier.height(10.dp))
        Button(
            onClick = {
                scope.launch {
                    openSettingsOnPhoneApp(context, dataClient, viewModel.phoneNode!!, appHelper)
                }
            }) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.SendToMobile,
                contentDescription = "SendToMobile",
                modifier = Modifier.size(30.dp),
            )
        }
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun WorkoutSelectionScreen(dataClient: DataClient, navController: NavController, viewModel: AppViewModel, appHelper: WearDataLayerAppHelper) {
    val scalingLazyListState: ScalingLazyListState = rememberScalingLazyListState()
    val workouts by viewModel.workouts

    val currentYear = remember {  Calendar.getInstance().get(Calendar.YEAR) }

    var waitTimeInSec by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    val userAge by viewModel.userAge
    val phoneNode = viewModel.phoneNode

    LaunchedEffect(Unit){
        scope.launch {
            while (true) {
                delay(1000) // Update every sec.
                waitTimeInSec += 1
                if(waitTimeInSec >= 5) break
            }
        }
    }

    Scaffold(
        positionIndicator = {
            PositionIndicator(
                scalingLazyListState = scalingLazyListState
            )
        }
    ){
        Text(
            modifier = Modifier.padding(horizontal = 50.dp, vertical = 10.dp),
            text = "My Workout Assistant",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.caption1,
        )

        ScalingLazyColumn(
            modifier = Modifier.padding(10.dp, 55.dp,10.dp,0.dp),
            state = scalingLazyListState,
        ) {
            if(!viewModel.isPhoneConnectedAndHasApp && waitTimeInSec == 5){
                item {
                    Text(
                        text = "Please install the app on your phone",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                    )
                }
            }else{
                if(userAge == currentYear && phoneNode != null){
                    item {
                        MissingAgeSettingMessage(dataClient, viewModel, appHelper)
                    }
                }else{
                    items(workouts) { workout ->
                        WorkoutListItem(workout) {
                            viewModel.setWorkout(workout)
                            navController.navigate(Screen.WorkoutDetail.route)
                        }
                    }
                }
            }
        }
    }
}
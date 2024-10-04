package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.SendToMobile
import androidx.compose.runtime.Composable
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
import com.gabstra.myworkoutassistant.composable.KeepOn
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.shared.Workout
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import com.gabstra.myworkoutassistant.shared.getVersionName
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
                modifier = Modifier.basicMarquee(
                    iterations = Int.MAX_VALUE,
                    initialDelayMillis = 5000
                ),
                style = MaterialTheme.typography.body2
            )
        },
        secondaryLabel = {
            Text(
                text = workout.description,
                modifier = Modifier.basicMarquee(
                    iterations = Int.MAX_VALUE,
                    initialDelayMillis = 5000
                ),
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

@Composable
fun MissingAppMessage(titleComposable: @Composable () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier.fillMaxSize()
    ) {
        titleComposable()
        Spacer(modifier = Modifier.height(15.dp))
        Text(
            modifier = Modifier.padding(vertical = 10.dp),
            text = "Please install the app on your phone",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.caption1,
        )
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun MissingAgeSettingMessage(
    dataClient: DataClient,
    viewModel: AppViewModel,
    appHelper: WearDataLayerAppHelper,
    titleComposable: @Composable () -> Unit
) {
    val context = LocalContext.current


    val scope = rememberCoroutineScope()

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier.fillMaxSize()
    ) {
        titleComposable()
        Spacer(modifier = Modifier.height(15.dp))
        Text(
            text = "Input your age on the phone",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.caption1,
        )
        Spacer(modifier = Modifier.height(15.dp))
        Button(
            onClick = {
                VibrateOnce(context)
                scope.launch {
                    openSettingsOnPhoneApp(context, dataClient, viewModel.phoneNode!!, appHelper)
                }
            }) {
            Icon(
                imageVector = Icons.AutoMirrored.Default.SendToMobile,
                contentDescription = "SendToMobile",
                modifier = Modifier.size(30.dp)
            )
        }
    }
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutSelectionScreen(
    dataClient: DataClient,
    navController: NavController,
    viewModel: AppViewModel,
    appHelper: WearDataLayerAppHelper
) {
    val scalingLazyListState: ScalingLazyListState = rememberScalingLazyListState(initialCenterItemIndex = 0)
    val workouts by viewModel.workouts.collectAsState()

    val sortedWorkouts = workouts.sortedBy { it.order }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }

    val userAge by viewModel.userAge

    val context = LocalContext.current
    val versionName = getVersionName(context);

    val titleComposable = @Composable {
        Text(
            modifier = Modifier
                .padding(0.dp, 0.dp, 0.dp, 10.dp)
                .combinedClickable(
                    onClick = {},
                    onLongClick = {
                        Toast
                            .makeText(
                                context,
                                "Build version code: $versionName",
                                Toast.LENGTH_LONG
                            )
                            .show()
                    }
                ),
            text = "My Workout Assistant",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.caption1,
        )
    }

    if (userAge == currentYear) {
        if(viewModel.isPhoneConnectedAndHasApp){
            MissingAgeSettingMessage(dataClient, viewModel, appHelper, titleComposable)
        }else{
            MissingAppMessage(titleComposable)
        }
        return
    }

    Scaffold(
        positionIndicator = {
            PositionIndicator(
                scalingLazyListState = scalingLazyListState
            )
        }
    ) {
        ScalingLazyColumn(
            modifier = Modifier.padding(10.dp, vertical = 0.dp),
            state = scalingLazyListState,
        ) {
            item {
                titleComposable()
            }

            if (sortedWorkouts.isEmpty()) {
                item {
                    Text(
                        modifier = Modifier.padding(vertical = 10.dp),
                        text = "No workouts available",
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                    )
                }
            } else {
                items(sortedWorkouts) { workout ->
                    WorkoutListItem(workout) {
                        navController.navigate(Screen.WorkoutDetail.route)
                        viewModel.setWorkout(workout)
                    }
                }
            }
        }
    }
}
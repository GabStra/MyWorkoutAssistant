package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.MarqueeAnimationMode
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListAnchorType
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import  androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Button
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.VibrateHard
import com.gabstra.myworkoutassistant.data.VibrateTwice
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.shared.Workout
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import com.gabstra.myworkoutassistant.shared.getVersionName
import kotlinx.coroutines.launch
import java.util.Calendar

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutListItem(workout: Workout, onItemClick: () -> Unit) {
    Chip(
        colors = ChipDefaults.chipColors(backgroundColor = MaterialTheme.colors.background),
        label = {
            Text(
                text = workout.name,
                style = MaterialTheme.typography.body2,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        },
        secondaryLabel = {
            Text(
                text = workout.description,
                style = MaterialTheme.typography.caption3,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        },
        onClick = { onItemClick() },
        modifier = Modifier
            .fillMaxWidth()
            .height(50.dp)
            .padding(2.dp),
    )
}

@Composable
fun MissingAppMessage(titleComposable: @Composable () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier.fillMaxSize().padding(10.dp)
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

    Box(modifier = Modifier.fillMaxSize().padding(10.dp),contentAlignment = Alignment.Center){
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(15.dp),
        ) {
            titleComposable()
            Text(
                text = "Input your age on the phone",
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
            )
            Box(modifier = Modifier.padding(horizontal = 15.dp)){
                ButtonWithText(
                    text = "Open mobile app",
                    onClick = {
                        VibrateGentle(context)
                        scope.launch {
                            openSettingsOnPhoneApp(context, dataClient, viewModel.phoneNode!!, appHelper)
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background,
                )
            }
        }
    }

}

@Composable
fun rememberNotificationPermissionState(): State<Boolean> {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    // Create mutable state to track permission status
    val permissionState = remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        )
    }

    // Update permission state when lifecycle resumes
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                permissionState.value = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    return permissionState
}

@Composable
fun NotificationPermissionHandler(content: @Composable (Boolean, () -> Unit) -> Unit) {
    val context = LocalContext.current
    val permissionState = rememberNotificationPermissionState().value

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        // This will be called when the user responds to the permission dialog
        // The state will be updated on the next lifecycle resume
    }

    val requestPermission = {
        permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    content(permissionState, requestPermission)
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutSelectionScreen(
    dataClient: DataClient,
    navController: NavController,
    viewModel: AppViewModel,
    appHelper: WearDataLayerAppHelper
) {
    val scalingLazyListState: ScalingLazyListState = rememberScalingLazyListState()
    val workouts by viewModel.workouts.collectAsState()

    val sortedWorkouts = workouts.sortedBy { it.order }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }

    val userAge by viewModel.userAge

    val context = LocalContext.current
    val versionName = getVersionName(context);

    var showClearData by remember { mutableStateOf(false) }

    val titleComposable = @Composable {
        Column(horizontalAlignment = Alignment.CenterHorizontally){
            Text(
                modifier = Modifier
                    .padding(0.dp, 0.dp, 0.dp, 10.dp)
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            VibrateHard(context)
                            Toast
                                .makeText(
                                    context,
                                    "Build version code: $versionName",
                                    Toast.LENGTH_LONG
                                )
                                .show()
                        },
                        onDoubleClick = {
                            showClearData = true
                            VibrateTwice(context)
                        }
                    ),
                text = "My Workout Assistant",
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
            )
            NotificationPermissionHandler { hasPermission, requestPermission ->
                if (!hasPermission) {
                    ButtonWithText(text = "Request notification permission", onClick = {
                        VibrateGentle(context)
                        requestPermission()
                    })
                }
            }
        }
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
            modifier = Modifier.padding(10.dp),
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
                items(
                    items = sortedWorkouts,
                    key = { workout -> workout.id }
                ) { workout ->
                    WorkoutListItem(workout) {
                        VibrateGentle(context)
                        navController.navigate(Screen.WorkoutDetail.route)
                        viewModel.setWorkout(workout)
                    }
                }
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showClearData,
        title = "Clear Data",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.resetAll()
            Toast
                .makeText(
                    context,
                    "Data reset",
                    Toast.LENGTH_SHORT
                )
                .show()
            showClearData = false
        },
        handleNoClick = {
            showClearData = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showClearData = false
        },
        holdTimeInMillis = 1000
    )
}
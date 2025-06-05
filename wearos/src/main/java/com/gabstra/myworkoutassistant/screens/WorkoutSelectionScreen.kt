package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.getVersionName
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
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
            .height(50.dp),
    )
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
    hapticsViewModel: HapticsViewModel,
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
    val scope = rememberCoroutineScope()

    Scaffold(
        positionIndicator = {
            PositionIndicator(
                scalingLazyListState = scalingLazyListState
            )
        }
    ) {
        ScalingLazyColumn(
            modifier = Modifier.padding(10.dp).fillMaxWidth(),
            state = scalingLazyListState,
        ) {
            item {
                Text(
                    modifier = Modifier
                        .padding(vertical = 10.dp)
                        .combinedClickable(
                            onClick = {},
                            onLongClick = {
                                hapticsViewModel.doHardVibration()
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
                                hapticsViewModel.doHardVibrationTwice()
                            }
                        ),
                    text = "My Workout Assistant",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3.copy(fontWeight = FontWeight.Bold),
                )
            }

            item{
                NotificationPermissionHandler { hasPermission, requestPermission ->
                    if (!hasPermission) {
                        ButtonWithText(text = "Request notification permission", onClick = {
                            hapticsViewModel.doGentleVibration()
                            requestPermission()
                        })
                    }
                }
            }

            if (userAge == currentYear) {
                if(viewModel.isPhoneConnectedAndHasApp){
                    item{
                        Text(
                            modifier = Modifier.padding(vertical = 10.dp),
                            text = "Input your age on the phone",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.caption1,
                        )
                    }
                    item{
                        ButtonWithText(
                            text = "Open mobile app",
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                scope.launch {
                                    openSettingsOnPhoneApp(context, dataClient, viewModel.phoneNode!!, appHelper)
                                }
                            },
                            backgroundColor = MaterialTheme.colors.background,
                        )
                    }
                }else{
                    item{
                        Text(
                            modifier = Modifier.padding(vertical = 10.dp),
                            text = "Please install the app on your phone",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.caption1,
                        )
                    }
                }
            }else{
                if (sortedWorkouts.isEmpty()) {
                    item {
                        Text(
                            modifier = Modifier.padding(vertical = 10.dp).fillMaxWidth(),
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
                            hapticsViewModel.doGentleVibration()
                            navController.navigate(Screen.WorkoutDetail.route)
                            viewModel.setWorkout(workout)
                        }
                    }
                }
            }


        }
    }

    LaunchedEffect(showClearData) {
        if(showClearData){
            viewModel.lightScreenPermanently()
        }else{
            viewModel.restoreScreenDimmingState()
        }
    }

    CustomDialogYesOnLongPress(
        show = showClearData,
        title = "Clear Data",
        message = "Do you want to proceed?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
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
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showClearData = false
        },
        holdTimeInMillis = 1000
    )
}
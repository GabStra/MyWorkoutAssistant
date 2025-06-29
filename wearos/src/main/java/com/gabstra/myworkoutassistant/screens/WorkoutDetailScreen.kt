package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.Orange
import kotlinx.coroutines.flow.drop

@Composable
fun WorkoutDetailScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    hrViewModel : SensorDataViewModel
) {
    val workout by appViewModel.selectedWorkout
    val context = LocalContext.current

    var showDeleteDialog by remember { mutableStateOf(false) }

    val hasWorkoutRecord by appViewModel.hasWorkoutRecord.collectAsState()
    val hasExercises by appViewModel.hasExercises.collectAsState()

    val basePermissions = listOf(
        Manifest.permission.BODY_SENSORS,
        Manifest.permission.BLUETOOTH_SCAN,
        Manifest.permission.BLUETOOTH_CONNECT,
        Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION,
        Manifest.permission.POST_NOTIFICATIONS
    )

    val permissionLauncherStart = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        if (result.all { it.value }) {
            if(hasWorkoutRecord) appViewModel.deleteWorkoutRecord()
            appViewModel.startWorkout()
            navController.navigate(Screen.Workout.route)
            appViewModel.consumeStartWorkout()
        }
    }

    val permissionLauncherResume = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        if (result.all { it.value }) {
            appViewModel.resumeWorkoutFromRecord()
            navController.navigate(Screen.Workout.route)
        }
    }

    LaunchedEffect(appViewModel.executeStartWorkout) {
        if(appViewModel.executeStartWorkout.value!=null) {
            permissionLauncherStart.launch(basePermissions.toTypedArray())
        }
    }

    if(appViewModel.executeStartWorkout.value == null){
        var marqueeEnabled by remember { mutableStateOf(false) }
        val scalingLazyListState: ScalingLazyListState = rememberScalingLazyListState()

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
                    Text(
                        text = workout.name,
                        modifier = Modifier
                            .clickable(onClick = {
                                marqueeEnabled = !marqueeEnabled
                            })
                            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
                            .padding(0.dp, 0.dp, 0.dp, 10.dp),
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3.copy(fontWeight = FontWeight.Bold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                item {
                    ButtonWithText(
                        text = "Start",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            permissionLauncherStart.launch(basePermissions.toTypedArray())
                        },
                        backgroundColor = Orange,
                        borderColor = Orange,
                        textColor = DarkGray,
                        enabled = hasExercises
                    )
                }

                if (hasWorkoutRecord) {
                    item {
                        ButtonWithText(
                            text = "Resume",
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                permissionLauncherResume.launch(basePermissions.toTypedArray())
                            },
                            backgroundColor = MaterialTheme.colors.background,
                        )
                    }

                    item {
                        ButtonWithText(
                            text = "Delete record",
                            onClick = {
                                showDeleteDialog = true
                            },
                            backgroundColor = MaterialTheme.colors.background,
                        )
                    }
                }
                item {
                    ButtonWithText(
                        text = "Send history",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            appViewModel.sendWorkoutHistoryToPhone() { success ->
                                if (success)
                                    Toast.makeText(
                                        context,
                                        "Workout History sent to phone",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                else
                                    Toast.makeText(context, "Nothing to send", Toast.LENGTH_SHORT)
                                        .show()
                            }
                        },
                        backgroundColor = MaterialTheme.colors.background,
                        enabled = hasExercises
                    )
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        snapshotFlow { showDeleteDialog }
            .drop(1)
            .collect { isDialogShown ->
                if (isDialogShown) {
                    appViewModel.lightScreenPermanently()
                } else {
                    appViewModel.restoreScreenDimmingState()
                }
            }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = "Resume Workout",
        message = "Do you want to proceed?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            appViewModel.deleteWorkoutRecord()
            showDeleteDialog = false
        },
        handleNoClick = {
            showDeleteDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showDeleteDialog = false
        },
        holdTimeInMillis = 1000
    )
}
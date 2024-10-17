package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateGentle
import android.Manifest
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.RequiresApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress

import com.gabstra.myworkoutassistant.data.AppViewModel

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
@Composable
fun WorkoutDetailScreen(navController: NavController, viewModel: AppViewModel, hrViewModel : SensorDataViewModel) {
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    var showDeleteDialog by remember { mutableStateOf(false) }

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val hasExercises by viewModel.hasExercises.collectAsState()

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
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()
            viewModel.startWorkout()
            navController.navigate(Screen.Workout.route)
        }
    }

    val permissionLauncherResume = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        if (result.all { it.value }) {
            viewModel.resumeWorkoutFromRecord()
            navController.navigate(Screen.Workout.route)
        }
    }

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
                    style = MaterialTheme.typography.caption1,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            item {
                ButtonWithText(
                    text = "Start",
                    onClick = {
                        VibrateGentle(context)
                        permissionLauncherStart.launch(basePermissions.toTypedArray())
                    },
                    backgroundColor = MaterialTheme.colors.background,
                    enabled = hasExercises
                )
            }

            if (hasWorkoutRecord) {
                item {
                    ButtonWithText(
                        text = "Resume",
                        onClick = {
                            VibrateGentle(context)
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
                        VibrateGentle(context)
                        viewModel.sendWorkoutHistoryToPhone() { success ->
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

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = "Resume workout",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.deleteWorkoutRecord()
            showDeleteDialog = false
        },
        handleNoClick = {
            showDeleteDialog = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showDeleteDialog = false
        },
        holdTimeInMillis = 1000
    )
}
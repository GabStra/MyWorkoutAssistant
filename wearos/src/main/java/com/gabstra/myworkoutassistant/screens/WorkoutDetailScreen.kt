package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateOnce
import android.Manifest
import android.os.Build
import android.util.Log
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.RequiresApi
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.SendToMobile
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SendToMobile
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress

import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification

import com.google.accompanist.permissions.ExperimentalPermissionsApi

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

    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)
    var marqueeEnabled by remember { mutableStateOf(false) }

    ScalingLazyColumn(
        modifier = Modifier.fillMaxSize().padding(vertical = 5.dp, horizontal = 10.dp),
        state = listState,
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        item{
            Text(
                text = workout.name,
                modifier = Modifier
                    .clickable(onClick = {
                        marqueeEnabled = !marqueeEnabled
                    })
                    .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
                    .padding(20.dp),
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.title2,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }

        item{
            ButtonWithText(
                text = "Start",
                onClick = {
                    VibrateOnce(context)
                    permissionLauncherStart.launch(basePermissions.toTypedArray())
                },
                backgroundColor = MaterialTheme.colors.primary,
                enabled = hasExercises
            )
        }

        if(hasWorkoutRecord) {
            item {
                ButtonWithText(
                    text = "Resume",
                    onClick = {
                        VibrateOnce(context)
                        permissionLauncherResume.launch(basePermissions.toTypedArray())
                    },
                    backgroundColor = Color.DarkGray,
                )
            }

            item {
                ButtonWithText(
                    text = "Delete record",
                    onClick = {
                        showDeleteDialog = true
                    },
                    backgroundColor = Color.DarkGray,
                )
            }
        }
        item{
            ButtonWithText(
                text = "Send history",
                onClick = {
                    VibrateOnce(context)
                    viewModel.sendWorkoutHistoryToPhone() { success ->
                        if (success)
                            Toast.makeText(context, "Workout History sent to phone", Toast.LENGTH_SHORT).show()
                        else
                            Toast.makeText(context, "Nothing to send", Toast.LENGTH_SHORT).show()
                    }
                },
                backgroundColor = Color.DarkGray,
                enabled = hasExercises
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = "Resume workout",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.deleteWorkoutRecord()
            showDeleteDialog = false
        },
        handleNoClick = {
            showDeleteDialog = false
            VibrateOnce(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showDeleteDialog = false
        },
        holdTimeInMillis = 1000
    )
}
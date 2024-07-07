package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.VibrateOnce
import android.Manifest
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.RequiresApi
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
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
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.showWorkoutInProgressNotification

import com.google.accompanist.permissions.ExperimentalPermissionsApi

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
@Composable
fun WorkoutDetailScreen(navController: NavController, viewModel: AppViewModel, hrViewModel : MeasureDataViewModel) {
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    val basePermissions = listOf(
        Manifest.permission.BODY_SENSORS,
        Manifest.permission.BLUETOOTH_SCAN,
        Manifest.permission.BLUETOOTH_CONNECT,
        Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION,
        Manifest.permission.POST_NOTIFICATIONS
    )


    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        if (result.all { it.value }) {
            viewModel.startWorkout()
            navController.navigate(Screen.Workout.route)
        }
    }


    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = workout.name,
            modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE),
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.title2
        )
        Spacer(modifier = Modifier.height(15.dp))

        /*

        Button(
            onClick = {
                VibrateOnce(context)
                permissionLauncher.launch(basePermissions.toTypedArray())
            },
            modifier = Modifier.size(35.dp),
            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
        ) {
            Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
        }

        */

        Column(
            verticalArrangement = Arrangement.spacedBy(15.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Button(
                onClick = {
                    VibrateOnce(context)
                    permissionLauncher.launch(basePermissions.toTypedArray())
                },
                modifier = Modifier.height(35.dp).width(90.dp),
                colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    Icon(imageVector = Icons.Default.PlayArrow, contentDescription = "Start")
                    Text(text = "Start")
                }
            }

            Button(
                onClick = {
                    VibrateOnce(context)
                    viewModel.sendWorkoutHistoryToPhone() { success ->
                        if (success)
                            Toast.makeText(context, "Workout History sent to phone", Toast.LENGTH_SHORT).show()
                        else
                            Toast.makeText(context, "Nothing to send", Toast.LENGTH_SHORT).show()
                    }
                },
                modifier = Modifier.height(35.dp).width(150.dp),
                colors = ButtonDefaults.buttonColors(backgroundColor = Color.DarkGray)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    Icon(imageVector = Icons.AutoMirrored.Filled.SendToMobile, contentDescription = "Send to phone")
                    Text(text = "Send history")
                }
            }
        }
    }
}
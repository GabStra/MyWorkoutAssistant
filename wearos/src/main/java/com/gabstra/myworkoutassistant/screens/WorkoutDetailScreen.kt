package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.Context
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel

@Composable
fun WorkoutDetailScreen(
    navController: NavController,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    hrViewModel : SensorDataViewModel
) {
    val selectedWorkoutId by viewModel.selectedWorkoutId
    val workouts by viewModel.workouts.collectAsState()

    val workout = remember(selectedWorkoutId,workouts) { workouts.find { it.id == selectedWorkoutId }!! }
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
            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            prefs.edit { putBoolean("isWorkoutInProgress", true) }

            navController.navigate(Screen.Workout.route)
            viewModel.consumeStartWorkout()
        }
    }

    val permissionLauncherResume = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        if (result.all { it.value }) {
            viewModel.resumeWorkoutFromRecord()
            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            prefs.edit { putBoolean("isWorkoutInProgress", true) }

            navController.navigate(Screen.Workout.route)
        }
    }

    LaunchedEffect(viewModel.executeStartWorkout) {
        if(viewModel.executeStartWorkout.value!=null) {
            permissionLauncherStart.launch(basePermissions.toTypedArray())
        }
    }

    if(viewModel.executeStartWorkout.value == null){
        var marqueeEnabled by remember { mutableStateOf(false) }
        val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
        val spec = rememberTransformationSpec()

        ScreenScaffold(
            scrollState = state,
        ){ contentPadding ->
            TransformingLazyColumn(
                contentPadding = contentPadding,
                state = state,
            ) {
                item {
                    ListHeader(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
                    ) {
                        Text(
                            text = workout.name,
                            modifier = Modifier
                                .clickable(onClick = {
                                    marqueeEnabled = !marqueeEnabled
                                })
                                .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }

                item {
                    Button(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            permissionLauncherStart.launch(basePermissions.toTypedArray())
                        },
                    ) {
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Start",
                            textAlign = TextAlign.Center,
                            style =  MaterialTheme.typography.bodyLarge,
                        )
                    }
                }

                if (hasWorkoutRecord) {
                    item {
                        Button(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec).animateItem(),
                            transformation = SurfaceTransformation(spec),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                permissionLauncherResume.launch(basePermissions.toTypedArray())
                            }
                        ) {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = "Resume",
                                textAlign = TextAlign.Center,
                                style =  MaterialTheme.typography.bodyLarge,
                            )
                        }
                    }

                    item {
                        ButtonWithText(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec).animateItem(),
                            transformation = SurfaceTransformation(spec),
                            text = "Delete record",
                            onClick = {
                                showDeleteDialog = true
                            }
                        )
                    }
                }
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
                        text = "Send history",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
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
                        enabled = hasExercises
                    )
                }
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = "Resume Workout",
        message = "Do you want to proceed?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.deleteWorkoutRecord()
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
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}
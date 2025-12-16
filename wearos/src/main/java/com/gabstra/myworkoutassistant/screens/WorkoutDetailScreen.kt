package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.Context
import android.widget.Toast
import androidx.activity.compose.BackHandler
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
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
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
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.delay

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

    BackHandler(true) {
        navController.popBackStack()
    }

    var showDeleteDialog by remember { mutableStateOf(false) }
    var showStartConfirmationDialog by remember { mutableStateOf(false) }

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val hasExercises by viewModel.hasExercises.collectAsState()
    val isCheckingWorkoutRecord by viewModel.isCheckingWorkoutRecord.collectAsState()
    
    // Track when checking started and ensure minimum display time to prevent flashing
    var showLoading by remember(selectedWorkoutId) { mutableStateOf(true) }
    var checkStartTime by remember(selectedWorkoutId) { mutableStateOf(System.currentTimeMillis()) }
    
    LaunchedEffect(selectedWorkoutId) {
        showLoading = true
        checkStartTime = System.currentTimeMillis()
    }
    
    LaunchedEffect(isCheckingWorkoutRecord) {
        if (!isCheckingWorkoutRecord) {
            // Check completed, but ensure minimum display time (300ms) to prevent flashing
            val elapsed = System.currentTimeMillis() - checkStartTime
            val remainingTime = maxOf(0, 300 - elapsed)
            delay(remainingTime)
            showLoading = false
        }
    }

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

    // Show loading screen while checking workout record (with minimum display time to prevent flashing)
    if (showLoading || isCheckingWorkoutRecord) {
        LoadingScreen(viewModel, text = "Loading")
        return
    }

    if(viewModel.executeStartWorkout.value == null){
        var marqueeEnabled by remember { mutableStateOf(false) }
        val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
        val spec = rememberTransformationSpec()

        ScreenScaffold(
            scrollState = state,
            scrollIndicator = {
                ScrollIndicator(
                    state = state,
                    colors = ScrollIndicatorDefaults.colors(
                        indicatorColor = MaterialTheme.colorScheme.onBackground,
                        trackColor = MediumDarkGray
                    )
                )
            }
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
                            style = MaterialTheme.typography.titleMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            color = MaterialTheme.colorScheme.onBackground
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
                            if (hasWorkoutRecord) {
                                showStartConfirmationDialog = true
                            } else {
                                permissionLauncherStart.launch(basePermissions.toTypedArray())
                            }
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
                            text = "Delete paused workout",
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
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
                        text = "Back",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            navController.popBackStack()
                        }
                    )
                }
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = "Delete Paused Workout",
        message = "Are you sure you want to delete this paused workout?",
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
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    CustomDialogYesOnLongPress(
        show = showStartConfirmationDialog,
        title = "Start New Workout",
        message = "An existing paused workout will be deleted. Continue?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showStartConfirmationDialog = false
            permissionLauncherStart.launch(basePermissions.toTypedArray())
        },
        handleNoClick = {
            showStartConfirmationDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showStartConfirmationDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}
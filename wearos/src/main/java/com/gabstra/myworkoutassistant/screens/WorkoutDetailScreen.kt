package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.CircularProgressIndicator
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
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
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
    val isSyncingToPhone by viewModel.isSyncingToPhone
    
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
            viewModel.clearRecoveryCheckpoint()

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
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator()
            Spacer(Modifier.height(8.dp))
            LoadingText(baseText = "Loading")
        }
        return
    }

    if(viewModel.executeStartWorkout.value == null){
        val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
        val spec = rememberTransformationSpec()

        Box(
            modifier = Modifier.semantics {
                contentDescription = "Workout detail: ${workout.name}"
            }
        ) {
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
                                .transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                        ) {
                            Text(
                                text = workout.name,
                                modifier = Modifier,
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
                                .semantics { contentDescription = "Start workout" }
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
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
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onPrimary
                            )
                        }
                    }

                    if (hasWorkoutRecord) {
                        item {
                            Button(
                                modifier = Modifier
                                    .semantics { contentDescription = "Resume workout" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
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
                                    color = MaterialTheme.colorScheme.onPrimary
                                )
                            }
                        }

                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = InterruptedWorkoutCopy.DELETE_BUTTON,
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
                                .transformedHeight(this, spec),
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
            
            LoadingOverlay(isVisible = isSyncingToPhone, text = "Syncing...")
        }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = InterruptedWorkoutCopy.DELETE_TITLE,
        message = InterruptedWorkoutCopy.DELETE_MESSAGE,
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.deleteWorkoutRecord()
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
        message = InterruptedWorkoutCopy.START_NEW_WORKOUT_MESSAGE,
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
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

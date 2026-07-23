package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
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
import androidx.compose.runtime.mutableLongStateOf
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
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings
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
    var checkStartTime by remember(selectedWorkoutId) { mutableLongStateOf(System.currentTimeMillis()) }
    
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

    fun hasAllWorkoutPermissions(): Boolean =
        basePermissions.all { permission ->
            ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
        }

    fun navigateToWorkout() {
        navController.navigate(Screen.Workout.route) {
            popUpTo(0) { inclusive = true }
            launchSingleTop = true
        }
    }

    fun startWorkoutAfterPermissions() {
        if (hasWorkoutRecord) viewModel.deleteWorkoutRecord()
        viewModel.startWorkout()
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", true) }
        viewModel.clearRecoveryCheckpoint()

        navigateToWorkout()
        viewModel.consumeStartWorkout()
    }

    fun resumeWorkoutAfterPermissions() {
        viewModel.resumeWorkoutFromRecord()
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", true) }

        navigateToWorkout()
        viewModel.consumeStartWorkout()
    }

    val permissionLauncherStart = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        startWorkoutAfterPermissions()
    }

    val permissionLauncherResume = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        resumeWorkoutAfterPermissions()
    }

    fun requestPermissionsOrStartWorkout() {
        if (hasAllWorkoutPermissions()) {
            startWorkoutAfterPermissions()
        } else {
            permissionLauncherStart.launch(basePermissions.toTypedArray())
        }
    }

    fun requestPermissionsOrResumeWorkout() {
        if (hasAllWorkoutPermissions()) {
            resumeWorkoutAfterPermissions()
        } else {
            permissionLauncherResume.launch(basePermissions.toTypedArray())
        }
    }

    LaunchedEffect(
        viewModel.executeStartWorkout.value,
        showLoading,
        isCheckingWorkoutRecord,
        hasWorkoutRecord
    ) {
        if (viewModel.executeStartWorkout.value != null && !showLoading && !isCheckingWorkoutRecord) {
            if (hasWorkoutRecord) {
                requestPermissionsOrResumeWorkout()
            } else {
                requestPermissionsOrStartWorkout()
            }
        }
    }

    // Show loading screen while checking workout record (with minimum display time to prevent flashing)
    if (showLoading || isCheckingWorkoutRecord) {
        FullScreenLoadingIndicator(
            text = IncompleteWorkoutStrings.CHECKING_SESSION_PROGRESS,
        )
        return
    }

    if(viewModel.executeStartWorkout.value == null){
        val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
        val spec = rememberTransformationSpec(
            ResponsiveTransformationSpec.smallScreen(
                containerAlpha = TransformationVariableSpec(1f),
                contentAlpha = TransformationVariableSpec(1f),
                scale = TransformationVariableSpec(0.75f)
            ),
            ResponsiveTransformationSpec.largeScreen(
                containerAlpha = TransformationVariableSpec(1f),
                contentAlpha = TransformationVariableSpec(1f),
                scale = TransformationVariableSpec(0.6f)
            )
        )

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

                    if (hasWorkoutRecord) {
                        item {
                            Text(
                                text = IncompleteWorkoutStrings.SINGULAR,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    item {
                        WearPrimaryButton(
                            modifier = Modifier
                                .semantics { contentDescription = "Start workout" }
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                            text = "Start",
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                if (hasWorkoutRecord) {
                                    showStartConfirmationDialog = true
                                } else {
                                    requestPermissionsOrStartWorkout()
                                }
                            },
                        )
                    }

                    if (hasWorkoutRecord) {
                        item {
                            WearPrimaryButton(
                                modifier = Modifier
                                    .semantics { contentDescription = "Resume incomplete workout" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = "Resume",
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    requestPermissionsOrResumeWorkout()
                                }
                            )
                        }
                    }

                    if (hasExercises) {
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "View workout exercises" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = "Exercises",
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    navController.navigate(Screen.WorkoutExercises.route)
                                }
                            )
                        }
                    }

                    if (hasWorkoutRecord) {
                        item {
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = "Discard incomplete workout" }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = IncompleteWorkoutStrings.DISCARD_BUTTON,
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
        }
    }

    CustomDialogYesOnLongPress(
        show = showDeleteDialog,
        title = IncompleteWorkoutStrings.DELETE_TITLE,
        message = IncompleteWorkoutStrings.DELETE_MESSAGE,
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.discardCurrentIncompleteWorkout()
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
        title = IncompleteWorkoutStrings.START_NEW_WORKOUT_TITLE,
        message = IncompleteWorkoutStrings.START_NEW_WORKOUT_MESSAGE,
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showStartConfirmationDialog = false
            requestPermissionsOrStartWorkout()
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

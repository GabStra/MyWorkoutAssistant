package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.selection.selectableGroup
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.RadioButton
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
import com.gabstra.myworkoutassistant.composables.PermissionRequestDialog
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.WorkoutNameText
import com.gabstra.myworkoutassistant.composables.missingWorkoutPermissions
import com.gabstra.myworkoutassistant.composables.workoutPermissionMessage
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings
import com.gabstra.myworkoutassistant.shared.workout.presentation.orderWorkoutsForPresentation
import kotlinx.coroutines.delay

@Composable
private fun Workout.detailTitle(): String =
    if (recurringSessionId == null) name
    else "${prescriptionLabel ?: prescriptionOrdinal?.let { stringResource(R.string.wear_prescription_with_ordinal, it) } ?: stringResource(R.string.wear_recurring_session)} · $name"

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
    val recurringPrescriptions = remember(workout.recurringSessionId, workouts) {
        workout.recurringSessionId?.let { sessionId ->
            orderWorkoutsForPresentation(
                workouts.filter { it.enabled && it.isActive && it.recurringSessionId == sessionId }
            )
        }.orEmpty()
    }
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
    
    LaunchedEffect(selectedWorkoutId, isCheckingWorkoutRecord) {
        if (!isCheckingWorkoutRecord) {
            // Check completed, but ensure minimum display time (300ms) to prevent flashing
            val elapsed = System.currentTimeMillis() - checkStartTime
            val remainingTime = maxOf(0, 300 - elapsed)
            delay(remainingTime)
            showLoading = false
        }
    }

    var showPermissionRationale by remember { mutableStateOf(false) }
    var permissionsToRequest by remember { mutableStateOf(emptyList<String>()) }
    var resumeAfterPermissionRequest by remember { mutableStateOf(false) }

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

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        showPermissionRationale = false
        permissionsToRequest = emptyList()
        if (resumeAfterPermissionRequest) resumeWorkoutAfterPermissions()
        else startWorkoutAfterPermissions()
        resumeAfterPermissionRequest = false
    }

    fun requestPermissionsOrStartWorkout() {
        val missingPermissions = missingWorkoutPermissions(
            context,
            workout.heartRateSource,
            viewModel.useSamsungHeartRate.value
        )
        if (missingPermissions.isEmpty()) {
            startWorkoutAfterPermissions()
        } else {
            permissionsToRequest = missingPermissions
            resumeAfterPermissionRequest = false
            showPermissionRationale = true
        }
    }

    fun requestPermissionsOrResumeWorkout() {
        val missingPermissions = missingWorkoutPermissions(
            context,
            workout.heartRateSource,
            viewModel.useSamsungHeartRate.value
        )
        if (missingPermissions.isEmpty()) {
            resumeWorkoutAfterPermissions()
        } else {
            permissionsToRequest = missingPermissions
            resumeAfterPermissionRequest = true
            showPermissionRationale = true
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

    if (showPermissionRationale) {
        PermissionRequestDialog(
            title = stringResource(R.string.wear_workout_permissions),
            message = workoutPermissionMessage(permissionsToRequest),
            onContinue = {
                showPermissionRationale = false
                permissionLauncher.launch(permissionsToRequest.toTypedArray())
            },
            onDismiss = {
                showPermissionRationale = false
                permissionsToRequest = emptyList()
                resumeAfterPermissionRequest = false
                viewModel.consumeStartWorkout()
            },
        )
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

        val detailTitleText = workout.detailTitle()
        val workoutDetailCd = stringResource(R.string.wear_workout_detail_cd, detailTitleText)

        Box(
            modifier = Modifier.semantics {
                contentDescription = workoutDetailCd
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
                    modifier = if (recurringPrescriptions.isNotEmpty()) Modifier.selectableGroup() else Modifier,
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
                            WorkoutNameText(text = detailTitleText)
                        }
                    }

                    if (recurringPrescriptions.isNotEmpty()) {
                        item {
                            ListHeader(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                            ) {
                                Text(
                                    text = stringResource(R.string.wear_prescription_header),
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.titleMedium,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                            }
                        }
                        recurringPrescriptions.forEach { prescription ->
                            item {
                                RadioButton(
                                    selected = prescription.id == selectedWorkoutId,
                                    onSelect = {
                                        viewModel.setSelectedWorkoutId(prescription.id)
                                    },
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .transformedHeight(this, spec),
                                    transformation = SurfaceTransformation(spec),
                                    label = {
                                        Text(
                                            text = prescription.prescriptionLabel
                                                ?: prescription.prescriptionOrdinal?.let { stringResource(R.string.wear_prescription_with_ordinal, it) }
                                                ?: stringResource(R.string.wear_recurring_session)
                                        )
                                    }
                                )
                            }
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
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                    }

                    if (hasWorkoutRecord) {
                        item {
                            val resumeWorkoutCd = stringResource(R.string.wear_resume_workout_cd)
                            WearPrimaryButton(
                                modifier = Modifier
                                    .semantics { contentDescription = resumeWorkoutCd }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = stringResource(R.string.wear_resume),
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    requestPermissionsOrResumeWorkout()
                                }
                            )
                        }
                    }

                    if (recurringPrescriptions.isNotEmpty()) {
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                    }

                    item {
                        val startWorkoutCd = stringResource(R.string.wear_start_workout_cd)
                        val startModifier = Modifier
                            .semantics { contentDescription = startWorkoutCd }
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                        val onStartClick = {
                            hapticsViewModel.doGentleVibration()
                            if (hasWorkoutRecord) {
                                showStartConfirmationDialog = true
                            } else {
                                requestPermissionsOrStartWorkout()
                            }
                        }
                        if (hasWorkoutRecord) {
                            ButtonWithText(
                                modifier = startModifier,
                                transformation = SurfaceTransformation(spec),
                                text = stringResource(R.string.wear_start_new),
                                onClick = onStartClick,
                            )
                        } else {
                            WearPrimaryButton(
                                modifier = startModifier,
                                transformation = SurfaceTransformation(spec),
                                text = stringResource(R.string.wear_start),
                                onClick = onStartClick,
                            )
                        }
                    }

                    if (hasExercises) {
                        item {
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        item {
                            val viewExercisesCd = stringResource(R.string.wear_view_exercises_cd)
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = viewExercisesCd }
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec),
                                transformation = SurfaceTransformation(spec),
                                text = stringResource(R.string.wear_exercises),
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    navController.navigate(Screen.WorkoutExercises.route)
                                }
                            )
                        }
                    }

                    if (hasWorkoutRecord) {
                        item {
                            val discardWorkoutCd = stringResource(R.string.wear_discard_workout_cd)
                            ButtonWithText(
                                modifier = Modifier
                                    .semantics { contentDescription = discardWorkoutCd }
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
                            text = stringResource(R.string.wear_back),
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

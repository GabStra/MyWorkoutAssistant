package com.gabstra.myworkoutassistant.composables

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.LocationOff
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.tooling.preview.PreviewParameter
import androidx.compose.ui.tooling.preview.PreviewParameterProvider
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.presentation.theme.numeralMicro
import com.gabstra.myworkoutassistant.preview.createPreviewWorkoutStateMachine
import com.gabstra.myworkoutassistant.screens.setFieldValue
import com.gabstra.myworkoutassistant.services.RunningTrackingError
import com.gabstra.myworkoutassistant.services.RunningTrackingService
import com.gabstra.myworkoutassistant.services.RunningTrackingState
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.running.DistanceUnit
import com.gabstra.myworkoutassistant.shared.running.RunningEnvironment
import com.gabstra.myworkoutassistant.shared.running.RunningPrescription
import com.gabstra.myworkoutassistant.shared.running.RunningResult
import com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint
import com.gabstra.myworkoutassistant.shared.running.RunningTargetType
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RunningSetData
import com.gabstra.myworkoutassistant.shared.sets.RunningSet
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import java.util.UUID
import kotlin.math.roundToInt

@Composable
internal fun RunningSetScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    modifier: Modifier,
    state: WorkoutState.Set,
    prescription: RunningPrescription,
    onComplete: () -> Unit,
    exerciseTitleComposable: @Composable () -> Unit,
    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
    previewState: RunningSetScreenPreviewState? = null,
) {
    val context = LocalContext.current
    val liveTracker by RunningTrackingService.state.collectAsState()
    val runningControlsDialogOpen by viewModel.isRunningControlsDialogOpen.collectAsState()
    val tracker = previewState?.tracker ?: liveTracker
    val trackingErrorMessage = tracker.error?.let { stringResource(it.messageResId) }
    val showRunningControlsDialog = previewState?.showControlsDialog ?: runningControlsDialogOpen
    val isInspectionMode = LocalInspectionMode.current
    val distanceUnit = if (isInspectionMode) DistanceUnit.KILOMETERS else viewModel.workoutStore.distanceUnit
    val distanceUnitLabel = distanceUnit.abbreviation()
    var elapsedMillis by remember(state.set.id, previewState) {
        mutableLongStateOf(previewState?.elapsedMillis ?: tracker.elapsedTimeMillis)
    }
    var completed by remember(state.set.id, previewState) { mutableStateOf(previewState?.completed ?: false) }
    var correctionMeters by remember(state.set.id, previewState) {
        mutableDoubleStateOf(previewState?.correctionMeters ?: tracker.distanceMeters ?: 0.0)
    }
    var initialCorrectionMeters by remember(state.set.id, previewState) {
        mutableDoubleStateOf(previewState?.correctionMeters ?: tracker.distanceMeters ?: 0.0)
    }
    var isDistanceEditing by remember(state.set.id, previewState) {
        mutableStateOf(previewState?.editingDistance ?: false)
    }
    var targetAlerted by remember(state.set.id, previewState) {
        mutableStateOf(previewState?.targetAlerted ?: false)
    }
    var showPermissionRationale by remember { mutableStateOf(false) }
    var permissionsToRequest by remember { mutableStateOf(emptyList<String>()) }
    val isOutdoor = prescription.environment == RunningEnvironment.OUTDOOR
    val locationGranted = previewState?.locationGranted ?: (!isOutdoor || ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED)

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        showPermissionRationale = false
        permissionsToRequest = emptyList()
        viewModel.closeRunningControlsDialog()
        val hasLocation = !isOutdoor || ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        RunningTrackingService.reset()
        RunningTrackingService.start(context, isOutdoor, useGps = hasLocation && isOutdoor)
    }

    LaunchedEffect(tracker.running, tracker.paused) {
        if (previewState != null) return@LaunchedEffect
        while (tracker.running && !tracker.paused) {
            delay(1000)
            elapsedMillis = tracker.elapsedTimeMillis.coerceAtLeast(elapsedMillis) + 1000
        }
    }

    val currentDistanceMeters = distanceForDisplay(tracker, isOutdoor)
    val goalReached = when (prescription.targetType) {
        RunningTargetType.TIME -> elapsedMillis >= prescription.targetValue.times(1000).toLong()
        RunningTargetType.DISTANCE -> currentDistanceMeters >= prescription.targetValue
    }
    LaunchedEffect(tracker.running, completed) {
        if (!tracker.running || completed) viewModel.closeRunningControlsDialog()
    }
    LaunchedEffect(goalReached) {
        if (goalReached && !targetAlerted && !isInspectionMode) {
            targetAlerted = true
            hapticsViewModel.doHardVibrationTwice()
        }
    }

    fun startTracking() {
        val requested = mutableListOf<String>()
        if (isOutdoor && !locationGranted) {
            requested += Manifest.permission.ACCESS_FINE_LOCATION
            requested += Manifest.permission.ACCESS_COARSE_LOCATION
        }
        if (Build.VERSION.SDK_INT >= 36) {
            val permission = "android.permission.health.READ_HEART_RATE"
            if (ContextCompat.checkSelfPermission(context, permission) != PackageManager.PERMISSION_GRANTED) requested += permission
        } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.BODY_SENSORS) != PackageManager.PERMISSION_GRANTED) {
            requested += Manifest.permission.BODY_SENSORS
        }
        if (requested.isEmpty()) {
            viewModel.closeRunningControlsDialog()
            RunningTrackingService.reset()
            RunningTrackingService.start(context, isOutdoor, useGps = isOutdoor && locationGranted)
        } else {
            permissionsToRequest = requested
            showPermissionRationale = true
        }
    }

    fun finishRun() {
        elapsedMillis = tracker.elapsedTimeMillis.coerceAtLeast(elapsedMillis)
        val measuredDistance = distanceForDisplay(tracker, isOutdoor)
        correctionMeters = measuredDistance
        initialCorrectionMeters = measuredDistance
        completed = true
        viewModel.closeRunningControlsDialog()
        RunningTrackingService.stop(context)
        state.hasBeenExecuted = true
        when (val data = state.currentSetData) {
            is RunningSetData -> state.currentSetData = data.copy(hasBeenExecuted = true)
            is EnduranceSetData -> state.currentSetData = data.copy(endTimer = elapsedMillis.toInt(), hasBeenExecuted = true)
            else -> {}
        }
        if (isOutdoor) {
            saveResult(viewModel, state, tracker, elapsedMillis, correctionMeters, true, onComplete)
        }
    }

    val isCompletedTreadmill = completed && !isOutdoor
    customComponentWrapper {
        if (isCompletedTreadmill && isDistanceEditing) {
            Dialog(
                onDismissRequest = { isDistanceEditing = false },
                properties = DialogProperties(
                    dismissOnBackPress = true,
                    dismissOnClickOutside = false,
                    usePlatformDefaultWidth = false,
                ),
            ) {
                Box(
                    modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
                ) {
                    ControlButtonsVertical(
                        modifier = Modifier.fillMaxSize(),
                        onMinusTap = { correctionMeters = (correctionMeters - 100).coerceAtLeast(0.0) },
                        onMinusLongPress = { correctionMeters = (correctionMeters - 100).coerceAtLeast(0.0) },
                        onPlusTap = { correctionMeters += 100.0 },
                        onPlusLongPress = { correctionMeters += 100.0 },
                        isMinusEnabled = correctionMeters > 0.0,
                        isResetEnabled = correctionMeters != initialCorrectionMeters,
                        onCloseClick = { isDistanceEditing = false },
                        onResetClick = {
                            correctionMeters = initialCorrectionMeters
                            hapticsViewModel.doGentleVibration()
                        },
                    ) {
                        SetValueSection(label = stringResource(R.string.run_label_distance, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            TightNumericText(
                                text = formatDistanceValue(correctionMeters, distanceUnit),
                                style = MaterialTheme.typography.numeralSmall,
                            )
                        }
                    }
                }
            }
        } else Column(
            modifier = modifier
                .fillMaxSize()
                .then(
                    if (isCompletedTreadmill) Modifier else Modifier.verticalScroll(rememberScrollState()),
                )
                // Padding inside the scroll (scrolls with content) so resting title/footer
                // sit at the mask's edge bands and dissolve like side content.
                .padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            if (!completed && !tracker.running) exerciseTitleComposable()
            Text(
                text = if (isOutdoor) stringResource(R.string.run_outdoor) else stringResource(R.string.run_treadmill),
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
            )
            if (completed && !isOutdoor) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier.weight(1f).heightIn(min = 48.dp),
                        contentAlignment = Alignment.TopCenter,
                    ) {
                        SetValueSection(label = stringResource(R.string.run_label_elapsed), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            TightNumericText(
                                text = formatElapsed(elapsedMillis),
                                style = MaterialTheme.typography.numeralExtraSmall,
                            )
                        }
                    }
                    val editDistanceDescription = stringResource(
                        R.string.run_cd_edit_treadmill_distance,
                        formatDistanceDescription(correctionMeters, distanceUnit)
                    )
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = 48.dp)
                            .semantics(mergeDescendants = true) {
                                contentDescription = editDistanceDescription
                            }
                            .clickable(role = Role.Button) {
                                isDistanceEditing = true
                                hapticsViewModel.doGentleVibration()
                            },
                        contentAlignment = Alignment.TopCenter,
                    ) {
                        SetValueSection(label = stringResource(R.string.run_label_distance, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            Row(
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                TightNumericText(
                                    text = formatDistanceValue(correctionMeters, distanceUnit),
                                    style = MaterialTheme.typography.numeralExtraSmall,
                                )
                                Icon(
                                    imageVector = Icons.Default.Edit,
                                    contentDescription = null,
                                    modifier = Modifier.padding(start = 4.dp).size(14.dp),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            } else if (tracker.running || completed || elapsedMillis > 0L) {
                // Hidden while the run has never started (no tracking, no accrued time).
                SetValueSection(label = stringResource(R.string.run_label_elapsed), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                    TightNumericText(
                        text = formatElapsed(elapsedMillis),
                        style = MaterialTheme.typography.numeralSmall,
                    )
                }
            }
            if (!completed) {
                if (!tracker.running) {
                    RunPlayIconButton(contentDescription = stringResource(R.string.run_cd_start_run), onClick = ::startTracking)
                } else if (tracker.paused) {
                    RunPlayIconButton(
                        contentDescription = stringResource(R.string.run_cd_resume_run),
                        onClick = {
                            RunningTrackingService.resume(context)
                            hapticsViewModel.doGentleVibration()
                        },
                    )
                }
            }
            if (tracker.running && !tracker.paused && !completed) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp,Alignment.CenterHorizontally),
                ) {
                    val distanceUnavailableLabel = stringResource(R.string.run_distance_unavailable)
                    Box(Modifier.weight(1f,false), contentAlignment = Alignment.Center) {
                        SetValueSection(label = stringResource(R.string.run_label_distance, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            DistanceValueText(
                                text = formatDistanceValue(currentDistanceMeters.takeIf { it > 0.0 }, distanceUnit),
                                currentDistanceMeters = currentDistanceMeters,
                                distanceUnit = distanceUnit,
                                distanceUnavailableLabel = distanceUnavailableLabel,
                                style = MaterialTheme.typography.numeralMicro,
                            )
                        }
                    }
                    Box(Modifier.weight(1f,false), contentAlignment = Alignment.Center) {
                        SetValueSection(label = stringResource(R.string.run_label_avg_pace, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            TightNumericText(
                                text = formatAveragePaceValue(elapsedMillis, currentDistanceMeters, distanceUnit),
                                style = MaterialTheme.typography.numeralMicro,
                            )
                        }
                    }
                }
                if (isOutdoor && (!locationGranted || !tracker.locationAvailable)) {
                    val hasSavedRoute = tracker.route.isNotEmpty()
                    val gpsStatus = if (hasSavedRoute) {
                        stringResource(R.string.run_gps_lost)
                    } else {
                        stringResource(R.string.run_no_gps)
                    }
                    val gpsLostDescription = stringResource(R.string.run_cd_gps_lost_route_saved)
                    val gpsUnavailableDescription = stringResource(R.string.run_cd_gps_unavailable_no_route)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 30.dp)
                            .semantics(mergeDescendants = true) {
                                contentDescription = if (hasSavedRoute) {
                                    gpsLostDescription
                                } else {
                                    gpsUnavailableDescription
                                }
                            },
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            imageVector = Icons.Default.LocationOff,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = gpsStatus,
                            modifier = Modifier.padding(start = 4.dp),
                            style = MaterialTheme.typography.labelSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
            if (!completed) {
                val (goalLabel, goalValue) = goalLabelAndValue(prescription, distanceUnit)
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Same stacked label/value style as the distance and pace cells.
                    SetValueSection(
                        label = goalLabel,
                        headerStyle = MaterialTheme.typography.bodyExtraSmall,
                    ) {
                        TightNumericText(
                            text = goalValue,
                            style = MaterialTheme.typography.numeralMicro,
                            color = if (goalReached) Green else Color.Unspecified,
                        )
                    }
                    if (goalReached) {
                        Icon(
                            imageVector = Icons.Default.Check,
                            contentDescription = stringResource(R.string.run_cd_goal_reached),
                            modifier = Modifier.padding(start = 4.dp).size(20.dp),
                            tint = Green,
                        )
                    }
                }
            }
            trackingErrorMessage?.let {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 28.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.Default.ErrorOutline,
                        contentDescription = null,
                        modifier = Modifier.size(14.dp),
                        tint = MaterialTheme.colorScheme.error,
                    )
                    Text(
                        text = it,
                        modifier = Modifier.padding(start = 4.dp),
                        style = MaterialTheme.typography.labelSmall,
                        textAlign = TextAlign.Center,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }

            if (completed && !isOutdoor) {
                WearPrimaryButton(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 32.dp),
                    text = stringResource(R.string.run_save_run),
                    onClick = { saveResult(viewModel, state, tracker, elapsedMillis, correctionMeters, isOutdoor, onComplete) },
                )
            }
        }
    }

    if (showRunningControlsDialog && tracker.running && !completed && !showPermissionRationale) {
        val (dialogGoalLabel, dialogGoalValue) = goalLabelAndValue(prescription, distanceUnit)
        RunningControlsDialog(
            isPaused = tracker.paused,
            distance = formatDistanceValue(currentDistanceMeters.takeIf { it > 0.0 }, distanceUnit),
            averagePace = formatAveragePaceValue(elapsedMillis, currentDistanceMeters, distanceUnit),
            goalLabel = dialogGoalLabel,
            goalValue = dialogGoalValue,
            distanceUnitLabel = distanceUnitLabel,
            onPauseResume = {
                if (tracker.paused) RunningTrackingService.resume(context) else RunningTrackingService.pause(context)
                hapticsViewModel.doGentleVibration()
                viewModel.closeRunningControlsDialog()
            },
            onFinish = ::finishRun,
            onDismiss = viewModel::closeRunningControlsDialog,
        )
    }

    if (showPermissionRationale) {
        PermissionRequestDialog(
            title = stringResource(R.string.run_permission_title),
            message = workoutPermissionMessage(permissionsToRequest),
            onContinue = {
                showPermissionRationale = false
                viewModel.closeRunningControlsDialog()
                permissionLauncher.launch(permissionsToRequest.toTypedArray())
            },
            onDismiss = {
                showPermissionRationale = false
                permissionsToRequest = emptyList()
            },
        )
    }
}

@Composable
private fun RunPlayIconButton(contentDescription: String, onClick: () -> Unit) {
    EnhancedIconButton(
        modifier = Modifier.size(WearStandardIconButtonSize),
        hitBoxScale = 1f,
        onClick = onClick,
        colors = wearColoredIconButtonColors(containerColor = Green),
    ) {
        Icon(
            modifier = Modifier.size(WearStandardIconButtonIconSize),
            imageVector = Icons.Default.PlayArrow,
            contentDescription = contentDescription,
            tint = androidx.wear.compose.material3.LocalContentColor.current,
        )
    }
}

@Composable
private fun RunningControlsDialog(
    isPaused: Boolean,
    distance: String,
    averagePace: String,
    goalLabel: String,
    goalValue: String,
    distanceUnitLabel: String,
    onPauseResume: () -> Unit,
    onFinish: () -> Unit,
    onDismiss: () -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
            usePlatformDefaultWidth = false,
        ),
    ) {
        Box(
            modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.SpaceEvenly,
            ) {
                Text(stringResource(R.string.run_controls_title), style = MaterialTheme.typography.titleMedium)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp,Alignment.CenterHorizontally),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.weight(1f,false), contentAlignment = Alignment.Center) {
                        SetValueSection(label = stringResource(R.string.run_label_distance, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            TightNumericText(
                                text = distance,
                                style = MaterialTheme.typography.numeralMicro,
                            )
                        }
                    }
                    Box(Modifier.weight(1f,false), contentAlignment = Alignment.Center) {
                        SetValueSection(label = stringResource(R.string.run_label_avg_pace, distanceUnitLabel), headerStyle = MaterialTheme.typography.bodyExtraSmall) {
                            TightNumericText(
                                text = averagePace,
                                style = MaterialTheme.typography.numeralMicro,
                            )
                        }
                    }
                }
                LabeledNumericValue(
                    label = goalLabel,
                    value = goalValue,
                    style = MaterialTheme.typography.bodyExtraSmall,
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(20.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    EnhancedIconButton(
                        modifier = Modifier.size(WearStandardIconButtonSize),
                        hitBoxScale = 1f,
                        onClick = onPauseResume,
                        colors = wearColoredIconButtonColors(
                            containerColor = if (isPaused) Green else MaterialTheme.colorScheme.primary,
                        ),
                    ) {
                        Icon(
                            modifier = Modifier.size(WearStandardIconButtonIconSize),
                            imageVector = if (isPaused) Icons.Default.PlayArrow else Icons.Default.Pause,
                            contentDescription = if (isPaused) stringResource(R.string.run_cd_resume_run) else stringResource(R.string.run_cd_pause_run),
                            tint = androidx.wear.compose.material3.LocalContentColor.current,
                        )
                    }
                    EnhancedIconButton(
                        modifier = Modifier.size(WearStandardIconButtonSize),
                        hitBoxScale = 1f,
                        onClick = onFinish,
                        colors = wearColoredIconButtonColors(containerColor = Red),
                    ) {
                        Icon(
                            modifier = Modifier.size(WearStandardIconButtonIconSize),
                            imageVector = Icons.Default.Stop,
                            contentDescription = stringResource(R.string.run_cd_finish_run),
                            tint = androidx.wear.compose.material3.LocalContentColor.current,
                        )
                    }
                }
                EnhancedIconButton(
                    buttonSize = 40.dp,
                    hitBoxScale = 1.2f,
                    onClick = onDismiss,
                    colors = wearColoredIconButtonColors(MaterialTheme.colorScheme.surfaceContainerHigh),
                    buttonModifier = Modifier.clip(CircleShape),
                ) {
                    Icon(
                        modifier = Modifier.size(20.dp),
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = stringResource(R.string.run_cd_back_to_run),
                        tint = androidx.wear.compose.material3.LocalContentColor.current,
                    )
                }
            }
        }
    }
}

private fun saveResult(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    tracker: com.gabstra.myworkoutassistant.services.RunningTrackingState,
    elapsedMillis: Long,
    distanceMeters: Double,
    isOutdoor: Boolean,
    onComplete: () -> Unit,
) {
    val validDistance = distanceMeters.takeIf { it > 0.0 }
    val heartRates = tracker.heartRates
    val result = RunningResult(
        exerciseId = state.exerciseId.toString(),
        elapsedTimeMillis = elapsedMillis,
        distanceMeters = validDistance,
        averagePaceSecondsPerKilometer = validDistance
            ?.takeIf { it >= MIN_DISTANCE_FOR_PACE_METERS }
            ?.let { elapsedMillis / 1000.0 / (it / 1000.0) },
        averageHeartRateBpm = heartRates.takeIf { it.isNotEmpty() }?.average()?.roundToInt(),
        minHeartRateBpm = heartRates.minOrNull(),
        maxHeartRateBpm = heartRates.maxOrNull(),
        route = if (isOutdoor) tracker.route else emptyList(),
    )
    viewModel.recordRunningResult(result)
    viewModel.storeSetData()
    viewModel.pushAndStoreWorkoutData(false, null) { onComplete() }
}

private const val MIN_DISTANCE_FOR_PACE_METERS = 10.0

private fun formatElapsed(millis: Long): String {
    val seconds = millis / 1000
    return "%02d:%02d".format(seconds / 60, seconds % 60)
}

private fun formatAveragePaceValue(elapsedMillis: Long, distanceMeters: Double, distanceUnit: DistanceUnit): String {
    val metersPerUnit = distanceUnit.metersPerUnit()
    if (distanceMeters < metersPerUnit / 200.0) return "—:—"
    val secondsPerUnit = (elapsedMillis / 1000.0 / (distanceMeters / metersPerUnit)).roundToInt()
    return "%02d:%02d".format(secondsPerUnit / 60, secondsPerUnit % 60)
}

private fun formatDistanceValue(meters: Double?, distanceUnit: DistanceUnit): String =
    meters?.let { "%.2f".format(it / distanceUnit.metersPerUnit()) } ?: "—"

private fun formatDistanceDescription(meters: Double, distanceUnit: DistanceUnit): String =
    "${formatDistanceValue(meters, distanceUnit)} ${distanceUnit.abbreviation()}"

@Composable
private fun DistanceValueText(
    text: String,
    currentDistanceMeters: Double,
    distanceUnit: DistanceUnit,
    distanceUnavailableLabel: String,
    style: TextStyle,
) {
    TightNumericText(
        text = text,
        modifier = Modifier.semantics {
            contentDescription = currentDistanceMeters
                .takeIf { it > 0.0 }
                ?.let { formatDistanceDescription(it, distanceUnit) }
                ?: distanceUnavailableLabel
        },
        style = style,
    )
}

@Composable
private fun goalLabelAndValue(
    prescription: RunningPrescription,
    distanceUnit: DistanceUnit,
): Pair<String, String> = when (prescription.targetType) {
    RunningTargetType.TIME -> stringResource(R.string.run_goal_time_label) to
        formatElapsed((prescription.targetValue * 1000).toLong())
    RunningTargetType.DISTANCE -> stringResource(
        R.string.run_goal_distance_label,
        distanceUnit.abbreviation(),
    ) to formatDistanceValue(prescription.targetValue, distanceUnit)
}

private fun DistanceUnit.abbreviation(): String = when (this) {
    DistanceUnit.KILOMETERS -> "km"
    DistanceUnit.MILES -> "mi"
}

private fun DistanceUnit.metersPerUnit(): Double = when (this) {
    DistanceUnit.KILOMETERS -> 1_000.0
    DistanceUnit.MILES -> 1_609.344
}

private fun distanceFromRoute(route: List<com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint>): Double =
    route.zipWithNext().sumOf { (a, b) ->
        val lat = Math.toRadians(b.latitude - a.latitude)
        val lon = Math.toRadians(b.longitude - a.longitude)
        val h = kotlin.math.sin(lat / 2).let { it * it } + kotlin.math.cos(Math.toRadians(a.latitude)) *
            kotlin.math.cos(Math.toRadians(b.latitude)) * kotlin.math.sin(lon / 2).let { it * it }
        6_371_000.0 * 2 * kotlin.math.asin(kotlin.math.sqrt(h.coerceIn(0.0, 1.0)))
    }

private fun distanceForDisplay(
    tracker: RunningTrackingState,
    isOutdoor: Boolean,
): Double = if (isOutdoor && tracker.route.size >= 2) {
    distanceFromRoute(tracker.route)
} else {
    tracker.distanceMeters?.takeIf { it > 0.0 } ?: distanceFromRoute(tracker.route)
}

internal data class RunningSetScreenPreviewState(
    val tracker: RunningTrackingState,
    val elapsedMillis: Long = tracker.elapsedTimeMillis,
    val completed: Boolean = false,
    val editingDistance: Boolean = false,
    val showControlsDialog: Boolean = false,
    val locationGranted: Boolean = true,
    val correctionMeters: Double? = null,
    val targetAlerted: Boolean = false,
)

private data class RunningSetPreviewFixture(
    val viewModel: AppViewModel,
    val state: WorkoutState.Set,
    val prescription: RunningPrescription,
)

private data class RunningSetScreenPreviewCase(
    val label: String,
    val environment: RunningEnvironment,
    val targetType: RunningTargetType,
    val targetValue: Double,
    val screenState: RunningSetScreenPreviewState,
) {
    override fun toString(): String = label
}

private class RunningSetScreenPreviewProvider : PreviewParameterProvider<RunningSetScreenPreviewCase> {
    private val sampleRoute = listOf(
        RunningRoutePoint(37.4219, -122.0840, 2_000, 5.0),
        RunningRoutePoint(37.4221, -122.0838, 7_000, 5.2),
        RunningRoutePoint(37.4223, -122.0836, 12_000, 5.1),
    )

    private val activeOutdoor = RunningTrackingState(
        running = true,
        elapsedTimeMillis = 332_000,
        distanceMeters = 1_080.0,
        heartRates = listOf(131, 136, 142),
        route = sampleRoute,
        locationAvailable = true,
    )

    override val values: Sequence<RunningSetScreenPreviewCase> = sequenceOf(
        RunningSetScreenPreviewCase(
            "Outdoor · time goal · ready",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.TIME,
            1_800.0,
            RunningSetScreenPreviewState(RunningTrackingState()),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · distance goal · recording",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(activeOutdoor),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · run controls",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(activeOutdoor, showControlsDialog = true),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · paused",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.TIME,
            1_800.0,
            RunningSetScreenPreviewState(activeOutdoor.copy(paused = true)),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · paused · run controls",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(activeOutdoor.copy(paused = true), showControlsDialog = true),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · finished",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.TIME,
            300.0,
            RunningSetScreenPreviewState(
                tracker = activeOutdoor.copy(running = false, elapsedTimeMillis = 300_000),
                elapsedMillis = 300_000,
                completed = true,
                targetAlerted = true,
            ),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · GPS lost · route retained",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(activeOutdoor.copy(locationAvailable = false)),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · permission denied · no route",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.TIME,
            1_800.0,
            RunningSetScreenPreviewState(
                tracker = RunningTrackingState(running = true, elapsedTimeMillis = 48_000),
                locationGranted = false,
            ),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · target reached",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.TIME,
            300.0,
            RunningSetScreenPreviewState(
                tracker = activeOutdoor.copy(elapsedTimeMillis = 300_000),
                elapsedMillis = 300_000,
                targetAlerted = true,
            ),
        ),
        RunningSetScreenPreviewCase(
            "Outdoor · tracking error",
            RunningEnvironment.OUTDOOR,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(
                tracker = RunningTrackingState(
                    error = RunningTrackingError.HEALTH_SERVICES_REGISTRATION_FAILED,
                    errorDiagnostic = "Health Services unavailable",
                ),
            ),
        ),
        RunningSetScreenPreviewCase(
            "Treadmill · distance goal · ready",
            RunningEnvironment.TREADMILL,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(RunningTrackingState()),
        ),
        RunningSetScreenPreviewCase(
            "Treadmill · recording",
            RunningEnvironment.TREADMILL,
            RunningTargetType.TIME,
            1_800.0,
            RunningSetScreenPreviewState(
                RunningTrackingState(
                    running = true,
                    elapsedTimeMillis = 540_000,
                    distanceMeters = 1_200.0,
                    heartRates = listOf(128, 133, 139),
                ),
            ),
        ),
        RunningSetScreenPreviewCase(
            "Treadmill · paused",
            RunningEnvironment.TREADMILL,
            RunningTargetType.TIME,
            1_800.0,
            RunningSetScreenPreviewState(
                RunningTrackingState(
                    running = true,
                    paused = true,
                    elapsedTimeMillis = 540_000,
                    distanceMeters = 1_200.0,
                    heartRates = listOf(128, 133, 139),
                ),
            ),
        ),
        RunningSetScreenPreviewCase(
            "Treadmill · correct distance",
            RunningEnvironment.TREADMILL,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(
                tracker = RunningTrackingState(elapsedTimeMillis = 1_845_000, distanceMeters = 4_960.0),
                elapsedMillis = 1_845_000,
                completed = true,
                correctionMeters = 5_000.0,
            ),
        ),
        RunningSetScreenPreviewCase(
            "Treadmill · edit distance",
            RunningEnvironment.TREADMILL,
            RunningTargetType.DISTANCE,
            5_000.0,
            RunningSetScreenPreviewState(
                tracker = RunningTrackingState(elapsedTimeMillis = 1_845_000, distanceMeters = 4_960.0),
                elapsedMillis = 1_845_000,
                completed = true,
                editingDistance = true,
                correctionMeters = 5_000.0,
            ),
        ),
    )
}

private fun buildRunningSetPreviewFixture(
    environment: RunningEnvironment,
    targetType: RunningTargetType,
    targetValue: Double,
): RunningSetPreviewFixture {
    val exerciseId = UUID.fromString("51000000-0000-0000-0000-000000000001")
    val set = RunningSet(
        id = UUID.fromString("52000000-0000-0000-0000-000000000001"),
    )
    val state = WorkoutState.Set(
        exerciseId = exerciseId,
        set = set,
        setIndex = 0u,
        previousSetData = null,
        currentSetDataState = mutableStateOf(RunningSetData()),
        hasNoHistory = true,
        skipped = false,
        currentBodyWeight = 75.0,
        streak = 0,
        progressionState = ProgressionState.PROGRESS,
        isWarmupSet = false,
        equipmentId = null,
    )
    val prescription = RunningPrescription(environment, targetType, targetValue)
    val viewModel = AppViewModel()
    viewModel.exercisesById = mapOf(
        exerciseId to Exercise(
            id = exerciseId,
            enabled = true,
            name = "Easy Run",
            notes = "",
            sets = listOf(set),
            exerciseType = ExerciseType.RUNNING,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            runningPrescription = prescription,
        )
    )
    val stateMachine = createPreviewWorkoutStateMachine(listOf(state))
    setFieldValue(viewModel, "stateMachine", stateMachine)
    setFieldValue(viewModel, "setStates", java.util.LinkedList(listOf(state)))
    return RunningSetPreviewFixture(viewModel, state, prescription)
}

@Preview(
    name = "Running set states",
    group = "RunningSetScreen",
    device = WearDevices.LARGE_ROUND,
    showBackground = true,
)
@Composable
private fun RunningSetScreenStatesPreview(
    @PreviewParameter(RunningSetScreenPreviewProvider::class)
    previewCase: RunningSetScreenPreviewCase,
) {
    val fixture = remember(previewCase.environment, previewCase.targetType, previewCase.targetValue) {
        buildRunningSetPreviewFixture(
            environment = previewCase.environment,
            targetType = previewCase.targetType,
            targetValue = previewCase.targetValue,
        )
    }
    RunningSetScreenPreview(fixture, previewCase.screenState)
}

@Composable
private fun RunningSetScreenPreview(
    fixture: RunningSetPreviewFixture,
    screenState: RunningSetScreenPreviewState,
) {
    val context = LocalContext.current
    val hapticsViewModel = remember(context) {
        HapticsViewModel(context, HapticsHelper(context))
    }
    val heartRateChangeViewModel = remember { HeartRateChangeViewModel() }
    val chartAppViewModel = fixture.viewModel

    MyWorkoutAssistantTheme {
        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            RunningSetScreen(
                viewModel = fixture.viewModel,
                hapticsViewModel = hapticsViewModel,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(WorkoutPagerPageSafeAreaPadding)
                    // Mirror the EXERCISE_DETAIL pager page mask so the preview matches production.
                    // No padding after the mask: it would clip content inside the fade bands.
                    .circleMask(radiusOffset = 16.dp, fadeWidth = 5.dp)
                    .padding(horizontal = WorkoutPagerLayoutTokens.OverlayContentHorizontalPadding),
                state = fixture.state,
                prescription = fixture.prescription,
                onComplete = {},
                exerciseTitleComposable = { Text("Easy Run", style = MaterialTheme.typography.titleSmall) },
                customComponentWrapper = { content -> Box(Modifier.fillMaxSize()) { content() } },
                previewState = screenState,
            )
            HeartRateCircularChart(
                modifier = Modifier
                    .fillMaxSize()
                    .clipToBounds(),
                appViewModel = chartAppViewModel,
                hapticsViewModel = hapticsViewModel,
                heartRateChangeViewModel = heartRateChangeViewModel,
                hr = screenState.tracker.heartRates.lastOrNull() ?: 140,
                age = 30,
                measuredMaxHeartRate = null,
                restingHeartRate = null,
                lowerBoundMaxHRPercent = null,
                upperBoundMaxHRPercent = null,
            )
            ExerciseIndicator(
                viewModel = fixture.viewModel,
                modifier = Modifier
                    .fillMaxSize()
                    .clipToBounds(),
                currentStateOverride = fixture.state,
                selectedExerciseId = fixture.state.exerciseId,
            )
        }
    }
}

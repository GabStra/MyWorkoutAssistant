package com.gabstra.myworkoutassistant.composables.workout.pages

import com.gabstra.myworkoutassistant.composables.*

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.platform.LocalLocale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.FilledTonalButton
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
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.shared.DarkOrange
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.model.WATCH_SESSION_STATE_RETURNED_HOME
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.launch


@Composable
fun ControlsPage(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
    canChangeEquipment: Boolean = false,
    onChangeEquipmentClick: () -> Unit = {}
) {
    val isInspectionMode = LocalInspectionMode.current
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()
    val screenState by viewModel.screenState.collectAsState()
    val currentWorkoutState = screenState.workoutState

    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()

    var showGoBackDialog by remember { mutableStateOf(false) }
    var showSkipExerciseDialog by remember { mutableStateOf(false) }
    var showFinishEarlyDialog by remember { mutableStateOf(false) }
    var shouldResumeTimerAfterSkipDialog by remember { mutableStateOf(false) }
    var shouldResumeTimerAfterFinishEarlyDialog by remember { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it.id == updatedState.set.id }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val isActiveSetPage =
        currentWorkoutState is WorkoutState.Set &&
            currentWorkoutState.exerciseId == updatedState.exerciseId &&
            currentWorkoutState.set.id == updatedState.set.id
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
    val scrollState = rememberScrollState()
    val showNavigationSection = !isHistoryEmpty || isActiveSetPage
    val showExerciseSection =
        (isMovementSet &&
            (exercise.exerciseType == ExerciseType.WEIGHT ||
                exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
            canChangeEquipment) ||
            (isMovementSet && isLastSet) ||
            isMovementSet

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        showSkipExerciseDialog = false
        showFinishEarlyDialog = false
        shouldResumeTimerAfterSkipDialog = false
        shouldResumeTimerAfterFinishEarlyDialog = false
        scrollState.scrollTo(0)
    }

    fun shouldPauseCurrentTimerForDialog(): Boolean {
        val currentSetState = currentWorkoutState as? WorkoutState.Set ?: return false
        return (currentSetState.set is TimedDurationSet || currentSetState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(currentSetState.set.id)
    }

    fun pauseCurrentTimerForDialog() {
        if (shouldPauseCurrentTimerForDialog()) {
            viewModel.workoutTimerService.pauseTimer(updatedState.set.id)
        }
    }

    fun resumeCurrentTimerAfterDialog(shouldResume: Boolean) {
        if (
            shouldResume &&
            currentWorkoutState is WorkoutState.Set &&
            (currentWorkoutState.set is TimedDurationSet || currentWorkoutState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(updatedState.set.id)
        ) {
            viewModel.workoutTimerService.resumeTimer(updatedState.set.id)
        }
    }

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
    val keepScreenOnOverride by viewModel.keepScreenOn

    ScreenScaffold(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = "Workout controls page" },
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
    ) { _ ->
        TransformingLazyColumn(
            modifier = Modifier
                .padding(horizontal = 20.dp)
                .semantics { contentDescription = "Workout controls page" },
            contentPadding = WorkoutPagerPageSafeAreaPadding,
            state = state
        ) {
            if (showNavigationSection) {
                item {
                    ControlsPageSectionHeader(
                        text = "Navigation",
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            )
                    )
                }
            }
            if (!isHistoryEmpty) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = "Back",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            // Handle go back for calibration flow:
                            // CalibrationRIRSelection → Set(isCalibrationSet) → CalibrationLoadSelection → previous non-Rest state
                            // Use undo() for CalibrationRIRSelection and Set(isCalibrationSet) to maintain proper state sequence
                            // Use goToPreviousNonRestState() for CalibrationLoadSelection to skip Rest states
                            when (currentWorkoutState) {
                                is WorkoutState.CalibrationRIRSelection -> {
                                    // Go back one step to calibration Set execution
                                    // undo() will move to Set(isCalibrationSet=true), calibration context updates to EXECUTING
                                    viewModel.undo()
                                    viewModel.lightScreenUp()
                                }

                                is WorkoutState.Set -> {
                                    if (currentWorkoutState.isCalibrationSet) {
                                        // Go back one step to CalibrationLoadSelection
                                        // undo() will move to CalibrationLoadSelection, calibration context updates to LOAD_SELECTION
                                        viewModel.undo()
                                        viewModel.lightScreenUp()
                                    } else {
                                        // Show dialog for non-calibration sets
                                        showGoBackDialog = true
                                    }
                                }

                                is WorkoutState.CalibrationLoadSelection -> {
                                    // Go back to previous non-Rest state (skipping Rest states)
                                    // This will typically be a Set from the previous exercise
                                    viewModel.goToPreviousNonRestStateWear()
                                    viewModel.lightScreenUp()
                                }

                                else -> {
                                    // Show dialog for other states
                                    showGoBackDialog = true
                                }
                            }
                        },
                        enabled = true,
                    )
                }
            }
            if (showNavigationSection && showExerciseSection) {
                item {
                    Spacer(modifier = Modifier.height(10.dp))
                }
            }
            if (showExerciseSection) {
                item {
                    ControlsPageSectionHeader(
                        text = "Exercise",
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            )
                    )
                }
            }
            if (
                isMovementSet &&
                (exercise.exerciseType == ExerciseType.WEIGHT ||
                    exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
                canChangeEquipment
            ) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = "Change equipment",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            onChangeEquipmentClick()
                        }
                    )
                }
            }
            if (isMovementSet && isLastSet) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = "Add rest-pause set",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false, context) {
                                viewModel.addNewRestPauseSet()
                            }
                        }
                    )
                }
            }
            if (isMovementSet) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = "Add set",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false, context) {
                                viewModel.addNewSetStandard()
                            }
                        }
                    )
                }
            }
            if (showExerciseSection) {
                item {
                    Spacer(modifier = Modifier.height(10.dp))
                }
            }
            item {
                ControlsPageSectionHeader(
                    text = "Preferences",
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        )
                )
            }
            item {
                val alertSoundEnabled = screenState.isAlertSoundEnabled
                val updateAlertSoundEnabled: (Boolean) -> Unit = { enabled ->
                    viewModel.setAlertSoundEnabled(enabled)
                    if (enabled) {
                        hapticsViewModel.doHardVibrationWithBeep()
                    } else {
                        hapticsViewModel.doGentleVibration()
                    }
                }

                FilledTonalButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    colors = ButtonDefaults.filledTonalButtonColors(),
                    onClick = {
                        updateAlertSoundEnabled(!alertSoundEnabled)
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "Alert sound",
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (alertSoundEnabled) {
                                    "Critical alerts vibrate and beep"
                                } else {
                                    "Critical alerts vibrate only"
                                },
                                style = MaterialTheme.typography.bodyExtraSmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(
                            checked = alertSoundEnabled,
                            onCheckedChange = updateAlertSoundEnabled,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                            ),
                        )
                    }
                }
            }

            item {
                val exerciseDefaultKeepOn = exercise.keepScreenOn
                val statusText = when {
                    exerciseDefaultKeepOn -> "This exercise keeps the screen on"
                    !exerciseDefaultKeepOn && !keepScreenOnOverride -> "Screen can dim for this exercise"
                    else -> "Screen will stay on for this workout"
                }
                val isSwitchEnabled = !exerciseDefaultKeepOn
                val switchChecked = exerciseDefaultKeepOn || keepScreenOnOverride

                FilledTonalButton(
                    enabled = isSwitchEnabled,
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    colors = ButtonDefaults.filledTonalButtonColors(),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.toggleKeepScreenOn()
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = "Keep screen on",
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = statusText,
                                style = MaterialTheme.typography.bodyExtraSmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(
                            checked = switchChecked,
                            onCheckedChange = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.toggleKeepScreenOn()
                            },
                            enabled = isSwitchEnabled,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                                disabledCheckedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                disabledCheckedTrackColor = DarkOrange,
                                disabledCheckedBorderColor = DarkOrange,
                            ),
                            modifier = Modifier
                        )
                    }
                }
            }
            item {
                Spacer(modifier = Modifier.height(10.dp))
            }
            item {
                ControlsPageSectionHeader(
                    text = "Session",
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        )
                )
            }
            if (isActiveSetPage) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .semantics { contentDescription = "Skip exercise action" }
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = "Skip exercise",
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            showSkipExerciseDialog = true
                        }
                    )
                }
            }
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    text = "Finish early",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        showFinishEarlyDialog = true
                    }
                )
            }
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    text = "Go Home",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        onBeforeGoHome?.invoke()
                        viewModel.stopWorkoutSessionHeartbeat()
                        viewModel.upsertWorkoutRecord(
                            updatedState.exerciseId,
                            updatedState.setIndex,
                            WATCH_SESSION_STATE_RETURNED_HOME
                        )
                        cancelWorkoutInProgressNotification(context)
                        scope.launch {
                            viewModel.flushWorkoutSync()
                        }

                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
                )
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go back one set",
        message = "Return to the previous set?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.goToPreviousSetWear()
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showGoBackDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
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
        show = showSkipExerciseDialog,
        title = "Skip exercise",
        message = "Skip all remaining sets for this exercise?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showSkipExerciseDialog = false
            viewModel.skipCurrentExerciseWear(context)
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showSkipExerciseDialog = false
            shouldResumeTimerAfterSkipDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showSkipExerciseDialog = false
            shouldResumeTimerAfterSkipDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                shouldResumeTimerAfterSkipDialog = shouldPauseCurrentTimerForDialog()
                pauseCurrentTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeCurrentTimerAfterDialog(shouldResumeTimerAfterSkipDialog)
                shouldResumeTimerAfterSkipDialog = false
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    CustomDialogYesOnLongPress(
        show = showFinishEarlyDialog,
        title = "Finish early",
        message = "End the workout now? All remaining exercises and sets will be skipped.",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showFinishEarlyDialog = false
            viewModel.finishWorkoutEarlyWear(context)
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showFinishEarlyDialog = false
            shouldResumeTimerAfterFinishEarlyDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showFinishEarlyDialog = false
            shouldResumeTimerAfterFinishEarlyDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                shouldResumeTimerAfterFinishEarlyDialog = shouldPauseCurrentTimerForDialog()
                pauseCurrentTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeCurrentTimerAfterDialog(shouldResumeTimerAfterFinishEarlyDialog)
                shouldResumeTimerAfterFinishEarlyDialog = false
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

@Composable
private fun ControlsPageSectionHeader(
    text: String,
    modifier: Modifier = Modifier
) {
    val currentLocale = LocalLocale.current.platformLocale
    Text(
        text = text.uppercase(currentLocale),
        modifier = modifier.padding(horizontal = 25.dp),
        style = workoutPagerTitleTextStyle(),
        color = MaterialTheme.colorScheme.onBackground,
        textAlign = TextAlign.Center
    )
}

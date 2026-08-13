// PageButtons.kt
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.AlertSoundPreferences
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlin.math.roundToInt

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    canChangeEquipment: Boolean = false,
    onChangeEquipmentClick: () -> Unit = {},
    onLeaveWorkout: () -> Unit = {}
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()
    val context = LocalContext.current
    var alertSoundEnabled by rememberSaveable {
        mutableStateOf(AlertSoundPreferences.isEnabled(context))
    }
    val updateAlertSoundEnabled: (Boolean) -> Unit = { enabled ->
        alertSoundEnabled = enabled
        AlertSoundPreferences.setEnabled(context, enabled)
        if (enabled) {
            hapticsViewModel.doHardVibrationWithBeep()
        } else {
            hapticsViewModel.doGentleVibration()
        }
    }

    var showGoBackDialog by rememberSaveable { mutableStateOf(false) }
    var showSkipExerciseDialog by rememberSaveable { mutableStateOf(false) }
    var showFinishEarlyDialog by rememberSaveable { mutableStateOf(false) }
    var shouldResumeTimerAfterDialog by rememberSaveable { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets
    val setIndex = exerciseSets.indexOfFirst { it.id == updatedState.set.id }
    val isLastSet = setIndex == exerciseSets.size - 1
    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val currentWorkoutState = viewModel.workoutState.value
    val isActiveSetPage = currentWorkoutState is WorkoutState.Set &&
        currentWorkoutState.exerciseId == updatedState.exerciseId &&
        currentWorkoutState.set.id == updatedState.set.id
    val keepScreenOn by viewModel.keepScreenOn
    val dimmedScreenBrightness by viewModel.dimmedScreenBrightness
    val exerciseKeepsScreenOn = exercise.keepScreenOn
    val keepScreenOnChecked = exerciseKeepsScreenOn || keepScreenOn
    val keepScreenOnEnabled = !exerciseKeepsScreenOn
    val keepScreenOnStatus = when {
        exerciseKeepsScreenOn -> "On for this exercise"
        keepScreenOn -> "On for this workout"
        else -> "Can dim for this exercise"
    }
    val showNavigationSection = !isHistoryEmpty
    val showExerciseSection = isMovementSet

    val state = rememberLazyListState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        showSkipExerciseDialog = false
        showFinishEarlyDialog = false
        shouldResumeTimerAfterDialog = false
        state.scrollToItem(0)
    }

    fun pauseTimerForDialog() {
        val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return
        if (
            (currentState.set is TimedDurationSet || currentState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(currentState.set.id)
        ) {
            shouldResumeTimerAfterDialog = true
            viewModel.workoutTimerService.pauseTimer(currentState.set.id)
        }
    }

    fun resumeTimerAfterDialog() {
        val currentState = viewModel.workoutState.value as? WorkoutState.Set
        if (
            shouldResumeTimerAfterDialog &&
            currentState != null &&
            (currentState.set is TimedDurationSet || currentState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(currentState.set.id)
        ) {
            viewModel.workoutTimerService.resumeTimer(currentState.set.id)
        }
        shouldResumeTimerAfterDialog = false
    }

    fun stopCurrentTimer() {
        val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return
        if (currentState.set is TimedDurationSet || currentState.set is EnduranceSet) {
            viewModel.workoutTimerService.unregisterTimer(currentState.set.id)
            currentState.startTime = null
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .imePadding()
            .padding(horizontal = 12.dp),
        state = state,
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        if (showNavigationSection) {
            item {
                PageButtonsSectionHeader("Navigation")
            }
        }

        if (!isHistoryEmpty) {
            item {
            ButtonWithText(
                text = "Back",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    if (updatedState.isCalibrationSet) {
                        viewModel.undo()
                        viewModel.lightScreenUp()
                    } else {
                        showGoBackDialog = true
                    }
                },
                style = AppButtonStyle.Tonal
            )
            }
        }

        if (showNavigationSection && showExerciseSection) {
            item { Spacer(modifier = Modifier.height(10.dp)) }
        }

        if (showExerciseSection) {
            item {
                PageButtonsSectionHeader("Exercise")
            }
        }

        if (canChangeEquipment) {
            item {
                ButtonWithText(
                    text = "Change equipment",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        onChangeEquipmentClick()
                    },
                    style = AppButtonStyle.Tonal
                )
            }
        }

        if (isMovementSet && isLastSet) {
            item {
                ButtonWithText(
                    text = "Add rest-pause set",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    style = AppButtonStyle.Tonal
                )
            }
        }

        if (isMovementSet) {
            item {
                ButtonWithText(
                    text = "Add set",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewSetStandard()
                        }
                    },
                    style = AppButtonStyle.Tonal
                )
            }
        }

        item { Spacer(modifier = Modifier.height(10.dp)) }
        item { PageButtonsSectionHeader("Preferences") }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.extraLarge,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                ),
                onClick = {
                    updateAlertSoundEnabled(!alertSoundEnabled)
                },
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text("Alert sound", style = MaterialTheme.typography.titleMedium)
                        Text(
                            text = if (alertSoundEnabled) {
                                "Critical alerts vibrate and beep"
                            } else {
                                "Critical alerts vibrate only"
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.78f),
                        )
                    }
                    Switch(
                        checked = alertSoundEnabled,
                        onCheckedChange = updateAlertSoundEnabled,
                    )
                }
            }
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.extraLarge,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    disabledContainerColor = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.6f),
                    disabledContentColor = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.6f),
                ),
                enabled = keepScreenOnEnabled,
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    viewModel.toggleKeepScreenOn()
                },
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(
                            text = "Keep screen on",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Text(
                            text = keepScreenOnStatus,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(20.dp),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.78f),
                            maxLines = 1,
                        )
                    }
                    Switch(
                        checked = keepScreenOnChecked,
                        enabled = keepScreenOnEnabled,
                        onCheckedChange = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.toggleKeepScreenOn()
                        }
                    )
                }
            }
        }

        item {
            val dimSliderTrackColor = lerp(
                start = MaterialTheme.colorScheme.secondaryContainer,
                stop = MaterialTheme.colorScheme.background,
                fraction = 0.45f,
            )
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.extraLarge,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                ),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "Dim brightness",
                            style = MaterialTheme.typography.titleMedium,
                        )
                    }
                    Text(
                        text = "Brightness used after the screen becomes inactive",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.78f),
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Slider(
                            value = dimmedScreenBrightness,
                            onValueChange = { brightness ->
                                viewModel.setDimmedScreenBrightness(snapDimmedScreenBrightness(brightness))
                            },
                            onValueChangeFinished = {
                                WorkoutDisplayPreferences.setDimmedScreenBrightness(
                                    context = context,
                                    brightness = viewModel.dimmedScreenBrightness.value,
                                )
                                hapticsViewModel.doGentleVibration()
                            },
                            modifier = Modifier.weight(1f),
                            valueRange = MinimumDimmedScreenBrightness..MaximumDimmedScreenBrightness,
                            steps = (
                                (MaximumDimmedScreenBrightness - MinimumDimmedScreenBrightness) /
                                    DimmedScreenBrightnessStep
                                ).roundToInt() - 1,
                            colors = SliderDefaults.colors(
                                thumbColor = MaterialTheme.colorScheme.primary,
                                activeTrackColor = MaterialTheme.colorScheme.primary,
                                inactiveTrackColor = dimSliderTrackColor,
                                activeTickColor = dimSliderTrackColor,
                                inactiveTickColor = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.55f),
                            ),
                            track = { sliderState ->
                                SliderDefaults.Track(
                                    sliderState = sliderState,
                                    colors = SliderDefaults.colors(
                                        activeTrackColor = MaterialTheme.colorScheme.primary,
                                        inactiveTrackColor = dimSliderTrackColor,
                                        activeTickColor = dimSliderTrackColor,
                                        inactiveTickColor = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.55f),
                                    ),
                                    thumbTrackGapSize = 0.dp,
                                )
                            },
                        )
                        Text(
                            text = formatDimmedScreenBrightnessPercent(dimmedScreenBrightness),
                            modifier = Modifier.width(48.dp),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            textAlign = TextAlign.End,
                        )
                    }
                }
            }
        }

        item { Spacer(modifier = Modifier.height(10.dp)) }
        item { PageButtonsSectionHeader("Session") }

        if (isActiveSetPage) {
            item {
                ButtonWithText(
                    text = "Skip exercise",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        showSkipExerciseDialog = true
                    },
                    style = AppButtonStyle.Tonal
                )
            }
        }

        item {
            ButtonWithText(
                text = "Finish early",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    showFinishEarlyDialog = true
                },
                style = AppButtonStyle.Tonal
            )
        }

        item {
            ButtonWithText(
                text = "Leave workout",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    onLeaveWorkout()
                },
                style = AppButtonStyle.Tonal
            )
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go back one set",
        message = "Do you want to proceed?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.goToPreviousSet()
            viewModel.lightScreenUp()
            showGoBackDialog = false
        },
        handleNoClick = {
            showGoBackDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = { showGoBackDialog = false },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) viewModel.setDimming(false)
            else viewModel.reEvaluateDimmingForCurrentState()
        }
    )

    CustomDialogYesOnLongPress(
        show = showSkipExerciseDialog,
        title = "Skip exercise",
        message = "Skip all remaining sets for this exercise?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showSkipExerciseDialog = false
            stopCurrentTimer()
            viewModel.skipCurrentExercise(context) {
                viewModel.lightScreenUp()
            }
        },
        handleNoClick = {
            showSkipExerciseDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = { showSkipExerciseDialog = false },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                pauseTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeTimerAfterDialog()
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
            stopCurrentTimer()
            viewModel.finishWorkoutEarly(context) {
                viewModel.lightScreenUp()
            }
        },
        handleNoClick = {
            showFinishEarlyDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = { showFinishEarlyDialog = false },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                pauseTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeTimerAfterDialog()
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

@Composable
private fun PageButtonsSectionHeader(text: String) {
    Text(
        text = text.uppercase(),
        modifier = Modifier.fillMaxWidth(),
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onBackground,
        textAlign = TextAlign.Center
    )
}



// PageButtons.kt
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel

@Composable
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
            .navigationBarsPadding()
            .imePadding()
            .padding(horizontal = 35.dp),
        state = state,
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            PageButtonsSectionHeader("Navigation")
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

        item {
            Spacer(modifier = Modifier.height(4.dp))
            PageButtonsSectionHeader("Exercise")
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

        item {
            Spacer(modifier = Modifier.height(4.dp))
            PageButtonsSectionHeader("Preferences")
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.extraLarge,
                colors = CardDefaults.cardColors()
            ) {
                ListItem(
                    headlineContent = {
                        Text(
                            text = "Keep screen on",
                            style = MaterialTheme.typography.titleMedium
                        )
                    },
                    trailingContent = {
                        Switch(
                            checked = keepScreenOn,
                            onCheckedChange = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.toggleKeepScreenOn()
                            }
                        )
                    },
                    // Make ListItem use the Card's container color
                    colors = ListItemDefaults.colors(containerColor = Color.Transparent)
                )
            }
        }

        item {
            Spacer(modifier = Modifier.height(4.dp))
            PageButtonsSectionHeader("Session")
        }

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
        style = MaterialTheme.typography.labelLarge,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center
    )
}



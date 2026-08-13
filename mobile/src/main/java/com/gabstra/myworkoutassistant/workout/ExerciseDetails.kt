package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import java.time.LocalDateTime

@Composable
fun ExerciseDetail(
    modifier: Modifier = Modifier,
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit,
    targetRepRange: String? = null,
    heartRateChart: @Composable () -> Unit = {},

    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    var isValueEditorVisible by remember(updatedState.set.id) { mutableStateOf(false) }
    val handleEditModeEnabled = {
        isValueEditorVisible = true
        onEditModeEnabled()
    }
    val handleEditModeDisabled = {
        isValueEditorVisible = false
        onEditModeDisabled()
    }

    when (updatedState.set) {
        is WeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            Column(modifier = modifier.fillMaxSize()) {
                WeightSetScreen(
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    state = updatedState,
                    forceStopEditMode = false,
                    onEditModeDisabled = handleEditModeDisabled,
                    onEditModeEnabled = handleEditModeEnabled,
                    extraInfo = extraInfo,
                    exerciseTitleComposable = {
                        exerciseTitleComposable {
                            hapticsViewModel.doGentleVibration()
                        }
                    },
                    targetRepRange = targetRepRange,
                    customComponentWrapper = customComponentWrapper
                )

                heartRateChart()

                ExerciseDoneButton(
                    visible = !isValueEditorVisible,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                )
            }
        }

        is BodyWeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            Column(modifier = modifier.fillMaxSize()) {
                BodyWeightSetScreen(
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    state = updatedState,
                    forceStopEditMode = false,
                    onEditModeDisabled = handleEditModeDisabled,
                    onEditModeEnabled = handleEditModeEnabled,
                    extraInfo = extraInfo,
                    exerciseTitleComposable = { exerciseTitleComposable {} },
                    targetRepRange = targetRepRange,
                    customComponentWrapper = customComponentWrapper
                )

                heartRateChart()

                ExerciseDoneButton(
                    visible = !isValueEditorVisible,
                    hapticsViewModel = hapticsViewModel,
                    viewModel = viewModel,
                )
            }
        }

        is TimedDurationSet -> {
            TimedDurationSetScreen(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                modifier = modifier,
                state = updatedState,
                onTimerEnd = {
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
                    }
                },
                onTimerDisabled = onTimerDisabled,
                onTimerEnabled = onTimerEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = { exerciseTitleComposable {} },
                heartRateChart = heartRateChart,
                customComponentWrapper = customComponentWrapper
            )
        }

        is EnduranceSet -> EnduranceSetScreen(
            viewModel = viewModel,
            hapticsViewModel = hapticsViewModel,
            modifier = modifier,
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false, context) {
                    viewModel.goToNextState()
                    viewModel.lightScreenUp()
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = { exerciseTitleComposable {} },
            heartRateChart = heartRateChart,
            customComponentWrapper = customComponentWrapper
        )

        is RestSet -> throw IllegalStateException("Rest set should not be here")
    }
}

@Composable
private fun ExerciseDoneButton(
    visible: Boolean,
    hapticsViewModel: HapticsViewModel,
    viewModel: WorkoutViewModel,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(
                start = 100.dp,
                end = 100.dp,
                top = 32.dp,
                bottom = 40.dp,
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        AppPrimaryButton(
            modifier = Modifier.alpha(if (visible) 1f else 0f),
            text = "Done",
            enabled = visible,
            onClick = {
                hapticsViewModel.doGentleVibration()
                viewModel.openCustomDialog()
                viewModel.lightScreenUp()
            },
        )
    }
}


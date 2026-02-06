package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
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

    customComponentWrapper: @Composable (@Composable () -> Unit) -> Unit,
) {
    val context = LocalContext.current

    when (updatedState.set) {
        is WeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            Column(modifier = modifier, verticalArrangement = Arrangement.Center) {
                WeightSetScreen(
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    modifier = Modifier,
                    state = updatedState,
                    forceStopEditMode = false,
                    onEditModeDisabled = onEditModeDisabled,
                    onEditModeEnabled = onEditModeEnabled,
                    extraInfo = extraInfo,
                    exerciseTitleComposable = {
                        exerciseTitleComposable {
                            hapticsViewModel.doGentleVibration()
                        }
                    },
                    customComponentWrapper = customComponentWrapper
                )

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 100.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Button(
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.openCustomDialog()
                            viewModel.lightScreenUp()
                        },
                    ) {
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Done",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                }
            }
        }

        is BodyWeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            Column(modifier = modifier, verticalArrangement = Arrangement.Center) {
                BodyWeightSetScreen(
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    modifier = Modifier,
                    state = updatedState,
                    forceStopEditMode = false,
                    onEditModeDisabled = onEditModeDisabled,
                    onEditModeEnabled = onEditModeEnabled,
                    extraInfo = extraInfo,
                    exerciseTitleComposable = { exerciseTitleComposable {} },
                    customComponentWrapper = customComponentWrapper
                )

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 100.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Button(
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.openCustomDialog()
                            viewModel.lightScreenUp()
                        },
                    ) {
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Done",
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                }
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
            customComponentWrapper = customComponentWrapper
        )

        is RestSet -> throw IllegalStateException("Rest set should not be here")
    }
}


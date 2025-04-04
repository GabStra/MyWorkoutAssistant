package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import java.time.LocalDateTime

@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable () -> Unit,
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

            WeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = updatedState.isWarmupSet,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable,
                customComponentWrapper = customComponentWrapper
            )
        }

        is BodyWeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            BodyWeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = updatedState.isWarmupSet,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable,
                customComponentWrapper = customComponentWrapper
            )
        }

        is TimedDurationSet -> {
            TimedDurationSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                onTimerEnd = {
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.upsertWorkoutRecord(updatedState.set.id)
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
                    }
                },
                onTimerDisabled = onTimerDisabled,
                onTimerEnabled = onTimerEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable,
                customComponentWrapper = customComponentWrapper
            )
        }

        is EnduranceSet -> EnduranceSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false, context) {
                    viewModel.upsertWorkoutRecord(updatedState.set.id)
                    viewModel.goToNextState()
                    viewModel.lightScreenUp()
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = exerciseTitleComposable,
            customComponentWrapper = customComponentWrapper
        )

        is RestSet -> throw IllegalStateException("Rest set should not be here")
    }
}
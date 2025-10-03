package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.time.LocalDateTime

@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
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

    var openDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    var showWeightInfoDialog by remember { mutableStateOf(false) }

    fun startOpenDialogJob() {
        if( openDialogJob?.isActive == true) return
        openDialogJob?.cancel()
        viewModel.setDimming(false)
        openDialogJob = coroutineScope.launch {
            showWeightInfoDialog = true
            kotlinx.coroutines.delay(10000L)
            showWeightInfoDialog = false
            viewModel.reEvaluateDimmingForCurrentState()
        }
    }

    when (updatedState.set) {
        is WeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            WeightSetScreen(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = { exerciseTitleComposable {
                    startOpenDialogJob()
                    hapticsViewModel.doGentleVibration()
                } },
                customComponentWrapper = customComponentWrapper
            )

            val weightSetData = (updatedState.currentSetData as WeightSetData)
            WeightInfoDialog(
                show = showWeightInfoDialog,
                weight = weightSetData.getWeight(),
                equipment = updatedState.equipment,
                onClick = {
                    openDialogJob?.cancel()
                    viewModel.reEvaluateDimmingForCurrentState()
                    showWeightInfoDialog = false
                }
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
                hapticsViewModel = hapticsViewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = { exerciseTitleComposable {} },
                customComponentWrapper = customComponentWrapper
            )

            val bodyWeightSetData = (updatedState.currentSetData as BodyWeightSetData)
            WeightInfoDialog(
                show = showWeightInfoDialog,
                weight = bodyWeightSetData.additionalWeight,
                equipment = updatedState.equipment,
                onClick = {
                    openDialogJob?.cancel()
                    showWeightInfoDialog = false
                }
            )
        }

        is TimedDurationSet -> {
            TimedDurationSetScreen(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                modifier = Modifier.fillMaxSize(),
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
            modifier = Modifier.fillMaxSize(),
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
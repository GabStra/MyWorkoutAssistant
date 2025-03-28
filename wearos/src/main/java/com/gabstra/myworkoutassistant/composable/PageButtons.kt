package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState


@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val context = LocalContext.current

    var showGoBackDialog by remember { mutableStateOf(false) }
    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it === updatedState.set }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
    }

    ScalingLazyColumn(
        modifier = Modifier
            .fillMaxSize(),
        state = listState
    ) {
        item {
            ButtonWithText(
                text = "Back",
                onClick = {
                    VibrateGentle(context)
                    showGoBackDialog = true
                },
                enabled = !isHistoryEmpty,
                backgroundColor = MaterialTheme.colors.background
            )
        }
        item {
            val dimmingEnabled by viewModel.enableScreenDimming
            ButtonWithText(
                text = if (dimmingEnabled) "Disable Dimming" else "Enable Dimming",
                onClick = {
                    VibrateGentle(context)
                    viewModel.toggleScreenDimming()
                },
                backgroundColor = if (dimmingEnabled)
                    MaterialTheme.colors.background
                else
                    MaterialTheme.colors.primary
            )
        }
        if (isMovementSet) {
            item {
                ButtonWithText(
                    text = "Add Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewSetStandard()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
        if (nextWorkoutState !is WorkoutState.Rest) {
            item {
                ButtonWithText(
                    text = "Add Rest",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRest()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }

        if (isMovementSet && isLastSet) {
            item {
                ButtonWithText(
                    text = "Add Rest-Pause Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go to previous Set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.goToPreviousSet()
            viewModel.lightScreenUp()
            showGoBackDialog = false
        },
        handleNoClick = {
            showGoBackDialog = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        holdTimeInMillis = 1000
    )
}
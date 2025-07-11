package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray

import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.flow.drop


@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val context = LocalContext.current

    var showGoBackDialog by remember { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it === updatedState.set }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
    val scrollState = rememberScrollState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        scrollState.scrollTo(0)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalColumnScrollbar(
                scrollState = scrollState,
                scrollBarColor = LightGray
            )
            .padding(horizontal = 15.dp)
            .verticalScroll(scrollState),
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        ButtonWithText(
            text = "Back",
            onClick = {
                hapticsViewModel.doGentleVibration()
                showGoBackDialog = true
            },
            enabled = !isHistoryEmpty,
        )
        val dimmingEnabled by viewModel.currentScreenDimmingState

        ButtonWithText(
            text = if (dimmingEnabled) "Disable Dimming" else "Enable Dimming",
            onClick = {
                hapticsViewModel.doGentleVibration()
                viewModel.toggleScreenDimming()
            },
            textColor = if (dimmingEnabled)
                MaterialTheme.colors.onBackground
            else
                MaterialTheme.colors.background,
            backgroundColor = if (dimmingEnabled)
                MediumDarkGray
            else
                MaterialTheme.colors.primary
        )
        if (isMovementSet) {
            ButtonWithText(
                text = "Add Set",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.addNewSetStandard()
                    }
                }
            )
        }
        if (nextWorkoutState !is WorkoutState.Rest) {
            ButtonWithText(
                text = "Add Rest",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.addNewRest()
                    }
                }
            )
        }

        if (isMovementSet && isLastSet) {
            ButtonWithText(
                text = "Add Rest-Pause Set",
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

    LaunchedEffect(Unit) {
        snapshotFlow { showGoBackDialog }
            .drop(1)
            .collect { isDialogShown ->
                if (isDialogShown) {
                    viewModel.lightScreenPermanently()
                } else {
                    viewModel.restoreScreenDimmingState()
                }
            }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go to previous Set",
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
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        holdTimeInMillis = 1000
    )
}
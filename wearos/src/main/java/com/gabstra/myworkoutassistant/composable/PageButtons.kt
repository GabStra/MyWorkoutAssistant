package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
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
            .padding(10.dp)
            .verticalColumnScrollbar(
                scrollState = scrollState,
                scrollBarColor = Color.White,
                scrollBarTrackColor = Color.DarkGray,
            )
            .padding(horizontal = 10.dp)
            .verticalScroll(scrollState),
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        ButtonWithText(
            text = "Back",
            onClick = {
                VibrateGentle(context)
                showGoBackDialog = true
            },
            enabled = !isHistoryEmpty,
            backgroundColor = MaterialTheme.colors.background
        )
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
        if (isMovementSet) {
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
        if (nextWorkoutState !is WorkoutState.Rest) {
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

        if (isMovementSet && isLastSet) {
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
// PageButtons.kt
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel

@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()
    val context = LocalContext.current

    var showGoBackDialog by rememberSaveable { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets
    val setIndex = exerciseSets.indexOfFirst { it.id == updatedState.set.id }
    val isLastSet = setIndex == exerciseSets.size - 1
    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val keepScreenOn by viewModel.keepScreenOn

    val state = rememberLazyListState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        state.scrollToItem(0)
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
            // Lower emphasis for "Back"
            ButtonWithText(
                text = "Back",
                onClick = {
                    hapticsViewModel.doGentleVibration()
                    showGoBackDialog = true
                },
                enabled = !isHistoryEmpty,
                style = AppButtonStyle.Filled
            )
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

        if (isMovementSet && isLastSet) {
            item {
                // Medium emphasis for Rest-Pause
                ButtonWithText(
                    text = "Add Rest-Pause set",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    style = AppButtonStyle.Filled
                )
            }
        }

        if (isMovementSet) {
            item {
                // Primary action: Filled
                ButtonWithText(
                    text = "Add set",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewSetStandard()
                        }
                    },
                    style = AppButtonStyle.Filled
                )
            }
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
}

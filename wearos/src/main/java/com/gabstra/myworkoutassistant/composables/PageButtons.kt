package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.CheckboxButton
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.checkboxButtonColors
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.launch


@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()
    val screenState by viewModel.screenState.collectAsState()
    val currentWorkoutState = screenState.workoutState

    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()

    var showGoBackDialog by remember { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it.id == updatedState.set.id }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
    val scrollState = rememberScrollState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        scrollState.scrollTo(0)
    }

    val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec()
    val keepScreenOn by viewModel.keepScreenOn

    ScreenScaffold(
        modifier = Modifier.fillMaxSize(),
        scrollState = state,
        scrollIndicator = {
            ScrollIndicator(
                state = state,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { contentPadding ->
        TransformingLazyColumn(
            contentPadding = contentPadding,
            state = state,
        ) {
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec).animateItem(),
                    transformation = SurfaceTransformation(spec),
                    text = "Back",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        // Handle go back for calibration flow:
                        // CalibrationRIRSelection → Set(isCalibrationSet) → CalibrationLoadSelection → previous non-Rest state
                        // Use undo() for CalibrationRIRSelection and Set(isCalibrationSet) to maintain proper state sequence
                        // Use goToPreviousNonRestState() for CalibrationLoadSelection to skip Rest states
                        when (currentWorkoutState) {
                            is WorkoutState.CalibrationRIRSelection -> {
                                // Go back one step to calibration Set execution
                                // undo() will move to Set(isCalibrationSet=true), calibration context updates to EXECUTING
                                viewModel.undo()
                                viewModel.lightScreenUp()
                            }
                            is WorkoutState.Set -> {
                                if (currentWorkoutState.isCalibrationSet) {
                                    // Go back one step to CalibrationLoadSelection
                                    // undo() will move to CalibrationLoadSelection, calibration context updates to LOAD_SELECTION
                                    viewModel.undo()
                                    viewModel.lightScreenUp()
                                } else {
                                    // Show dialog for non-calibration sets
                                    showGoBackDialog = true
                                }
                            }
                            is WorkoutState.CalibrationLoadSelection -> {
                                // Go back to previous non-Rest state (skipping Rest states)
                                // This will typically be a Set from the previous exercise
                                viewModel.goToPreviousNonRestState()
                                viewModel.lightScreenUp()
                            }
                            else -> {
                                // Show dialog for other states
                                showGoBackDialog = true
                            }
                        }
                    },
                    enabled = !isHistoryEmpty,
                )
            }
            item{
                CheckboxButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec).animateItem(),
                    transformation = SurfaceTransformation(spec),
                    colors = checkboxButtonColors(),
                    label = { Text(
                        text = "Keep on",
                        textAlign = TextAlign.Center
                    ) },
                    checked = keepScreenOn,
                    onCheckedChange = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.toggleKeepScreenOn()
                    }
                )
            }

            if (isMovementSet && isLastSet) {
                item{
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
                        text = "Add Rest-Pause set",
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
            if (isMovementSet) {
                item{
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec).animateItem(),
                        transformation = SurfaceTransformation(spec),
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
            }
/*            item{
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec).animateItem(),
                    transformation = SurfaceTransformation(spec),
                    text = "Go to next exercise",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.goToNextExercise()
                    }
                )
            }*/
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec).animateItem(),
                    transformation = SurfaceTransformation(spec),
                    text = "Go Home",
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        onBeforeGoHome?.invoke()
                        // Save workout record (updatedState is already WorkoutState.Set)
                        viewModel.upsertWorkoutRecord(updatedState.exerciseId, updatedState.setIndex)
                        
                        // Clear ongoing workout notification/icon
                        cancelWorkoutInProgressNotification(context)
                        
                        // Clear workout in progress flag
                        val prefs = context.getSharedPreferences("workout_state", android.content.Context.MODE_PRIVATE)
                        prefs.edit { putBoolean("isWorkoutInProgress", false) }
                        viewModel.clearRecoveryCheckpoint()
                        
                        // Flush any pending sync before navigating away
                        scope.launch {
                            viewModel.flushWorkoutSync()
                        }
                        
                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
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
        },
        handleNoClick = {
            showGoBackDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

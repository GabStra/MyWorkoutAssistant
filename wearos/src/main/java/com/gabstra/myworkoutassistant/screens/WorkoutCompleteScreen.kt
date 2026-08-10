package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.content.Context
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.navigation.NavController
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.ProgressionSection
import com.gabstra.myworkoutassistant.composables.ProgressionInfo
import com.gabstra.myworkoutassistant.composables.ProgressionSectionContent
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.WorkoutPagerHeaderReservedHeight
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(
    navController: NavController,
    viewModel: AppViewModel,
    state : WorkoutState.Completed,
    hrViewModel: SensorDataViewModel,
    hapticsViewModel: HapticsViewModel,
    externalHeartRateController: ExternalHeartRateDeviceController?
){
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    var progressionDataCalculated by remember { mutableStateOf(false) }
    var progressionIsEmpty by remember { mutableStateOf<Boolean?>(null) }
    var completionSyncInitiated by remember { mutableStateOf(false) }

    val scope = rememberWearCoroutineScope()

    fun returnToWorkoutSelection() {
        hapticsViewModel.doGentleVibration()
        viewModel.clearCompletionPushCompleted()
        scope.launch { viewModel.flushWorkoutSync() }
        navController.navigate(Screen.WorkoutSelection.route) {
            popUpTo(0) { inclusive = true }
        }
        viewModel.closeCustomDialog()
    }

    // Run critical completion persistence immediately so next app launch does not show recovery.
    LaunchedEffect(Unit) {
        if (!completionSyncInitiated) {
            completionSyncInitiated = true

            if (!workout.usesExternalHeartRateDevice) {
                hrViewModel.stopMeasuringHeartRate()
            } else {
                externalHeartRateController?.disconnectFromDevice()
            }
            cancelWorkoutInProgressNotification(context)

            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            prefs.edit { putBoolean("isWorkoutInProgress", false) }

            viewModel.pushAndStoreWorkoutData(
                isDone = true,
                context = context,
                forceNotSend = false,
                endReason = viewModel.resolveCompletionEndReasonForPersistence()
            ) {
                android.util.Log.d(
                    "WorkoutSync",
                    "SYNC_TRACE event=completion_force_send side=wear isDone=true"
                )
                viewModel.clearRecoveryCheckpoint()
                viewModel.deleteWorkoutRecord()
                viewModel.flushWorkoutSync()
            }
        }
    }

    // Defer UX-only side effects (haptics, sensors, notification) so they don't run on first frame.
    LaunchedEffect(Unit) {

        viewModel.setDimming(false)

        delay(500)
        hapticsViewModel.doShortImpulseWithBeep()
    }

    WorkoutCompleteScreenContent(
        workoutName = workout.name,
        progressionDataCalculated = progressionDataCalculated,
        progressionIsEmpty = progressionIsEmpty == true,
        onDoneClick = ::returnToWorkoutSelection,
        progressionContent = {
            ProgressionSection(
                modifier = Modifier.weight(1f),
                viewModel = viewModel,
                waitForCompletionPush = true,
                onProgressionDataCalculated = { isEmpty ->
                    if (!progressionDataCalculated) {
                        progressionDataCalculated = true
                        progressionIsEmpty = isEmpty
                    }
                }
            )
        }
    )

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title =  "Workout complete",
        message = "Return to the main menu?",
        handleYesClick = ::returnToWorkoutSelection,
        handleNoClick = {
            viewModel.closeCustomDialog()
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
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

@Composable
private fun WorkoutCompleteScreenContent(
    workoutName: String,
    progressionDataCalculated: Boolean,
    progressionIsEmpty: Boolean,
    onDoneClick: () -> Unit,
    progressionContent: @Composable ColumnScope.() -> Unit
) {
    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    Column(
        verticalArrangement = Arrangement.SpaceBetween,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 5.dp)
            .padding(
                top = WorkoutPagerHeaderReservedHeight + 2.5.dp,
                bottom = if (progressionIsEmpty) 12.5.dp else 20.dp,
            )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Text(
                text = "COMPLETED",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                modifier = Modifier.fillMaxWidth(),
                textModifier = Modifier.fillMaxWidth(),
                text = workoutName,
                style = MaterialTheme.typography.titleLarge
            )
        }

        progressionContent()

        if (progressionDataCalculated) {
            WearPrimaryButton(
                modifier = if (progressionIsEmpty) Modifier else Modifier.padding(top = 5.dp),
                text = "Done",
                onClick = onDoneClick,
            )
        }
    }
}

@Preview(
    name = "Completed - no progression",
    device = WearDevices.LARGE_ROUND,
    showBackground = true,
)
@Composable
private fun EmptyWorkoutCompleteScreenPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        WorkoutCompleteScreenContent(
            workoutName = "Push Day",
            progressionDataCalculated = true,
            progressionIsEmpty = true,
            onDoneClick = {},
            progressionContent = {},
        )
    }
}

@Preview(
    name = "Completed - with progression",
    device = WearDevices.LARGE_ROUND,
    showBackground = true,
)
@Composable
private fun PopulatedWorkoutCompleteScreenPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        WorkoutCompleteScreenContent(
            workoutName = "Push Day",
            progressionDataCalculated = true,
            progressionIsEmpty = false,
            onDoneClick = {},
            progressionContent = {
                ProgressionSectionContent(
                    modifier = Modifier.weight(1f),
                    progressionData = listOf(
                        ProgressionInfo("Bench Press", Ternary.ABOVE),
                        ProgressionInfo("Shoulder Press", Ternary.EQUAL),
                        ProgressionInfo("Triceps Extension", Ternary.BELOW),
                    ),
                )
            }
        )
    }
}

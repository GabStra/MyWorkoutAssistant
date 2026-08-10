package com.gabstra.myworkoutassistant.workout

import android.annotation.SuppressLint
import android.content.Context
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.delay

@SuppressLint("DefaultLocale")
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutCompleteScreen(
    appViewModel: AppViewModel,
    viewModel: WorkoutViewModel,
    state : WorkoutState.Completed,
    hapticsViewModel: HapticsViewModel,
){
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val workout by viewModel.selectedWorkout
    val context = LocalContext.current

    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()

    val headerStyle = MaterialTheme.typography.titleSmall
    var completionSaved by remember { mutableStateOf(false) }

    LaunchedEffect(Unit){
        delay(500)

        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", false) }

        viewModel.setDimming(false)
        hapticsViewModel.doShortImpulse()

        viewModel.pushAndStoreWorkoutData(
            isDone = true,
            context = context,
            endReason = viewModel.resolveCompletionEndReasonForPersistence()
        ) {
            if(hasWorkoutRecord) viewModel.deleteWorkoutRecord()
            completionSaved = true
        }
    }

    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(30.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Text(
                text = "Completed",
                textAlign = TextAlign.Center,
                style = headerStyle
            )
            ScalableText(
                text = workout.name,
                style = MaterialTheme.typography.displayLarge
            )
        }

        Text(
            modifier = Modifier.padding(top = 5.dp),
            text = if (completionSaved) "Workout saved" else "Saving workout…",
            style = headerStyle,
            textAlign = TextAlign.Center,
        )

        if (completionSaved) {
            WorkoutProgressionSummary(
                viewModel = viewModel,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 24.dp)
            )
        }

        AppPrimaryButton(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 24.dp),
            text = "Done",
            enabled = completionSaved,
            textAlign = TextAlign.Center,
            onClick = {
                hapticsViewModel.doGentleVibration()
                appViewModel.initScreenData(ScreenData.Workouts(0))
            }
        )
    }

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title =  "Workout completed",
        message = "Return to the main menu?",
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            appViewModel.initScreenData(ScreenData.Workouts(0))
            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            viewModel.closeCustomDialog()
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
        },
        holdTimeInMillis = 1000,
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}


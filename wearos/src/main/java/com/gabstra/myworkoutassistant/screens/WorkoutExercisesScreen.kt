package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.wear.compose.material3.CircularProgressIndicator
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.composables.workout.pages.ExercisesPage
import com.gabstra.myworkoutassistant.composables.workout.pages.buildExercisesPageItems
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun WorkoutExercisesScreen(
    navController: NavController,
    sourceViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
) {
    val context = LocalContext.current
    val selectedWorkoutId by sourceViewModel.selectedWorkoutId
    val previewViewModel: AppViewModel = viewModel(
        key = "workout-exercises-${selectedWorkoutId ?: "none"}"
    )
    val workoutState by previewViewModel.workoutState.collectAsState()
    val isHydrating by previewViewModel.isSessionHydrationInFlightFlow.collectAsState()
    var selectedExercise by remember(selectedWorkoutId) { mutableStateOf<Exercise?>(null) }

    BackHandler(true) {
        navController.popBackStack()
    }

    LaunchedEffect(selectedWorkoutId) {
        val workoutId = selectedWorkoutId ?: return@LaunchedEffect
        previewViewModel.initApplicationContext(context.applicationContext)
        previewViewModel.initExerciseHistoryDao(context)
        previewViewModel.initRestHistoryDao(context)
        previewViewModel.initWorkoutHistoryDao(context)
        previewViewModel.initWorkoutScheduleDao(context)
        previewViewModel.initWorkoutRecordDao(context)
        previewViewModel.initExerciseInfoDao(context)
        previewViewModel.initExerciseSessionProgressionDao(context)
        previewViewModel.updateWorkoutStore(sourceViewModel.workoutStore)
        previewViewModel.setSelectedWorkoutId(workoutId)
        previewViewModel.startWorkout()
    }

    val pageItems = remember(workoutState, previewViewModel.allWorkoutStates.size) {
        buildExercisesPageItems(previewViewModel)
    }
    LaunchedEffect(pageItems) {
        if (selectedExercise == null) {
            selectedExercise = pageItems.firstOrNull()?.representativeExercise
        }
    }

    val exercise = selectedExercise
    if (isHydrating || exercise == null || pageItems.isEmpty()) {
        FullScreenLoadingIndicator(text = "Loading exercises")
        return
    }

    val previewWorkoutState = workoutState.takeUnless { it is WorkoutState.Preparing }
        ?: previewViewModel.allWorkoutStates.firstOrNull()
        ?: return
    var selectedRestPageId by remember(selectedWorkoutId) { mutableStateOf<java.util.UUID?>(null) }
    ExercisesPage(
        selectedExercise = exercise,
        selectedRestPageId = selectedRestPageId,
        workoutState = previewWorkoutState,
        viewModel = previewViewModel,
        hapticsViewModel = hapticsViewModel,
        currentExercise = pageItems.first().representativeExercise,
        showAllAsCompleted = true,
        onPageSelected = { exerciseSelection, restPageId ->
            selectedExercise = exerciseSelection
            selectedRestPageId = restPageId
        },
    )
}

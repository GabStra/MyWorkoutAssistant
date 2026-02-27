package com.gabstra.myworkoutassistant.screens

import androidx.compose.runtime.Composable
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun ExerciseHistoryTab(
    appViewModel: AppViewModel,
    workout: Workout,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    initialHistoryMode: Int,
    onGoBack: () -> Unit,
    onNavigateToOverview: () -> Unit
) {
    ExerciseHistoryScreen(
        appViewModel = appViewModel,
        workout = workout,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        exercise = exercise,
        initialSelectedTabIndex = initialHistoryMode,
        onGoBack = onGoBack,
        embedded = true,
        onNavigateToOverview = onNavigateToOverview
    )
}

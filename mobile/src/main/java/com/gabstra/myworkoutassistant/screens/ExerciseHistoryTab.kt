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
    selectedHistoryMode: Int,
    onGoBack: () -> Unit,
) {
    ExerciseHistoryScreen(
        appViewModel = appViewModel,
        workout = workout,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        exercise = exercise,
        selectedHistoryMode = selectedHistoryMode,
        onGoBack = onGoBack,
    )
}

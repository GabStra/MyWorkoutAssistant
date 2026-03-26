package com.gabstra.myworkoutassistant.screens

import androidx.compose.runtime.Composable
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

import java.util.UUID

@Composable
fun ExerciseHistoryTab(
    appViewModel: AppViewModel,
    workout: Workout,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    workoutHistoryId: UUID?,
    pageIndex: Int,
    selectedTopTab: Int,
    selectedHistoryMode: Int,
    onGoBack: () -> Unit,
    onDisplayedWorkoutHistoryIdChange: (UUID?) -> Unit,
) {
    ExerciseHistoryScreen(
        appViewModel = appViewModel,
        workout = workout,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        exercise = exercise,
        workoutHistoryId = workoutHistoryId,
        selectedHistoryMode = selectedHistoryMode,
        onGoBack = onGoBack,
        onSelectedWorkoutHistoryIdChanged = { id ->
            if (pageIndex == selectedTopTab) {
                onDisplayedWorkoutHistoryIdChange(id)
            }
        },
    )
}

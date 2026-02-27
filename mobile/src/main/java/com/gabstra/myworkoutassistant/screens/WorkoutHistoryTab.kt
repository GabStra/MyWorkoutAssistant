package com.gabstra.myworkoutassistant.screens

import androidx.compose.runtime.Composable
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import java.util.UUID

@Composable
fun WorkoutHistoryTab(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    workoutHistoryId: UUID?,
    setHistoryDao: SetHistoryDao,
    workout: Workout,
    onGoBack: () -> Unit,
    onNavigateToOverview: () -> Unit
) {
    WorkoutHistoryScreen(
        appViewModel = appViewModel,
        healthConnectClient = healthConnectClient,
        workoutHistoryDao = workoutHistoryDao,
        workoutRecordDao = workoutRecordDao,
        workoutHistoryId = workoutHistoryId,
        setHistoryDao = setHistoryDao,
        workout = workout,
        onGoBack = onGoBack,
        embedded = true,
        onNavigateToOverview = onNavigateToOverview
    )
}

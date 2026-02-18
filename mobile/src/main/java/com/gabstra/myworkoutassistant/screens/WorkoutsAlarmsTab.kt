package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.ActiveScheduleCard
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun WorkoutsAlarmsTab(
    workouts: List<Workout>,
    enabledWorkouts: List<Workout>,
    workoutScheduleDao: WorkoutScheduleDao,
    scope: CoroutineScope,
    onSyncClick: () -> Unit,
    updateMessage: Any?
) {
    val scrollState = rememberScrollState()

    var allSchedules by remember { mutableStateOf<List<WorkoutSchedule>>(emptyList()) }
    var isLoadingSchedules by remember { mutableStateOf(true) }

    // Check if any schedules have previousEnabledState set (meaning they were bulk disabled)
    val hasBulkDisabledSchedules = remember(allSchedules) {
        allSchedules.any { it.previousEnabledState != null }
    }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            allSchedules = workoutScheduleDao.getAllSchedules()
            isLoadingSchedules = false
        }
    }

    // Refresh schedules when update message changes
    LaunchedEffect(updateMessage) {
        withContext(Dispatchers.IO) {
            allSchedules = workoutScheduleDao.getAllSchedules()
        }
    }

    // Group schedules by workout
    val schedulesByWorkout = remember(allSchedules, enabledWorkouts) {
        val enabledByGlobalId = enabledWorkouts.associateBy { it.globalId }
        allSchedules.groupBy { schedule ->
            enabledByGlobalId[schedule.workoutId]?.globalId
        }.filterKeys { it != null }
    }

    // Check if there are any matching schedules for the current plan
    val hasMatchingSchedules = remember(schedulesByWorkout) {
        schedulesByWorkout.values.any { it.isNotEmpty() }
    }

    if (isLoadingSchedules) {
        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            CircularProgressIndicator(
                modifier = Modifier.width(32.dp),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MediumDarkGray,
            )
        }
    } else if (!hasMatchingSchedules) {
        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            StyledCard(
                modifier = Modifier
                    .padding(15.dp),
            ) {
                Text(
                    modifier = Modifier
                        .padding(15.dp),
                    text = "No alarms found",
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = .87f),
                )
            }
        }
    } else {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            // Bulk toggle button - only show if there are schedules for available workouts
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    scope.launch(Dispatchers.IO) {
                        if (hasBulkDisabledSchedules) {
                            // Restore all schedules
                            val updatedSchedules = allSchedules.map { schedule ->
                                val previousState = schedule.previousEnabledState
                                if (previousState != null) {
                                    schedule.copy(
                                        isEnabled = previousState,
                                        previousEnabledState = null
                                    )
                                } else {
                                    schedule
                                }
                            }
                            updatedSchedules.forEach { schedule ->
                                workoutScheduleDao.update(schedule)
                            }
                            allSchedules = workoutScheduleDao.getAllSchedules()
                        } else {
                            // Disable all schedules
                            val updatedSchedules = allSchedules.map { schedule ->
                                schedule.copy(
                                    previousEnabledState = schedule.isEnabled,
                                    isEnabled = false
                                )
                            }
                            updatedSchedules.forEach { schedule ->
                                workoutScheduleDao.update(schedule)
                            }
                            allSchedules = workoutScheduleDao.getAllSchedules()
                        }
                        // Trigger sync to watch
                        withContext(Dispatchers.Main) {
                            onSyncClick()
                        }
                    }
                },
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background,
                    disabledContentColor = DisabledContentGray
                )
            ) {
                Text(
                    text = if (hasBulkDisabledSchedules) "Restore All Alarms" else "Disable All Alarms",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            }

            schedulesByWorkout.forEach { (workoutGlobalId, schedules) ->
                val workout = workouts.find { it.globalId == workoutGlobalId && it.isActive }
                if (workout != null && schedules.isNotEmpty()) {
                    StyledCard {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(15.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            Text(
                                text = workout.name,
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onBackground
                            )

                            schedules.forEachIndexed { index, schedule ->
                                ActiveScheduleCard(
                                    schedule = schedule,
                                    index = index,
                                    workout = workout
                                )
                                if (index < schedules.size - 1) {
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant,
                                        modifier = Modifier.padding(vertical = 5.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

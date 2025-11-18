package com.gabstra.myworkoutassistant.receivers

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.util.UUID

class WorkoutAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val scheduleId = intent.getStringExtra("SCHEDULE_ID") ?: return

        // Check synchronously before launching coroutine to prevent race condition
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

        if (isWorkoutInProgress) {
            // A workout is active, so we skip the notification.
            return
        }

        val scope = CoroutineScope(Dispatchers.IO)
        scope.launch {

            val database = AppDatabase.getDatabase(context)
            val scheduleDao = database.workoutScheduleDao()
            val schedule = scheduleDao.getScheduleById(UUID.fromString(scheduleId))
            
            if (schedule != null && schedule.isEnabled) {
                // Get the workout
                val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout = workoutStore.workouts.find { it.globalId == schedule.workoutId }
                
                if (workout != null && (schedule.lastNotificationSentAt == null || schedule.lastNotificationSentAt != LocalDate.now())) {
                    withContext(Dispatchers.Main) {
                        val notificationHelper = WorkoutNotificationHelper(context)
                        notificationHelper.showNotification(schedule, workout)
                    }

                    // Mark one-time schedules as executed
                    if (schedule.specificDate != null) {
                        scheduleDao.markAsExecuted(schedule.id)
                    } else if (schedule.daysOfWeek > 0) {
                        // Reschedule for recurring workouts
                        val scheduler = WorkoutAlarmScheduler(context)
                        scheduler.cancelSchedule(schedule)
                        scheduler.scheduleWorkout(schedule)
                    }

                    scheduleDao.setLastNotificationSentAt(schedule.id, LocalDate.now())
                }
            }
        }
    }
}

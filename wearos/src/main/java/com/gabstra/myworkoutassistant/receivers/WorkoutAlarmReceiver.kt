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
import java.util.UUID

class WorkoutAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val scheduleId = intent.getStringExtra("SCHEDULE_ID") ?: return
        
        // Launch a coroutine to handle the database operations
        val scope = CoroutineScope(Dispatchers.IO)
        scope.launch {
            val database = AppDatabase.getDatabase(context)
            val scheduleDao = database.workoutScheduleDao()
            val workoutSchedule = scheduleDao.getScheduleById(UUID.fromString(scheduleId))
            
            if (workoutSchedule != null && workoutSchedule.isEnabled) {
                // Get the workout
                val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout = workoutStore.workouts.find { it.id == workoutSchedule.workoutId }
                
                if (workout != null) {
                    // Show notification
                    withContext(Dispatchers.Main) {
                        val notificationHelper = WorkoutNotificationHelper(context)
                        notificationHelper.showNotification(workoutSchedule, workout)
                    }
                    
                    // Mark one-time schedules as executed
                    if (workoutSchedule.specificDate != null) {
                        scheduleDao.markAsExecuted(workoutSchedule.id)
                    } else if (workoutSchedule.daysOfWeek > 0) {
                        // Reschedule for recurring workouts
                        val scheduler = WorkoutAlarmScheduler(context)
                        scheduler.scheduleWorkout(workoutSchedule)
                    }
                }
            }
        }
    }
}

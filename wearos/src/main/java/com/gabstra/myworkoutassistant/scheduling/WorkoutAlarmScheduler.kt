package com.gabstra.myworkoutassistant.scheduling

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.gabstra.myworkoutassistant.receivers.WorkoutAlarmReceiver
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Calendar

class WorkoutAlarmScheduler(private val context: Context) {
    private val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
    private val scope = CoroutineScope(Dispatchers.IO)
    
    fun scheduleWorkout(schedule: WorkoutSchedule) {
        val intent = Intent(context, WorkoutAlarmReceiver::class.java).apply {
            putExtra("SCHEDULE_ID", schedule.id.toString())
        }
        
        val pendingIntent = PendingIntent.getBroadcast(
            context,
            schedule.id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        // Calculate next alarm time
        val calendar = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, schedule.hour)
            set(Calendar.MINUTE, schedule.minute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
            
            // If the time is in the past, add a day
            if (timeInMillis <= System.currentTimeMillis()) {
                add(Calendar.DAY_OF_YEAR, 1)
            }
            
            // If specific date is set, use that instead
            schedule.specificDate?.let {
                set(Calendar.YEAR, it.year)
                set(Calendar.MONTH, it.monthValue - 1)
                set(Calendar.DAY_OF_MONTH, it.dayOfMonth)
                
                // If specific date is in the past, don't schedule
                if (timeInMillis <= System.currentTimeMillis()) {
                    return
                }
            }
            
            // If days of week are specified, find the next valid day
            if (schedule.daysOfWeek > 0 && schedule.specificDate == null) {
                var daysAdded = 0
                var dayFound = false
                
                while (!dayFound && daysAdded < 7) {
                    val dayOfWeek = get(Calendar.DAY_OF_WEEK) - 1 // Convert to 0-based (0 = Sunday)
                    val isDayEnabled = (schedule.daysOfWeek and (1 shl dayOfWeek)) != 0
                    
                    if (isDayEnabled) {
                        dayFound = true
                    } else {
                        add(Calendar.DAY_OF_YEAR, 1)
                        daysAdded++
                    }
                }
            }
        }

        // Check for permission to schedule exact alarms on Android S (API 31) and above
        if (alarmManager.canScheduleExactAlarms()) {
            alarmManager.setExactAndAllowWhileIdle(
                AlarmManager.RTC_WAKEUP,
                calendar.timeInMillis,
                pendingIntent
            )
        } else {
            // Fall back to inexact alarm or request permission
            requestExactAlarmPermission()

            // Meanwhile, use setAndAllowWhileIdle as a fallback
            alarmManager.setAndAllowWhileIdle(
                AlarmManager.RTC_WAKEUP,
                calendar.timeInMillis,
                pendingIntent
            )
        }
    }

    private fun requestExactAlarmPermission() {
        val intent = Intent().apply {
            action = android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM
        }
        // This intent needs to be started from an Activity context
        // You may need to pass this intent back to your activity to start it
        // Or use a broadcast to notify your activity to show a permission dialog
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun cancelSchedule(schedule: WorkoutSchedule) {
        val intent = Intent(context, WorkoutAlarmReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            context,
            schedule.id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        alarmManager.cancel(pendingIntent)
    }
    
    fun rescheduleAllWorkouts() {
        scope.launch {
            val database = AppDatabase.getDatabase(context)
            val schedules = database.workoutScheduleDao().getActiveSchedules()
            
            schedules.forEach { schedule ->
                scheduleWorkout(schedule)
            }
        }
    }
}

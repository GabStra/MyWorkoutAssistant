package com.gabstra.myworkoutassistant.receivers

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.util.UUID

class WorkoutAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val scheduleId = intent.getStringExtra("SCHEDULE_ID")
            ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
            ?: return
        val pendingResult = goAsync()
        val appCeh = (context.applicationContext as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext
        val scope = CoroutineScope(Dispatchers.IO + appCeh)
        scope.launch {
            try {
                handleTriggeredAlarm(context, scheduleId)
            } catch (t: Throwable) {
                Log.e(TAG, "Failed to process triggered workout alarm for scheduleId=$scheduleId", t)
            } finally {
                pendingResult.finish()
            }
        }
    }

    private suspend fun handleTriggeredAlarm(context: Context, scheduleId: UUID) {
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)
        val today = LocalDate.now()

        val database = AppDatabase.getDatabase(context)
        val scheduleDao = database.workoutScheduleDao()
        val schedule = scheduleDao.getScheduleById(scheduleId) ?: return

        if (!schedule.isEnabled) {
            return
        }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.find { it.globalId == schedule.workoutId }

        val shouldShowNotification =
            !isWorkoutInProgress &&
                workout != null &&
                (schedule.lastNotificationSentAt == null || schedule.lastNotificationSentAt != today)

        try {
            if (shouldShowNotification) {
                withContext(Dispatchers.Main) {
                    val notificationHelper = WorkoutNotificationHelper(context)
                    notificationHelper.showNotification(schedule, workout)
                    context.startActivity(
                        notificationHelper.createAlarmActivityIntent(schedule).apply {
                            addFlags(
                                Intent.FLAG_ACTIVITY_NEW_TASK or
                                    Intent.FLAG_ACTIVITY_CLEAR_TOP or
                                    Intent.FLAG_ACTIVITY_SINGLE_TOP
                            )
                        }
                    )
                }
            }
        } finally {
            advanceTriggeredSchedule(context, scheduleDao, schedule, today)
        }
    }

    private suspend fun advanceTriggeredSchedule(
        context: Context,
        scheduleDao: WorkoutScheduleDao,
        schedule: WorkoutSchedule,
        triggeredOn: LocalDate
    ) {
        when {
            schedule.specificDate != null -> scheduleDao.markAsExecuted(schedule.id)
            schedule.daysOfWeek > 0 -> {
                val scheduler = WorkoutAlarmScheduler(context)
                scheduler.cancelSchedule(schedule)
                scheduler.scheduleWorkout(schedule)
            }
            else -> return
        }

        scheduleDao.setLastNotificationSentAt(schedule.id, triggeredOn)
    }

    companion object {
        private const val TAG = "WorkoutAlarmReceiver"
    }
}

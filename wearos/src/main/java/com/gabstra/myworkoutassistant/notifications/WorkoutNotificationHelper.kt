package com.gabstra.myworkoutassistant.notifications

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.WorkoutAlarmActivity
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule

class WorkoutNotificationHelper(private val context: Context) {
    companion object {
        const val CHANNEL_ID = "workout_reminders"
    }

    private val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    init {
        createNotificationChannel()
    }
    
    private fun createNotificationChannel() {
        val name = "Workout Reminders"
        val descriptionText = "Notifications for scheduled workouts"
        val importance = NotificationManager.IMPORTANCE_HIGH

        val channel = NotificationChannel(CHANNEL_ID, name, importance).apply {
            description = descriptionText
        }

        notificationManager.createNotificationChannel(channel)
    }
    
    fun buildWorkoutNotification(schedule: WorkoutSchedule, workout: Workout): Notification {
        val fullScreenIntent = Intent(context, WorkoutAlarmActivity::class.java).apply {
            putExtra("WORKOUT_ID", schedule.workoutId.toString())
            putExtra("SCHEDULE_ID", schedule.id.toString())
        }

        if (schedule.label.isNotEmpty()){
            fullScreenIntent.putExtra("LABEL", schedule.label)
        }


        val fullScreenPI = PendingIntent.getActivity(
            context, schedule.id.hashCode(), fullScreenIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_workout_icon)
            .setContentTitle(workout.name)
            .setContentText(if (schedule.label.isNotEmpty()) schedule.label else "Time for your workout!")
            .setCategory(NotificationCompat.CATEGORY_ALARM)          // <- alarm category
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)                                        // keep it ongoing in shade
            .setAutoCancel(false)                                    // don’t auto-dismiss on tap
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setFullScreenIntent(fullScreenPI, true)                 // <- launches alarm UI

        return builder.build()
    }

    fun clearChannelNotifications() {
        val activeNotifications: Array<StatusBarNotification>? = notificationManager.activeNotifications

        activeNotifications?.forEach { sbn ->
            if (sbn.notification.channelId == CHANNEL_ID) {
                notificationManager.cancel(sbn.id)
            }
        }
    }

    fun showNotification(schedule: WorkoutSchedule, workout: Workout) {
        val notification = buildWorkoutNotification(schedule, workout)

        clearChannelNotifications()
        notificationManager.notify(schedule.id.hashCode(), notification)
    }
}

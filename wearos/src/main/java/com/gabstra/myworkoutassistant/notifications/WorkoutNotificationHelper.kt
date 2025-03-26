package com.gabstra.myworkoutassistant.notifications

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.RingtoneManager
import android.os.Build
import androidx.core.app.NotificationCompat
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule

class WorkoutNotificationHelper(private val context: Context) {
    companion object {
        const val CHANNEL_ID = "workout_reminders"
    }
    
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



        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.createNotificationChannel(channel)
    }
    
    fun buildWorkoutNotification(schedule: WorkoutSchedule, workout: Workout): Notification {
        // Create an explicit intent for the workout activity
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("WORKOUT_ID", schedule.workoutId.toString())
            putExtra("SCHEDULE_ID", schedule.id.toString())
        }
        
        val pendingIntent = PendingIntent.getActivity(
            context,
            schedule.id.hashCode(),
            intent, 
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val vibrationPattern = longArrayOf(
            0,      // Start immediately

            // First set of 3 pulses
            200,    // Short pulse 1
            200,    // Pause
            200,    // Short pulse 2
            200,    // Pause
            200,    // Short pulse 3

            500,    // Longer pause between sets

            // Second set of 3 pulses
            200,    // Short pulse 1
            200,    // Pause
            200,    // Short pulse 2
            200,    // Pause
            200,    // Short pulse 3

            500,    // Longer pause between sets

            // Third set of 3 pulses
            200,    // Short pulse 1
            200,    // Pause
            200,    // Short pulse 2
            200,    // Pause
            200     // Short pulse 3
        )

        // Build the notification
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_workout)
            .setContentTitle(workout.name)
            .setContentText(if (schedule.label.isNotEmpty()) schedule.label else "Time for your workout!")
            .setContentIntent(pendingIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setFullScreenIntent(pendingIntent, true)
            .setVibrate(vibrationPattern)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM))
            .setPriority(NotificationCompat.PRIORITY_MAX)

        return builder.build()
    }
    
    fun showNotification(schedule: WorkoutSchedule, workout: Workout) {
        val notification = buildWorkoutNotification(schedule, workout)
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        notificationManager.notify(schedule.id.hashCode(), notification)
    }
}

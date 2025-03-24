package com.gabstra.myworkoutassistant.notifications

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule

class WorkoutNotificationHelper(private val context: Context) {
    companion object {
        const val CHANNEL_ID = "workout_reminders"
        const val NOTIFICATION_GROUP = "workout_group"
    }
    
    init {
        createNotificationChannel()
    }
    
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val name = "Workout Reminders"
            val descriptionText = "Notifications for scheduled workouts"
            val importance = NotificationManager.IMPORTANCE_HIGH
            val channel = NotificationChannel(CHANNEL_ID, name, importance).apply {
                description = descriptionText
                enableVibration(true)
            }
            
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
        }
    }
    
    fun buildWorkoutNotification(schedule: WorkoutSchedule, workout: Workout): Notification {
        // Create an explicit intent for the workout activity
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("WORKOUT_ID", schedule.workoutId.toString())
            putExtra("SCHEDULE_ID", schedule.id.toString())
            putExtra("AUTO_START", true)
        }
        
        val pendingIntent = PendingIntent.getActivity(
            context, 
            schedule.id.hashCode(), 
            intent, 
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        // Build the notification
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_workout)
            .setContentTitle(workout.name)
            .setContentText(if (schedule.label.isNotEmpty()) schedule.label else "Time for your workout!")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        
        // For Wear OS, we can use a full-screen intent
        builder.setFullScreenIntent(pendingIntent, true)
        
        return builder.build()
    }
    
    fun showNotification(schedule: WorkoutSchedule, workout: Workout) {
        val notification = buildWorkoutNotification(schedule, workout)
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(schedule.id.hashCode(), notification)
    }
}

package com.gabstra.myworkoutassistant.data

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.gabstra.myworkoutassistant.R

fun showWorkoutInProgressNotification(context: Context) {
    val channelId = "workout_progress_channel"
    val notificationId = 1

    // Create an intent that will open the app when the notification is tapped
    val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)?.apply {
        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
    }
    val pendingIntent = PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    // Create a notification channel for Android O and above
    val name = "Workout Progress"
    val descriptionText = "A workout is in progress"
    val importance = NotificationManager.IMPORTANCE_LOW
    val channel = NotificationChannel(channelId, name, importance).apply {
        description = descriptionText
    }
    // Register the channel with the system
    val notificationManager: NotificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    notificationManager.createNotificationChannel(channel)

    // Build the notification
    val notification = NotificationCompat.Builder(context, channelId)
        .setSmallIcon(R.drawable.ic_workout)
        .setContentTitle("Workout in Progress")
        .setContentText("Tap to open the app.")
        .setContentIntent(pendingIntent)
        .setPriority(NotificationCompat.PRIORITY_MAX)
        .setOngoing(true) // Remove the notification when tapped
        .build()

    // Show the notification
    with(NotificationManagerCompat.from(context)) {
        notify(notificationId, notification)
    }
}

fun cancelWorkoutInProgressNotification(context: Context) {
    val notificationId = 1 // The same ID that was used to show the notification

    // Cancel the notification with the specific ID
    with(NotificationManagerCompat.from(context)) {
        cancel(notificationId)
    }
}
package com.gabstra.myworkoutassistant.data

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import com.gabstra.myworkoutassistant.shared.workout.timer.formatTimerNotificationStatus
import java.util.UUID

internal const val OPEN_ACTIVE_WORKOUT_ACTION =
    "com.gabstra.myworkoutassistant.OPEN_ACTIVE_WORKOUT"

internal fun Intent.configureOpenActiveWorkoutIntent(workoutGlobalId: UUID? = null): Intent = apply {
    action = OPEN_ACTIVE_WORKOUT_ACTION
    flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
    if (workoutGlobalId != null) {
        putExtra("WORKOUT_ID", workoutGlobalId.toString())
    } else {
        removeExtra("WORKOUT_ID")
    }
}

@SuppressLint("MissingPermission")
fun showWorkoutInProgressNotification(
    context: Context,
    workoutGlobalId: UUID? = null,
    timerUiState: WorkoutTimerService.TimerUiState? = null,
) {
    val channelId = "workout_progress_channel"
    val notificationId = 1

    // Create an intent that will return the user to the active workout when the notification is tapped.
    val intent = Intent(context, MainActivity::class.java)
        .configureOpenActiveWorkoutIntent(workoutGlobalId)
    val pendingIntent = PendingIntent.getActivity(
        context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    // Create a notification channel for Android O and above
    val name = "Workout Progress"
    val descriptionText = "A workout is in progress"
    val importance = NotificationManager.IMPORTANCE_HIGH
    val channel = NotificationChannel(channelId, name, importance).apply {
        description = descriptionText
        enableVibration(false)
        setSound(null, null)
    }
    // Register the channel with the system
    val notificationManager: NotificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    notificationManager.createNotificationChannel(channel)

    // Build the notification builder
    val notificationBuilder = NotificationCompat.Builder(context, channelId)
        .setSmallIcon(R.drawable.ic_workout_icon) // Notification small icon; OngoingActivity supplies the watch-face badge.
        .setContentTitle("Workout in Progress")
        .setContentIntent(pendingIntent)
        .setCategory(NotificationCompat.CATEGORY_WORKOUT)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setColor(ContextCompat.getColor(context, R.color.ic_launcher_background))
        .setColorized(true)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setOngoing(true)

    val ongoingActivityStatus = if (timerUiState == null) {
        notificationBuilder
            .setContentText("Tap to open the app.")
            .setShowWhen(false)
            .setUsesChronometer(false)
        Status.Builder().addTemplate("Workout in progress").build()
    } else if (!timerUiState.isRunning) {
        val pausedStatus = formatTimerNotificationStatus(timerUiState) ?: "Workout in progress"
        notificationBuilder
            .setContentText(pausedStatus)
            .setShowWhen(false)
            .setUsesChronometer(false)
        Status.Builder().addTemplate(pausedStatus).build()
    } else {
        val elapsedRealtime = SystemClock.elapsedRealtime()
        val timerLabel = when (timerUiState.timerType) {
            WorkoutTimerService.TimerType.REST -> "Rest"
            WorkoutTimerService.TimerType.TIMED_DURATION_SET -> "Set"
            WorkoutTimerService.TimerType.ENDURANCE_SET -> "Set elapsed"
        }
        val timerPart = when (timerUiState.timerType) {
            WorkoutTimerService.TimerType.REST,
            WorkoutTimerService.TimerType.TIMED_DURATION_SET ->
                Status.TimerPart(elapsedRealtime + timerUiState.displayMillis)

            WorkoutTimerService.TimerType.ENDURANCE_SET ->
                Status.StopwatchPart(elapsedRealtime - timerUiState.displayMillis)
        }
        val isCountdown = timerUiState.timerType != WorkoutTimerService.TimerType.ENDURANCE_SET
        val timerBaseWallClockMillis = if (isCountdown) {
            System.currentTimeMillis() + timerUiState.displayMillis
        } else {
            System.currentTimeMillis() - timerUiState.displayMillis
        }
        notificationBuilder
            .setContentText(timerLabel)
            .setWhen(timerBaseWallClockMillis)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setChronometerCountDown(isCountdown)
        Status.Builder()
            .addTemplate("#label# #timer#")
            .addPart("label", Status.TextPart(timerLabel))
            .addPart("timer", timerPart)
            .build()
    }

    OngoingActivity.Builder(context, notificationId, notificationBuilder)
        // The watch face ongoing button does not inherit notification colorization,
        // so the ongoing icons carry their own contrast and occupy most of the viewport.
        .setAnimatedIcon(R.drawable.avd_ongoing_workout_badge)
        .setStaticIcon(R.drawable.ic_ongoing_workout_badge)
        .setTouchIntent(pendingIntent)
        .setStatus(ongoingActivityStatus)
        .build()
        .apply(context)

    val notification = notificationBuilder.build()

    // *** 2. Build and show the notification ***
    // Show the notification using the same ID
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

@SuppressLint("MissingPermission")
fun showTimerCompletedNotification(
    context: Context,
    workoutGlobalId: UUID? = null,
    title: String = "Timer completed",
    message: String = "Tap to continue workout"
) {
    val channelId = "timer_completion_channel"
    val notificationId = 3

    val intent = Intent(context, MainActivity::class.java)
        .configureOpenActiveWorkoutIntent(workoutGlobalId)
    val pendingIntent = PendingIntent.getActivity(
        context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    val channel = NotificationChannel(
        channelId,
        "Timer Completion",
        NotificationManager.IMPORTANCE_HIGH
    ).apply {
        description = "Notifications when workout timers complete"
        enableVibration(true)
        setSound(null, null)
    }
    val notificationManager: NotificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    notificationManager.createNotificationChannel(channel)

    val notification = NotificationCompat.Builder(context, channelId)
        .setSmallIcon(R.drawable.ic_workout_icon)
        .setContentTitle(title)
        .setContentText(message)
        .setContentIntent(pendingIntent)
        .setAutoCancel(true)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setDefaults(NotificationCompat.DEFAULT_ALL)
        .setCategory(NotificationCompat.CATEGORY_ALARM)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setColor(ContextCompat.getColor(context, R.color.ic_launcher_background))
        .build()

    with(NotificationManagerCompat.from(context)) {
        notify(notificationId, notification)
    }
}

@SuppressLint("MissingPermission")
fun showSyncCompleteNotification(context: Context) {
    val channelId = "sync_status_channel"
    val notificationId = 2

    // Create an intent that will open the app when the notification is tapped
    val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)
    val pendingIntent = PendingIntent.getActivity(
        context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    val channelName = "Sync Status"
    val channelDescription = "Notifications for sync events"
    // Use IMPORTANCE_HIGH to ensure sound and vibration
    val channelImportance = NotificationManager.IMPORTANCE_HIGH
    val channel = NotificationChannel(channelId, channelName, channelImportance).apply {
        description = channelDescription
        // Enable vibration and sound
        enableVibration(true)
        // Use default notification sound (or setSound(null, null) to use system default)
        setSound(null, null) // This uses the system default notification sound
    }
    val notificationManager: NotificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    notificationManager.createNotificationChannel(channel)

    val notification = NotificationCompat.Builder(context, channelId)
        .setSmallIcon(R.drawable.ic_workout_icon)
        .setContentTitle("Sync complete")
        .setContentText("Workout data updated")
        .setContentIntent(pendingIntent) // Add intent to open app when tapped
        .setAutoCancel(true)
        .setColor(ContextCompat.getColor(context, R.color.ic_launcher_background))
        .setPriority(NotificationCompat.PRIORITY_HIGH) // Increase priority
        .setDefaults(NotificationCompat.DEFAULT_ALL) // Use default sound, vibration, and lights
        .build()

    with(NotificationManagerCompat.from(context)) {
        notify(notificationId, notification)
    }
}

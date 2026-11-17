package com.gabstra.myworkoutassistant.notifications

import android.Manifest
import android.app.ActivityManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import com.gabstra.myworkoutassistant.shared.workout.timer.formatTimerNotificationStatus

private const val ACTIVE_WORKOUT_CHANNEL_ID = "active_workout"
private const val ACTIVE_WORKOUT_NOTIFICATION_ID = 1
private const val TIMER_COMPLETION_CHANNEL_ID = "timer_completion"
private const val TIMER_COMPLETION_NOTIFICATION_ID = 2

fun showActiveWorkoutNotification(
    context: Context,
    timerUiState: WorkoutTimerService.TimerUiState? = null,
) {
    if (
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
        PackageManager.PERMISSION_GRANTED
    ) {
        return
    }

    val notificationManager = context.getSystemService(NotificationManager::class.java)
    notificationManager.createNotificationChannel(
        NotificationChannel(
            ACTIVE_WORKOUT_CHANNEL_ID,
            context.getString(R.string.notif_channel_active_workout),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = context.getString(R.string.notif_channel_active_workout_desc)
            setSound(null, null)
            enableVibration(false)
        },
    )

    val openAppIntent = Intent(context, MainActivity::class.java).apply {
        flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
    }
    val pendingIntent = PendingIntent.getActivity(
        context,
        0,
        openAppIntent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val notificationBuilder = NotificationCompat.Builder(context, ACTIVE_WORKOUT_CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_workout_notification)
        .setContentTitle(context.getString(R.string.notif_workout_in_progress))
        .setContentIntent(pendingIntent)
        .setCategory(NotificationCompat.CATEGORY_WORKOUT)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .setOngoing(true)
        .setOnlyAlertOnce(true)

    if (timerUiState == null || !timerUiState.isRunning) {
        notificationBuilder
            .setContentText(
                formatTimerNotificationStatus(timerUiState)
                    ?: context.getString(R.string.notif_tap_to_return),
            )
            .setShowWhen(false)
            .setUsesChronometer(false)
    } else {
        val isCountdown = timerUiState.timerType != WorkoutTimerService.TimerType.ENDURANCE_SET
        val timerBaseWallClockMillis = if (isCountdown) {
            System.currentTimeMillis() + timerUiState.displayMillis
        } else {
            System.currentTimeMillis() - timerUiState.displayMillis
        }
        notificationBuilder
            .setContentText(
                when (timerUiState.timerType) {
                    WorkoutTimerService.TimerType.REST -> context.getString(R.string.notif_rest_timer)
                    WorkoutTimerService.TimerType.TIMED_DURATION_SET -> context.getString(R.string.notif_set_timer)
                    WorkoutTimerService.TimerType.ENDURANCE_SET -> context.getString(R.string.notif_set_elapsed)
                    WorkoutTimerService.TimerType.SUPERSET_CAP -> context.getString(R.string.notif_time_left)
                    WorkoutTimerService.TimerType.SUPERSET_ROUND_CADENCE -> context.getString(R.string.notif_round)
                },
            )
            .setWhen(timerBaseWallClockMillis)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setChronometerCountDown(isCountdown)
    }

    NotificationManagerCompat.from(context).notify(
        ACTIVE_WORKOUT_NOTIFICATION_ID,
        notificationBuilder.build(),
    )
}

fun cancelActiveWorkoutNotification(context: Context) {
    NotificationManagerCompat.from(context).cancel(ACTIVE_WORKOUT_NOTIFICATION_ID)
}

fun showTimerCompletedNotification(
    context: Context,
    title: String,
    message: String,
) {
    if (
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
        PackageManager.PERMISSION_GRANTED
    ) {
        return
    }

    val notificationManager = context.getSystemService(NotificationManager::class.java)
    notificationManager.createNotificationChannel(
        NotificationChannel(
            TIMER_COMPLETION_CHANNEL_ID,
            context.getString(R.string.notif_channel_timer_completion),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = context.getString(R.string.notif_channel_timer_completion_desc)
            enableVibration(true)
        },
    )

    val pendingIntent = PendingIntent.getActivity(
        context,
        0,
        Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        },
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val notification = NotificationCompat.Builder(context, TIMER_COMPLETION_CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_workout_notification)
        .setContentTitle(title)
        .setContentText(message)
        .setContentIntent(pendingIntent)
        .setAutoCancel(true)
        .setCategory(NotificationCompat.CATEGORY_ALARM)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setDefaults(NotificationCompat.DEFAULT_ALL)
        .build()

    NotificationManagerCompat.from(context).notify(TIMER_COMPLETION_NOTIFICATION_ID, notification)
}

fun isAppInForeground(): Boolean {
    val processState = ActivityManager.RunningAppProcessInfo()
    ActivityManager.getMyMemoryState(processState)
    return processState.importance == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND
}

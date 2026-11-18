package com.gabstra.myworkoutassistant.data

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.widget.RemoteViews
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.complications.WorkoutComplication
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
    val name = context.getString(R.string.notif_channel_workout_progress)
    val descriptionText = context.getString(R.string.notif_channel_workout_progress_desc)
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
        .setContentTitle(context.getString(R.string.notif_workout_in_progress_title))
        .setContentIntent(pendingIntent)
        .setCategory(NotificationCompat.CATEGORY_WORKOUT)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setColor(ContextCompat.getColor(context, R.color.ic_launcher_background))
        .setColorized(true)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setOngoing(true)

    // What the Samsung Now Bar card (built from this notification, see below) shows.
    var nowBarText = context.getString(R.string.notif_workout_in_progress)
    var nowBarChronometer: RemoteViews? = null
    val ongoingActivityStatus = if (timerUiState == null) {
        notificationBuilder
            .setContentText(context.getString(R.string.notif_tap_to_open_app))
            .setShowWhen(false)
            .setUsesChronometer(false)
        Status.Builder().addTemplate(context.getString(R.string.notif_workout_in_progress)).build()
    } else if (!timerUiState.isRunning) {
        val pausedStatus = formatTimerNotificationStatus(context, timerUiState)
            ?: context.getString(R.string.notif_workout_in_progress)
        nowBarText = pausedStatus
        notificationBuilder
            .setContentText(pausedStatus)
            .setShowWhen(false)
            .setUsesChronometer(false)
        Status.Builder().addTemplate(pausedStatus).build()
    } else {
        val elapsedRealtime = SystemClock.elapsedRealtime()
        val timerLabel = when (timerUiState.timerType) {
            WorkoutTimerService.TimerType.REST -> context.getString(R.string.notif_timer_rest)
            WorkoutTimerService.TimerType.TIMED_DURATION_SET -> context.getString(R.string.notif_timer_set)
            WorkoutTimerService.TimerType.ENDURANCE_SET -> context.getString(R.string.notif_timer_set_elapsed)
            WorkoutTimerService.TimerType.SUPERSET_CAP -> context.getString(R.string.notif_timer_time_left)
            WorkoutTimerService.TimerType.SUPERSET_ROUND_CADENCE -> context.getString(R.string.notif_timer_round)
        }
        val timerPart = when (timerUiState.timerType) {
            WorkoutTimerService.TimerType.REST,
            WorkoutTimerService.TimerType.TIMED_DURATION_SET,
            WorkoutTimerService.TimerType.SUPERSET_CAP,
            WorkoutTimerService.TimerType.SUPERSET_ROUND_CADENCE ->
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
        nowBarText = timerLabel
        // RemoteViews is how the Now Bar card gets a live timer instead of static text.
        // Chronometer runs on the elapsedRealtime time base, not wall clock.
        val chronometerBase = if (isCountdown) {
            SystemClock.elapsedRealtime() + timerUiState.displayMillis
        } else {
            SystemClock.elapsedRealtime() - timerUiState.displayMillis
        }
        nowBarChronometer = RemoteViews(context.packageName, R.layout.nowbar_chronometer_remote).apply {
            setChronometerCountDown(R.id.nowbar_chronometer, isCountdown)
            // null format: let Chronometer pick MM:SS / H:MM:SS itself.
            setChronometer(R.id.nowbar_chronometer, chronometerBase, null, true)
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

    if (Build.MANUFACTURER.equals("samsung", ignoreCase = true)) {
        // One UI Watch's Now Bar draws OngoingActivity cards inside a hard-coded gray oval
        // inset by 2dp and animates only lottie:// icons. A card supplied by the
        // notification itself has no background icon, so the badge fills the whole slot.
        val icon = Icon.createWithContentUri(
            Uri.parse(
                "lottie://${context.packageName}/" +
                    context.resources.getResourceEntryName(R.raw.ongoing_workout_badge_lottie)
            )
        )
        val nowBarData = Bundle().apply {
            putInt("type", 1)
            putParcelable("cardIconLeft", icon)
            putParcelable("expandViewIcon", icon)
            putParcelable("queIcon", icon)
            putString("cardContents", nowBarText)
            putString("expandPrimaryInfo", nowBarText)
            putString("expandSecondaryInfo", context.getString(R.string.notif_workout_in_progress))
            nowBarChronometer?.let {
                putParcelable("cardChronometerRemoteView", it)
                putParcelable("expandChronometerRemoteView", it)
            }
        }
        notificationBuilder.addExtras(Bundle().apply {
            putBundle("customDisplayBundle", Bundle().apply {
                putBoolean("enableNowBar", true)
                putBundle("nowBarData", nowBarData)
            })
        })
    } else {
        // Stock Wear OS animates the AVD in the ongoing-activity chip directly.
        OngoingActivity.Builder(context, notificationId, notificationBuilder)
            .setAnimatedIcon(R.drawable.avd_ongoing_workout_badge)
            .setStaticIcon(R.drawable.ic_ongoing_workout_badge)
            .setTouchIntent(pendingIntent)
            .setStatus(ongoingActivityStatus)
            .build()
            .apply(context)
    }

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
    WorkoutComplication.clear(context)
}

@SuppressLint("MissingPermission")
fun showTimerCompletedNotification(
    context: Context,
    workoutGlobalId: UUID? = null,
    title: String = context.getString(R.string.notif_timer_completed),
    message: String = context.getString(R.string.notif_tap_to_continue_workout)
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
        context.getString(R.string.notif_channel_timer_completion),
        NotificationManager.IMPORTANCE_HIGH
    ).apply {
        description = context.getString(R.string.notif_channel_timer_completion_desc)
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

private const val SYNC_STATUS_CHANNEL_ID = "sync_status_channel"
private const val SYNC_COMPLETE_NOTIFICATION_ID = 2
private const val SYNC_IN_PROGRESS_NOTIFICATION_ID = 4

private fun ensureSyncStatusChannel(context: Context) {
    val channel = NotificationChannel(
        SYNC_STATUS_CHANNEL_ID,
        context.getString(R.string.notif_channel_sync_status),
        NotificationManager.IMPORTANCE_HIGH  // ensure sound and vibration
    ).apply {
        description = context.getString(R.string.notif_channel_sync_status_desc)
        enableVibration(true)
        setSound(null, null) // system default notification sound
    }
    val notificationManager: NotificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    notificationManager.createNotificationChannel(channel)
}

private fun syncStatusPendingIntent(context: Context): PendingIntent {
    val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)
    return PendingIntent.getActivity(
        context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
}

/**
 * Shown while a phone sync is running and the app is not in the foreground, so the transfer is
 * visible in the notification stream on Wear.
 */
@SuppressLint("MissingPermission")
fun showSyncInProgressNotification(context: Context) {
    ensureSyncStatusChannel(context)
    val notification = NotificationCompat.Builder(context, SYNC_STATUS_CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_workout_icon)
        .setContentTitle(context.getString(R.string.sync_notif_syncing_title))
        .setContentText(context.getString(R.string.sync_notif_syncing_text))
        .setContentIntent(syncStatusPendingIntent(context))
        .setOngoing(true)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setColor(ContextCompat.getColor(context, R.color.ic_launcher_background))
        .build()

    with(NotificationManagerCompat.from(context)) {
        notify(SYNC_IN_PROGRESS_NOTIFICATION_ID, notification)
    }
}

fun cancelSyncInProgressNotification(context: Context) {
    with(NotificationManagerCompat.from(context)) {
        cancel(SYNC_IN_PROGRESS_NOTIFICATION_ID)
    }
}

@SuppressLint("MissingPermission")
fun showSyncCompleteNotification(context: Context) {
    val channelId = SYNC_STATUS_CHANNEL_ID
    val notificationId = SYNC_COMPLETE_NOTIFICATION_ID

    val pendingIntent = syncStatusPendingIntent(context)
    ensureSyncStatusChannel(context)

    val notification = NotificationCompat.Builder(context, channelId)
        .setSmallIcon(R.drawable.ic_workout_icon)
        .setContentTitle(context.getString(R.string.notif_sync_complete))
        .setContentText(context.getString(R.string.notif_sync_complete_text))
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

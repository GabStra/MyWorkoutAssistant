package com.gabstra.myworkoutassistant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * Keeps [DataLayerListenerService] in the foreground from [Service.onCreate] so the system does
 * not kill the process before Google Play services delivers [com.google.android.gms.wearable.WearableListenerService.onDataChanged]
 * events. The notification is updated when an active sync starts.
 */
internal object DataLayerSyncForegroundHelper {

    private const val TAG = "DataLayerSyncForegroundHelper"
    private const val CHANNEL_ID = "data_layer_sync_foreground_channel"
    private const val NOTIFICATION_ID = 100

    /**
     * Call from [DataLayerListenerService.onCreate] immediately after [Service.onCreate] so the
     * WearableListenerService is already a foreground service before any Data Layer events arrive.
     */
    fun startFromServiceCreated(service: Service) {
        postForeground(
            service,
            title = service.getString(R.string.sync_notif_listening_title),
            text = service.getString(R.string.sync_notif_listening_text)
        )
    }

    /**
     * Call when a sync handshake or backup starts; updates the foreground notification.
     */
    fun startIfNeeded(service: Service) {
        postForeground(
            service,
            title = service.getString(R.string.sync_notif_syncing_title),
            text = service.getString(R.string.sync_notif_syncing_text)
        )
    }

    private fun ensureChannel(service: Service) {
        val nm = service.getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            service.getString(R.string.sync_notif_channel_phone_sync),
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = service.getString(R.string.sync_notif_channel_phone_sync_desc)
            setShowBadge(false)
        }
        nm.createNotificationChannel(channel)
    }

    private fun contentPendingIntent(service: Service): PendingIntent {
        val launchIntent = service.packageManager.getLaunchIntentForPackage(service.packageName)
            ?: Intent(Intent.ACTION_MAIN).apply {
                setPackage(service.packageName)
                addCategory(Intent.CATEGORY_LAUNCHER)
            }
        return PendingIntent.getActivity(
            service,
            0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun postForeground(service: Service, title: String, text: String) {
        ensureChannel(service)
        val notification = NotificationCompat.Builder(service, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_workout_icon)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(contentPendingIntent(service))
            .setColor(ContextCompat.getColor(service, R.color.ic_launcher_background))
            .build()
        try {
            ServiceCompat.startForeground(
                service,
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } catch (e: Exception) {
            Log.e(TAG, "startForeground failed title=$title", e)
        }
    }

    /**
     * Call from [Service.onDestroy] only. Do not stop mid-sync — that would drop process priority
     * before GMS finishes delivering Data Layer batches.
     */
    fun stopIfActive(service: Service) {
        try {
            ServiceCompat.stopForeground(service, ServiceCompat.STOP_FOREGROUND_DETACH)
        } catch (e: Exception) {
            Log.w(TAG, "stopForeground failed", e)
        }
    }
}

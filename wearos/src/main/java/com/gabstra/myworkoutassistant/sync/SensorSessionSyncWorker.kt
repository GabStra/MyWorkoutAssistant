package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.delay
import java.util.concurrent.TimeUnit

/**
 * Retries failed sensor-session transfers. Eligible sessions are COMPLETED sessions that are not
 * yet marked as synced; the transfer itself is handled by [SensorSessionSyncSender].
 */
class SensorSessionSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        return runCatching {
            val context = applicationContext
            // The session row is marked COMPLETED slightly before its chunks finish compressing;
            // give the capture pipeline a moment to settle before enumerating sessions.
            delay(COMPLETION_SETTLE_MS)

            val syncedIds = SensorSessionSyncedIdTracker.getSyncedIds(context)
            val pendingSessionIds = AppDatabase.getDatabase(context)
                .motionCaptureSyncDao()
                .getSessionsByStatus(MotionCaptureSessionStatus.COMPLETED.name)
                .map { it.id }
                .filterNot { it in syncedIds }
                .toSet()

            if (pendingSessionIds.isEmpty()) {
                Log.d(TAG, "SYNC_TRACE event=worker_noop side=wear channel=sensorSession reason=worker_retry")
                return@runCatching Result.success()
            }

            Log.d(
                TAG,
                "SYNC_TRACE event=worker_send side=wear channel=sensorSession pending=${pendingSessionIds.size}"
            )
            val result = SensorSessionSyncSender.send(
                context = context,
                dataClient = Wearable.getDataClient(context),
                sessionIds = pendingSessionIds
            )
            if (result.failedSessionIds.isEmpty()) {
                Result.success()
            } else {
                Log.w(
                    TAG,
                    "Sensor session sync failed for ${result.failedSessionIds.size} session(s); scheduling retry"
                )
                Result.retry()
            }
        }.getOrElse {
            Log.e(TAG, "Sensor session sync worker failed", it)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "SensorSessionSyncWorker"
        private const val UNIQUE_WORK_NAME = "wear_sensor_session_sync"
        private const val COMPLETION_SETTLE_MS = 10_000L

        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<SensorSessionSyncWorker>()
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                UNIQUE_WORK_NAME,
                ExistingWorkPolicy.APPEND_OR_REPLACE,
                request
            )
        }
    }
}

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
import com.google.android.gms.wearable.Wearable
import java.util.concurrent.TimeUnit

class WorkoutHistorySyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        return runCatching {
            val context = applicationContext
            val dataClient = Wearable.getDataClient(context)
            val validPendingIds = AppDatabase.getDatabase(context)
                .workoutHistoryDao()
                .getAllWorkoutHistoriesByIsDone(true)
                .map { it.id }
                .toSet()
                .intersect(PendingWorkoutHistorySyncTracker.getPendingIds(context))
            PendingWorkoutHistorySyncTracker.retain(context, validPendingIds)

            val pendingIds = validPendingIds
            if (pendingIds.isEmpty()) {
                Log.d(TAG, "SYNC_TRACE event=worker_noop side=wear channel=history reason=worker_retry")
                return Result.success()
            }

            val claim = WearOutboundWorkoutHistorySyncCoordinator.claimWorkerRetryBatch(pendingIds)
            if (claim == null || claim.claimedHistoryIds.isEmpty()) {
                Log.d(TAG, "SYNC_TRACE event=worker_noop side=wear channel=history reason=worker_retry pending=${pendingIds.size}")
                return Result.success()
            }

            Log.d(
                TAG,
                "SYNC_TRACE event=worker_claim side=wear channel=history reason=${claim.reason.wireValue} claimedHistoryCount=${claim.claimedHistoryIds.size}"
            )
            val result = WearCompletedHistorySyncSender.send(
                context = context,
                dataClient = dataClient,
                historyIds = claim.claimedHistoryIds,
                reason = claim.reason
            )
            val succeededHistoryIds = claim.claimedHistoryIds - result.failedHistoryIds
            if (succeededHistoryIds.isNotEmpty()) {
                PendingWorkoutHistorySyncTracker.dequeue(context, succeededHistoryIds)
            }
            val followUpDecision = WearOutboundWorkoutHistorySyncCoordinator.completeWorkerRetryBatch(
                claim = claim,
                failedHistoryIds = result.failedHistoryIds
            )
            if (followUpDecision is WearWorkoutHistorySyncDecision.EnqueueWorker) {
                Log.w(
                    TAG,
                    "SYNC_TRACE event=worker_retry side=wear channel=history reason=${followUpDecision.reason.wireValue} failedHistoryCount=${result.failedHistoryIds.size}"
                )
                Result.retry()
            } else {
                Result.success()
            }
        }.getOrElse {
            Log.e(TAG, "Workout history sync worker failed", it)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "WorkoutHistorySyncWorker"
        private const val UNIQUE_WORK_NAME = "wear_workout_history_sync"

        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<WorkoutHistorySyncWorker>()
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                UNIQUE_WORK_NAME,
                ExistingWorkPolicy.APPEND_OR_REPLACE,
                request
            )
        }
    }
}

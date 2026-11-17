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
import com.gabstra.myworkoutassistant.shared.profile.Profiles
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
            // Locate each queued history in whichever profile owns it. Validating against the
            // active profile alone would prune, and so lose, uploads queued before a switch.
            val profileByHistoryId = buildMap {
                Profiles.profiles(context).forEach { profile ->
                    AppDatabase.getDatabase(context, profile.id)
                        .workoutHistoryDao()
                        .getCompletedWorkoutHistoryIds()
                        .forEach { put(it, profile.id) }
                }
            }
            val validPendingIds = profileByHistoryId.keys
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
            // A batch can span profiles; send each group through its own database.
            val failedHistoryIds = claim.claimedHistoryIds
                .groupBy { profileByHistoryId[it] ?: Profiles.activeProfileId(context) }
                .flatMap { (profileId, ids) ->
                    WearCompletedHistorySyncSender.send(
                        context = context,
                        dataClient = dataClient,
                        historyIds = ids.toSet(),
                        reason = claim.reason,
                        profileId = profileId,
                    ).failedHistoryIds
                }
                .toSet()
            val succeededHistoryIds = claim.claimedHistoryIds - failedHistoryIds
            if (succeededHistoryIds.isNotEmpty()) {
                PendingWorkoutHistorySyncTracker.dequeue(context, succeededHistoryIds)
            }
            val followUpDecision = WearOutboundWorkoutHistorySyncCoordinator.completeWorkerRetryBatch(
                claim = claim,
                failedHistoryIds = failedHistoryIds
            )
            if (followUpDecision is WearWorkoutHistorySyncDecision.EnqueueWorker) {
                Log.w(
                    TAG,
                    "SYNC_TRACE event=worker_retry side=wear channel=history reason=${followUpDecision.reason.wireValue} failedHistoryCount=${failedHistoryIds.size}"
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

package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.data.sendWorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.Wearable
import java.util.UUID
import java.util.concurrent.TimeUnit

class WorkoutHistorySyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        return runCatching {
            val context = applicationContext
            val db = AppDatabase.getDatabase(context)
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val restHistoryDao = db.restHistoryDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
            val dataClient = Wearable.getDataClient(context)

            val pendingIds = PendingWorkoutHistorySyncTracker.getPendingIds(context)
            if (pendingIds.isEmpty()) {
                Log.d(TAG, "No pending Wear-originated workout histories to sync")
                return Result.success()
            }

            val allCompleted = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
            val validPendingIds = allCompleted.map { it.id }.toSet().intersect(pendingIds)
            PendingWorkoutHistorySyncTracker.retain(context, validPendingIds)
            val historiesToSync = allCompleted.filter { it.id in validPendingIds }
            if (historiesToSync.isEmpty()) {
                Log.d(TAG, "No completed pending Wear-originated workout histories to sync")
                return Result.success()
            }

            var hasFailures = false
            historiesToSync.forEach { workoutHistory ->
                try {
                    val workout = workoutStore.workouts.find { it.id == workoutHistory.workoutId }
                    if (workout == null) {
                        Log.w(TAG, "Skipping history ${workoutHistory.id}: workout not found")
                        return@forEach
                    }

                    val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                    val restHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(workoutHistory.id)
                    val exercises = workout.workoutComponents.filterIsInstance<Exercise>() +
                        workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                    val exerciseInfos = exercises.mapNotNull { exerciseInfoDao.getExerciseInfoById(it.id) }
                    val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                    val progressions = exerciseSessionProgressionDao.getByWorkoutHistoryId(workoutHistory.id)
                    val errorLogs = try {
                        (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                    } catch (e: Exception) {
                        Log.e(TAG, "Error getting error logs", e)
                        emptyList()
                    }

                    val tx = UUID.randomUUID().toString()
                    val (success, _) = sendWorkoutHistoryStore(
                        dataClient = dataClient,
                        workoutHistoryStore = WorkoutHistoryStore(
                            WorkoutHistory = workoutHistory,
                            SetHistories = setHistories,
                            ExerciseInfos = exerciseInfos,
                            WorkoutRecord = workoutRecord,
                            ExerciseSessionProgressions = progressions,
                            ErrorLogs = errorLogs,
                            RestHistories = restHistories
                        ),
                        context = context,
                        transactionId = tx
                    )

                    if (success) {
                        PendingWorkoutHistorySyncTracker.dequeue(context, workoutHistory.id)
                        if (errorLogs.isNotEmpty()) {
                            runCatching {
                                (context.applicationContext as? MyApplication)?.clearErrorLogs()
                            }.onFailure { Log.e(TAG, "Error clearing error logs", it) }
                        }
                    } else {
                        hasFailures = true
                        Log.w(TAG, "Sync failed for history ${workoutHistory.id}; will retry")
                    }
                } catch (e: Exception) {
                    hasFailures = true
                    Log.e(TAG, "Error syncing history ${workoutHistory.id}", e)
                }
            }

            if (hasFailures) Result.retry() else Result.success()
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

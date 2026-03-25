package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.sendAppBackup
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.TimeUnit

class MobileSyncToWatchWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        return runCatching {
            val context = applicationContext
            val dataClient = Wearable.getDataClient(context)
            val db = AppDatabase.getDatabase(context)
            val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
            val workoutStore = workoutStoreRepository.getWorkoutStore()

            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val restHistoryDao = db.restHistoryDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            val allowedWorkouts = workoutStore.workouts.filter { workout ->
                workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
            }

            val adjustedWorkouts = allowedWorkouts.map { workout ->
                val adjustedWorkoutComponents = workout.workoutComponents.map { workoutComponent ->
                    when (workoutComponent) {
                        is Exercise -> workoutComponent.copy(
                            sets = ensureRestSeparatedBySets(workoutComponent.sets),
                            requiredAccessoryEquipmentIds = workoutComponent.requiredAccessoryEquipmentIds ?: emptyList()
                        )
                        is Superset -> workoutComponent.copy(
                            exercises = workoutComponent.exercises.map { exercise ->
                                exercise.copy(
                                    sets = ensureRestSeparatedBySets(exercise.sets),
                                    requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()
                                )
                            }
                        )
                        is Rest -> workoutComponent
                    }
                }
                workout.copy(
                    workoutComponents = ensureRestSeparatedByExercises(adjustedWorkoutComponents)
                )
            }

            val workoutRecords = workoutRecordDao.getAll()
            val filteredWorkoutHistories = workoutHistories.filter { workoutHistory ->
                allowedWorkouts.any { it.id == workoutHistory.workoutId } &&
                    (workoutHistory.isDone || workoutRecords.any { it.workoutHistoryId == workoutHistory.id })
            }

            val allExercises = allowedWorkouts.flatMap { workout ->
                workout.workoutComponents.filterIsInstance<Exercise>() +
                    workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
            }.distinctBy { it.id }

            val workoutHistoryIdsByExercise = allExercises.mapNotNull { exercise ->
                val setHistoriesForExercise = setHistoryDao.getSetHistoriesByExerciseId(exercise.id)
                val workoutHistoryIds = setHistoriesForExercise.mapNotNull { it.workoutHistoryId }.distinct()
                if (workoutHistoryIds.isEmpty()) null else exercise.id to workoutHistoryIds
            }.toMap()

            val workoutHistoriesByExerciseId = workoutHistoryIdsByExercise.mapValues { (_, ids) ->
                filteredWorkoutHistories
                    .filter { it.id in ids }
                    .sortedByDescending { it.startTime }
                    .take(15)
                    .map { it.id }
            }

            val requiredWorkoutHistoryIds = workoutHistoriesByExerciseId.values.flatten().toSet()
            val validWorkoutHistories = filteredWorkoutHistories.filter { it.id in requiredWorkoutHistoryIds }
            val validWorkoutHistoryIds = validWorkoutHistories
                .map { it.id }
                .toHashSet()
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                setHistory.workoutHistoryId != null &&
                    setHistory.workoutHistoryId in validWorkoutHistoryIds
            }
            val restHistories = restHistoryDao.getAll().filter { rest ->
                rest.workoutHistoryId != null && rest.workoutHistoryId in validWorkoutHistoryIds
            }
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val exerciseSessionProgressions = exerciseSessionProgressionDao
                .getAllExerciseSessionProgressions()
                .filter { progression -> progression.workoutHistoryId in validWorkoutHistoryIds }
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            val appBackup = AppBackup(
                workoutStore.copy(workouts = adjustedWorkouts),
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() },
                restHistories
            )

            workerSyncMutex.withLock {
                sendAppBackup(dataClient, appBackup, context)
            }
            PhoneToWatchSyncCoordinator.onWorkerSyncAttemptSucceeded(context.applicationContext)
            Result.success()
        }.getOrElse { exception ->
            Log.e(TAG, "Mobile sync worker failed", exception)
            PhoneToWatchSyncCoordinator.onWorkerSyncAttemptWillRetry(applicationContext)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "MobileSyncToWatchWorker"
        const val UNIQUE_WORK_NAME = "mobile_sync_to_watch"
        private val workerSyncMutex = Mutex()

        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>()
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                UNIQUE_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request
            )
        }
    }
}

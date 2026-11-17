package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.sendAppBackup
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.WorkoutStoreValidationException
import com.gabstra.myworkoutassistant.shared.profile.UserProfile
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.motion.collectExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.sortedLatestFirst
import com.gabstra.myworkoutassistant.shared.validateWorkoutStoreForRuntimeUse
import com.gabstra.myworkoutassistant.shared.workout.model.isNormallyCompleted
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID
import java.util.concurrent.TimeUnit

class MobileSyncToWatchWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        val isManualSync = inputData.getBoolean(INPUT_IS_MANUAL_SYNC, false)
        val isFinalJob = inputData.getBoolean(INPUT_IS_FINAL_JOB, true)
        val isGlobalSync = inputData.getBoolean(INPUT_IS_GLOBAL_SYNC, true)
        val capturedFingerprint = inputData.getString(INPUT_SYNC_FINGERPRINT)
        // Push the profile this run targets, not necessarily the one the phone is showing.
        val targetProfileId = inputData.getString(INPUT_PROFILE_ID)
            ?: Profiles.activeProfileId(applicationContext)
        var transactionId: String? = null
        return runCatching {
            val context = applicationContext
            val dataClient = Wearable.getDataClient(context)
            val targetProfile = Profiles.profiles(context).firstOrNull { it.id == targetProfileId }
            if (targetProfile == null) {
                // A profile can be deleted between enqueue and execution. Skipping keeps the
                // remaining profile jobs alive and avoids recreating deleted data on the watch.
                Log.w(TAG, "Skipping sync for profile $targetProfileId: it is no longer on this phone")
                if (isGlobalSync && isFinalJob) {
                    PhoneToWatchSyncCoordinator.onWorkerSyncAttemptSucceeded(
                        context.applicationContext,
                        capturedFingerprint,
                        isManualSync,
                    )
                }
                return Result.success()
            }
            val db = AppDatabase.getDatabase(context, targetProfileId)
            val workoutStoreRepository = WorkoutStoreRepository(
                Profiles.directory(context, targetProfileId),
                context.filesDir,
            )
            val workoutStore = workoutStoreRepository.getWorkoutStore()
            validateWorkoutStoreForRuntimeUse(workoutStore)

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

            // Plateau-style pruning above can drop an in-progress session from every exercise's
            // "top 15" window (e.g. shared exercise id across many programs, or zero set rows yet).
            // Workout records still reference that history; Wear merge drops records without a
            // matching history in the payload, which hides Resume after sync.
            val requiredFromActiveRecords = workoutRecords
                .asSequence()
                .filter { record -> allowedWorkouts.any { it.id == record.workoutId } }
                .map { it.workoutHistoryId }
                .toSet()

            // Next-prescription guidance needs only the parent session row of the latest normally
            // completed step; it must survive even when that step left no measured set rows to make
            // it into an exercise's top-15 history window.
            val requiredFromRecurringPrescriptions = requiredRecurringPrescriptionHistoryIds(
                allowedWorkouts = allowedWorkouts,
                histories = filteredWorkoutHistories,
            )

            val requiredWorkoutHistoryIds =
                workoutHistoriesByExerciseId.values.flatten().toSet() +
                    requiredFromActiveRecords +
                    requiredFromRecurringPrescriptions
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

            val adjustedWorkoutStore = adjustedWorkoutStoreForPhoneSync(workoutStore)
            val appBackup = AppBackup(
                adjustedWorkoutStore,
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() },
                restHistories,
                ExerciseMovements = collectExerciseMovementBackups(context, adjustedWorkoutStore),
                ProfileId = targetProfileId,
                ProfileName = targetProfile.name,
            )

            workerSyncMutex.withLock {
                Log.d(
                    TAG,
                    "SYNC_TRACE event=worker_start side=mobile channel=full_backup"
                )
                sendAppBackup(
                    dataClient = dataClient,
                    appBackup = appBackup,
                    context = context,
                    onProgress = { phase, acknowledgedProgress ->
                        transactionId?.let { activeTransactionId ->
                            if (isGlobalSync) {
                                PhoneToWatchSyncCoordinator.updateManualSyncState(
                                    transactionId = activeTransactionId,
                                    phase = phase,
                                    progress = acknowledgedProgress,
                                )
                            }
                        }
                    },
                    onTransactionStarted = { startedTransactionId ->
                        transactionId = startedTransactionId
                        if (isGlobalSync) {
                            PhoneToWatchSyncCoordinator.onTransactionStarted(startedTransactionId)
                        }
                    },
                )
            }
            Log.d(
                TAG,
                "SYNC_TRACE event=worker_complete side=mobile channel=full_backup"
            )
            if (isGlobalSync && isFinalJob) {
                PhoneToWatchSyncCoordinator.onWorkerSyncAttemptSucceeded(
                    context.applicationContext,
                    capturedFingerprint,
                    isManualSync
                )
            }
            Result.success()
        }.getOrElse { exception ->
            if (exception is CancellationException) {
                if (isGlobalSync) PhoneToWatchSyncCoordinator.onWorkerSyncStopped()
                throw exception
            }
            if (exception is WorkoutStoreValidationException) {
                Log.e(TAG, "Mobile sync worker aborted because workout-store validation failed: ${exception.userMessage}")
                if (isGlobalSync) PhoneToWatchSyncCoordinator.onWorkerSyncStopped()
                return Result.failure()
            }
            Log.e(TAG, "SYNC_TRACE event=worker_retry side=mobile channel=full_backup", exception)
            Log.e(TAG, "Mobile sync worker failed", exception)
            val shouldRetry = !isGlobalSync ||
                PhoneToWatchSyncCoordinator.onWorkerSyncAttemptWillRetry(applicationContext)
            if (shouldRetry) {
                Result.retry()
            } else {
                // A user-triggered manual sync is being enqueued immediately, so avoid leaving the old
                // failed unique work in exponential backoff ahead of the replacement request.
                Result.success()
            }
        }
    }

    companion object {
        private const val TAG = "MobileSyncToWatchWorker"
        const val UNIQUE_WORK_NAME = "mobile_sync_to_watch"
        const val SYNC_TAG = "mobile_sync_to_watch_work"
        private const val INPUT_IS_MANUAL_SYNC = "is_manual_sync"
        private const val INPUT_PROFILE_ID = "profile_id"
        private const val INPUT_IS_FINAL_JOB = "is_final_job"
        private const val INPUT_IS_GLOBAL_SYNC = "is_global_sync"
        private const val INPUT_SYNC_FINGERPRINT = "sync_fingerprint"
        private val workerSyncMutex = Mutex()

        fun enqueue(context: Context, fingerprint: String? = null) {
            enqueueInternal(context, ExistingWorkPolicy.KEEP, fingerprint = fingerprint)
        }

        fun enqueueManual(context: Context, fingerprint: String? = null) {
            enqueueInternal(
                context,
                ExistingWorkPolicy.REPLACE,
                isManualSync = true,
                fingerprint = fingerprint,
            )
        }

        /** Pushes one profile's data, e.g. after a watch claims that profile. */
        fun enqueueForProfile(context: Context, profileId: String) {
            val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>()
                .setInputData(
                    workDataOf(
                        INPUT_IS_MANUAL_SYNC to false,
                        INPUT_PROFILE_ID to profileId,
                        INPUT_IS_FINAL_JOB to true,
                        INPUT_IS_GLOBAL_SYNC to false,
                    )
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build()
            // Its own chain per profile: sharing the active profile's unique name would let
            // KEEP drop this push and REPLACE (manual sync) cancel it.
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                "${UNIQUE_WORK_NAME}_$profileId",
                ExistingWorkPolicy.KEEP,
                request,
            )
        }

        private fun enqueueInternal(
            context: Context,
            policy: ExistingWorkPolicy,
            isManualSync: Boolean = false,
            fingerprint: String? = null,
        ) {
            val jobs = planProfileSyncJobs(Profiles.profiles(context.applicationContext))
            if (jobs.isEmpty()) {
                Log.w(TAG, "No phone profiles to sync")
                return
            }
            val requests = jobs.map { job ->
                OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>()
                    .setInputData(
                        workDataOf(
                            INPUT_IS_MANUAL_SYNC to isManualSync,
                            INPUT_PROFILE_ID to job.profileId,
                            INPUT_IS_FINAL_JOB to job.isFinalJob,
                            INPUT_IS_GLOBAL_SYNC to true,
                            INPUT_SYNC_FINGERPRINT to fingerprint,
                        )
                    )
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                    .addTag(SYNC_TAG)
                    .build()
            }
            val workManager = WorkManager.getInstance(context.applicationContext)
            var continuation = workManager.beginUniqueWork(
                UNIQUE_WORK_NAME,
                policy,
                requests.first(),
            )
            requests.drop(1).forEach { request ->
                continuation = continuation.then(request)
            }
            continuation.enqueue()
        }
    }
}

/** Normalize the complete shared workout list; only history rows are profile-pruned. */
internal fun adjustedWorkoutStoreForPhoneSync(workoutStore: WorkoutStore): WorkoutStore =
    workoutStore.copy(workouts = workoutStore.workouts.map { workout ->
        val components = workout.workoutComponents.map { component ->
            when (component) {
                is Exercise -> component.copy(
                    sets = ensureRestSeparatedBySets(component.sets),
                    requiredAccessoryEquipmentIds = component.requiredAccessoryEquipmentIds ?: emptyList(),
                )
                is Superset -> component.copy(
                    exercises = component.exercises.map { exercise ->
                        exercise.copy(
                            sets = ensureRestSeparatedBySets(exercise.sets),
                            requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList(),
                        )
                    },
                )
                is Rest -> component
            }
        }
        workout.copy(workoutComponents = ensureRestSeparatedByExercises(components))
    })

internal data class ProfileSyncJob(
    val profileId: String,
    val profileName: String,
    val isFinalJob: Boolean,
)

/**
 * Freezes the profile set at enqueue time. Each job carries its own pinned source profile id,
 * so scheduling never depends on (or changes) the phone's active profile. Duplicate ids in a
 * corrupt index are collapsed to one job.
 */
internal fun planProfileSyncJobs(profiles: List<UserProfile>): List<ProfileSyncJob> {
    val distinctProfiles = profiles.distinctBy { it.id }
    return distinctProfiles.mapIndexed { index, profile ->
        ProfileSyncJob(
            profileId = profile.id,
            profileName = profile.name,
            isFinalJob = index == distinctProfiles.lastIndex,
        )
    }
}

/**
 * Parent history ids that must accompany the synced store so the watch can resolve the next
 * prescription for each active recurring family. Only normally completed sessions inside
 * [allowedWorkouts] are considered; set-row eligibility is intentionally irrelevant here.
 */
internal fun requiredRecurringPrescriptionHistoryIds(
    allowedWorkouts: List<Workout>,
    histories: List<WorkoutHistory>,
): Set<UUID> {
    val completedHistories = histories.filter { it.isNormallyCompleted() }
    val activeFamilies = allowedWorkouts
        .filter { it.isActive && it.enabled && it.recurringSessionId != null }
        .groupBy { it.recurringSessionId }

    return activeFamilies.values.flatMap { family ->
        val familyGlobalIds = family.map { it.globalId }.toSet()
        val sessionId = family.first().recurringSessionId
        completedHistories
            .filter { history ->
                history.globalId in familyGlobalIds &&
                    (history.recurringSessionId == null || history.recurringSessionId == sessionId)
            }
            .sortedLatestFirst()
            .take(1)
            .map { it.id }
    }.toSet()
}

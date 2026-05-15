package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.data.sendWorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.findWorkoutForHistory
import com.google.android.gms.wearable.DataClient
import kotlinx.coroutines.sync.withLock
import java.util.UUID

internal data class WearCompletedHistorySyncResult(
    val attemptedHistoryIds: Set<UUID>,
    val failedHistoryIds: Set<UUID>
)

internal object WearCompletedHistorySyncSender {
    private const val TAG = "WearCompletedHistorySyncSender"
    private const val LOG_TAG = "WorkoutSync"

    suspend fun send(
        context: Context,
        dataClient: DataClient,
        historyIds: Set<UUID>,
        reason: WearWorkoutHistorySyncReason,
        transactionRegistrar: ((transactionId: String, workoutHistoryId: UUID) -> Unit)? = null
    ): WearCompletedHistorySyncResult {
        if (historyIds.isEmpty()) {
            return WearCompletedHistorySyncResult(emptySet(), emptySet())
        }

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()
        val restHistoryDao = db.restHistoryDao()
        val workoutRecordDao = db.workoutRecordDao()
        val exerciseInfoDao = db.exerciseInfoDao()
        val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val allCompleted = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
        val completedById = allCompleted.associateBy { it.id }

        val attemptedIds = linkedSetOf<UUID>()
        val failedIds = linkedSetOf<UUID>()

        for (historyId in historyIds) {
            val workoutHistory = completedById[historyId] ?: continue
            attemptedIds += historyId
            try {
                val workout = workoutStore.findWorkoutForHistory(workoutHistory)
                if (workout == null) {
                    Log.w(TAG, "reason=${reason.wireValue} historyId=$historyId skipped because workout was not found")
                    continue
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(historyId)
                val exerciseInfos = workout.workoutComponents
                    .flatMap { component ->
                        when (component) {
                            is com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise -> listOf(component)
                            is com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset -> component.exercises
                            else -> emptyList()
                        }
                    }
                    .mapNotNull { exerciseInfoDao.getExerciseInfoById(it.id) }
                val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                val exerciseSessionProgressions =
                    exerciseSessionProgressionDao.getByWorkoutHistoryId(historyId)
                val errorLogs = runCatching {
                    (context.applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                }.getOrElse {
                    Log.e(TAG, "reason=${reason.wireValue} historyId=$historyId failed to read error logs", it)
                    emptyList()
                }
                val transactionId = UUID.randomUUID().toString()
                transactionRegistrar?.invoke(transactionId, historyId)

                Log.d(
                    LOG_TAG,
                    "SYNC_TRACE event=direct_send side=wear channel=history reason=${reason.wireValue} historyId=$historyId tx=$transactionId"
                )
                val success = sendWorkoutHistoryStore(
                    dataClient = dataClient,
                    workoutHistoryStore = WorkoutHistoryStore(
                        WorkoutHistory = workoutHistory,
                        SetHistories = setHistories,
                        ExerciseInfos = exerciseInfos,
                        WorkoutRecord = workoutRecord,
                        ExerciseSessionProgressions = exerciseSessionProgressions,
                        ErrorLogs = errorLogs,
                        RestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(historyId)
                    ),
                    context = context,
                    transactionId = transactionId
                ).first

                if (!success) {
                    failedIds += historyId
                    Log.w(
                        LOG_TAG,
                        "SYNC_TRACE event=direct_send_failed side=wear channel=history reason=${reason.wireValue} historyId=$historyId tx=$transactionId"
                    )
                } else if (errorLogs.isNotEmpty()) {
                    runCatching {
                        (context.applicationContext as? MyApplication)?.clearErrorLogs()
                    }.onFailure {
                        Log.e(TAG, "reason=${reason.wireValue} historyId=$historyId failed to clear error logs", it)
                    }
                }
            } catch (exception: Exception) {
                failedIds += historyId
                Log.e(
                    TAG,
                    "reason=${reason.wireValue} historyId=$historyId failed during completed-history sync",
                    exception
                )
            }
        }

        return WearCompletedHistorySyncResult(
            attemptedHistoryIds = attemptedIds,
            failedHistoryIds = failedIds
        )
    }
}

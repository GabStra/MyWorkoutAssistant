package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.sync.PendingWorkoutHistorySyncTracker
import com.gabstra.myworkoutassistant.sync.WorkoutHistorySyncWorker
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking

object CrossDeviceWearSyncStateHelper {
    fun clearWearHistoryState(context: Context) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        PendingWorkoutHistorySyncTracker.clear(context)
    }

    fun waitForWearSyncMarker(
        context: Context,
        timeoutMs: Long = E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
    ) = runBlocking {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (PendingWorkoutHistorySyncTracker.getPendingIds(context).isEmpty()) {
                return@runBlocking
            }
            delay(500)
        }
        error("Pending Wear workout history sync queue did not drain within ${timeoutMs}ms.")
    }

    fun waitForCompletedHistoryAndEnqueueSync(
        context: Context,
        timeoutMs: Long = 20_000
    ) = runBlocking {
        val workoutHistoryDao = AppDatabase.getDatabase(context).workoutHistoryDao()
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val completed = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
            if (completed.isNotEmpty()) {
                waitForPhoneConnection(context, timeoutMs = timeoutMs)
                PendingWorkoutHistorySyncTracker.enqueue(
                    context,
                    completed.map { it.id }
                )
                WorkoutHistorySyncWorker.enqueue(context)
                return@runBlocking
            }
            delay(500)
        }
        error("Completed workout history row was not persisted on Wear within ${timeoutMs}ms.")
    }

    private suspend fun waitForPhoneConnection(
        context: Context,
        timeoutMs: Long
    ) {
        val nodeClient = Wearable.getNodeClient(context)
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val connectedNodes = runCatching { Tasks.await(nodeClient.connectedNodes) }
                .getOrDefault(emptyList())
            if (connectedNodes.isNotEmpty()) {
                return
            }
            delay(500)
        }
        error("Wear device did not regain a connected phone node within ${timeoutMs}ms.")
    }
}

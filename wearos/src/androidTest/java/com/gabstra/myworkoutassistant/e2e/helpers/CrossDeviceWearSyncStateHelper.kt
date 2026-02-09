package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.sync.WorkoutHistorySyncWorker
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking

object CrossDeviceWearSyncStateHelper {
    fun clearWearHistoryState(context: Context) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        context.getSharedPreferences("synced_workout_history_ids", Context.MODE_PRIVATE)
            .edit()
            .remove("ids")
            .apply()
    }

    fun waitForWearSyncMarker(context: Context, timeoutMs: Long = 120_000) = runBlocking {
        val prefs = context.getSharedPreferences("synced_workout_history_ids", Context.MODE_PRIVATE)
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val ids = prefs.getStringSet("ids", emptySet()) ?: emptySet()
            if (ids.isNotEmpty()) {
                return@runBlocking
            }
            delay(1_000)
        }
        error("Workout sync marker was not written on Wear within ${timeoutMs}ms.")
    }

    fun waitForCompletedHistoryAndEnqueueSync(context: Context, timeoutMs: Long = 30_000) = runBlocking {
        val workoutHistoryDao = AppDatabase.getDatabase(context).workoutHistoryDao()
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val completed = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
            if (completed.isNotEmpty()) {
                WorkoutHistorySyncWorker.enqueue(context)
                return@runBlocking
            }
            delay(1_000)
        }
        error("Completed workout history row was not persisted on Wear within ${timeoutMs}ms.")
    }
}

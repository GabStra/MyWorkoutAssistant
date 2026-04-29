package com.gabstra.myworkoutassistant.e2e

import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ExactBackupPhoneToWearResumeRecordVerificationE2ETest {

    @Test
    fun phoneSync_preservesResumeRecordForTargetWorkoutOnWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val workoutRecordDao = db.workoutRecordDao()
        val workoutHistoryDao = db.workoutHistoryDao()

        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            val targetRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(TARGET_WORKOUT_ID)
            val targetHistory = targetRecord?.let { workoutHistoryDao.getWorkoutHistoryById(it.workoutHistoryId) }
            if (targetRecord != null && targetHistory != null && !targetHistory.isDone) {
                Log.d(
                    TAG,
                    "Target resume pair found on wear: record=${targetRecord.id}, history=${targetHistory.id}"
                )
                return@runBlocking
            }
            delay(500)
        }

        val allRecords = workoutRecordDao.getAll()
        val targetRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(TARGET_WORKOUT_ID)
        val targetHistory = workoutHistoryDao.getWorkoutHistoryById(TARGET_WORKOUT_HISTORY_ID)
        val targetWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            .filter { it.workoutId == TARGET_WORKOUT_ID || it.globalId == TARGET_WORKOUT_GLOBAL_ID }
            .sortedByDescending { it.startTime }

        val traceMessage = buildString {
            appendLine("Target resume pair missing on wear after phone sync.")
            appendLine("targetWorkoutId=$TARGET_WORKOUT_ID targetHistoryId=$TARGET_WORKOUT_HISTORY_ID")
            appendLine("recordForTargetWorkout=${targetRecord?.id ?: "null"}")
            appendLine("recordForTargetWorkout.historyId=${targetRecord?.workoutHistoryId ?: "null"}")
            appendLine("targetHistoryExists=${targetHistory != null} targetHistoryIsDone=${targetHistory?.isDone}")
            appendLine("allRecordWorkoutIds=${allRecords.map { it.workoutId to it.workoutHistoryId }}")
            appendLine(
                "targetWorkoutHistories=${
                    targetWorkoutHistories.map { history ->
                        Triple(history.id, history.isDone, history.startTime)
                    }
                }"
            )
        }
        Log.e(TAG, traceMessage)
        error(traceMessage)
    }

    companion object {
        private const val TAG = "ExactBackupWearResumeE2E"
        private val TARGET_WORKOUT_ID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
        private val TARGET_WORKOUT_HISTORY_ID = UUID.fromString("9b67898a-febe-4c09-9d4e-830cff9ca864")
        private val TARGET_WORKOUT_GLOBAL_ID = UUID.fromString("63c3379f-f734-424c-94e5-05af28a945f8")
    }
}

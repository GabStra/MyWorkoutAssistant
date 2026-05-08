package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDeviceSyncSpec
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ResumePhoneToWearWorkoutHistorySyncVerificationE2ETest {
    @Test
    fun phoneSync_sendsResumeStateToWearWithoutDuplicatingCompletedExercises() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)

        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        var matchedHistoryId: UUID? = null

        while (System.currentTimeMillis() < deadline) {
            val workoutRecord = db.workoutRecordDao()
                .getWorkoutRecordByWorkoutId(ResumeCrossDeviceSyncSpec.WORKOUT_ID)
            val history = workoutRecord?.let { db.workoutHistoryDao().getWorkoutHistoryById(it.workoutHistoryId) }
            val setHistories = history?.let { db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(it.id) }

            val historyMatches = history != null &&
                !history.isDone &&
                history.id == ResumeCrossDeviceSyncSpec.INCOMPLETE_HISTORY_ID &&
                history.workoutId == ResumeCrossDeviceSyncSpec.WORKOUT_ID &&
                history.globalId == ResumeCrossDeviceSyncSpec.WORKOUT_GLOBAL_ID
            val setStateMatches = setHistories != null && hasNoDuplicatePreviouslyCompletedExerciseRows(setHistories)

            if (historyMatches && setStateMatches) {
                matchedHistoryId = history.id
                break
            }
            delay(500)
        }

        require(matchedHistoryId != null) {
            "Expected synced resume history not found on Wear without duplicates. " +
                "workoutId=${ResumeCrossDeviceSyncSpec.WORKOUT_ID} historyId=${ResumeCrossDeviceSyncSpec.INCOMPLETE_HISTORY_ID}"
        }
    }

    private fun hasNoDuplicatePreviouslyCompletedExerciseRows(
        setHistories: List<com.gabstra.myworkoutassistant.shared.SetHistory>
    ): Boolean {
        val duplicateSetIds = setHistories.groupingBy { it.setId }.eachCount().filterValues { it > 1 }
        if (duplicateSetIds.isNotEmpty()) {
            return false
        }
        val countsByExercise = setHistories.groupingBy { it.exerciseId }.eachCount()
        return ResumeCrossDeviceSyncSpec.SEEDED_EXERCISE_EXACT_COUNTS.all { (exerciseId, expectedCount) ->
            countsByExercise[exerciseId] == expectedCount
        }
    }
}

package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class WorkoutFinishEarlySyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
        val EXPECTED_SET_IDS = listOf(
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_ID
        )
        val EXPECTED_SKIPPED_SET_IDS = EXPECTED_SET_IDS.drop(1).toSet()
    }

    @Test
    fun crossDeviceSync_finishEarlyArrivesAsClosedEarlyEndedHistoryOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val timeoutMs = CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(45_000)
        val success = waitForFinishedEarlyState(context, timeoutMs)
        assertTrue(buildFailureMessage(context), success)
    }

    private suspend fun waitForFinishedEarlyState(
        context: android.content.Context,
        timeoutMs: Long
    ): Boolean {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs

        do {
            val matchingHistories = db.workoutHistoryDao()
                .getAllWorkoutHistories()
                .filter(::isRecentMatchingHistory)
                .filter { it.isDone && it.endReason == WorkoutSessionEndReason.FINISHED_EARLY }

            val activeRecord = db.workoutRecordDao()
                .getWorkoutRecordByWorkoutId(CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID)
            val unfinishedHistories = db.workoutHistoryDao()
                .getAllWorkoutHistories()
                .filter {
                    !it.isDone &&
                        it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                        it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                        isHistoryRecent(it)
                }

            val history = matchingHistories.singleOrNull()
            val hasExpectedSets = history?.let { matchingHistory ->
                val setHistories = db.setHistoryDao()
                    .getSetHistoriesByWorkoutHistoryIdOrdered(matchingHistory.id)
                val actualSetIds = setHistories.map { it.setId }
                val skippedSetIds = setHistories.filter { it.skipped }.map { it.setId }.toSet()
                actualSetIds == EXPECTED_SET_IDS &&
                    skippedSetIds == EXPECTED_SKIPPED_SET_IDS &&
                    setHistories.firstOrNull()?.skipped == false
            } == true

            if (matchingHistories.size == 1 && activeRecord == null && unfinishedHistories.isEmpty() && hasExpectedSets) {
                return true
            }

            if (System.currentTimeMillis() >= deadline) {
                return false
            }
            delay(500)
        } while (true)
    }

    private fun buildFailureMessage(context: android.content.Context): String {
        val db = AppDatabase.getDatabase(context)
        val matchingHistories = runBlocking {
            db.workoutHistoryDao()
                .getAllWorkoutHistories()
                .filter(::isRecentMatchingHistory)
        }
        val activeRecord = runBlocking {
            db.workoutRecordDao()
                .getWorkoutRecordByWorkoutId(CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID)
        }
        val unfinishedHistories = runBlocking {
            db.workoutHistoryDao().getAllWorkoutHistories().filter {
                !it.isDone &&
                    it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                    isHistoryRecent(it)
            }
        }
        val matchingSetSummary = runBlocking {
            matchingHistories.associate { history ->
                history.id to db.setHistoryDao()
                    .getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
                    .map { "${it.setId}:${it.skipped}" }
            }
        }

        return "Expected one recent FINISHED_EARLY synced history with skipped remaining sets and no active record. " +
            "histories=${matchingHistories.map { "${it.id}:${it.isDone}:${it.endReason}" }} " +
            "activeRecord=${activeRecord?.id} unfinishedHistories=${unfinishedHistories.map { it.id }} " +
            "setSummary=$matchingSetSummary"
    }

    private fun isRecentMatchingHistory(history: WorkoutHistory): Boolean {
        return history.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
            history.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
            isHistoryRecent(history)
    }

    private fun isHistoryRecent(history: WorkoutHistory): Boolean {
        val ageMinutes = Duration.between(history.startTime, LocalDateTime.now()).toMinutes()
        return ageMinutes in 0..HISTORY_RECENCY_MINUTES
    }
}

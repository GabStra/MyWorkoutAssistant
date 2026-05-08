package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDevicePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ResumeWorkoutDiscardSyncVerificationTest {

    @Test
    fun crossDeviceDiscard_removesIncompleteResumeStateFromPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val timeoutMs = CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(45_000)
        val success = waitForDiscardedState(context, timeoutMs)
        assertTrue(buildFailureMessage(context), success)
    }

    private suspend fun waitForDiscardedState(
        context: android.content.Context,
        timeoutMs: Long
    ): Boolean {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs

        do {
            val activeRecord = db.workoutRecordDao()
                .getWorkoutRecordByWorkoutId(ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID)
            val unfinishedHistories = db.workoutHistoryDao().getAllWorkoutHistories().filter {
                !it.isDone &&
                    it.workoutId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
            }
            val seededSetHistories = db.setHistoryDao()
                .getSetHistoriesByWorkoutHistoryIdOrdered(ResumeCrossDevicePhoneWorkoutStoreFixture.INCOMPLETE_HISTORY_ID)

            if (activeRecord == null && unfinishedHistories.isEmpty() && seededSetHistories.isEmpty()) {
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
        val activeRecord = runBlocking {
            db.workoutRecordDao().getWorkoutRecordByWorkoutId(ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID)
        }
        val unfinishedHistories = runBlocking {
            db.workoutHistoryDao().getAllWorkoutHistories().filter {
                !it.isDone &&
                    it.workoutId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
            }
        }
        val seededSetCount = runBlocking {
            db.setHistoryDao()
                .getSetHistoriesByWorkoutHistoryIdOrdered(ResumeCrossDevicePhoneWorkoutStoreFixture.INCOMPLETE_HISTORY_ID)
                .size
        }
        return "Expected Wear discard to clear the phone incomplete resume state. " +
            "activeRecord=${activeRecord?.id} unfinishedHistories=${unfinishedHistories.map { it.id }} " +
            "seededSetCount=$seededSetCount"
    }
}

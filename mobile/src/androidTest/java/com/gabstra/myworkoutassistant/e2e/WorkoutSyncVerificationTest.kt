package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutSyncVerificationTest {
    private fun resolvedSyncTimeoutMs(): Long = 45_000

    private suspend fun hasCompletedCrossDeviceHistory(
        context: android.content.Context
    ): Boolean {
        val db = AppDatabase.getDatabase(context)
        val expectedSetIds = CrossDeviceSyncAssertions.finalCheckpoint.expectedSetIds.toSet()
        val histories = db.workoutHistoryDao().getAllWorkoutHistories()

        return histories.any { history ->
                history.isDone &&
                history.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                history.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                db.setHistoryDao()
                    .getSetHistoriesByWorkoutHistoryId(history.id)
                    .map { it.setId }
                    .toSet() == expectedSetIds
        }
    }

    @Test
    fun crossDeviceSync_wearWorkoutHistoryArrivesOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assumeTrue(
            "Requires a completed cross-device sync history. Run via run_cross_device_sync_e2e.ps1.",
            hasCompletedCrossDeviceHistory(context)
        )

        CrossDeviceSyncAssertions.waitForCheckpoint(
            context = context,
            checkpoint = CrossDeviceSyncAssertions.finalCheckpoint,
            timeoutMs = resolvedSyncTimeoutMs()
        )

        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = resolvedSyncTimeoutMs()
        )
    }

    @Test
    fun crossDeviceSync_completionClearsActiveRecordAndUnfinishedHistory() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assumeTrue(
            "Requires a completed cross-device sync history. Run via run_cross_device_sync_e2e.ps1.",
            hasCompletedCrossDeviceHistory(context)
        )

        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = resolvedSyncTimeoutMs()
        )

        val db = AppDatabase.getDatabase(context)
        val activeRecord = db.workoutRecordDao()
            .getWorkoutRecordByWorkoutId(CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID)
        assertNull(
            "Expected the active Wear workout record to be cleared after completion sync.",
            activeRecord
        )

        val unfinishedHistories = db.workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                !it.isDone &&
                    it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
            }
        assertTrue(
            "Expected no unfinished histories to remain after completion sync, " +
                "but found ${unfinishedHistories.map { it.id }}.",
            unfinishedHistories.isEmpty()
        )
    }
}

package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class WorkoutSyncLateRetryIgnoredVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
        const val SYNC_TIMEOUT_MS = 45_000L
        const val POST_COMPLETION_GRACE_MS = 3_000L
    }

    private suspend fun hasRecentCompletedCrossDeviceHistory(
        context: android.content.Context
    ): Boolean {
        val db = AppDatabase.getDatabase(context)
        val expectedSetIds = CrossDeviceSyncAssertions.finalCheckpoint.expectedSetIds.toSet()
        val histories = db.workoutHistoryDao().getAllWorkoutHistories()

        return histories.any { history ->
            history.isDone &&
                history.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                history.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                Duration.between(history.startTime, LocalDateTime.now()).toMinutes() in 0..HISTORY_RECENCY_MINUTES &&
                db.setHistoryDao()
                    .getSetHistoriesByWorkoutHistoryId(history.id)
                    .map { it.setId }
                    .toSet() == expectedSetIds
        }
    }

    @Test
    fun crossDeviceSync_lateStaleRetryIsIgnoredAfterCompletion() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assumeTrue(
            "Requires a recent completed cross-device sync history. Run via run_cross_device_sync_e2e.ps1.",
            hasRecentCompletedCrossDeviceHistory(context)
        )

        CrossDeviceSyncAssertions.waitForCheckpoint(
            context = context,
            checkpoint = CrossDeviceSyncAssertions.finalCheckpoint,
            timeoutMs = SYNC_TIMEOUT_MS
        )
        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = SYNC_TIMEOUT_MS
        )

        val db = AppDatabase.getDatabase(context)
        val baselineMatchingHistories = db.workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                    Duration.between(it.startTime, LocalDateTime.now()).toMinutes() in 0..HISTORY_RECENCY_MINUTES
            }

        delay(POST_COMPLETION_GRACE_MS)
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()

        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = SYNC_TIMEOUT_MS
        )

        val afterGraceHistories = db.workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                    Duration.between(it.startTime, LocalDateTime.now()).toMinutes() in 0..HISTORY_RECENCY_MINUTES
            }

        assertEquals(
            "Expected late stale retry chunks not to create additional recent histories.",
            baselineMatchingHistories.map { it.id to it.isDone },
            afterGraceHistories.map { it.id to it.isDone }
        )
        assertTrue(
            "Expected exactly one completed recent history after the stale retry grace window, " +
                "but found ${afterGraceHistories.map { it.id to it.isDone }}.",
            afterGraceHistories.count { it.isDone } == 1
        )
        assertTrue(
            "Expected no recent unfinished histories after the stale retry grace window, " +
                "but found ${afterGraceHistories.filterNot { it.isDone }.map { it.id }}.",
            afterGraceHistories.none { !it.isDone }
        )
    }
}

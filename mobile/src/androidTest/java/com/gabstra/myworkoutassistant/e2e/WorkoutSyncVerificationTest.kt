package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class WorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
    }

    private fun resolvedSyncTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 45_000 else 120_000
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
    fun crossDeviceSync_wearWorkoutHistoryArrivesOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assumeTrue(
            "Requires a recent completed cross-device sync history. Run via run_cross_device_sync_e2e.ps1.",
            hasRecentCompletedCrossDeviceHistory(context)
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
}

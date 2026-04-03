package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgeFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.time.Duration.Companion.milliseconds

@RunWith(AndroidJUnit4::class)
class DoubleProgressionNoHistoryPhoneToWearWorkoutHistorySyncVerificationE2ETest {
    @Test
    fun phoneSync_doesNotSeedHistoricalSessionOnWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS

        while (System.currentTimeMillis() < deadline) {
            val syncedWorkoutPresent = repository.getWorkoutStore().workouts.any {
                it.id == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                    it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
            }
            val matchingDoneHistories = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .filter {
                    it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
                }
            if (syncedWorkoutPresent && matchingDoneHistories.isEmpty()) {
                return@runBlocking
            }
            delay(500)
        }

        val matchingDoneHistories = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
            .filter {
                it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                    it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
            }
        error(
            "Expected no phone-seeded previous-session history on Wear for the initial no-history sync. " +
                "foundHistoryIds=${matchingDoneHistories.joinToString(prefix = "[", postfix = "]") { it.id.toString() }}"
        )
    }
}

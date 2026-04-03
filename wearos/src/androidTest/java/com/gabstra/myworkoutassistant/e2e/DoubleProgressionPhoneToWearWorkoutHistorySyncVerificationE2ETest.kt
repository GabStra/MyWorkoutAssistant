package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgeFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class DoubleProgressionPhoneToWearWorkoutHistorySyncVerificationE2ETest {
    @Test
    fun phoneSync_sendsHistoricalPreviousSessionToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS

        while (System.currentTimeMillis() < deadline) {
            val matchingHistory = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .firstOrNull {
                    it.id == DoubleProgressionRoundTripBadgeFixture.PREVIOUS_SESSION_HISTORY_ID &&
                        it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
                }
            val setData = matchingHistory?.let {
                db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(
                    it.id,
                    DoubleProgressionRoundTripBadgeFixture.SET_ID
                )?.setData as? WeightSetData
            }
            if (
                setData != null &&
                setData.actualReps == DoubleProgressionRoundTripBadgeFixture.PREVIOUS_SESSION_REPS &&
                abs(setData.actualWeight - DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT) <=
                DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE
            ) {
                return@runBlocking
            }
            delay(500)
        }

        val candidateHistories = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
            .filter {
                it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                    it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
            }
            .sortedByDescending { it.startTime }
        error(
            "Expected phone-seeded previous-session history was not found on Wear within timeout. " +
                "Expected historyId=${DoubleProgressionRoundTripBadgeFixture.PREVIOUS_SESSION_HISTORY_ID}, " +
                "foundHistoryIds=${candidateHistories.joinToString(prefix = "[", postfix = "]") { it.id.toString() }}"
        )
    }
}

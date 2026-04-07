package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class AutoRegulationWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 180L
        const val POLL_INTERVAL_MS = 500L
    }

    private fun resolvedSyncTimeoutMs(): Long = 60_000

    @Test
    fun crossDeviceSync_twoWearAutoRegulationSessionsArriveOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + resolvedSyncTimeoutMs()

        while (System.currentTimeMillis() < deadline) {
            val matchingHistories = db.workoutHistoryDao().getAllWorkoutHistories()
                .filter(::isRecentMatchingHistory)

            val baselineHistory = matchingHistories.firstOrNull { history ->
                historyMatchesBaselineSession(db, history)
            }
            val adjustedHistory = matchingHistories.firstOrNull { history ->
                historyMatchesAdjustedSession(db, history)
            }

            if (baselineHistory != null && adjustedHistory != null) {
                return@runBlocking
            }
            delay(POLL_INTERVAL_MS)
        }

        val allMatchingIds = db.workoutHistoryDao().getAllWorkoutHistories()
            .filter(::isRecentMatchingHistory)
            .map { history -> buildHistorySummary(db, history) }
        error(
            "Expected both Wear-produced auto-regulation sessions on phone within timeout. " +
                "matchingHistories=$allMatchingIds"
        )
    }

    private fun isRecentMatchingHistory(history: WorkoutHistory): Boolean {
        val ageMinutes = Duration.between(history.startTime, LocalDateTime.now()).toMinutes()
        return history.isDone &&
            history.workoutId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.WORKOUT_ID &&
            history.globalId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
            ageMinutes in 0..HISTORY_RECENCY_MINUTES
    }

    private suspend fun historyMatchesBaselineSession(
        db: AppDatabase,
        history: WorkoutHistory
    ): Boolean {
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
        if (setHistories.size != 2) return false

        val firstSet = setHistories[0]
        val secondSet = setHistories[1]
        val firstData = firstSet.setData as? WeightSetData ?: return false
        val secondData = secondSet.setData as? WeightSetData ?: return false

        return firstSet.setId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_1_ID &&
            secondSet.setId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_2_ID &&
            firstData.actualReps in
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.MIN_REPS..
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.MAX_REPS &&
            secondData.actualReps == AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS &&
            abs(firstData.actualWeight - AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.WEIGHT_TOLERANCE &&
            abs(secondData.actualWeight - AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.WEIGHT_TOLERANCE
    }

    private suspend fun historyMatchesAdjustedSession(
        db: AppDatabase,
        history: WorkoutHistory
    ): Boolean {
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
        if (setHistories.size != 2) return false

        val firstSet = setHistories[0]
        val secondSet = setHistories[1]
        val firstData = firstSet.setData as? WeightSetData ?: return false
        val secondData = secondSet.setData as? WeightSetData ?: return false

        return firstSet.setId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_1_ID &&
            secondSet.setId == AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_2_ID &&
            firstData.actualReps == AutoRegulationSetBadgePhoneWorkoutStoreFixture.SECOND_SESSION_FIRST_SET_REPS &&
            secondData.actualReps == AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS &&
            abs(firstData.actualWeight - AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.WEIGHT_TOLERANCE &&
            abs(
                secondData.actualWeight -
                    AutoRegulationSetBadgePhoneWorkoutStoreFixture.EXPECTED_ADJUSTED_SECOND_SET_WEIGHT
            ) <= AutoRegulationSetBadgePhoneWorkoutStoreFixture.WEIGHT_TOLERANCE
    }

    private suspend fun buildHistorySummary(
        db: AppDatabase,
        history: WorkoutHistory
    ): String {
        val setSummary = db.setHistoryDao()
            .getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
            .joinToString(prefix = "[", postfix = "]") { setHistory ->
                val data = setHistory.setData as? WeightSetData
                "${setHistory.setId}:${data?.actualReps}@${data?.actualWeight}"
            }
        return "${history.id}:$setSummary"
    }
}

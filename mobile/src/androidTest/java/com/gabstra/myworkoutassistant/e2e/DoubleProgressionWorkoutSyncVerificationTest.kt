package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class DoubleProgressionWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 180L
        const val POLL_INTERVAL_MS = 500L
    }

    private fun resolvedSyncTimeoutMs(): Long = 60_000

    @Test
    fun crossDeviceSync_twoRoundTripDoubleProgressionSessionsArriveOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + resolvedSyncTimeoutMs()

        while (System.currentTimeMillis() < deadline) {
            val matchingHistories = db.workoutHistoryDao().getAllWorkoutHistories()
                .filter(::isRecentMatchingHistory)

            val repsByHistory = matchingHistories.mapNotNull { history ->
                val setHistory = db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(
                    history.id,
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SET_ID
                ) ?: return@mapNotNull null
                val setData = setHistory.setData as? WeightSetData ?: return@mapNotNull null
                setData.actualReps
            }.sorted()

            val exercise = repository.getWorkoutStore().workouts
                .firstOrNull {
                    it.id == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
                }
                ?.workoutComponents
                ?.singleOrNull() as? Exercise

            val nextSessionReps = (exercise?.sets?.singleOrNull()?.let { it as? com.gabstra.myworkoutassistant.shared.sets.WeightSet })?.reps

            if (
                repsByHistory == listOf(
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.PREVIOUS_SESSION_REPS,
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.FIRST_WEAR_SESSION_REPS,
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SECOND_WEAR_SESSION_REPS
                ) &&
                nextSessionReps == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SECOND_WEAR_SESSION_REPS
            ) {
                return@runBlocking
            }

            delay(POLL_INTERVAL_MS)
        }

        val allMatching = db.workoutHistoryDao().getAllWorkoutHistories()
            .filter(::isRecentMatchingHistory)
            .mapNotNull { history ->
                val setData = db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(
                    history.id,
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SET_ID
                )?.setData as? WeightSetData ?: return@mapNotNull null
                "${history.id}:${setData.actualReps}@${setData.actualWeight}"
            }
        val exercise = WorkoutStoreRepository(context.filesDir).getWorkoutStore().workouts
            .firstOrNull { it.id == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_ID }
            ?.workoutComponents
            ?.singleOrNull() as? Exercise
        error(
            "Expected seeded+two Wear double-progression histories on phone and aligned template reps=${DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SECOND_WEAR_SESSION_REPS}. " +
                "histories=$allMatching, currentStoreReps=${(exercise?.sets?.singleOrNull() as? com.gabstra.myworkoutassistant.shared.sets.WeightSet)?.reps}"
        )
    }

    private fun isRecentMatchingHistory(history: com.gabstra.myworkoutassistant.shared.WorkoutHistory): Boolean {
        val ageMinutes = Duration.between(history.startTime, LocalDateTime.now()).toMinutes()
        return history.isDone &&
            history.workoutId == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_ID &&
            history.globalId == DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
            ageMinutes in 0..HISTORY_RECENCY_MINUTES
    }
}

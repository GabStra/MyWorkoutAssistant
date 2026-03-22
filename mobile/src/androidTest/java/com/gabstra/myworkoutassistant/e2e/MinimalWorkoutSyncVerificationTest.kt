package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class MinimalWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
    }

    private suspend fun findRecentCompletedMinimalHistoryId(
        context: android.content.Context,
        timeoutMs: Long
    ): java.util.UUID? = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
        context = context,
        timeoutMs = timeoutMs
    ) { db, history ->
        history.isDone &&
            history.workoutId == MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
            history.globalId == MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
            Duration.between(history.startTime, LocalDateTime.now()).toMinutes() in 0..HISTORY_RECENCY_MINUTES &&
            db.setHistoryDao()
                .getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
                .map { it.setId } == MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.expectedSetIdsInOrder()
    }

    @Test
    fun crossDeviceSync_minimalWorkoutRetainsAllSetAndRestHistory() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = findRecentCompletedMinimalHistoryId(context, timeoutMs = 0)
        assumeTrue(
            "Requires a recent completed minimal cross-device sync history. Run MinimalPhoneSyncPreparationTest and WearMinimalCrossDeviceSetSyncProducerE2ETest first.",
            historyId != null
        )
        val db = AppDatabase.getDatabase(context)
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(checkNotNull(historyId))
        assertEquals(
            MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.expectedSetIdsInOrder(),
            setHistories.map { it.setId }
        )
        assertTrue(setHistories[0].setData is WeightSetData)
        assertTrue(setHistories[1].setData is RestSetData)
        assertTrue(setHistories[2].setData is WeightSetData)
        assertTrue(setHistories[3].setData is RestSetData)
        assertTrue(setHistories[4].setData is WeightSetData)

        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull {
            it.id == MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        } ?: error("Minimal synced workout store entry was not found.")
        val exercise = workout.workoutComponents.single() as? Exercise
            ?: error("Expected a single synced exercise in the minimal workout.")

        assertEquals(
            MinimalCrossDeviceSyncPhoneWorkoutStoreFixture.expectedSetIdsInOrder(),
            exercise.sets.map { it.id }
        )
        assertTrue(exercise.sets[0] is WeightSet)
        assertTrue(exercise.sets[1] is RestSet)
        assertTrue(exercise.sets[2] is WeightSet)
        assertTrue(exercise.sets[3] is RestSet)
        assertTrue(exercise.sets[4] is WeightSet)
    }
}

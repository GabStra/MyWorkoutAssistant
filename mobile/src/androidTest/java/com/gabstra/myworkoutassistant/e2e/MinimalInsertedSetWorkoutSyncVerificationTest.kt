package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class MinimalInsertedSetWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
    }

    private fun resolvedSyncTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 45_000 else 120_000
    }

    private suspend fun findRecentInsertedSetHistoryId(
        context: android.content.Context,
        timeoutMs: Long
    ): UUID? {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            val matchingHistoryId = db.workoutHistoryDao().getAllWorkoutHistories()
                .firstOrNull { history ->
                    if (!history.isDone ||
                        history.workoutId != MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.WORKOUT_ID ||
                        history.globalId != MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID ||
                        Duration.between(history.startTime, LocalDateTime.now()).toMinutes() !in 0..HISTORY_RECENCY_MINUTES
                    ) {
                        false
                    } else {
                        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
                        setHistories.size == 4 &&
                            setHistories[0].setId == MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_1_ID &&
                            setHistories[3].setId == MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_2_ID &&
                            setHistories[1].setId !in MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.initialSetIdsInOrder() &&
                            setHistories[2].setId !in MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.initialSetIdsInOrder() &&
                            setHistories[0].setData is WeightSetData &&
                            setHistories[1].setData is RestSetData &&
                            setHistories[2].setData is WeightSetData &&
                            setHistories[3].setData is WeightSetData
                    }
                }
                ?.id
            if (matchingHistoryId != null) {
                return matchingHistoryId
            }
            Thread.sleep(500)
        }
        return null
    }

    @Test
    fun crossDeviceSync_insertedMiddleSetRetainsOrderAndSavedWorkoutStructure() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val timeoutMs = resolvedSyncTimeoutMs()
        val db = AppDatabase.getDatabase(context)
        val historyId = findRecentInsertedSetHistoryId(context, timeoutMs)
            ?: error("Inserted-set synced workout history was not found.")
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(historyId)

        assertEquals(MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_1_ID, setHistories[0].setId)
        assertEquals(MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_2_ID, setHistories[3].setId)
        assertTrue(setHistories[1].setData is RestSetData)
        assertTrue(setHistories[2].setData is WeightSetData)

        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull {
            it.id == MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        } ?: error("Inserted-set synced workout store entry was not found.")
        val exercise = workout.workoutComponents.single() as? Exercise
            ?: error("Expected a single synced exercise in the inserted-set workout.")

        assertEquals(4, exercise.sets.size)
        assertEquals(MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_1_ID, exercise.sets[0].id)
        assertEquals(MinimalCrossDeviceInsertedSetPhoneWorkoutStoreFixture.SET_2_ID, exercise.sets[3].id)
        assertTrue(exercise.sets[1] is RestSet)
        assertTrue(exercise.sets[2] is WeightSet)
    }
}

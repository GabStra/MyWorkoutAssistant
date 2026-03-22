package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture
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
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class MinimalInsertedRestWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
    }

    private suspend fun findRecentInsertedRestHistoryId(
        context: android.content.Context,
        timeoutMs: Long
    ): UUID? = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
        context = context,
        timeoutMs = timeoutMs
    ) { db, history ->
        if (!history.isDone ||
            history.workoutId != MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.WORKOUT_ID ||
            history.globalId != MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID ||
            Duration.between(history.startTime, LocalDateTime.now()).toMinutes() !in 0..HISTORY_RECENCY_MINUTES
        ) {
            false
        } else {
            val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
            setHistories.size == 3 &&
                setHistories[0].setId == MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_1_ID &&
                setHistories[2].setId == MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_2_ID &&
                setHistories[1].setId !in MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.initialSetIdsInOrder() &&
                setHistories[0].setData is WeightSetData &&
                setHistories[1].setData is RestSetData &&
                setHistories[2].setData is WeightSetData
        }
    }

    @Test
    fun crossDeviceSync_insertedMiddleRestRetainsOrderAndSavedWorkoutStructure() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = findRecentInsertedRestHistoryId(context, timeoutMs = 0)
        assumeTrue(
            "Requires a recent completed minimal inserted-rest cross-device sync history. Run MinimalInsertedRestPhoneSyncPreparationTest and WearMinimalCrossDeviceInsertedRestSyncProducerE2ETest first.",
            historyId != null
        )
        val db = AppDatabase.getDatabase(context)
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(checkNotNull(historyId))

        assertEquals(MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_1_ID, setHistories[0].setId)
        assertEquals(MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_2_ID, setHistories[2].setId)
        assertTrue(setHistories[1].setData is RestSetData)

        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull {
            it.id == MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        } ?: error("Inserted-rest synced workout store entry was not found.")
        val exercise = workout.workoutComponents.single() as? Exercise
            ?: error("Expected a single synced exercise in the inserted-rest workout.")

        assertEquals(3, exercise.sets.size)
        assertEquals(MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_1_ID, exercise.sets[0].id)
        assertEquals(MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.SET_2_ID, exercise.sets[2].id)
        assertTrue(exercise.sets[1] is RestSet)
        assertTrue(exercise.sets[2] is WeightSet)

        val exerciseInfo = db.exerciseInfoDao()
            .getExerciseInfoById(MinimalCrossDeviceInsertedRestPhoneWorkoutStoreFixture.EXERCISE_ID)
            ?: error("Expected ExerciseInfo for inserted-rest exercise.")
        assertEquals(3, exerciseInfo.bestSession.sets.size)
        assertEquals(3, exerciseInfo.lastSuccessfulSession.sets.size)
    }
}

package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
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
class MinimalRestPauseWorkoutSyncVerificationTest {
    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
    }

    private suspend fun findRecentRestPauseHistoryId(
        context: android.content.Context,
        timeoutMs: Long
    ): UUID? = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
        context = context,
        timeoutMs = timeoutMs
    ) { db, history ->
        if (!history.isDone ||
            history.workoutId != MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.WORKOUT_ID ||
            history.globalId != MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID ||
            Duration.between(history.startTime, LocalDateTime.now()).toMinutes() !in 0..HISTORY_RECENCY_MINUTES
        ) {
            false
        } else {
            val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
            setHistories.size == 3 &&
                setHistories[0].setId == MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.SET_1_ID &&
                setHistories[0].setData is WeightSetData &&
                (setHistories[1].setData as? RestSetData)?.subCategory == SetSubCategory.RestPauseSet &&
                (setHistories[2].setData as? WeightSetData)?.subCategory == SetSubCategory.RestPauseSet
        }
    }

    @Test
    fun crossDeviceSync_restPauseHistorySyncsButWorkoutStructureStaysProgrammed() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = findRecentRestPauseHistoryId(context, timeoutMs = 0)
        assumeTrue(
            "Requires a recent completed minimal rest-pause cross-device sync history. Run MinimalRestPausePhoneSyncPreparationTest and WearMinimalCrossDeviceRestPauseSyncProducerE2ETest first.",
            historyId != null
        )
        val db = AppDatabase.getDatabase(context)
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(checkNotNull(historyId))

        assertEquals(3, setHistories.size)
        assertTrue(setHistories[1].setData is RestSetData)
        assertTrue(setHistories[2].setData is WeightSetData)

        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull {
            it.id == MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        } ?: error("Rest-pause synced workout store entry was not found.")
        val exercise = workout.workoutComponents.single() as? Exercise
            ?: error("Expected a single synced exercise in the rest-pause workout.")

        assertEquals(1, exercise.sets.size)
        assertEquals(MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.SET_1_ID, exercise.sets.single().id)
        assertTrue(exercise.sets.single() is WeightSet)

        val exerciseInfo = db.exerciseInfoDao()
            .getExerciseInfoById(MinimalCrossDeviceRestPausePhoneWorkoutStoreFixture.EXERCISE_ID)
            ?: error("Expected ExerciseInfo for rest-pause exercise.")
        assertEquals(1, exerciseInfo.bestSession.sets.size)
        assertEquals(1, exerciseInfo.lastSuccessfulSession.sets.size)
    }
}

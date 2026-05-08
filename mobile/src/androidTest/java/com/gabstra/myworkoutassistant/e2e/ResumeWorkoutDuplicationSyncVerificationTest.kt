package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDevicePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ResumeWorkoutDuplicationSyncVerificationTest {
    private suspend fun findCompletedHistoryId(
        context: android.content.Context,
        timeoutMs: Long
    ): UUID? = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
        context = context,
        timeoutMs = timeoutMs
    ) { db, history ->
        history.isDone &&
            history.workoutId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID &&
            history.globalId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
            db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
                .size == ResumeCrossDevicePhoneWorkoutStoreFixture.EXPECTED_TOTAL_SET_COUNT
    }

    @Test
    fun crossDeviceResume_completionDoesNotDuplicatePreviouslyCompletedExerciseHistories() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = findCompletedHistoryId(
            context = context,
            timeoutMs = CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(45_000)
        )
        assumeTrue(
            "Requires a recent completed resume cross-device sync history. Run ResumePhoneSyncPreparationTest and WearResumeCrossDeviceSyncProducerE2ETest first.",
            historyId != null
        )

        val db = AppDatabase.getDatabase(context)
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(checkNotNull(historyId))
        val duplicateSetIds = setHistories.groupingBy { it.setId }.eachCount().filterValues { it > 1 }

        assertEquals(
            "Completed resume history should not duplicate any set ids.",
            emptyMap<UUID, Int>(),
            duplicateSetIds
        )
        assertEquals(
            "Completed resume history should contain the expected total number of set rows.",
            ResumeCrossDevicePhoneWorkoutStoreFixture.EXPECTED_TOTAL_SET_COUNT,
            setHistories.size
        )

        val exactCountsByExercise = setHistories.groupingBy { it.exerciseId }.eachCount()
        ResumeCrossDevicePhoneWorkoutStoreFixture.SEEDED_EXERCISE_EXACT_COUNTS.forEach { (exerciseId, expectedCount) ->
            assertEquals(
                "Exercise $exerciseId should retain exactly its seeded completed rows after resume sync.",
                expectedCount,
                exactCountsByExercise[exerciseId] ?: 0
            )
        }

        val activeRecord = db.workoutRecordDao()
            .getWorkoutRecordByWorkoutId(ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID)
        assertNull("Expected no active workout record after completed resume sync.", activeRecord)

        val unfinishedHistories = db.workoutHistoryDao().getAllWorkoutHistories().filter {
            !it.isDone &&
                it.workoutId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == ResumeCrossDevicePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        }
        assertEquals(
            "Expected no recent unfinished histories after completed resume sync.",
            emptyList<UUID>(),
            unfinishedHistories.map { it.id }
        )
    }
}

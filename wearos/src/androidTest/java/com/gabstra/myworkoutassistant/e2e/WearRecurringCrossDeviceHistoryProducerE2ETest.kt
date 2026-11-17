package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.RecurringCrossDeviceFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.findWorkoutForHistory
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.sync.WearCompletedHistorySyncSender
import com.gabstra.myworkoutassistant.sync.WearWorkoutHistorySyncReason
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Sends recurring history through the production Wear Data Layer sender; it does not fake receive. */
@RunWith(AndroidJUnit4::class)
class WearRecurringCrossDeviceHistoryProducerE2ETest {

    @Test
    fun completedRecurringHistorySnapshotsSendOverDataLayerAndCanBeReplayed() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val runId = requiredRunId()
        val profileId = RecurringCrossDeviceFixture.profileId(runId)
        assertTrue(
            "Phone sync did not publish the test profile index entry",
            Profiles.profiles(context).any { it.id == profileId },
        )

        val store = WorkoutStoreRepository(
            Profiles.directory(context, profileId),
            context.filesDir,
        ).getWorkoutStore()
        val workout = store.workouts.single { it.id == RecurringCrossDeviceFixture.workoutId(runId, 2) }
        val history = RecurringCrossDeviceFixture.completedHistory(runId)
        assertEquals(workout.id, store.findWorkoutForHistory(history)?.id)
        val setHistories = RecurringCrossDeviceFixture.completedSetHistories(runId)
        val exercisesByTrack = workout.workoutComponents.filterIsInstance<Exercise>()
            .associateBy { requireNotNull(it.recurringExerciseId) }
        assertEquals(3, exercisesByTrack.size)
        assertEquals(RecurringCrossDeviceFixture.sessionId(runId), history.recurringSessionId)

        val db = AppDatabase.getDatabase(context, profileId)
        db.workoutHistoryDao().insert(history)
        db.setHistoryDao().insertAll(*setHistories.toTypedArray())
        val storedSetHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(history.id)
        assertEquals(3, storedSetHistories.size)
        for (slot in RecurringCrossDeviceFixture.Slot.values()) {
            val stored = storedSetHistories.single { it.recurringExerciseId == RecurringCrossDeviceFixture.trackId(runId, slot) }
            assertEquals(RecurringCrossDeviceFixture.exerciseId(runId, 2, slot), stored.exerciseId)
            assertEquals(RecurringCrossDeviceFixture.definitionId(runId, slot), stored.exerciseDefinitionIdSnapshot)
            assertEquals("WEIGHT", stored.exerciseTypeSnapshot)
            assertEquals(RecurringCrossDeviceFixture.setId(runId, 2, slot), stored.setId)
            assertEquals(RecurringCrossDeviceFixture.HISTORY_WEIGHT, (stored.setData as WeightSetData).actualWeight, 0.0)
        }

        repeat(2) {
            val result = WearCompletedHistorySyncSender.send(
                context = context,
                dataClient = Wearable.getDataClient(context),
                historyIds = setOf(history.id),
                reason = WearWorkoutHistorySyncReason.CompletedWorkout,
                profileId = profileId,
            )
            assertEquals(setOf(history.id), result.attemptedHistoryIds)
            assertTrue("Wear history sync failed: ${result.failedHistoryIds}", result.failedHistoryIds.isEmpty())
        }
    }

    private fun requiredRunId(): String = requireNotNull(
        InstrumentationRegistry.getArguments().getString("run_id")
    ) { "The recurring cross-device runner must provide the run_id instrumentation argument." }
}

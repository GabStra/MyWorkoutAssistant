package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.RecurringCrossDeviceFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import com.gabstra.myworkoutassistant.sync.pushProfileIndexToWatches
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/** Production Data Layer prep and receiver verification for recurring prescription identities. */
@RunWith(AndroidJUnit4::class)
class RecurringCrossDevicePhoneSyncE2ETest {

    @Test
    fun prepareRecurringCrossDeviceProfileAndPushToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val runId = requiredRunId()
        val profileId = RecurringCrossDeviceFixture.profileId(runId)
        val previouslyActiveProfileId = Profiles.activeProfileId(context)
        check(previouslyActiveProfileId != profileId) {
            "The recurring scratch profile must never replace the user's active profile."
        }
        Profiles.ensureProfile(context, profileId, RecurringCrossDeviceFixture.PROFILE_NAME)

        val repository = WorkoutStoreRepository(Profiles.directory(context, profileId), context.filesDir)
        val existingStore = repository.getWorkoutStore()
        val recurringStore = RecurringCrossDeviceFixture.createWorkoutStore(runId)
        val ownedWorkoutIds = setOf(
            RecurringCrossDeviceFixture.workoutId(runId, RecurringCrossDeviceFixture.FOUNDATION_ORDINAL),
            RecurringCrossDeviceFixture.workoutId(runId, RecurringCrossDeviceFixture.PROGRESSION_ORDINAL),
        )
        val ownedDefinitionIds = RecurringCrossDeviceFixture.Slot.values()
            .mapTo(mutableSetOf()) { RecurringCrossDeviceFixture.definitionId(runId, it) }
        val ownedPlanId = RecurringCrossDeviceFixture.planId(runId)
        val mergedStore = existingStore.copy(
            exerciseDefinitions = existingStore.exerciseDefinitions
                .filterNot { it.id in ownedDefinitionIds } + recurringStore.exerciseDefinitions,
            workouts = existingStore.workouts
                .filterNot { it.id in ownedWorkoutIds } + recurringStore.workouts,
            workoutPlans = existingStore.workoutPlans
                .filterNot { it.id == ownedPlanId } + recurringStore.workoutPlans,
        )
        repository.saveWorkoutStore(mergedStore)

        // Clear only this run's deterministic history rows so a reused run_id is repeatable.
        val historyId = RecurringCrossDeviceFixture.historyId(runId)
        val db = AppDatabase.getDatabase(context, profileId)
        db.setHistoryDao().deleteByWorkoutHistoryId(historyId)
        db.workoutHistoryDao().deleteById(historyId)
        db.close()

        pushProfileIndexToWatches(context)
        MobileSyncToWatchWorker.enqueueForProfile(context, profileId)
        val workName = "${MobileSyncToWatchWorker.UNIQUE_WORK_NAME}_$profileId"
        val finishedWork = withTimeout(SYNC_TIMEOUT_MS) {
            WorkManager.getInstance(context).getWorkInfosForUniqueWorkFlow(workName).first { infos ->
                infos.any { it.state.isFinished }
            }
        }
        val result = finishedWork.firstOrNull { it.state.isFinished }
            ?: error("Recurring phone-to-Wear sync finished without a WorkManager result.")
        assertEquals("Phone-to-Wear sync failed: $result", WorkInfo.State.SUCCEEDED, result.state)
        assertEquals(previouslyActiveProfileId, Profiles.activeProfileId(context))
    }

    @Test
    fun verifyWearRecurringHistorySnapshotsAndCleanScratchProfile() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val runId = requiredRunId()
        val profileId = RecurringCrossDeviceFixture.profileId(runId)
        try {
            val db = AppDatabase.getDatabase(context, profileId)
            val history = awaitRecurringHistory(db, RecurringCrossDeviceFixture.historyId(runId))
            assertEquals(RecurringCrossDeviceFixture.sessionId(runId), history.recurringSessionId)
            assertEquals(RecurringCrossDeviceFixture.workoutId(runId, 2), history.workoutId)
            assertEquals(RecurringCrossDeviceFixture.uuid(runId, "progression.global"), history.globalId)
            assertTrue(history.isDone)

            val historiesWithId = db.workoutHistoryDao().getAllWorkoutHistories()
                .filter { it.id == history.id }
            assertEquals("Replayed Wear sync should not duplicate the history row", 1, historiesWithId.size)
            val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(history.id)
            assertEquals(3, setHistories.size)
            for (slot in RecurringCrossDeviceFixture.Slot.values()) {
                val setHistory = setHistories.single {
                    it.recurringExerciseId == RecurringCrossDeviceFixture.trackId(runId, slot)
                }
                assertEquals(RecurringCrossDeviceFixture.exerciseId(runId, 2, slot), setHistory.exerciseId)
                assertEquals(RecurringCrossDeviceFixture.setId(runId, 2, slot), setHistory.setId)
                assertEquals(RecurringCrossDeviceFixture.definitionId(runId, slot), setHistory.exerciseDefinitionIdSnapshot)
                assertEquals("WEIGHT", setHistory.exerciseTypeSnapshot)
                assertEquals(RecurringCrossDeviceFixture.HISTORY_WEIGHT, (setHistory.setData as WeightSetData).actualWeight, 0.0)
            }
            db.close()
        } finally {
            cleanupScratchProfile(context, runId)
        }
    }

    /** Safe to invoke from the runner's finally path when an earlier cross-device stage fails. */
    @Test
    fun cleanupRecurringCrossDeviceScratchProfile() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        cleanupScratchProfile(context, requiredRunId())
    }

    private suspend fun awaitRecurringHistory(
        db: AppDatabase,
        historyId: UUID,
    ): WorkoutHistory {
        val deadline = System.currentTimeMillis() + HISTORY_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            val history = db.workoutHistoryDao().getWorkoutHistoryById(historyId)
            val sets = history?.let { db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(it.id) }.orEmpty()
            if (history?.isDone == true && sets.size == RecurringCrossDeviceFixture.Slot.values().size) {
                return history
            }
            delay(250)
        }
        error("Wear recurring history $historyId and all set snapshots were not received within $HISTORY_TIMEOUT_MS ms.")
    }

    private suspend fun cleanupScratchProfile(
        context: android.content.Context,
        runId: String,
    ) {
        val profileId = RecurringCrossDeviceFixture.profileId(runId)
        check(Profiles.activeProfileId(context) != profileId) {
            "Refusing to delete the active profile during recurring sync test cleanup."
        }
        var profileExists = Profiles.profiles(context).any { it.id == profileId }
        val repository = WorkoutStoreRepository(Profiles.directory(context, profileId), context.filesDir)
        val store = repository.getWorkoutStore()
        val ownedWorkoutIds = setOf(
            RecurringCrossDeviceFixture.workoutId(runId, RecurringCrossDeviceFixture.FOUNDATION_ORDINAL),
            RecurringCrossDeviceFixture.workoutId(runId, RecurringCrossDeviceFixture.PROGRESSION_ORDINAL),
        )
        val ownedDefinitionIds = RecurringCrossDeviceFixture.Slot.values()
            .mapTo(mutableSetOf()) { RecurringCrossDeviceFixture.definitionId(runId, it) }
        val ownedPlanId = RecurringCrossDeviceFixture.planId(runId)
        val hasOwnedStoreRows = store.workouts.any { it.id in ownedWorkoutIds } ||
            store.exerciseDefinitions.any { it.id in ownedDefinitionIds } ||
            store.workoutPlans.any { it.id == ownedPlanId }

        if (hasOwnedStoreRows && !profileExists) {
            Profiles.ensureProfile(context, profileId, RecurringCrossDeviceFixture.PROFILE_NAME)
            profileExists = Profiles.profiles(context).any { it.id == profileId }
        }

        if (hasOwnedStoreRows) {
            repository.saveWorkoutStore(
                store.copy(
                    exerciseDefinitions = store.exerciseDefinitions.filterNot { it.id in ownedDefinitionIds },
                    workouts = store.workouts.filterNot { it.id in ownedWorkoutIds },
                    workoutPlans = store.workoutPlans
                        .filterNot { it.id == ownedPlanId }
                        .map { plan -> plan.copy(workoutIds = plan.workoutIds.filterNot { it in ownedWorkoutIds }) },
                )
            )
        }

        if (profileExists) {
            val db = AppDatabase.getDatabase(context, profileId)
            val historyId = RecurringCrossDeviceFixture.historyId(runId)
            db.setHistoryDao().deleteByWorkoutHistoryId(historyId)
            db.workoutHistoryDao().deleteById(historyId)
            db.close()
            assertTrue("Failed to delete the test-owned scratch profile", Profiles.delete(context, profileId))
            pushProfileIndexToWatches(context)
        }
    }

    private fun requiredRunId(): String = requireNotNull(
        InstrumentationRegistry.getArguments().getString("run_id")
    ) { "The recurring cross-device runner must provide the run_id instrumentation argument." }

    private companion object {
        const val HISTORY_TIMEOUT_MS = 60_000L
        const val SYNC_TIMEOUT_MS = 180_000L
    }
}

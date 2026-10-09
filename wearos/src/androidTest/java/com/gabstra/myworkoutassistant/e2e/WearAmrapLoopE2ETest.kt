package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AmrapLoopWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearAmrapLoopE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        AmrapLoopWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun amrapSuperset_loopsRoundUntilCapExpires_thenCutsToCompletion() = runBlocking {
        startWorkout(AmrapLoopWorkoutStoreFixture.getWorkoutName())

        // Enter the AMRAP container (starts the cap window).
        val preBlockCompleted = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = 20_000
        )
        require(preBlockCompleted) { "Failed to complete the pre-AMRAP set" }

        // Round 1: both members, then the loop must re-present member one instead
        // of completing the workout (cap still running).
        require(WearWorkoutStateMutationHelper.completeCurrentSet(device, context)) {
            "Failed to complete AMRAP member one (round 1)"
        }
        require(WearWorkoutStateMutationHelper.completeCurrentSet(device, context)) {
            "Failed to complete AMRAP member two (round 1)"
        }
        require(WearWorkoutStateMutationHelper.completeCurrentSet(device, context)) {
            "AMRAP round did not loop: completing the last member did not lead back to member one"
        }
        require(WearWorkoutStateMutationHelper.completeCurrentSet(device, context)) {
            "Failed to complete AMRAP member two (round 2)"
        }

        // No further input: the cap must cut past the looping block hands-free.
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 90_000)

        assertRecordedRoundsLoopAndComplete()
    }

    private suspend fun assertRecordedRoundsLoopAndComplete() {
        val db = AppDatabase.getDatabase(context)
        val history = db.workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(true)
            .filter { it.workoutId == AmrapLoopWorkoutStoreFixture.getWorkoutId() }
            .maxByOrNull { it.startTime }
            ?: error("No completed history found for the AMRAP loop run.")

        val rows = db.setHistoryDao()
            .getSetHistoriesByWorkoutHistoryId(history.id)
            .sortedBy { it.executionSequence?.toInt() ?: Int.MAX_VALUE }

        val recordedIds = rows.map { it.setId }
        assertEquals(
            "Recorded sets should be pre-block + two full rounds of both members",
            listOf(
                AmrapLoopWorkoutStoreFixture.preBlockSetId,
                AmrapLoopWorkoutStoreFixture.memberOneSetId,
                AmrapLoopWorkoutStoreFixture.memberTwoSetId,
                AmrapLoopWorkoutStoreFixture.memberOneSetId,
                AmrapLoopWorkoutStoreFixture.memberTwoSetId
            ),
            recordedIds
        )
        assertEquals(
            "Superset rounds should be tagged 1,1,2,2 on the looped rows",
            listOf(null, 1u, 1u, 2u, 2u),
            rows.map { it.supersetRound }
        )
    }
}

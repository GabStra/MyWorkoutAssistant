package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ExactBackupResumeFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutCompletionHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExactBackupResumeBugReproE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private var seededSetCount: Int = 0
    private var seededRestCount: Int = 0

    override fun prepareAppStateBeforeLaunch() {
        ExactBackupResumeFixture.setup(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun exactBackup_resumeThenComplete_preservesRowsFromIncompleteHistory() {
        captureSeededIncompleteHistoryCounts()

        val enteredWorkout = if (workoutDriver.waitForRecoveryDialog(10_000)) {
            workoutDriver.clickRecoveryResume(timeoutMs = 10_000) &&
                device.wait(
                    Until.hasObject(
                        By.descContains(SetValueSemantics.WeightSetTypeDescription)
                    ),
                    30_000
                )
        } else {
            workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
                workoutName = ExactBackupResumeFixture.WORKOUT_NAME,
                inWorkoutSelector = By.descContains(SetValueSemantics.WeightSetTypeDescription),
                timeoutMs = 30_000
            ).enteredWorkout
        }
        val enteredAfterSkip = if (!enteredWorkout) {
            val whoopPrepVisible =
                device.wait(Until.hasObject(By.textContains("WHOOP")), 5_000) ||
                    device.wait(Until.hasObject(By.textContains("Getting your")), 3_000)
            val skipClicked = if (whoopPrepVisible) {
                runCatching { workoutDriver.clickText("Skip", 15_000) }.isSuccess
            } else {
                false
            }
            if (skipClicked) {
                device.wait(
                    Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
                    20_000
                )
            } else {
                false
            }
        } else {
            false
        }

        require(enteredWorkout || enteredAfterSkip) {
            "Could not enter resumed workout flow from exact backup fixture."
        }

        WearWorkoutCompletionHelper.completeWorkoutViaStateMutations(
            device = device,
            context = context,
            maxSteps = 120,
            completionErrorMessage = "Workout did not complete within step limit while reproducing backup resume bug."
        )
        assertCompletedHistoryContainsAllRowsFromSeededIncompleteHistorySnapshot()
    }

    private fun captureSeededIncompleteHistoryCounts() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val seededHistoryId = UUID.fromString(ExactBackupResumeFixture.WORKOUT_HISTORY_ID)
        seededSetCount = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(seededHistoryId).size
        seededRestCount = db.restHistoryDao().getByWorkoutHistoryIdOrdered(seededHistoryId).size
        require(seededSetCount > 0) { "Seeded incomplete history has no set rows before resume." }
    }

    private fun assertCompletedHistoryContainsAllRowsFromSeededIncompleteHistorySnapshot() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val workoutId = UUID.fromString(ExactBackupResumeFixture.WORKOUT_ID)

        val completedHistory = db.workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(true)
            .filter { it.workoutId == workoutId }
            .maxByOrNull { it.startTime }
            ?: error("No completed history found for exact-backup resume run.")

        val completedSets = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(completedHistory.id)
        val completedRests = db.restHistoryDao().getByWorkoutHistoryIdOrdered(completedHistory.id)

        require(completedSets.size >= seededSetCount) {
            "BUG REPRODUCED: completed history has fewer set rows than pre-resume incomplete history. seeded=$seededSetCount completed=${completedSets.size}"
        }
        require(completedRests.size >= seededRestCount) {
            "BUG REPRODUCED: completed history has fewer rest rows than pre-resume incomplete history. seeded=$seededRestCount completed=${completedRests.size}"
        }
    }
}

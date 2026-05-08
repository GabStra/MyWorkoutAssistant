package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.data.WorkoutRecoveryCheckpointStore
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.BHingeOhpResumeExecutionFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutCompletionHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class WearBHingeOhpResumeDuplicateHistoryE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        BHingeOhpResumeExecutionFixture.setup(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun executePartOfBHingeOhp_thenResumeToCompletion_doesNotDuplicateCompletedExerciseRows() {
        startWorkout(BHingeOhpResumeExecutionFixture.WORKOUT_NAME)
        ensureWorkoutSetScreenVisibleAfterExternalPrep()
        progressUntilNextExerciseIsBulgarianSplitSquat()
        val unfinishedHistoryId = requireLatestUnfinishedHistoryId()
        assertPreResumeCounts(unfinishedHistoryId)

        device.pressHome()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        runBlocking {
            WorkoutRecoveryCheckpointStore(context).clearRuntimeSnapshot(synchronous = true)
        }
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = BHingeOhpResumeExecutionFixture.WORKOUT_NAME,
            inWorkoutSelector = By.descContains(SetValueSemantics.WeightSetTypeDescription),
            timeoutMs = 30_000
        )
        require(resumed.enteredWorkout) {
            "Could not resume '${BHingeOhpResumeExecutionFixture.WORKOUT_NAME}' after backgrounding."
        }
        ensureWorkoutSetScreenVisibleAfterExternalPrep()

        WearWorkoutCompletionHelper.completeWorkoutViaStateMutations(
            device = device,
            context = context,
            maxSteps = 120,
            completionErrorMessage = "Workout did not complete within step limit while reproducing B — Hinge/OHP resume-history duplication.",
            forceNotSend = true
        )
        assertCompletedHistoryDidNotDuplicatePreResumeRows()
    }

    private fun progressUntilNextExerciseIsBulgarianSplitSquat() {
        val targetExerciseId = BHingeOhpResumeExecutionFixture.BULGARIAN_SPLIT_SQUAT_EXERCISE_ID
        val deadline = System.currentTimeMillis() + 180_000

        while (System.currentTimeMillis() < deadline) {
            val currentExerciseId = WearWorkoutStateMutationHelper.getCurrentExerciseId()
            if (currentExerciseId == targetExerciseId) {
                return
            }

            val advancedFromSet = WearWorkoutStateMutationHelper.completeCurrentSet(
                device = device,
                context = context,
                timeoutMs = 20_000,
                forceNotSend = true
            )

            if (advancedFromSet) {
                continue
            }

            val advancedFromRest = WearWorkoutStateMutationHelper.skipCurrentRest(
                device = device,
                timeoutMs = 15_000,
                forceNotSend = true
            )

            if (advancedFromRest) {
                continue
            }

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        error("Timed out before reaching Bulgarian Split Squat. LastState=${WearWorkoutStateMutationHelper.describeCurrentState()}")
    }

    private fun requireLatestUnfinishedHistoryId(): UUID = runBlocking {
        val history = AppDatabase.getDatabase(context)
            .workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(false)
            .filter {
                it.workoutId == BHingeOhpResumeExecutionFixture.WORKOUT_ID &&
                    it.globalId == BHingeOhpResumeExecutionFixture.WORKOUT_GLOBAL_ID
            }
            .maxByOrNull { it.version.toLong() }
            ?: error("No unfinished B — Hinge/OHP history found before resume.")
        history.id
    }

    private fun loadSetHistories(workoutHistoryId: UUID): List<SetHistory> = runBlocking {
        AppDatabase.getDatabase(context)
            .setHistoryDao()
            .getSetHistoriesByWorkoutHistoryIdOrdered(workoutHistoryId)
    }

    private fun snapshotCurrentHistoryCounts(workoutHistoryId: UUID): Map<UUID, Int> {
        return loadSetHistories(workoutHistoryId)
            .mapNotNull { setHistory -> setHistory.exerciseId?.let { it to setHistory } }
            .groupingBy { it.first }
            .eachCount()
    }

    private fun assertPreResumeCounts(workoutHistoryId: UUID) {
        val preResumeCounts = snapshotCurrentHistoryCounts(workoutHistoryId)
        BHingeOhpResumeExecutionFixture.EXPECTED_PRE_RESUME_COMPLETED_COUNTS.forEach { (exerciseId, expected) ->
            val actual = preResumeCounts[exerciseId] ?: 0
            require(actual == expected) {
                "Expected pre-resume completed rows for exercise=$exerciseId to be $expected, but found $actual."
            }
        }
    }

    private fun assertCompletedHistoryDidNotDuplicatePreResumeRows() = runBlocking {
        val completedHistory = AppDatabase.getDatabase(context)
            .workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(true)
            .filter {
                it.workoutId == BHingeOhpResumeExecutionFixture.WORKOUT_ID &&
                    it.globalId == BHingeOhpResumeExecutionFixture.WORKOUT_GLOBAL_ID
            }
            .maxByOrNull(WorkoutHistory::version)
            ?: error("No completed B — Hinge/OHP history found after resume.")

        val countsByExercise = AppDatabase.getDatabase(context)
            .setHistoryDao()
            .getSetHistoriesByWorkoutHistoryIdOrdered(completedHistory.id)
            .mapNotNull { setHistory -> setHistory.exerciseId?.let { it to setHistory } }
            .groupingBy { it.first }
            .eachCount()

        BHingeOhpResumeExecutionFixture.EXPECTED_PRE_RESUME_COMPLETED_COUNTS.forEach { (exerciseId, expected) ->
            val actual = countsByExercise[exerciseId] ?: 0
            require(actual == expected) {
                "BUG REPRODUCED: completed history duplicated pre-resume exercise rows for exercise=$exerciseId expected=$expected actual=$actual"
            }
        }
    }

    private fun ensureWorkoutSetScreenVisibleAfterExternalPrep() {
        if (waitForAnyActiveWorkoutScreen(5_000)) {
            return
        }

        val whoopPrepVisible =
            device.wait(Until.hasObject(By.textContains("WHOOP")), 5_000) ||
                device.wait(Until.hasObject(By.textContains("Getting your")), 3_000)
        if (whoopPrepVisible) {
            runCatching { workoutDriver.clickText("Skip", 15_000) }
        }
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 3_000)
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)

        require(waitForAnyActiveWorkoutScreen(20_000)) {
            "Active workout set screen did not appear after external heart-rate preparation."
        }
    }

    private fun waitForAnyActiveWorkoutScreen(timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (
                device.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription))
            ) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }
}

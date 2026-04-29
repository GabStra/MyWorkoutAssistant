package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeAWorkoutHistoryFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutCompletionHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearResumeHistoryBugReproE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        ResumeAWorkoutHistoryFixture.setup(
            context = context,
            mode = ResumeAWorkoutHistoryFixture.ResumeSeedMode.OrderDriftOnWorkSets
        )
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun resumeThenComplete_orderDrift_shouldStillPreservePreResumeExerciseHistory() {
        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = ResumeAWorkoutHistoryFixture.WORKOUT_NAME,
            inWorkoutSelector = By.descContains(SetValueSemantics.WeightSetTypeDescription),
            timeoutMs = 30_000
        )
        require(resumed.enteredWorkout) {
            "Could not enter resumed workout flow for '${ResumeAWorkoutHistoryFixture.WORKOUT_NAME}'."
        }

        WearWorkoutCompletionHelper.completeWorkoutViaStateMutations(
            device = device,
            context = context,
            maxSteps = 80,
            completionErrorMessage = "Workout did not complete within step limit while reproducing resume-history loss."
        )
        assertCompletedHistoryStillContainsSeededExerciseRows()
    }

    private fun assertCompletedHistoryStillContainsSeededExerciseRows() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val completedHistory = db.workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(true)
            .filter { it.workoutId == ResumeAWorkoutHistoryFixture.WORKOUT_ID }
            .maxByOrNull { it.startTime }
            ?: error("No completed history found for resumed workout.")

        val completedSets = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(completedHistory.id)
        val countsByExercise = completedSets.groupingBy { it.exerciseId }.eachCount()

        ResumeAWorkoutHistoryFixture.SEEDED_EXERCISE_MIN_COUNTS.forEach { (exerciseId, expectedMinCount) ->
            val actualCount = countsByExercise[exerciseId] ?: 0
            require(actualCount >= expectedMinCount) {
                "BUG REPRODUCED: completed history dropped pre-resume rows for exercise=$exerciseId expectedAtLeast=$expectedMinCount actual=$actualCount historyId=${completedHistory.id}"
            }
        }
    }
}

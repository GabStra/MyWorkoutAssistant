package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDeviceSyncSpec
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutCompletionHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import kotlinx.coroutines.runBlocking

@RunWith(AndroidJUnit4::class)
class WearResumeCrossDeviceSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun resumeWorkout_completeAndSyncBackToPhone() {
        val enteredWorkout = enterResumedWorkout()
        require(enteredWorkout) {
            "Could not enter resumed workout flow for '${ResumeCrossDeviceSyncSpec.WORKOUT_NAME}'."
        }

        WearWorkoutCompletionHelper.completeWorkoutViaStateMutations(
            device = device,
            context = context,
            maxSteps = 80,
            completionErrorMessage = "Workout did not complete within step limit while validating cross-device resume duplication."
        )
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        assertCompletedHistoryDoesNotDuplicatePreviouslyCompletedExercises()
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private fun assertCompletedHistoryDoesNotDuplicatePreviouslyCompletedExercises() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val completedHistory = db.workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(true)
            .filter {
                it.workoutId == ResumeCrossDeviceSyncSpec.WORKOUT_ID &&
                    it.globalId == ResumeCrossDeviceSyncSpec.WORKOUT_GLOBAL_ID
            }
            .maxByOrNull { it.version.toLong() }
            ?: error("No completed history found for resume cross-device verification.")

        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(completedHistory.id)
        val duplicateSetIds = setHistories.groupingBy { it.setId }.eachCount().filterValues { it > 1 }
        require(duplicateSetIds.isEmpty()) {
            "BUG REPRODUCED: completed Wear history duplicated set ids after resume. duplicates=$duplicateSetIds"
        }

        val countsByExercise = setHistories.groupingBy { it.exerciseId }.eachCount()
        ResumeCrossDeviceSyncSpec.SEEDED_EXERCISE_EXACT_COUNTS.forEach { (exerciseId, expectedCount) ->
            val actualCount = countsByExercise[exerciseId] ?: 0
            require(actualCount == expectedCount) {
                "BUG REPRODUCED: previously completed exercise rows were duplicated after resume. " +
                    "exercise=$exerciseId expected=$expectedCount actual=$actualCount"
            }
        }
    }

    private fun enterResumedWorkout(): Boolean {
        val inWorkoutSelector = By.descContains(SetValueSemantics.WeightSetTypeDescription)
        val enteredViaRecovery = if (workoutDriver.waitForRecoveryDialog(10_000)) {
            workoutDriver.clickRecoveryResume(timeoutMs = 10_000) &&
                device.wait(Until.hasObject(inWorkoutSelector), 30_000)
        } else {
            false
        }
        if (enteredViaRecovery) {
            return true
        }

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = ResumeCrossDeviceSyncSpec.WORKOUT_NAME,
            inWorkoutSelector = inWorkoutSelector,
            timeoutMs = 30_000
        )
        if (resumed.enteredWorkout) {
            return true
        }

        val whoopPrepVisible =
            device.wait(Until.hasObject(By.textContains("WHOOP")), 5_000) ||
                device.wait(Until.hasObject(By.textContains("Getting your")), 3_000)
        if (!whoopPrepVisible) {
            return false
        }

        val skipClicked = runCatching { workoutDriver.clickText("Skip", 15_000) }.isSuccess
        return skipClicked && device.wait(Until.hasObject(inWorkoutSelector), 20_000)
    }
}

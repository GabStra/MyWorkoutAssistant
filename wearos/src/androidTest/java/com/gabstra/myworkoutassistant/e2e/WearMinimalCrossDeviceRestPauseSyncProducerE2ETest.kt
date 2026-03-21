package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceRestPauseWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearMinimalCrossDeviceRestPauseSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        MinimalCrossDeviceRestPauseWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun completeWorkout_withTemporaryRestPause_syncsHistoryButNotWorkoutStructure() {
        startWorkout(MinimalCrossDeviceRestPauseWorkoutStoreFixture.WORKOUT_NAME)
        require(WearWorkoutStateMutationHelper.addRestPauseSetAfterCurrent(device, context, timeoutMs = 15_000)) {
            "Failed to insert a temporary rest-pause set after the current set."
        }
        progressUntilWorkoutCompletion()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private fun progressUntilWorkoutCompletion(timeoutMs: Long = 60_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastStateDescription = "unknown"
        while (System.currentTimeMillis() < deadline) {
            lastStateDescription = WearWorkoutStateMutationHelper.describeCurrentState()
            if (isWorkoutCompleted()) return

            if (WearWorkoutStateMutationHelper.skipCurrentRest(device, timeoutMs = 5_000)) {
                continue
            }

            if (WearWorkoutStateMutationHelper.completeCurrentSet(device, context, timeoutMs = 20_000)) {
                continue
            }

            device.waitForIdle(500)
        }

        error("Workout did not reach completion while progressing rest-pause scenario. Last state=$lastStateDescription")
    }

    private fun isWorkoutCompleted(): Boolean {
        return WearWorkoutStateMutationHelper.isWorkoutCompleted() ||
            device.hasObject(androidx.test.uiautomator.By.text("Completed")) ||
            device.hasObject(androidx.test.uiautomator.By.text("COMPLETED")) ||
            device.hasObject(androidx.test.uiautomator.By.text("Workout completed")) ||
            device.hasObject(androidx.test.uiautomator.By.text("Go Home")) ||
            device.hasObject(androidx.test.uiautomator.By.desc("Go Home")) ||
            device.hasObject(androidx.test.uiautomator.By.text("My Workout Assistant"))
    }
}

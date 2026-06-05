package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearCrossDeviceFinishEarlySyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun finishEarly_syncsClosedEarlyEndedHistoryToPhone() {
        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
        flowHelper.waitForIntermediateSyncObservationWindow()
        require(waitForCurrentSet(CrossDeviceSyncWorkoutStoreFixture.SET_A1_ID)) {
            "Workout did not reach the opening set before attempting finish-early setup."
        }
        require(
            WearWorkoutStateMutationHelper.completeCurrentSet(
                device = device,
                context = context,
                timeoutMs = 20_000
            )
        ) {
            "Failed to complete the opening set before finishing the workout early."
        }
        flowHelper.waitForIntermediateSyncObservationWindow()
        require(
            WearWorkoutStateMutationHelper.finishWorkoutEarly(
                device = device,
                context = context,
                timeoutMs = 20_000
            )
        ) {
            "Failed to finish the workout early from the current Wear workout state."
        }
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
    }

    private fun waitForCurrentSet(
        expectedSetId: java.util.UUID,
        timeoutMs: Long = 10_000
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (WearWorkoutStateMutationHelper.getCurrentSetId() == expectedSetId) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }
}

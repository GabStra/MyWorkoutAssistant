package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearCrossDeviceSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun completeWorkout_syncsHistoryToPhone() {
        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
        flowHelper.completeComplexWorkoutWithDeterministicModifications()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }
}


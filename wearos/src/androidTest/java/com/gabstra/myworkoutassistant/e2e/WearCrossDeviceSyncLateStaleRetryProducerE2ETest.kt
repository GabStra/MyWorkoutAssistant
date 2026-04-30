package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WorkoutHistorySyncFaultInjectionHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearCrossDeviceSyncLateStaleRetryProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
        WorkoutHistorySyncFaultInjectionHelper.clear(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun completeWorkout_ignoresLateStaleRetryAfterCompletion() {
        WorkoutHistorySyncFaultInjectionHelper.configureSkipChunkOnce(context)
        WorkoutHistorySyncFaultInjectionHelper.configureLateStaleRetryAfterCompletionOnce(context)
        try {
            startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
            flowHelper.waitForIntermediateSyncObservationWindow()
            flowHelper.completeComplexWorkoutWithDeterministicModifications()
            workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
            CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
            CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
        } finally {
            WorkoutHistorySyncFaultInjectionHelper.clear(context)
        }
    }
}

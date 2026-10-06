package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceCheckpointAcknowledgments
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
    fun completeWorkout_syncsHistoryToPhone() {
        val requireAcknowledgments = InstrumentationRegistry.getArguments()
            .getString("wait_for_checkpoint_acknowledgments") == "true"
        val acknowledgments = if (requireAcknowledgments) CrossDeviceCheckpointAcknowledgments(context) else null
        try {
            startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
            if (acknowledgments != null) {
                acknowledgments.awaitCheckpoint("started")
            } else {
                flowHelper.waitForIntermediateSyncObservationWindow()
            }
            flowHelper.completeComplexWorkoutWithDeterministicModifications(
                onIntermediateSetCompleted = acknowledgments?.let { observer ->
                    { setId -> observer.awaitCheckpoint(setId.toString()) }
                }
            )
            workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
            CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
            CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
        } finally {
            acknowledgments?.close()
        }
    }
}


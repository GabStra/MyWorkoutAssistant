package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearMinimalCrossDeviceSetSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        MinimalCrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun completeMinimalWorkout_syncsAllSetAndRestHistoryToPhone() {
        startWorkout(MinimalCrossDeviceSyncWorkoutStoreFixture.WORKOUT_NAME)
        workoutDriver.completeCurrentSet(timeoutMs = 10_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        workoutDriver.skipRest(timeoutMs = 5_000)

        workoutDriver.completeCurrentSet(timeoutMs = 10_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        workoutDriver.skipRest(timeoutMs = 5_000)

        workoutDriver.completeCurrentSet(timeoutMs = 10_000)
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }
}

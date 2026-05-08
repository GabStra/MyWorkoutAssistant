package com.gabstra.myworkoutassistant.e2e

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.shared.workout.model.ACTIVE_SESSION_STALE_TIMEOUT_MS
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearWorkoutHeartbeatProducerE2ETest : WearBaseE2ETest() {
    private companion object {
        val OBSERVATION_WINDOW_MS = ACTIVE_SESSION_STALE_TIMEOUT_MS + 15_000L
    }

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Test
    fun keepWorkoutActivePastStaleWindow_soPhoneMustRelyOnHeartbeats() {
        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())

        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
        SystemClock.sleep(OBSERVATION_WINDOW_MS)
        device.pressHome()
        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
    }
}

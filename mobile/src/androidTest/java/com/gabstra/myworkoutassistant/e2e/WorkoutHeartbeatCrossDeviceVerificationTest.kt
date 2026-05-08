package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.helpers.WorkoutHeartbeatCrossDeviceObservationState
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutHeartbeatCrossDeviceVerificationTest {
    @Test
    fun crossDeviceSync_heartbeatObservationPassed() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assertTrue(
            "Heartbeat cross-device observation did not report success. " +
                "Details=${WorkoutHeartbeatCrossDeviceObservationState.details(context)}",
            WorkoutHeartbeatCrossDeviceObservationState.hasPassed(context)
        )
    }
}

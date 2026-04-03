package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.sync.PhoneToWatchSyncCoordinator
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NoOpWorkoutIntermediateSyncObservationTest {
    @Test
    fun noOp() = runBlocking {
        val mode = InstrumentationRegistry.getArguments().getString("cross_device_sync_mode")
        if (!mode.equals("observe_live", ignoreCase = true)) {
            return@runBlocking
        }

        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val deadline = System.currentTimeMillis() + OBSERVATION_WINDOW_MS
        while (System.currentTimeMillis() < deadline) {
            PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)
            delay(SYNC_PUMP_INTERVAL_MS)
        }
    }

    private companion object {
        const val OBSERVATION_WINDOW_MS = 180_000L
        const val SYNC_PUMP_INTERVAL_MS = 5_000L
    }
}

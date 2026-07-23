package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.sync.PhoneToWatchSyncCoordinator
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearUnavailableAppE2ETest {

    @Test
    fun manualSync_doesNotStartWhenWearAppIsUnavailable() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        val syncStarted = PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)

        assertFalse("Manual sync must not start without a reachable Wear app", syncStarted)
        assertNull(
            "Foreground sync state must remain inactive without a reachable Wear app",
            PhoneToWatchSyncCoordinator.manualSyncProgress.value
        )
    }
}

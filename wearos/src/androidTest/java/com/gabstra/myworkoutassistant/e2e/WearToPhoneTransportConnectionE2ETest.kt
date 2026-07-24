package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.data.checkConnection
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearToPhoneTransportConnectionE2ETest {

    @Test
    fun connectionCheck_reportsReachablePairedPhoneTransport() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        assertTrue(
            "Expected a reachable paired phone transport for this cross-device test",
            checkConnection(context, maxRetries = 1)
        )
    }
}

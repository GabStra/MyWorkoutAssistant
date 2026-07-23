package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.data.checkConnection
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearToPhoneUnavailableAppE2ETest {

    @Test
    fun syncDoesNotStartWhenPhoneAppIsUnavailable() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        assertFalse(
            "Wear sync must not start without a reachable phone app",
            checkConnection(context, maxRetries = 1)
        )
    }
}

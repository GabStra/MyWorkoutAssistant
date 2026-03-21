package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutIntermediateSyncObservationTest {

    private fun resolvedCheckpointTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 25_000 else 75_000
    }

    @Test
    fun crossDeviceSync_intermediateUpdatesArrivePerCompletedSet() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        CrossDeviceSyncAssertions.intermediateCheckpoints.forEach { checkpoint ->
            CrossDeviceSyncAssertions.waitForCheckpoint(
                context = context,
                checkpoint = checkpoint,
                timeoutMs = resolvedCheckpointTimeoutMs()
            )
        }

        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = resolvedCheckpointTimeoutMs()
        )
    }

    @Test
    fun crossDeviceSync_liveWearSessionIsWearOwnedAndNotInterrupted() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val activeCheckpoints = listOf(CrossDeviceSyncAssertions.startedCheckpoint) +
            CrossDeviceSyncAssertions.intermediateCheckpoints.dropLast(1)

        activeCheckpoints.forEach { checkpoint ->
            CrossDeviceSyncAssertions.waitForWearOwnedActiveState(
                context = context,
                checkpoint = checkpoint,
                timeoutMs = resolvedCheckpointTimeoutMs()
            )
        }
    }
}

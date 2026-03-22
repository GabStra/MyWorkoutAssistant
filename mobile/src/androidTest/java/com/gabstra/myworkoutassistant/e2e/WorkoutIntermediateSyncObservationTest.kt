package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutIntermediateSyncObservationTest {

    private fun resolvedCheckpointTimeoutMs(): Long =
        CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(fastProfileMs = 25_000, defaultMs = 75_000)

    private fun requireLiveObservationOrSkip() {
        assumeTrue(
            "Requires live cross-device sync orchestration. Run via run_cross_device_sync_e2e.ps1.",
            CrossDeviceSyncTestPrerequisites.isLiveObserverRun()
        )
    }

    @Test
    fun crossDeviceSync_intermediateUpdatesArrivePerCompletedSet() = runBlocking {
        requireLiveObservationOrSkip()
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
        requireLiveObservationOrSkip()
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

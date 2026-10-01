package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class WorkoutIntermediateSyncObservationTest {

    private fun resolvedCheckpointTimeoutMs(): Long =
        CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(timeoutMs = 25_000)

    private fun resolvedInitialCheckpointTimeoutMs(): Long =
        CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(timeoutMs = 180_000)

    private fun requireLiveObservationOrSkip() {
        assumeTrue(
            "Requires live cross-device sync orchestration. Run via run_cross_device_sync_e2e.ps1.",
            CrossDeviceSyncTestPrerequisites.isLiveObserverRun()
        )
    }

    @Test
    fun crossDeviceSync_liveWearSessionStaysWearOwnedAndIntermediateUpdatesArrive() = runBlocking {
        requireLiveObservationOrSkip()
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val activeCheckpoints = listOf(CrossDeviceSyncAssertions.startedCheckpoint) +
            CrossDeviceSyncAssertions.intermediateCheckpoints.dropLast(1)

        activeCheckpoints.forEachIndexed { index, checkpoint ->
            CrossDeviceSyncAssertions.waitForCheckpoint(
                context = context,
                checkpoint = checkpoint,
                timeoutMs = if (index == 0) {
                    resolvedInitialCheckpointTimeoutMs()
                } else {
                    resolvedCheckpointTimeoutMs()
                }
            )
            CrossDeviceSyncAssertions.waitForWearOwnedActiveState(
                context = context,
                checkpoint = checkpoint,
                timeoutMs = resolvedCheckpointTimeoutMs()
            )
            val checkpointKey = checkpoint.expectedSetIds.lastOrNull()?.toString() ?: "started"
            val nodes = Tasks.await(Wearable.getNodeClient(context).connectedNodes, 10, TimeUnit.SECONDS)
            check(nodes.isNotEmpty()) { "No connected Wear node to acknowledge checkpoint $checkpointKey" }
            val messageClient = Wearable.getMessageClient(context)
            nodes.forEach { node ->
                Tasks.await(
                    messageClient.sendMessage(
                        node.id,
                        "/e2e/workout-sync/checkpoint-observed",
                        checkpointKey.toByteArray(Charsets.UTF_8)
                    ),
                    10,
                    TimeUnit.SECONDS
                )
            }
        }

        CrossDeviceSyncAssertions.waitForCheckpoint(
            context = context,
            checkpoint = CrossDeviceSyncAssertions.finalCheckpoint,
            timeoutMs = resolvedCheckpointTimeoutMs()
        )

        CrossDeviceSyncAssertions.waitForFinalDerivedState(
            context = context,
            timeoutMs = resolvedCheckpointTimeoutMs()
        )
    }
}

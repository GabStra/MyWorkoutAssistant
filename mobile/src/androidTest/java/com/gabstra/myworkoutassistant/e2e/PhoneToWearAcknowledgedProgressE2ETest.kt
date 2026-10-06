package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import com.gabstra.myworkoutassistant.sync.PhoneToWatchSyncCoordinator
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearAcknowledgedProgressE2ETest {

    @Test
    fun manualSync_startedFromMainThreadReachesWearEndpoint() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val result = CompletableDeferred<Boolean>()

        CoroutineScope(Dispatchers.Main).launch {
            result.complete(PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context))
        }

        assertTrue(withTimeout(30_000L) { result.await() })
        PhoneToWatchSyncCoordinator.cancelManualSyncToWatch(context)
    }

    @Test
    fun manualSync_cancelClearsUiAndCancelsWorker() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        PhoneToWatchSyncCoordinator.install(context)
        assertTrue(PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context))
        withTimeout(30_000L) {
            PhoneToWatchSyncCoordinator.manualSyncUiState.first { it != null }
        }

        PhoneToWatchSyncCoordinator.cancelManualSyncToWatch(context)

        assertEquals(null, PhoneToWatchSyncCoordinator.manualSyncUiState.value)
        withTimeout(30_000L) {
            WorkManager.getInstance(context)
                .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
                .first { workInfos ->
                    workInfos.isNotEmpty() &&
                        workInfos.all { it.state.isFinished }
                }
        }
        Unit
    }

    @Test
    fun foregroundSync_attachesToJustEnqueuedRestoreWorker() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        PhoneToWatchSyncCoordinator.install(context)
        MobileSyncToWatchWorker.enqueue(context)

        assertTrue(
            "Foreground sync should attach to the restore worker without a second endpoint probe",
            PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)
        )
        assertTrue(PhoneToWatchSyncCoordinator.manualSyncProgress.value != null)

        withTimeout(180_000L) {
            PhoneToWatchSyncCoordinator.manualSyncProgress.first { it == null }
        }
        Unit
    }

    @Test
    fun manualSync_reportsWearAcknowledgedProgressAndClosesAfterCompletion() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val observedProgress = mutableListOf<Float>()
        val observedPhases = mutableListOf<SyncPhase>()

        PhoneToWatchSyncCoordinator.install(context)
        val progressCollector = launch {
            PhoneToWatchSyncCoordinator.manualSyncProgress
                .filterNotNull()
                .collect(observedProgress::add)
        }
        val phaseCollector = launch {
            PhoneToWatchSyncCoordinator.manualSyncUiState
                .filterNotNull()
                .collect { state -> observedPhases.add(state.phase) }
        }

        PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)
        withTimeout(180_000L) {
            PhoneToWatchSyncCoordinator.manualSyncProgress.first { it == null }
        }
        progressCollector.cancelAndJoin()
        phaseCollector.cancelAndJoin()

        assertTrue(
            "Expected receiver-confirmed progress from Wear, observed=$observedProgress",
            observedProgress.any { it > 0f }
        )
        assertTrue(
            "Acknowledged progress must stay within 0..1, observed=$observedProgress",
            observedProgress.all { it in 0f..1f }
        )
        val firstConnecting = observedPhases.indexOf(SyncPhase.CONNECTING)
        val firstTransferring = observedPhases.indexOf(SyncPhase.TRANSFERRING)
        val firstProcessing = observedPhases.indexOf(SyncPhase.PROCESSING)
        val firstCompleted = observedPhases.indexOf(SyncPhase.COMPLETED)
        assertTrue(
            "Expected authoritative phase order CONNECTING -> TRANSFERRING -> PROCESSING -> COMPLETED, observed=$observedPhases",
            firstConnecting >= 0 &&
                firstTransferring > firstConnecting &&
                firstProcessing > firstTransferring &&
                firstCompleted > firstProcessing
        )

        val latestWork = WorkManager.getInstance(context)
            .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
            .first()
            .lastOrNull()
        assertEquals(WorkInfo.State.SUCCEEDED, latestWork?.state)
    }
}

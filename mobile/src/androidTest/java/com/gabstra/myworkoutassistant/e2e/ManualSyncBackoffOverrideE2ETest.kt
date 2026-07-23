package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import com.gabstra.myworkoutassistant.sync.PhoneToWatchSyncCoordinator
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class ManualSyncBackoffOverrideE2ETest {

    @Test
    fun manualSync_replacesDelayedAutomaticWorkInsteadOfWaitingForBackoff() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val workManager = WorkManager.getInstance(context)
        val delayedAutomaticWork = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>()
            .setInitialDelay(5, TimeUnit.MINUTES)
            .build()

        try {
            workManager.enqueueUniqueWork(
                MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
                ExistingWorkPolicy.REPLACE,
                delayedAutomaticWork
            )
            withTimeout(10_000L) {
                workManager
                    .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
                    .first { infos ->
                        infos.any { info ->
                            info.id == delayedAutomaticWork.id &&
                                info.state == WorkInfo.State.ENQUEUED
                        }
                    }
            }

            PhoneToWatchSyncCoordinator.install(context)
            assertTrue(
                "Manual sync should be accepted while automatic work is delayed",
                PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)
            )

            delay(1_000L)
            val activeWork = workManager
                .getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
                .first()
                .firstOrNull { info ->
                    info.state == WorkInfo.State.ENQUEUED ||
                        info.state == WorkInfo.State.RUNNING ||
                        info.state == WorkInfo.State.BLOCKED
                }

            assertNotEquals(
                "Manual sync must replace delayed automatic work instead of attaching to its backoff",
                delayedAutomaticWork.id,
                activeWork?.id
            )
        } finally {
            workManager.cancelUniqueWork(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
        }
    }
}

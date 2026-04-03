package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class DoubleProgressionNoHistoryPhoneSyncPreparationTest {
    private fun resolvedWorkerTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 60_000 else 180_000
    }

    @Test
    fun preparePhoneForNoHistoryDoubleProgressionRoundTripBadgeVerification() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(
            DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.createWorkoutStore()
        )

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, resolvedWorkerTimeoutMs())
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long
    ) {
        val start = System.currentTimeMillis()
        WorkManager.getInstance(context).getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for phone->watch no-history double-progression sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Phone->watch no-history double-progression sync worker failed.")
                WorkInfo.State.CANCELLED -> error("Phone->watch no-history double-progression sync worker was cancelled.")
                else -> false
            }
        }
    }
}

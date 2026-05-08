package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDevicePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ResumePhoneSyncPreparationTest {
    @Test
    fun preparePhoneForResumeCrossDeviceSync() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)

        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        WorkoutStoreRepository(context.filesDir)
            .saveWorkoutStore(ResumeCrossDevicePhoneWorkoutStoreFixture.createWorkoutStore())
        db.workoutHistoryDao().insert(ResumeCrossDevicePhoneWorkoutStoreFixture.createIncompleteHistory())
        db.setHistoryDao().insertAll(
            *ResumeCrossDevicePhoneWorkoutStoreFixture.createSeededSetHistories().toTypedArray()
        )
        db.workoutRecordDao().insert(ResumeCrossDevicePhoneWorkoutStoreFixture.createWorkoutRecord())

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "mobile_sync_to_watch",
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, timeoutMs = 60_000)
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long
    ) {
        val workManager = WorkManager.getInstance(context)
        val start = System.currentTimeMillis()
        workManager.getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for mobile sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Mobile sync worker failed during resume phone prep.")
                WorkInfo.State.CANCELLED -> error("Mobile sync worker was cancelled during resume phone prep.")
                else -> false
            }
        }
    }
}

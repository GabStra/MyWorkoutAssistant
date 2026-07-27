package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CalibrationSupersetPhoneSyncPreparationTest {
    @Test
    fun preparePhoneForCalibrationSupersetCrossDeviceSync() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()
        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(
            CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.createWorkoutStore()
        )

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        val workManager = WorkManager.getInstance(context)
        workManager.enqueueUniqueWork("mobile_sync_to_watch", ExistingWorkPolicy.REPLACE, request)
        workManager.getWorkInfoByIdFlow(request.id).first { info ->
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Calibration superset sync worker failed.")
                WorkInfo.State.CANCELLED -> error("Calibration superset sync worker was cancelled.")
                else -> false
            }
        }
        Unit
    }
}

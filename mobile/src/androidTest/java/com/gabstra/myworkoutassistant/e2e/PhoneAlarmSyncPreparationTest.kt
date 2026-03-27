package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.AlarmTriggerPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import java.util.UUID
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneAlarmSyncPreparationTest {

    private fun resolvedWorkerTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 60_000 else 180_000
    }

    @Test
    fun preparePhoneForAlarmSync() {
        runBlocking {
            val context = ApplicationProvider.getApplicationContext<android.content.Context>()
            val db = AppDatabase.getDatabase(context)

            db.workoutHistoryDao().deleteAll()
            db.setHistoryDao().deleteAll()
            db.restHistoryDao().deleteAll()
            db.workoutRecordDao().deleteAll()
            db.exerciseInfoDao().deleteAll()
            db.exerciseSessionProgressionDao().deleteAll()
            db.workoutScheduleDao().deleteAll()

            WorkoutStoreRepository(context.filesDir).saveWorkoutStore(
                AlarmTriggerPhoneWorkoutStoreFixture.createWorkoutStore()
            )

            val alarmExpectation = AlarmTriggerPhoneWorkoutStoreFixture.createCrossDeviceAlarmExpectation()
            db.workoutScheduleDao().insert(alarmExpectation.schedule)

            val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
                ExistingWorkPolicy.REPLACE,
                request
            )
            waitForSyncWorkerSuccess(context, request.id, resolvedWorkerTimeoutMs())
        }
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long = 180_000
    ) {
        val workManager = WorkManager.getInstance(context)
        val startedAt = System.currentTimeMillis()
        workManager.getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - startedAt > timeoutMs) {
                error("Timed out waiting for mobile alarm sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Mobile alarm sync worker failed during phone prep.")
                WorkInfo.State.CANCELLED -> error("Mobile alarm sync worker was cancelled during phone prep.")
                else -> false
            }
        }
    }
}

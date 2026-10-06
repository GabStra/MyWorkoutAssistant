package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.ZercherMovementPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class PhoneToWearZercherMovementPreparationTest {

    @Test
    fun preparePhoneWithZercherMovementForWearPreview() = runBlocking {
        val appContext = ApplicationProvider.getApplicationContext<android.content.Context>()
        val testContext = InstrumentationRegistry.getInstrumentation().context
        val movementJson = ZercherMovementPhoneWorkoutStoreFixture.readMovementJson(testContext)
        val movementRef = ZercherMovementPhoneWorkoutStoreFixture.movementRef(movementJson)

        val db = AppDatabase.getDatabase(appContext)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        WorkoutStoreRepository(appContext.filesDir).saveWorkoutStore(
            ZercherMovementPhoneWorkoutStoreFixture.createWorkoutStore(movementRef)
        )
        ExerciseMovementStorage.writeMovementJson(
            context = appContext,
            movementRef = movementRef,
            json = movementJson
        )

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(appContext).enqueueUniqueWork(
            "mobile_sync_to_watch",
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(appContext, request.id)
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long = 60_000
    ) {
        val workManager = WorkManager.getInstance(context)
        val start = System.currentTimeMillis()
        workManager.getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for mobile sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Mobile sync worker failed during Zercher movement prep.")
                WorkInfo.State.CANCELLED -> error("Mobile sync worker was cancelled during Zercher movement prep.")
                else -> false
            }
        }
    }
}

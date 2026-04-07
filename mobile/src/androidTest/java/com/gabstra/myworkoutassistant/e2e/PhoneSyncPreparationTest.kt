package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class PhoneSyncPreparationTest {

    private fun resolvedWorkerTimeoutMs(): Long = 60_000

    @Test
    fun preparePhoneForCrossDeviceSync() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        val store = CrossDeviceSyncPhoneWorkoutStoreFixture.createWorkoutStore()
        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(store)
        seedDeterministicPhoneHistory(db)
        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "mobile_sync_to_watch",
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, resolvedWorkerTimeoutMs())
    }

    private suspend fun seedDeterministicPhoneHistory(db: AppDatabase) {
        val now = LocalDateTime.now().minusMinutes(5)
        val workoutHistory = WorkoutHistory(
            id = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
            workoutId = CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID,
            date = LocalDate.now(),
            time = LocalTime.now(),
            startTime = now,
            duration = 1_200,
            heartBeatRecords = listOf(108, 112, 115),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_GLOBAL_ID,
            version = 2u
        )

        val setA1 = SetHistory(
            id = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_SET_HISTORY_A1_ID,
            workoutHistoryId = workoutHistory.id,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
            order = 0u,
            startTime = now.minusMinutes(4),
            endTime = now.minusMinutes(3),
            setData = WeightSetData(
                actualReps = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_REPS,
                actualWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_WEIGHT,
                volume = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_REPS *
                    CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_WEIGHT
            ),
            skipped = false,
            executionSequence = 1u,
            version = 2u
        )

        val setA2 = SetHistory(
            id = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_SET_HISTORY_A2_ID,
            workoutHistoryId = workoutHistory.id,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
            order = 1u,
            startTime = now.minusMinutes(2),
            endTime = now.minusMinutes(1),
            setData = WeightSetData(
                actualReps = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_REPS,
                actualWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_WEIGHT,
                volume = CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_REPS *
                    CrossDeviceSyncPhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_WEIGHT
            ),
            skipped = false,
            executionSequence = 2u,
            version = 2u
        )

        db.workoutHistoryDao().insert(workoutHistory)
        db.setHistoryDao().insertAll(setA1, setA2)
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long = 180_000
    ) {
        val workManager = WorkManager.getInstance(context)
        val start = System.currentTimeMillis()
        workManager.getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for mobile sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Mobile sync worker failed during phone prep.")
                WorkInfo.State.CANCELLED -> error("Mobile sync worker was cancelled during phone prep.")
                else -> false
            }
        }
    }
}

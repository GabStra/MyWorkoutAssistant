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
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class DoubleProgressionPhoneSyncPreparationTest {
    private fun resolvedWorkerTimeoutMs(): Long = 60_000

    @Test
    fun preparePhoneForDoubleProgressionRoundTripBadgeVerification() = runBlocking {
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
        seedDeterministicPhoneHistory(db)

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, resolvedWorkerTimeoutMs())
    }

    private suspend fun seedDeterministicPhoneHistory(db: AppDatabase) {
        val now = LocalDateTime.now().minusMinutes(5)
        val workoutHistory = WorkoutHistory(
            id = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.PREVIOUS_SESSION_HISTORY_ID,
            workoutId = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_ID,
            date = LocalDate.now(),
            time = LocalTime.now(),
            startTime = now,
            duration = 480,
            heartBeatRecords = listOf(108, 111, 113),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID,
            version = 2u
        )

        val setHistory = SetHistory(
            id = UUID.fromString("78602027-f42d-4834-9cf3-f0193c63cc8f"),
            workoutHistoryId = workoutHistory.id,
            exerciseId = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.EXERCISE_ID,
            setId = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.SET_ID,
            order = 0u,
            startTime = now.minusMinutes(4),
            endTime = now.minusMinutes(3),
            setData = WeightSetData(
                actualReps = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.PREVIOUS_SESSION_REPS,
                actualWeight = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT,
                volume = DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.PREVIOUS_SESSION_REPS *
                    DoubleProgressionRoundTripBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT
            ),
            skipped = false,
            executionSequence = 1u,
            version = 2u
        )

        db.workoutHistoryDao().insert(workoutHistory)
        db.setHistoryDao().insert(setHistory)
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long
    ) {
        val start = System.currentTimeMillis()
        WorkManager.getInstance(context).getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for phone->watch double-progression sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Phone->watch double-progression sync worker failed.")
                WorkInfo.State.CANCELLED -> error("Phone->watch double-progression sync worker was cancelled.")
                else -> false
            }
        }
    }
}

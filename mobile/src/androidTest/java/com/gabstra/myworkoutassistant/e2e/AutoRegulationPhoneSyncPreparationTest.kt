package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgePhoneWorkoutStoreFixture
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
class AutoRegulationPhoneSyncPreparationTest {
    private fun resolvedWorkerTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 60_000 else 180_000
    }

    @Test
    fun preparePhoneForAutoRegulationPhoneToWearBadgeVerification() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)

        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(
            AutoRegulationSetBadgePhoneWorkoutStoreFixture.createWorkoutStore()
        )
        seedDeterministicPhoneHistory(db)

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )

        waitForSyncWorkerSuccess(
            context = context,
            requestId = request.id,
            timeoutMs = resolvedWorkerTimeoutMs()
        )
    }

    private suspend fun seedDeterministicPhoneHistory(db: AppDatabase) {
        val now = LocalDateTime.now().minusMinutes(5)
        val workoutHistory = WorkoutHistory(
            id = AutoRegulationSetBadgePhoneWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
            workoutId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.WORKOUT_ID,
            date = LocalDate.now(),
            time = LocalTime.now(),
            startTime = now,
            duration = 600,
            heartBeatRecords = listOf(110, 114, 118),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID,
            version = 2u
        )

        val firstSet = SetHistory(
            id = AutoRegulationSetBadgePhoneWorkoutStoreFixture.PHONE_TO_WEAR_SET_HISTORY_1_ID,
            workoutHistoryId = workoutHistory.id,
            exerciseId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.EXERCISE_ID,
            setId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_1_ID,
            order = 0u,
            startTime = now.minusMinutes(4),
            endTime = now.minusMinutes(3),
            setData = WeightSetData(
                actualReps = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS,
                actualWeight = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT,
                volume = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS *
                    AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT
            ),
            skipped = false,
            executionSequence = 1u,
            version = 2u
        )

        val secondSet = SetHistory(
            id = AutoRegulationSetBadgePhoneWorkoutStoreFixture.PHONE_TO_WEAR_SET_HISTORY_2_ID,
            workoutHistoryId = workoutHistory.id,
            exerciseId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.EXERCISE_ID,
            setId = AutoRegulationSetBadgePhoneWorkoutStoreFixture.SET_2_ID,
            order = 1u,
            startTime = now.minusMinutes(2),
            endTime = now.minusMinutes(1),
            setData = WeightSetData(
                actualReps = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS,
                actualWeight = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT,
                volume = AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_REPS *
                    AutoRegulationSetBadgePhoneWorkoutStoreFixture.TEMPLATE_WEIGHT
            ),
            skipped = false,
            executionSequence = 2u,
            version = 2u
        )

        db.workoutHistoryDao().insert(workoutHistory)
        db.setHistoryDao().insertAll(firstSet, secondSet)
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID,
        timeoutMs: Long
    ) {
        val start = System.currentTimeMillis()
        WorkManager.getInstance(context).getWorkInfoByIdFlow(requestId).first { info ->
            if (System.currentTimeMillis() - start > timeoutMs) {
                error("Timed out waiting for phone->watch auto-regulation sync worker success.")
            }
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Phone->watch auto-regulation sync worker failed.")
                WorkInfo.State.CANCELLED -> error("Phone->watch auto-regulation sync worker was cancelled.")
                else -> false
            }
        }
    }
}

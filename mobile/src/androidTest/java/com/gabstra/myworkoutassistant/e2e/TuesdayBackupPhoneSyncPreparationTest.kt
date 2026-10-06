package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class TuesdayBackupPhoneSyncPreparationTest {
    @Test
    fun restoreTuesdayBackupAndSyncToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val backupFile = File(requireNotNull(context.getExternalFilesDir(null)), BACKUP_FILE_NAME)
        require(backupFile.isFile) { "Staged backup not found at ${backupFile.absolutePath}." }
        val backup = fromJSONtoAppBackup(backupFile.readText())
        val targetWorkout = backup.WorkoutStore.workouts.single {
            it.id == WORKOUT_ID && it.isActive
        }
        require(targetWorkout.name == WORKOUT_NAME)

        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(
            backup.WorkoutStore.copy(
                workouts = backup.WorkoutStore.workouts.filter { it.isActive }
            )
        )
        clearPhoneHistory(AppDatabase.getDatabase(context))

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id)
    }

    private suspend fun clearPhoneHistory(db: AppDatabase) {
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.restHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()
        db.errorLogDao().deleteAll()
    }

    private suspend fun waitForSyncWorkerSuccess(
        context: android.content.Context,
        requestId: UUID
    ) {
        val workManager = WorkManager.getInstance(context)
        workManager.getWorkInfoByIdFlow(requestId).first { info ->
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> true
                WorkInfo.State.FAILED -> error("Phone-to-Wear sync worker failed.")
                WorkInfo.State.CANCELLED -> error("Phone-to-Wear sync worker was cancelled.")
                else -> false
            }
        }
    }

    companion object {
        private const val BACKUP_FILE_NAME = "workout_store_backup_2026-07-27_19-18-20.json"
        const val WORKOUT_NAME = "Day 1 - Tuesday Upper Strength + Traps"
        val WORKOUT_ID: UUID = UUID.fromString("4b3a063e-29ef-45e1-99fb-aa38a396c772")
    }
}

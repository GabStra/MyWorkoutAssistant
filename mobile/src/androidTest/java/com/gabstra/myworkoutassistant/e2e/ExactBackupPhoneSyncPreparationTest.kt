package com.gabstra.myworkoutassistant.e2e

import android.provider.MediaStore
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.shared.AppBackup
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
class ExactBackupPhoneSyncPreparationTest {

    @Test
    fun restoreExactBackupAndSyncToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val backup = readBackupFromDownloads()
        applyBackupToPhone(context, db, backup)
        assertTargetResumeRecordExistsOnPhone(db)

        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            MobileSyncToWatchWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id)
    }

    private fun readBackupFromDownloads(): AppBackup {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val appExternalBackupFile = context.getExternalFilesDir(null)?.let { dir ->
            File(dir, BACKUP_FILE_NAME)
        }
        if (appExternalBackupFile != null && appExternalBackupFile.exists()) {
            val json = appExternalBackupFile.readText()
            require(json.isNotBlank()) {
                "Backup file '$BACKUP_FILE_NAME' in app external files is empty."
            }
            Log.d(TAG, "Loaded exact backup from app external files (${json.length} chars)")
            return fromJSONtoAppBackup(json)
        }

        val resolver = context.contentResolver
        val uri = resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.MediaColumns._ID),
            "${MediaStore.MediaColumns.DISPLAY_NAME} = ?",
            arrayOf(BACKUP_FILE_NAME),
            null
        )?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
            val id = cursor.getLong(idIndex)
            MediaStore.Downloads.EXTERNAL_CONTENT_URI.buildUpon().appendPath(id.toString()).build()
        }

        requireNotNull(uri) {
            "Expected backup file '$BACKUP_FILE_NAME' in Downloads MediaStore on phone emulator."
        }
        val json = resolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
        require(!json.isNullOrBlank()) {
            "Backup file '$BACKUP_FILE_NAME' was found but could not be read."
        }
        Log.d(TAG, "Loaded exact backup from Downloads (${json.length} chars)")
        return fromJSONtoAppBackup(json)
    }

    private suspend fun applyBackupToPhone(
        context: android.content.Context,
        db: AppDatabase,
        appBackup: AppBackup
    ) {
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()
        val restHistoryDao = db.restHistoryDao()
        val exerciseInfoDao = db.exerciseInfoDao()
        val workoutScheduleDao = db.workoutScheduleDao()
        val workoutRecordDao = db.workoutRecordDao()
        val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
        val errorLogDao = db.errorLogDao()

        val allowedWorkouts = appBackup.WorkoutStore.workouts.filter { workout ->
            workout.isActive || appBackup.WorkoutHistories.any { it.workoutId == workout.id }
        }
        val workoutStore = appBackup.WorkoutStore.copy(workouts = allowedWorkouts)
        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(workoutStore)

        workoutHistoryDao.deleteAll()
        setHistoryDao.deleteAll()
        restHistoryDao.deleteAll()
        exerciseInfoDao.deleteAll()
        workoutScheduleDao.deleteAll()
        workoutRecordDao.deleteAll()
        exerciseSessionProgressionDao.deleteAll()
        errorLogDao.deleteAll()

        val validWorkoutHistories = appBackup.WorkoutHistories.filter { history ->
            allowedWorkouts.any { it.id == history.workoutId }
        }
        val validWorkoutHistoryIds = validWorkoutHistories.map { it.id }.toSet()

        val validSetHistories = appBackup.SetHistories.filter { setHistory ->
            setHistory.workoutHistoryId in validWorkoutHistoryIds
        }
        val validRestHistories = (appBackup.RestHistories ?: emptyList()).filter { restHistory ->
            restHistory.workoutHistoryId in validWorkoutHistoryIds
        }
        val validExerciseSessionProgressions = appBackup.ExerciseSessionProgressions.filter { progression ->
            progression.workoutHistoryId in validWorkoutHistoryIds
        }
        val validWorkoutRecords = appBackup.WorkoutRecords.filter { record ->
            allowedWorkouts.any { it.id == record.workoutId }
        }

        workoutHistoryDao.insertAll(*validWorkoutHistories.toTypedArray())
        setHistoryDao.insertAll(*validSetHistories.toTypedArray())
        restHistoryDao.insertAll(*validRestHistories.toTypedArray())
        exerciseInfoDao.insertAll(*appBackup.ExerciseInfos.toTypedArray())
        workoutScheduleDao.insertAll(*appBackup.WorkoutSchedules.toTypedArray())
        workoutRecordDao.insertAll(*validWorkoutRecords.toTypedArray())
        exerciseSessionProgressionDao.insertAll(*validExerciseSessionProgressions.toTypedArray())
        appBackup.ErrorLogs?.takeIf { it.isNotEmpty() }?.let { logs ->
            errorLogDao.insertAll(*logs.toTypedArray())
        }

        Log.d(
            TAG,
            "Applied backup to phone db: histories=${validWorkoutHistories.size}, " +
                "setHistories=${validSetHistories.size}, restHistories=${validRestHistories.size}, " +
                "records=${validWorkoutRecords.size}"
        )
    }

    private suspend fun assertTargetResumeRecordExistsOnPhone(db: AppDatabase) {
        val workoutRecordDao = db.workoutRecordDao()
        val workoutHistoryDao = db.workoutHistoryDao()
        val targetRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(TARGET_WORKOUT_ID)
        requireNotNull(targetRecord) {
            "Phone restore did not produce workout record for target workout $TARGET_WORKOUT_ID"
        }
        require(targetRecord.workoutHistoryId == TARGET_WORKOUT_HISTORY_ID) {
            "Phone target record points to ${targetRecord.workoutHistoryId}, expected $TARGET_WORKOUT_HISTORY_ID"
        }
        val targetHistory = workoutHistoryDao.getWorkoutHistoryById(targetRecord.workoutHistoryId)
        requireNotNull(targetHistory) {
            "Phone target workout history ${targetRecord.workoutHistoryId} missing after restore."
        }
        require(!targetHistory.isDone) {
            "Phone target workout history ${targetHistory.id} is done; expected unfinished for resume."
        }
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
                WorkInfo.State.FAILED -> error("Mobile sync worker failed for exact-backup prep.")
                WorkInfo.State.CANCELLED -> error("Mobile sync worker was cancelled for exact-backup prep.")
                else -> false
            }
        }
    }

    companion object {
        private const val TAG = "ExactBackupPhoneSyncPreparationTest"
        private const val BACKUP_FILE_NAME = "workout_store_backup_2026-04-28_18-12-49.json"
        private val TARGET_WORKOUT_ID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
        private val TARGET_WORKOUT_HISTORY_ID = UUID.fromString("9b67898a-febe-4c09-9d4e-830cff9ca864")
    }
}

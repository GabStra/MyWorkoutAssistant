package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistoriesByWorkoutAndExercise
import java.io.File
import kotlinx.coroutines.runBlocking

object ExactBackupResumeFixture {
    const val ASSET_NAME = "resume_exact_backup_fixture.json"
    const val WORKOUT_NAME = "A — Squat/Bench"
    const val WORKOUT_ID = "efdba35b-82bf-418e-9362-4ffa2d39e435"
    const val WORKOUT_HISTORY_ID = "9b67898a-febe-4c09-9d4e-830cff9ca864"

    fun setup(context: Context) {
        val backup = readBackupFromAsset(context)
        seedWorkoutStoreFile(context, backup)
        seedDatabase(context, backup)
    }

    private fun readBackupFromAsset(context: Context): AppBackup {
        val instrumentationAssets = InstrumentationRegistry.getInstrumentation().context.assets
        val json = try {
            instrumentationAssets.open(ASSET_NAME).bufferedReader().use { it.readText() }
        } catch (_: Exception) {
            context.assets.open(ASSET_NAME).bufferedReader().use { it.readText() }
        }
        return fromJSONtoAppBackup(json)
    }

    private fun seedWorkoutStoreFile(context: Context, backup: AppBackup) {
        val json = fromWorkoutStoreToJSON(backup.WorkoutStore)
        File(context.filesDir, "workout_store.json").writeText(json)
    }

    private fun seedDatabase(context: Context, backup: AppBackup) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        WearFixtureDatabaseSeeder.resetResumeScenarioTables(db)

        if (backup.WorkoutHistories.isNotEmpty()) {
            db.workoutHistoryDao().insertAll(*backup.WorkoutHistories.toTypedArray())
        }
        val sanitizedSetHistories = sanitizeRestPlacementInSetHistoriesByWorkoutAndExercise(backup.SetHistories)
        if (sanitizedSetHistories.isNotEmpty()) {
            db.setHistoryDao().insertAll(*sanitizedSetHistories.toTypedArray())
        }
        val restHistories = backup.RestHistories.orEmpty()
        if (restHistories.isNotEmpty()) {
            db.restHistoryDao().insertAll(*restHistories.toTypedArray())
        }
        if (backup.WorkoutRecords.isNotEmpty()) {
            db.workoutRecordDao().insertAll(*backup.WorkoutRecords.toTypedArray())
        }
        if (backup.ExerciseSessionProgressions.isNotEmpty()) {
            db.exerciseSessionProgressionDao().insertAll(*backup.ExerciseSessionProgressions.toTypedArray())
        }
        if (backup.ExerciseInfos.isNotEmpty()) {
            db.exerciseInfoDao().insertAll(*backup.ExerciseInfos.toTypedArray())
        }
    }
}

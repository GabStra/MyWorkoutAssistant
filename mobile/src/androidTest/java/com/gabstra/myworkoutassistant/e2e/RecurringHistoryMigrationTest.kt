package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RecurringHistoryMigrationTest {

    @Test
    fun migration70And72To73PreservesRowsAndIgnoresLegacySourceNotes() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val profileId = "recurring_migration_${UUID.randomUUID().toString().replace("-", "")}"
        val databaseName = Profiles.databaseName(profileId)
        val historyId = UUID.randomUUID()
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val history = WorkoutHistory(
            id = historyId,
            workoutId = workoutId,
            date = LocalDate.of(2026, 11, 15),
            time = LocalTime.of(9, 30),
            startTime = LocalDateTime.of(2026, 11, 15, 9, 30),
            duration = 900,
            heartBeatRecords = listOf(101, 112),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = globalId,
        )
        val setHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = historyId,
            exerciseId = exerciseId,
            setId = setId,
            order = 0u,
            startTime = history.startTime,
            endTime = history.startTime.plusSeconds(45),
            setData = WeightSetData(8, 42.5, 340.0, SetSubCategory.WorkSet),
            skipped = false,
        )
        val restHistory = RestHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = historyId,
            scope = RestHistoryScope.INTRA_EXERCISE,
            executionSequence = 1u,
            setData = RestSetData(15, 30),
            startTime = history.startTime.plusSeconds(45),
            endTime = history.startTime.plusSeconds(75),
            exerciseId = exerciseId,
            restSetId = UUID.randomUUID(),
            order = 1u,
        )
        val progression = ExerciseSessionProgression(
            id = UUID.randomUUID(),
            workoutHistoryId = historyId,
            exerciseId = exerciseId,
            expectedSets = listOf(SimpleSet(42.5, 8)),
            progressionState = ProgressionState.PROGRESS,
            vsExpected = Ternary.EQUAL,
            vsPrevious = Ternary.ABOVE,
            previousSessionVolume = 320.0,
            expectedVolume = 340.0,
            executedVolume = 340.0,
        )

        var db: AppDatabase? = null
        try {
            db = AppDatabase.getDatabase(context, profileId)
            db!!.workoutHistoryDao().insert(history)
            db!!.setHistoryDao().insert(setHistory)
            db!!.restHistoryDao().insert(restHistory)
            db!!.exerciseSessionProgressionDao().insert(progression)
            db!!.close()
            db = null

            // Recreate the v70 columns on a uniquely named database, then let Room apply every
            // production migration through v73.
            SQLiteDatabase.openDatabase(
                context.getDatabasePath(databaseName).absolutePath,
                null,
                SQLiteDatabase.OPEN_READWRITE,
            ).use { rawDb ->
                rawDb.execSQL("ALTER TABLE workout_history DROP COLUMN recurringSessionId")
                rawDb.execSQL("ALTER TABLE workout_history DROP COLUMN origin")
                rawDb.execSQL("ALTER TABLE workout_history DROP COLUMN startTimeKnown")
                rawDb.execSQL("ALTER TABLE workout_history DROP COLUMN durationKnown")
                rawDb.execSQL("ALTER TABLE set_history DROP COLUMN recurringExerciseId")
                rawDb.execSQL("ALTER TABLE set_history DROP COLUMN exerciseDefinitionIdSnapshot")
                rawDb.execSQL("ALTER TABLE set_history DROP COLUMN exerciseTypeSnapshot")
                rawDb.execSQL("ALTER TABLE set_history DROP COLUMN exerciseNameSnapshot")
                rawDb.version = 70
            }

            db = AppDatabase.getDatabase(context, profileId)
            val migratedHistory = requireNotNull(db!!.workoutHistoryDao().getWorkoutHistoryById(historyId))
            val migratedSet = requireNotNull(db!!.setHistoryDao().getSetHistoryById(setHistory.id))
            val migratedRest = requireNotNull(db!!.restHistoryDao().getById(restHistory.id))
            val migratedProgression = requireNotNull(
                db!!.exerciseSessionProgressionDao().getExerciseSessionProgressionById(progression.id),
            )
            assertEquals(listOf(101, 112), migratedHistory.heartBeatRecords)
            assertEquals(900, migratedHistory.duration)
            assertEquals(WorkoutHistoryOrigin.RECORDED, migratedHistory.origin)
            assertEquals(true, migratedHistory.startTimeKnown)
            assertEquals(true, migratedHistory.durationKnown)
            assertNull(migratedHistory.recurringSessionId)
            assertNull(migratedSet.recurringExerciseId)
            assertNull(migratedSet.exerciseDefinitionIdSnapshot)
            assertNull(migratedSet.exerciseTypeSnapshot)
            assertNull(migratedSet.exerciseNameSnapshot)
            assertEquals(42.5, (migratedSet.setData as WeightSetData).actualWeight, 0.0)
            assertEquals(restHistory, migratedRest)
            assertEquals(progression, migratedProgression)

            val sessionId = UUID.randomUUID()
            val trackId = UUID.randomUUID()
            val definitionId = UUID.randomUUID()
            val recurringHistory = migratedHistory.copy(
                recurringSessionId = sessionId,
                origin = WorkoutHistoryOrigin.USER_IMPORTED,
                time = LocalTime.MIDNIGHT,
                startTime = LocalDateTime.of(migratedHistory.date, LocalTime.MIDNIGHT),
                duration = 0,
                startTimeKnown = false,
                durationKnown = false,
            )
            val recurringSet = migratedSet.copy(
                startTime = null,
                endTime = null,
                recurringExerciseId = trackId,
                exerciseDefinitionIdSnapshot = definitionId,
                exerciseTypeSnapshot = "WEIGHT",
                exerciseNameSnapshot = "Dumbbell substitute",
            )
            val backup = AppBackup(
                WorkoutStore = WorkoutStore(
                    birthDateYear = 1990,
                    weightKg = 80.0,
                    progressionPercentageAmount = 0.05,
                ),
                WorkoutHistories = listOf(recurringHistory),
                SetHistories = listOf(recurringSet),
                ExerciseInfos = emptyList(),
                WorkoutSchedules = emptyList(),
                WorkoutRecords = emptyList(),
                ExerciseSessionProgressions = emptyList(),
            )

            val cleanBackupJson = fromAppBackupToJSON(backup)
            assertFalse(JSONObject(cleanBackupJson).getJSONArray("WorkoutHistories")
                .getJSONObject(0).has("sourceNote"))
            val legacyJsonObject = JSONObject(cleanBackupJson)
            legacyJsonObject.getJSONArray("WorkoutHistories").getJSONObject(0)
                .put("sourceNote", "legacy private note that should be ignored")
            val restored = fromJSONtoAppBackup(legacyJsonObject.toString())
            val restoredHistory = restored.WorkoutHistories.single()
            val restoredSet = restored.SetHistories.single()
            assertEquals(sessionId, restoredHistory.recurringSessionId)
            assertEquals(WorkoutHistoryOrigin.USER_IMPORTED, restoredHistory.origin)
            assertEquals(false, restoredHistory.startTimeKnown)
            assertEquals(false, restoredHistory.durationKnown)
            assertEquals(LocalTime.MIDNIGHT, restoredHistory.time)
            assertEquals(LocalDateTime.of(restoredHistory.date, LocalTime.MIDNIGHT), restoredHistory.startTime)
            assertEquals(0, restoredHistory.duration)
            assertEquals(trackId, restoredSet.recurringExerciseId)
            assertEquals(definitionId, restoredSet.exerciseDefinitionIdSnapshot)
            assertEquals("WEIGHT", restoredSet.exerciseTypeSnapshot)
            assertEquals("Dumbbell substitute", restoredSet.exerciseNameSnapshot)
            assertFalse(JSONObject(fromAppBackupToJSON(restored)).getJSONArray("WorkoutHistories")
                .getJSONObject(0).has("sourceNote"))

            db!!.workoutHistoryDao().update(restoredHistory)
            db!!.setHistoryDao().insert(restoredSet)
            val before72MigrationHistory = requireNotNull(
                db!!.workoutHistoryDao().getWorkoutHistoryById(historyId),
            )
            val before72MigrationSet = requireNotNull(db!!.setHistoryDao().getSetHistoryById(setHistory.id))
            val before72MigrationRest = requireNotNull(db!!.restHistoryDao().getById(restHistory.id))
            val before72MigrationProgression = requireNotNull(
                db!!.exerciseSessionProgressionDao().getExerciseSessionProgressionById(progression.id),
            )
            db!!.close()
            db = null

            // Simulate a populated v72 row with a non-null sourceNote. Production 72 -> 73 must
            // rebuild the table while retaining every remaining history and set value.
            SQLiteDatabase.openDatabase(
                context.getDatabasePath(databaseName).absolutePath,
                null,
                SQLiteDatabase.OPEN_READWRITE,
            ).use { rawDb ->
                rawDb.execSQL("ALTER TABLE workout_history ADD COLUMN sourceNote TEXT")
                rawDb.execSQL(
                    "UPDATE workout_history SET sourceNote = ? WHERE id = ?",
                    arrayOf("legacy private note", historyId.toString()),
                )
                rawDb.version = 72
            }

            db = AppDatabase.getDatabase(context, profileId)
            val after72MigrationHistory = requireNotNull(
                db!!.workoutHistoryDao().getWorkoutHistoryById(historyId),
            )
            val after72MigrationSet = requireNotNull(db!!.setHistoryDao().getSetHistoryById(setHistory.id))
            val after72MigrationRest = requireNotNull(db!!.restHistoryDao().getById(restHistory.id))
            val after72MigrationProgression = requireNotNull(
                db!!.exerciseSessionProgressionDao().getExerciseSessionProgressionById(progression.id),
            )
            assertEquals(before72MigrationHistory, after72MigrationHistory)
            assertEquals(before72MigrationSet, after72MigrationSet)
            assertEquals(before72MigrationRest, after72MigrationRest)
            assertEquals(before72MigrationProgression, after72MigrationProgression)
            assertFalse(databaseHasColumn(context, databaseName, "workout_history", "sourceNote"))
            assertFalse(databaseHasForeignKeyViolations(context, databaseName))
            assertEquals(WorkoutHistoryOrigin.USER_IMPORTED, after72MigrationHistory.origin)
            assertEquals(false, after72MigrationHistory.startTimeKnown)
            assertEquals(false, after72MigrationHistory.durationKnown)
            assertEquals(LocalTime.MIDNIGHT, after72MigrationHistory.time)
            assertEquals(LocalDateTime.of(after72MigrationHistory.date, LocalTime.MIDNIGHT), after72MigrationHistory.startTime)
            assertEquals(0, after72MigrationHistory.duration)
            assertEquals(42.5, (after72MigrationSet.setData as WeightSetData).actualWeight, 0.0)
        } finally {
            db?.close()
            context.deleteDatabase(databaseName)
        }
    }

    private fun databaseHasColumn(context: Context, databaseName: String, table: String, column: String): Boolean {
        SQLiteDatabase.openDatabase(
            context.getDatabasePath(databaseName).absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY,
        ).use { rawDb ->
            rawDb.rawQuery("PRAGMA table_info($table)", null).use { cursor ->
                val nameColumn = cursor.getColumnIndexOrThrow("name")
                while (cursor.moveToNext()) {
                    if (cursor.getString(nameColumn) == column) return true
                }
            }
        }
        return false
    }

    private fun databaseHasForeignKeyViolations(context: Context, databaseName: String): Boolean {
        SQLiteDatabase.openDatabase(
            context.getDatabasePath(databaseName).absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY,
        ).use { rawDb ->
            rawDb.rawQuery("PRAGMA foreign_key_check", null).use { cursor ->
                return cursor.moveToFirst()
            }
        }
    }
}

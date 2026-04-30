package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.typeconverters.ExerciseSessionSnapshotTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListSimpleSetTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ProgressionStateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.RestHistoryScopeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TernaryTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UUIDConverter

@Database(
    entities = [
        SetHistory::class,
        RestHistory::class,
        WorkoutHistory::class,
        WorkoutRecord::class,
        ExerciseInfo::class,
        WorkoutSchedule::class,
        ExerciseSessionProgression::class,
        ErrorLog::class
    ],
    version = 58,
    exportSchema = false
)
@TypeConverters(
    DateTimeTypeConverter::class,
    DateTypeConverter::class,
    TimeTypeConverter::class,
    SetDataTypeConverter::class,
    RestHistoryScopeTypeConverter::class,
    UUIDConverter::class,
    UIntConverter::class,
    ListIntConverter::class,
    ExerciseSessionSnapshotTypeConverter::class,
    ListSimpleSetTypeConverter::class,
    ProgressionStateTypeConverter::class,
    TernaryTypeConverter::class
)

abstract class AppDatabase : RoomDatabase() {
    abstract fun setHistoryDao(): SetHistoryDao
    abstract fun restHistoryDao(): RestHistoryDao
    abstract fun workoutHistoryDao(): WorkoutHistoryDao
    abstract fun workoutRecordDao(): WorkoutRecordDao
    abstract fun exerciseInfoDao(): ExerciseInfoDao
    abstract fun workoutScheduleDao(): WorkoutScheduleDao
    abstract fun exerciseSessionProgressionDao(): ExerciseSessionProgressionDao
    abstract fun errorLogDao(): ErrorLogDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getDatabase(context: Context): AppDatabase {
            val existing = INSTANCE
            if (existing != null && existing.isOpen) {
                return existing
            }

            return synchronized(this) {
                val current = INSTANCE
                if (current != null && current.isOpen) {
                    current
                } else {
                    val instance = Room.databaseBuilder(
                        context.applicationContext,
                        AppDatabase::class.java,
                        "app_database_2",
                    )
                        .fallbackToDestructiveMigration()
                        .addCallback(object : RoomDatabase.Callback() {
                            override fun onOpen(db: SupportSQLiteDatabase) {
                                super.onOpen(db)
                                db.execSQL(
                                    "DELETE FROM workout_record WHERE workoutHistoryId NOT IN " +
                                        "(SELECT id FROM workout_history)"
                                )
                                db.execSQL(
                                    """
                                    DELETE FROM workout_record
                                    WHERE id IN (
                                        SELECT victim.id
                                        FROM workout_record AS victim
                                        JOIN workout_record AS keeper
                                            ON victim.workoutId = keeper.workoutId
                                            AND (
                                                COALESCE(victim.lastActiveSyncAt, '') < COALESCE(keeper.lastActiveSyncAt, '')
                                                OR (
                                                    COALESCE(victim.lastActiveSyncAt, '') = COALESCE(keeper.lastActiveSyncAt, '')
                                                    AND victim.activeSessionRevision < keeper.activeSessionRevision
                                                )
                                                OR (
                                                    COALESCE(victim.lastActiveSyncAt, '') = COALESCE(keeper.lastActiveSyncAt, '')
                                                    AND victim.activeSessionRevision = keeper.activeSessionRevision
                                                    AND victim.id < keeper.id
                                                )
                                            )
                                    )
                                    """.trimIndent()
                                )
                                db.execSQL(
                                    "CREATE UNIQUE INDEX IF NOT EXISTS " +
                                        "index_workout_record_workoutId_unique ON workout_record(workoutId)"
                                )
                            }
                        })
                        .build()
                    INSTANCE = instance
                    instance
                }
            }
        }

        fun closeInstance() {
            synchronized(this) {
                INSTANCE?.close()
                INSTANCE = null
            }
        }
    }
}

package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.room.migration.Migration
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.typeconverters.HeartRateStreamsTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.HeartRateStreamTimesTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ExerciseSessionSnapshotTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.IbiRecordsTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListSimpleSetTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ProgressionStateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.RestHistoryScopeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TernaryTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UUIDConverter
import com.gabstra.myworkoutassistant.shared.datalayer.MotionCaptureSyncDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionDao
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import com.gabstra.myworkoutassistant.shared.typeconverters.WorkoutSessionEndReasonTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.RunningResultsTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.WorkoutHistoryOriginTypeConverter
import java.util.concurrent.ConcurrentHashMap

@Database(
    entities = [
        SetHistory::class,
        RestHistory::class,
        WorkoutHistory::class,
        WorkoutRecord::class,
        ExerciseInfo::class,
        WorkoutSchedule::class,
        ExerciseSessionProgression::class,
        ErrorLog::class,
        MotionCaptureSessionEntity::class,
        MotionCaptureSegmentEntity::class
    ],
    version = 73,
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
    IbiRecordsTypeConverter::class,
    HeartRateStreamsTypeConverter::class,
    HeartRateStreamTimesTypeConverter::class,
    ExerciseSessionSnapshotTypeConverter::class,
    ListSimpleSetTypeConverter::class,
    ProgressionStateTypeConverter::class,
    TernaryTypeConverter::class,
    WorkoutSessionEndReasonTypeConverter::class,
    RunningResultsTypeConverter::class,
    WorkoutHistoryOriginTypeConverter::class
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
    abstract fun motionCaptureSessionDao(): MotionCaptureSessionDao
    abstract fun motionCaptureSegmentDao(): MotionCaptureSegmentDao
    abstract fun motionCaptureSyncDao(): MotionCaptureSyncDao

    companion object {
        private val MIGRATION_60_61 = object : Migration(60, 61) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN runningResults TEXT NOT NULL DEFAULT '[]'")
            }
        }

        private val MIGRATION_62_63 = object : Migration(62, 63) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN ibiRecords TEXT NOT NULL DEFAULT '[]'")
            }
        }

        private val MIGRATION_63_64 = object : Migration(63, 64) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN restRmssdMs REAL")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN restSdnnMs REAL")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN sweatLossMl INTEGER")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN spo2MinPercent INTEGER")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN spo2AvgPercent INTEGER")
            }
        }

        private val MIGRATION_69_70 = object : Migration(69, 70) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE workout_history ADD COLUMN heartRateStreamTimes TEXT NOT NULL DEFAULT '{}'"
                )
                db.execSQL(
                    "ALTER TABLE workout_history ADD COLUMN heartRateStreamsStartEpochMs INTEGER"
                )
            }
        }

        private val MIGRATION_70_71 = object : Migration(70, 71) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN recurringSessionId TEXT")
                db.execSQL("ALTER TABLE set_history ADD COLUMN recurringExerciseId TEXT")
                db.execSQL("ALTER TABLE set_history ADD COLUMN exerciseDefinitionIdSnapshot TEXT")
                db.execSQL("ALTER TABLE set_history ADD COLUMN exerciseTypeSnapshot TEXT")
            }
        }

        private val MIGRATION_71_72 = object : Migration(71, 72) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN origin TEXT NOT NULL DEFAULT 'RECORDED'")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN startTimeKnown INTEGER NOT NULL DEFAULT 1")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN durationKnown INTEGER NOT NULL DEFAULT 1")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN sourceNote TEXT")
                db.execSQL("ALTER TABLE set_history ADD COLUMN exerciseNameSnapshot TEXT")
            }
        }

        /**
         * Removes the retired workout-level source note without dropping history rows.
         *
         * SQLite DROP COLUMN is not available on all supported Android versions, so rebuild
         * only workout_history from the exact Room 73 model. Before dropping the parent, stage
         * every table with an incoming workout-history foreign key: SQLite's implicit delete for
         * DROP TABLE can cascade into children when foreign-key enforcement is enabled. Restore
         * rows after the replacement parent has its original name, then verify relationships.
         */
        private val MIGRATION_72_73 = object : Migration(72, 73) {
            override fun migrate(db: SupportSQLiteDatabase) {
                val childTables = listOf(
                    "set_history",
                    "rest_history",
                    "exercise_session_progression",
                )
                childTables.forEach { table ->
                    db.execSQL("CREATE TEMP TABLE `${table}_migration_backup` AS SELECT * FROM `$table`")
                }
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS `workout_history_new` (
                        `id` TEXT NOT NULL,
                        `workoutId` TEXT NOT NULL,
                        `date` INTEGER NOT NULL,
                        `time` TEXT NOT NULL,
                        `startTime` INTEGER NOT NULL,
                        `duration` INTEGER NOT NULL,
                        `heartBeatRecords` TEXT NOT NULL,
                        `ibiRecords` TEXT NOT NULL,
                        `restRmssdMs` REAL,
                        `restSdnnMs` REAL,
                        `sweatLossMl` INTEGER,
                        `skinTempStartC` REAL,
                        `skinTempMaxC` REAL,
                        `heartRateSource` TEXT,
                        `heartRateStreams` TEXT NOT NULL,
                        `heartRateStreamTimes` TEXT NOT NULL,
                        `heartRateStreamsStartEpochMs` INTEGER,
                        `isDone` INTEGER NOT NULL,
                        `hasBeenSentToHealth` INTEGER NOT NULL,
                        `globalId` TEXT NOT NULL,
                        `version` INTEGER NOT NULL,
                        `endReason` TEXT NOT NULL,
                        `runningResults` TEXT NOT NULL,
                        `recurringSessionId` TEXT,
                        `origin` TEXT NOT NULL,
                        `startTimeKnown` INTEGER NOT NULL,
                        `durationKnown` INTEGER NOT NULL,
                        PRIMARY KEY(`id`)
                    )
                    """.trimIndent()
                )
                db.execSQL(
                    """
                    INSERT INTO `workout_history_new` (
                        `id`, `workoutId`, `date`, `time`, `startTime`, `duration`,
                        `heartBeatRecords`, `ibiRecords`, `restRmssdMs`, `restSdnnMs`,
                        `sweatLossMl`, `skinTempStartC`, `skinTempMaxC`, `heartRateSource`,
                        `heartRateStreams`, `heartRateStreamTimes`, `heartRateStreamsStartEpochMs`,
                        `isDone`, `hasBeenSentToHealth`, `globalId`, `version`, `endReason`,
                        `runningResults`, `recurringSessionId`, `origin`, `startTimeKnown`,
                        `durationKnown`
                    )
                    SELECT
                        `id`, `workoutId`, `date`, `time`, `startTime`, `duration`,
                        `heartBeatRecords`, `ibiRecords`, `restRmssdMs`, `restSdnnMs`,
                        `sweatLossMl`, `skinTempStartC`, `skinTempMaxC`, `heartRateSource`,
                        `heartRateStreams`, `heartRateStreamTimes`, `heartRateStreamsStartEpochMs`,
                        `isDone`, `hasBeenSentToHealth`, `globalId`, `version`, `endReason`,
                        `runningResults`, `recurringSessionId`, `origin`, `startTimeKnown`,
                        `durationKnown`
                    FROM `workout_history`
                    """.trimIndent()
                )
                db.execSQL("DROP TABLE `workout_history`")
                db.execSQL("ALTER TABLE `workout_history_new` RENAME TO `workout_history`")

                childTables.forEach { table ->
                    db.execSQL(
                        "INSERT OR IGNORE INTO `$table` SELECT * FROM `${table}_migration_backup`",
                    )
                    db.execSQL("DROP TABLE `${table}_migration_backup`")
                }

                db.query("PRAGMA foreign_key_check").use { cursor ->
                    check(!cursor.moveToFirst()) {
                        "Foreign-key violation after rebuilding workout_history for migration 72 -> 73"
                    }
                }
            }
        }

        private val MIGRATION_68_69 = object : Migration(68, 69) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE workout_history ADD COLUMN heartRateStreams TEXT NOT NULL DEFAULT '{}'"
                )
                db.execSQL("ALTER TABLE workout_history DROP COLUMN secondaryHeartBeatRecords")
                db.execSQL("ALTER TABLE workout_history DROP COLUMN secondaryIbiRecords")
            }
        }

        private val MIGRATION_67_68 = object : Migration(67, 68) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_record ADD COLUMN motionCaptureEnabled INTEGER")
            }
        }

        private val MIGRATION_66_67 = object : Migration(66, 67) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN heartRateSource TEXT")
                db.execSQL(
                    "ALTER TABLE workout_history ADD COLUMN secondaryHeartBeatRecords TEXT NOT NULL DEFAULT '[]'"
                )
                db.execSQL(
                    "ALTER TABLE workout_history ADD COLUMN secondaryIbiRecords TEXT NOT NULL DEFAULT '[]'"
                )
            }
        }

        private val MIGRATION_65_66 = object : Migration(65, 66) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history ADD COLUMN skinTempStartC REAL")
                db.execSQL("ALTER TABLE workout_history ADD COLUMN skinTempMaxC REAL")
            }
        }

        private val MIGRATION_64_65 = object : Migration(64, 65) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE workout_history DROP COLUMN spo2MinPercent")
                db.execSQL("ALTER TABLE workout_history DROP COLUMN spo2AvgPercent")
            }
        }

        private val MIGRATION_61_62 = object : Migration(61, 62) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS `motion_capture_session` (
                        `id` TEXT NOT NULL,
                        `workoutId` TEXT NOT NULL,
                        `workoutHistoryId` TEXT,
                        `status` TEXT NOT NULL,
                        `startedAtEpochMs` INTEGER NOT NULL,
                        `endedAtEpochMs` INTEGER,
                        `deviceManufacturer` TEXT NOT NULL,
                        `deviceModel` TEXT NOT NULL,
                        `deviceName` TEXT NOT NULL,
                        `appVersion` TEXT NOT NULL,
                        `sessionDirectoryName` TEXT NOT NULL,
                        `sensorConfigJson` TEXT NOT NULL,
                        `exerciseCandidatesJson` TEXT NOT NULL,
                        PRIMARY KEY(`id`)
                    )
                    """.trimIndent()
                )
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS `motion_capture_segment` (
                        `id` TEXT NOT NULL,
                        `sessionId` TEXT NOT NULL,
                        `sequenceIndex` INTEGER NOT NULL,
                        `startedAtEpochMs` INTEGER NOT NULL,
                        `endedAtEpochMs` INTEGER,
                        `startedAtElapsedRealtimeNanos` INTEGER NOT NULL,
                        `endedAtElapsedRealtimeNanos` INTEGER,
                        `stateName` TEXT NOT NULL,
                        `autoLabelJson` TEXT NOT NULL,
                        `correctedLabelJson` TEXT,
                        `reviewStatus` TEXT NOT NULL,
                        `chunkFileNamesJson` TEXT NOT NULL,
                        PRIMARY KEY(`id`)
                    )
                    """.trimIndent()
                )
            }
        }

        // One open instance per profile database, keyed by database name.
        private val instances = ConcurrentHashMap<String, AppDatabase>()

        fun getDatabase(context: Context): AppDatabase =
            getDatabase(context, Profiles.activeProfileId(context))

        /** Opens the database of a specific profile, e.g. when applying data that arrived tagged with one. */
        fun getDatabase(context: Context, profileId: String): AppDatabase {
            val databaseName = Profiles.databaseName(profileId)
            val existing = instances[databaseName]
            if (existing != null && existing.isOpen) {
                return existing
            }

            return synchronized(this) {
                val current = instances[databaseName]
                if (current != null && current.isOpen) {
                    current
                } else {
                    val instance = Room.databaseBuilder(
                        context.applicationContext,
                        AppDatabase::class.java,
                        databaseName,
                    )
                        .addMigrations(
                            MIGRATION_60_61, MIGRATION_61_62, MIGRATION_62_63, MIGRATION_63_64,
                            MIGRATION_64_65, MIGRATION_65_66, MIGRATION_66_67, MIGRATION_67_68,
                            MIGRATION_68_69, MIGRATION_69_70, MIGRATION_70_71, MIGRATION_71_72,
                            MIGRATION_72_73
                        )
                        .fallbackToDestructiveMigration(dropAllTables = true)
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
                    instances[databaseName] = instance
                    instance
                }
            }
        }

        fun closeInstance() {
            synchronized(this) {
                instances.values.forEach { it.close() }
                instances.clear()
            }
        }
    }
}

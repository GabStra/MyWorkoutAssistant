package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListSetHistoryTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListSimpleSetTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ProgressionStateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TernaryTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UUIDConverter

@Database(
    entities = [SetHistory::class, WorkoutHistory::class,WorkoutRecord::class, ExerciseInfo::class, WorkoutSchedule::class, ExerciseSessionProgression::class, ErrorLog::class],
    version = 54,
    exportSchema = false
)
@TypeConverters(
    DateTimeTypeConverter::class,
    DateTypeConverter::class,
    TimeTypeConverter::class,
    SetDataTypeConverter::class,
    UUIDConverter::class,
    UIntConverter::class,
    ListIntConverter::class,
    ListSetHistoryTypeConverter::class,
    ListSimpleSetTypeConverter::class,
    ProgressionStateTypeConverter::class,
    TernaryTypeConverter::class
)

abstract class AppDatabase : RoomDatabase() {
    abstract fun setHistoryDao(): SetHistoryDao
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

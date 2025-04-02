package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

import com.gabstra.myworkoutassistant.shared.typeconverters.DateTimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.ListIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UIntConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UUIDConverter

@Database(entities = [SetHistory::class, WorkoutHistory::class,WorkoutRecord::class, ExerciseInfo::class, WorkoutSchedule::class], version = 46, exportSchema = false)
@TypeConverters(DateTimeTypeConverter::class,DateTypeConverter::class, TimeTypeConverter::class, SetDataTypeConverter::class, UUIDConverter::class,UIntConverter::class,ListIntConverter::class)

abstract class AppDatabase : RoomDatabase() {
    abstract fun setHistoryDao(): SetHistoryDao
    abstract fun workoutHistoryDao(): WorkoutHistoryDao
    abstract fun workoutRecordDao(): WorkoutRecordDao
    abstract fun exerciseInfoDao(): ExerciseInfoDao
    abstract fun workoutScheduleDao(): WorkoutScheduleDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getDatabase(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
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
}

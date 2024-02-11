package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.UUIDConverter

@Database(entities = [SetHistory::class, WorkoutHistory::class], version = 17, exportSchema = false)
@TypeConverters(DateTypeConverter::class, SetDataTypeConverter::class, UUIDConverter::class)

abstract class AppDatabase : RoomDatabase() {
    abstract fun setHistoryDao(): SetHistoryDao
    abstract fun workoutHistoryDao(): WorkoutHistoryDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getDatabase(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "app_database",
                )
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}
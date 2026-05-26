package com.gabstra.myworkoutassistant.healthconnect.external

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTimeTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import com.gabstra.myworkoutassistant.shared.typeconverters.TimeTypeConverter

@Database(
    entities = [ExternalHealthConnectSessionEntity::class],
    version = 1,
    exportSchema = false,
)
@TypeConverters(
    DateTypeConverter::class,
    TimeTypeConverter::class,
    DateTimeTypeConverter::class,
    ExternalHeartRateSampleListTypeConverter::class,
)
abstract class ExternalHealthConnectSessionDatabase : RoomDatabase() {
    abstract fun externalHealthConnectSessionDao(): ExternalHealthConnectSessionDao

    companion object {
        @Volatile
        private var INSTANCE: ExternalHealthConnectSessionDatabase? = null

        fun getDatabase(context: Context): ExternalHealthConnectSessionDatabase {
            val existing = INSTANCE
            if (existing != null && existing.isOpen) {
                return existing
            }

            return synchronized(this) {
                val current = INSTANCE
                if (current != null && current.isOpen) {
                    current
                } else {
                    Room.databaseBuilder(
                        context.applicationContext,
                        ExternalHealthConnectSessionDatabase::class.java,
                        "external_health_connect_session_cache",
                    )
                        .fallbackToDestructiveMigration()
                        .build()
                        .also { INSTANCE = it }
                }
            }
        }
    }
}

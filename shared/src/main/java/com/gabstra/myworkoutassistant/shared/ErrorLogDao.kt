package com.gabstra.myworkoutassistant.shared

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface ErrorLogDao {
    @Query("SELECT * FROM error_log ORDER BY timestamp DESC")
    fun getAllErrorLogs(): Flow<List<ErrorLog>>
    
    @Query("SELECT * FROM error_log ORDER BY timestamp DESC LIMIT :limit")
    suspend fun getErrorLogs(limit: Int = 1000): List<ErrorLog>
    
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(errorLog: ErrorLog)
    
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(vararg errorLogs: ErrorLog)
    
    @Query("DELETE FROM error_log")
    suspend fun deleteAll()
    
    @Query("SELECT COUNT(*) FROM error_log")
    suspend fun getErrorLogCount(): Int
}


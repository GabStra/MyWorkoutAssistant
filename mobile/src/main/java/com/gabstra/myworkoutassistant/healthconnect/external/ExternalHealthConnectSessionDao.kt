package com.gabstra.myworkoutassistant.healthconnect.external

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow
import java.time.LocalDateTime

@Dao
interface ExternalHealthConnectSessionDao {
    @Query(
        """
        SELECT * FROM external_health_connect_session
        ORDER BY date DESC, time DESC, startTime DESC
        """
    )
    fun observeAllSessions(): Flow<List<ExternalHealthConnectSessionEntity>>

    @Query(
        """
        SELECT * FROM external_health_connect_session
        WHERE id = :id
        LIMIT 1
        """
    )
    suspend fun getById(id: String): ExternalHealthConnectSessionEntity?

    @Query(
        """
        SELECT id FROM external_health_connect_session
        WHERE startTime >= :startInclusive AND startTime <= :endInclusive
        """
    )
    suspend fun getIdsInRange(
        startInclusive: LocalDateTime,
        endInclusive: LocalDateTime,
    ): List<String>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(sessions: List<ExternalHealthConnectSessionEntity>)

    @Query("DELETE FROM external_health_connect_session WHERE id IN (:ids)")
    suspend fun deleteByIds(ids: List<String>)
}

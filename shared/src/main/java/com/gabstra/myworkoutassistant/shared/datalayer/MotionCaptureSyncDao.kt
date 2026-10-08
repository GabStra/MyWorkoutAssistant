package com.gabstra.myworkoutassistant.shared.datalayer

import androidx.room.Dao
import androidx.room.Query
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import kotlinx.coroutines.flow.Flow
import java.util.UUID

/**
 * Additional read/delete access to the motion-capture tables for the sensor-session sync feature.
 *
 * The insert/upsert paths live in [com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionDao]
 * and [com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentDao]; this DAO complements
 * them with the enumerate/delete queries needed by the watch sender and the phone receiver/UI.
 * These queries do not alter the schema, so no database version bump is required.
 */
@Dao
interface MotionCaptureSyncDao {
    @Query("SELECT * FROM motion_capture_session ORDER BY startedAtEpochMs DESC")
    fun observeAllSessions(): Flow<List<MotionCaptureSessionEntity>>

    @Query("SELECT * FROM motion_capture_session WHERE status = :status ORDER BY startedAtEpochMs ASC")
    suspend fun getSessionsByStatus(status: String): List<MotionCaptureSessionEntity>

    @Query("SELECT * FROM motion_capture_segment WHERE sessionId = :sessionId ORDER BY sequenceIndex ASC")
    fun observeSegmentsBySessionId(sessionId: UUID): Flow<List<MotionCaptureSegmentEntity>>

    @Query(
        "SELECT sessionId AS sessionId, COUNT(*) AS segmentCount " +
            "FROM motion_capture_segment GROUP BY sessionId"
    )
    fun observeSegmentCounts(): Flow<List<MotionCaptureSegmentCount>>

    @Query("DELETE FROM motion_capture_session WHERE id = :sessionId")
    suspend fun deleteSessionById(sessionId: UUID)

    @Query("DELETE FROM motion_capture_segment WHERE sessionId = :sessionId")
    suspend fun deleteSegmentsBySessionId(sessionId: UUID)
}

data class MotionCaptureSegmentCount(
    val sessionId: UUID,
    val segmentCount: Int
)

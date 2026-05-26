package com.gabstra.myworkoutassistant.shared.motion

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import java.util.UUID

@Dao
interface MotionCaptureSessionDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(session: MotionCaptureSessionEntity)

    @Query("SELECT * FROM motion_capture_session WHERE id = :id")
    suspend fun getById(id: UUID): MotionCaptureSessionEntity?

    @Query("SELECT * FROM motion_capture_session WHERE status = :status ORDER BY startedAtEpochMs DESC LIMIT 1")
    suspend fun getLatestByStatus(status: String): MotionCaptureSessionEntity?

    @Query("SELECT * FROM motion_capture_session WHERE workoutHistoryId = :workoutHistoryId ORDER BY startedAtEpochMs DESC LIMIT 1")
    suspend fun getLatestByWorkoutHistoryId(workoutHistoryId: UUID): MotionCaptureSessionEntity?

    @Query("SELECT * FROM motion_capture_session ORDER BY startedAtEpochMs DESC LIMIT 1")
    suspend fun getLatest(): MotionCaptureSessionEntity?
}

@Dao
interface MotionCaptureSegmentDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(segment: MotionCaptureSegmentEntity)

    @Query("SELECT * FROM motion_capture_segment WHERE id = :id")
    suspend fun getById(id: UUID): MotionCaptureSegmentEntity?

    @Query("SELECT * FROM motion_capture_segment WHERE sessionId = :sessionId ORDER BY sequenceIndex ASC")
    suspend fun getBySessionId(sessionId: UUID): List<MotionCaptureSegmentEntity>
}

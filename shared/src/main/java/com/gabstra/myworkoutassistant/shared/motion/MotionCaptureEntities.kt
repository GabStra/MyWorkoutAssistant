package com.gabstra.myworkoutassistant.shared.motion

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "motion_capture_session")
data class MotionCaptureSessionEntity(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val status: String,
    val startedAtEpochMs: Long,
    val endedAtEpochMs: Long?,
    val deviceManufacturer: String,
    val deviceModel: String,
    val deviceName: String,
    val appVersion: String,
    val sessionDirectoryName: String,
    val sensorConfigJson: String,
    val exerciseCandidatesJson: String
)

@Entity(tableName = "motion_capture_segment")
data class MotionCaptureSegmentEntity(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val sessionId: UUID,
    val sequenceIndex: Int,
    val startedAtEpochMs: Long,
    val endedAtEpochMs: Long?,
    val startedAtElapsedRealtimeNanos: Long,
    val endedAtElapsedRealtimeNanos: Long?,
    val stateName: String,
    val autoLabelJson: String,
    val correctedLabelJson: String?,
    val reviewStatus: String,
    val chunkFileNamesJson: String
)

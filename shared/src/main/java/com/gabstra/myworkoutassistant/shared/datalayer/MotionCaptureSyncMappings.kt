package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureJson
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus

/**
 * Bidirectional mapping between the motion-capture Room entities and the domain records used in
 * `MotionCaptureExportMetadata`. Used by the watch sender (entities -> records for export) and by
 * the phone receiver (records parsed from `metadata.json` -> entities for persistence).
 */
object MotionCaptureSyncMappings {
    fun sessionRecordToEntity(record: MotionCaptureSessionRecord): MotionCaptureSessionEntity =
        MotionCaptureSessionEntity(
            id = record.id,
            workoutId = record.workoutId,
            workoutHistoryId = record.workoutHistoryId,
            status = record.status.name,
            startedAtEpochMs = record.startedAtEpochMs,
            endedAtEpochMs = record.endedAtEpochMs,
            deviceManufacturer = record.deviceManufacturer,
            deviceModel = record.deviceModel,
            deviceName = record.deviceName,
            appVersion = record.appVersion,
            sessionDirectoryName = record.sessionDirectoryName,
            sensorConfigJson = MotionCaptureJson.sensorConfigToJson(record.sensorConfig),
            exerciseCandidatesJson = MotionCaptureJson.candidateListToJson(record.exerciseCandidates)
        )

    fun sessionEntityToRecord(entity: MotionCaptureSessionEntity): MotionCaptureSessionRecord =
        MotionCaptureSessionRecord(
            id = entity.id,
            workoutId = entity.workoutId,
            workoutHistoryId = entity.workoutHistoryId,
            status = MotionCaptureSessionStatus.valueOf(entity.status),
            startedAtEpochMs = entity.startedAtEpochMs,
            endedAtEpochMs = entity.endedAtEpochMs,
            deviceManufacturer = entity.deviceManufacturer,
            deviceModel = entity.deviceModel,
            deviceName = entity.deviceName,
            appVersion = entity.appVersion,
            sessionDirectoryName = entity.sessionDirectoryName,
            sensorConfig = MotionCaptureJson.sensorConfigFromJson(entity.sensorConfigJson),
            exerciseCandidates = MotionCaptureJson.candidateListFromJson(entity.exerciseCandidatesJson)
        )

    fun segmentRecordToEntity(record: MotionCaptureSegmentRecord): MotionCaptureSegmentEntity =
        MotionCaptureSegmentEntity(
            id = record.id,
            sessionId = record.sessionId,
            sequenceIndex = record.sequenceIndex,
            startedAtEpochMs = record.startedAtEpochMs,
            endedAtEpochMs = record.endedAtEpochMs,
            startedAtElapsedRealtimeNanos = record.startedAtElapsedRealtimeNanos,
            endedAtElapsedRealtimeNanos = record.endedAtElapsedRealtimeNanos,
            stateName = record.stateName,
            autoLabelJson = MotionCaptureJson.labelToJson(record.autoLabel),
            correctedLabelJson = record.correctedLabel?.let(MotionCaptureJson::labelToJson),
            reviewStatus = record.reviewStatus.name,
            chunkFileNamesJson = MotionCaptureJson.stringListToJson(record.chunkFileNames)
        )

    fun segmentEntityToRecord(entity: MotionCaptureSegmentEntity): MotionCaptureSegmentRecord =
        MotionCaptureSegmentRecord(
            id = entity.id,
            sessionId = entity.sessionId,
            sequenceIndex = entity.sequenceIndex,
            startedAtEpochMs = entity.startedAtEpochMs,
            endedAtEpochMs = entity.endedAtEpochMs,
            startedAtElapsedRealtimeNanos = entity.startedAtElapsedRealtimeNanos,
            endedAtElapsedRealtimeNanos = entity.endedAtElapsedRealtimeNanos,
            stateName = entity.stateName,
            autoLabel = MotionCaptureJson.labelFromJson(entity.autoLabelJson),
            correctedLabel = entity.correctedLabelJson?.let(MotionCaptureJson::labelFromJson),
            reviewStatus = MotionCaptureReviewStatus.valueOf(entity.reviewStatus),
            chunkFileNames = MotionCaptureJson.stringListFromJson(entity.chunkFileNamesJson)
        )
}

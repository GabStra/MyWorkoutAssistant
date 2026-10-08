package com.gabstra.myworkoutassistant.shared.motion

import java.util.UUID

object MotionCaptureSessionEditor {
    fun startSegment(
        sessionId: UUID,
        sequenceIndex: Int,
        label: MotionCaptureLabel,
        startedAtEpochMs: Long,
        startedAtElapsedRealtimeNanos: Long,
        initialChunkFileName: String? = null
    ): MotionCaptureSegmentRecord {
        return MotionCaptureSegmentRecord(
            id = UUID.randomUUID(),
            sessionId = sessionId,
            sequenceIndex = sequenceIndex,
            startedAtEpochMs = startedAtEpochMs,
            endedAtEpochMs = null,
            startedAtElapsedRealtimeNanos = startedAtElapsedRealtimeNanos,
            endedAtElapsedRealtimeNanos = null,
            stateName = label.stateName,
            autoLabel = label,
            correctedLabel = null,
            reviewStatus = MotionCaptureReviewStatus.PENDING,
            chunkFileNames = initialChunkFileName?.let(::listOf) ?: emptyList()
        )
    }

    fun closeSegment(
        segment: MotionCaptureSegmentRecord,
        endedAtEpochMs: Long,
        endedAtElapsedRealtimeNanos: Long
    ): MotionCaptureSegmentRecord {
        return segment.copy(
            endedAtEpochMs = endedAtEpochMs,
            endedAtElapsedRealtimeNanos = endedAtElapsedRealtimeNanos
        )
    }

    fun appendChunkReference(
        segment: MotionCaptureSegmentRecord,
        chunkFileName: String
    ): MotionCaptureSegmentRecord {
        if (segment.chunkFileNames.contains(chunkFileName)) {
            return segment
        }
        return segment.copy(chunkFileNames = segment.chunkFileNames + chunkFileName)
    }

    fun confirmSegment(segment: MotionCaptureSegmentRecord): MotionCaptureSegmentRecord =
        segment.copy(reviewStatus = MotionCaptureReviewStatus.CONFIRMED)

    fun relabelSegment(
        segment: MotionCaptureSegmentRecord,
        correctedLabel: MotionCaptureLabel,
        reviewStatus: MotionCaptureReviewStatus
    ): MotionCaptureSegmentRecord {
        return segment.copy(
            correctedLabel = correctedLabel,
            reviewStatus = reviewStatus
        )
    }
}

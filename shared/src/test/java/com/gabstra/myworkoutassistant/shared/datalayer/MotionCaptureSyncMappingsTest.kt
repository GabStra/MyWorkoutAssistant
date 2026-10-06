package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureExerciseCandidate
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabel
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelKind
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSensorConfig
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorType
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionRecord
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.UUID

class MotionCaptureSyncMappingsTest {

    private val sessionId = UUID.randomUUID()

    private fun buildSessionRecord() = MotionCaptureSessionRecord(
        id = sessionId,
        workoutId = UUID.randomUUID(),
        workoutHistoryId = UUID.randomUUID(),
        status = MotionCaptureSessionStatus.COMPLETED,
        startedAtEpochMs = 1_700_000_000_000L,
        endedAtEpochMs = 1_700_000_540_000L,
        deviceManufacturer = "Google",
        deviceModel = "Pixel Watch 2",
        deviceName = "lydia-t",
        appVersion = "1.2.3",
        sessionDirectoryName = sessionId.toString(),
        sensorConfig = MotionCaptureSensorConfig(
            sampleRateHz = 50,
            chunkSampleCount = 500,
            observedSensors = listOf(
                MotionSensorType.ACCELEROMETER,
                MotionSensorType.HEART_RATE
            )
        ),
        exerciseCandidates = listOf(
            MotionCaptureExerciseCandidate(
                exerciseId = UUID.randomUUID(),
                exerciseName = "Back Squat",
                exerciseType = ExerciseType.WEIGHT,
                supersetId = null,
                executionOrder = 0
            )
        )
    )

    private fun buildSegmentRecord() = MotionCaptureSegmentRecord(
        id = UUID.randomUUID(),
        sessionId = sessionId,
        sequenceIndex = 3,
        startedAtEpochMs = 1_700_000_010_000L,
        endedAtEpochMs = 1_700_000_040_000L,
        startedAtElapsedRealtimeNanos = 123L,
        endedAtElapsedRealtimeNanos = 456L,
        stateName = "Set",
        autoLabel = MotionCaptureLabel(
            kind = MotionCaptureLabelKind.EXERCISE,
            stateName = "Set",
            exerciseId = UUID.randomUUID(),
            exerciseName = "Back Squat",
            setId = UUID.randomUUID(),
            setIndex = 2u,
            exerciseType = ExerciseType.WEIGHT,
            isWarmupSet = false
        ),
        correctedLabel = MotionCaptureLabel(
            kind = MotionCaptureLabelKind.REST,
            stateName = "Rest"
        ),
        reviewStatus = MotionCaptureReviewStatus.RELABELED,
        chunkFileNames = listOf("chunk_00001.csv.gz", "chunk_00002.csv.gz")
    )

    @Test
    fun `session record to entity and back preserves all fields`() {
        val record = buildSessionRecord()

        val roundTripped = MotionCaptureSyncMappings.sessionEntityToRecord(
            MotionCaptureSyncMappings.sessionRecordToEntity(record)
        )

        assertEquals(record, roundTripped)
    }

    @Test
    fun `segment record to entity and back preserves all fields`() {
        val record = buildSegmentRecord()

        val roundTripped = MotionCaptureSyncMappings.segmentEntityToRecord(
            MotionCaptureSyncMappings.segmentRecordToEntity(record)
        )

        assertEquals(record, roundTripped)
    }

    @Test
    fun `segment without corrected label maps corrected label to null`() {
        val record = buildSegmentRecord().copy(correctedLabel = null)

        val roundTripped = MotionCaptureSyncMappings.segmentEntityToRecord(
            MotionCaptureSyncMappings.segmentRecordToEntity(record)
        )

        assertNull(roundTripped.correctedLabel)
        assertEquals(record.autoLabel, roundTripped.autoLabel)
    }
}

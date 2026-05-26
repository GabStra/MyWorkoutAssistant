package com.gabstra.myworkoutassistant.shared.motion

import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionCaptureSessionEditorTest {
    @Test
    fun `chunk metadata references are retained without duplicates`() {
        val segment = MotionCaptureSessionEditor.startSegment(
            sessionId = UUID.randomUUID(),
            sequenceIndex = 0,
            label = MotionCaptureLabel(
                kind = MotionCaptureLabelKind.EXERCISE,
                stateName = "Set"
            ),
            startedAtEpochMs = 1000L,
            startedAtElapsedRealtimeNanos = 2000L,
            initialChunkFileName = "chunk_00001.csv"
        )

        val appended = MotionCaptureSessionEditor.appendChunkReference(segment, "chunk_00002.csv")
        val deduplicated = MotionCaptureSessionEditor.appendChunkReference(appended, "chunk_00002.csv")

        assertEquals(listOf("chunk_00001.csv", "chunk_00002.csv"), deduplicated.chunkFileNames)
    }

    @Test
    fun `corrected label overwrites export label without losing auto label`() {
        val segment = MotionCaptureSessionEditor.startSegment(
            sessionId = UUID.randomUUID(),
            sequenceIndex = 0,
            label = MotionCaptureLabel(
                kind = MotionCaptureLabelKind.EXERCISE,
                stateName = "Set",
                exerciseName = "Squat"
            ),
            startedAtEpochMs = 1000L,
            startedAtElapsedRealtimeNanos = 2000L
        )

        val relabeled = MotionCaptureSessionEditor.relabelSegment(
            segment = segment,
            correctedLabel = segment.autoLabel.copy(exerciseName = "Front Squat"),
            reviewStatus = MotionCaptureReviewStatus.RELABELED
        )

        assertEquals("Squat", relabeled.autoLabel.exerciseName)
        assertEquals("Front Squat", relabeled.correctedLabel?.exerciseName)
        assertEquals(MotionCaptureReviewStatus.RELABELED, relabeled.reviewStatus)
    }

    @Test
    fun `segment closure records timestamps`() {
        val segment = MotionCaptureSessionEditor.startSegment(
            sessionId = UUID.randomUUID(),
            sequenceIndex = 0,
            label = MotionCaptureLabel(
                kind = MotionCaptureLabelKind.REST,
                stateName = "Rest"
            ),
            startedAtEpochMs = 1000L,
            startedAtElapsedRealtimeNanos = 2000L
        )

        val closed = MotionCaptureSessionEditor.closeSegment(segment, 1500L, 2500L)

        assertEquals(1500L, closed.endedAtEpochMs)
        assertEquals(2500L, closed.endedAtElapsedRealtimeNanos)
        assertTrue(closed.endedAtEpochMs!! >= closed.startedAtEpochMs)
    }
}

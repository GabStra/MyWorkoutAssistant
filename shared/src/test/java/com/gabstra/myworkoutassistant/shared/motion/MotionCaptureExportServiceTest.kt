package com.gabstra.myworkoutassistant.shared.motion

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.google.gson.Gson
import java.io.File
import java.nio.file.Files
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionCaptureExportServiceTest {
    @Test
    fun `export writes metadata manifest events and referenced chunks`() {
        val root = Files.createTempDirectory("motion-export-test").toFile()
        val sessionDirectory = File(root, "session").apply { mkdirs() }
        File(sessionDirectory, "chunk_00001.csv").writeText("sensorType\nACCELEROMETER\n")
        File(sessionDirectory, "events.csv").writeText(
            "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName," +
                "setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n" +
                "entered_set,1000,10,\"Set\",,,,\"0\",WEIGHT,false,,,\n"
        )
        val session = MotionCaptureSessionRecord(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            status = MotionCaptureSessionStatus.COMPLETED,
            startedAtEpochMs = 1000L,
            endedAtEpochMs = 2000L,
            deviceManufacturer = "Google",
            deviceModel = "Pixel Watch",
            deviceName = "pixel_watch",
            appVersion = "1.0",
            sessionDirectoryName = "session",
            sensorConfig = MotionCaptureSensorConfig(),
            exerciseCandidates = listOf(
                MotionCaptureExerciseCandidate(
                    exerciseId = UUID.randomUUID(),
                    exerciseName = "Squat",
                    exerciseType = ExerciseType.WEIGHT,
                    supersetId = null,
                    executionOrder = 0
                )
            )
        )
        val segments = listOf(
            MotionCaptureSegmentRecord(
                id = UUID.randomUUID(),
                sessionId = session.id,
                sequenceIndex = 0,
                startedAtEpochMs = 1000L,
                endedAtEpochMs = 2000L,
                startedAtElapsedRealtimeNanos = 10L,
                endedAtElapsedRealtimeNanos = 20L,
                stateName = "Set",
                autoLabel = MotionCaptureLabel(
                    kind = MotionCaptureLabelKind.EXERCISE,
                    stateName = "Set",
                    exerciseName = "Squat"
                ),
                correctedLabel = null,
                reviewStatus = MotionCaptureReviewStatus.CONFIRMED,
                chunkFileNames = listOf("chunk_00001.csv")
            )
        )

        val exportDirectory = MotionCaptureExportService().export(
            session = session,
            segments = segments,
            sessionDirectory = sessionDirectory,
            exportRootDirectory = File(root, "exports")
        )

        val metadata = Gson().fromJson(
            File(exportDirectory, "metadata.json").readText(),
            MotionCaptureExportMetadata::class.java
        )

        assertTrue(File(exportDirectory, "metadata.json").exists())
        assertTrue(File(exportDirectory, "events.csv").exists())
        assertTrue(File(exportDirectory, "chunk_00001.csv").exists())
        assertEquals(2, metadata.schemaVersion)
        assertEquals("events.csv", metadata.eventsFile)
        assertEquals(listOf("chunk_00001.csv"), metadata.exportedChunkFiles)
        assertEquals(listOf("chunk_00001.csv"), metadata.rawSensorFiles.map { it.fileName })
        assertEquals(false, metadata.workoutContext.orderedExerciseCandidates.first().noRepExpected)
    }
}

package com.gabstra.myworkoutassistant.shared.motion

import com.google.gson.GsonBuilder
import java.io.File

data class MotionCaptureExportMetadata(
    val schemaVersion: Int = 2,
    val session: MotionCaptureSessionRecord,
    val sensorConfig: MotionCaptureSensorConfig,
    val workoutContext: MotionCaptureWorkoutContext,
    val coarseReviewedSegments: List<MotionCaptureSegmentRecord>,
    val rawSensorFiles: List<MotionCaptureRawSensorFileReference>,
    val eventsFile: String,
    val exportedChunkFiles: List<String>
)

class MotionCaptureExportService {
    private val gson = GsonBuilder().setPrettyPrinting().create()
    private val eventsFileName = "events.csv"

    fun export(
        session: MotionCaptureSessionRecord,
        segments: List<MotionCaptureSegmentRecord>,
        sessionDirectory: File,
        exportRootDirectory: File
    ): File {
        require(sessionDirectory.exists()) { "Session directory does not exist: ${sessionDirectory.absolutePath}" }
        val exportDirectory = File(exportRootDirectory, session.id.toString()).apply { mkdirs() }
        val chunkFileNames = segments
            .flatMap { it.chunkFileNames }
            .distinct()
            .sorted()
        chunkFileNames.forEach { chunkFileName ->
            File(sessionDirectory, chunkFileName).copyTo(
                target = File(exportDirectory, chunkFileName),
                overwrite = true
            )
        }
        val sessionEventsFile = File(sessionDirectory, eventsFileName)
        val exportEventsFile = File(exportDirectory, eventsFileName)
        if (sessionEventsFile.exists()) {
            sessionEventsFile.copyTo(target = exportEventsFile, overwrite = true)
        } else {
            exportEventsFile.writeText(
                "eventType,epochTimeMs,elapsedRealtimeNanos,stateName,exerciseId,exerciseName," +
                    "setId,setIndex,exerciseType,noRepExpected,segmentId,reviewStatus,notes\n"
            )
        }
        val metadata = MotionCaptureExportMetadata(
            session = session,
            sensorConfig = session.sensorConfig,
            workoutContext = MotionCaptureWorkoutContext(
                workoutId = session.workoutId,
                workoutHistoryId = session.workoutHistoryId,
                orderedExerciseCandidates = session.exerciseCandidates
            ),
            coarseReviewedSegments = segments,
            rawSensorFiles = chunkFileNames.map(::MotionCaptureRawSensorFileReference),
            eventsFile = eventsFileName,
            exportedChunkFiles = chunkFileNames
        )
        File(exportDirectory, "metadata.json").writeText(gson.toJson(metadata))
        return exportDirectory
    }
}

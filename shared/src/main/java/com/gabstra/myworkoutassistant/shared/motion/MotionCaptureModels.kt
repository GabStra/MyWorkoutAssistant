package com.gabstra.myworkoutassistant.shared.motion

import com.gabstra.myworkoutassistant.shared.ExerciseType
import java.util.UUID

enum class MotionSensorType {
    ACCELEROMETER,
    GYROSCOPE,
    ROTATION_VECTOR,
    HEART_RATE,
    STEP_COUNTER,
    GRAVITY,
    LINEAR_ACCELERATION,
    PRESSURE
}

fun ExerciseType.supportsRepAnnotations(): Boolean = when (this) {
    ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT -> true
    ExerciseType.COUNTUP, ExerciseType.COUNTDOWN, ExerciseType.RUNNING -> false
}

data class MotionSensorSample(
    val sensorType: MotionSensorType,
    val epochTimeMs: Long,
    val elapsedRealtimeNanos: Long,
    val accuracy: Int,
    val x: Float,
    val y: Float,
    val z: Float,
    val w: Float? = null
)

data class MotionCaptureSensorConfig(
    val sampleRateHz: Int = 50,
    val chunkSampleCount: Int = 500,
    val enabledSensors: List<MotionSensorType> = listOf(
        MotionSensorType.ACCELEROMETER,
        MotionSensorType.GYROSCOPE,
        MotionSensorType.ROTATION_VECTOR,
        MotionSensorType.HEART_RATE,
        MotionSensorType.GRAVITY,
        MotionSensorType.LINEAR_ACCELERATION,
        MotionSensorType.PRESSURE
    ),
    // Sensors actually present/registered on the capturing device; null on records written before this field existed.
    val observedSensors: List<MotionSensorType>? = null,
    // True only when the user explicitly toggled capture on for this session (vs routine auto-capture
    // that rides the default-on preference); null on legacy records. Drives whether the on-watch
    // review UI is offered after the workout.
    val userInitiated: Boolean? = null
)

enum class MotionCaptureSessionStatus {
    ACTIVE,
    COMPLETED,
    ABANDONED
}

enum class MotionCaptureLabelKind {
    EXERCISE,
    REST,
    TRANSITION
}

enum class MotionCaptureReviewStatus {
    PENDING,
    CONFIRMED,
    RELABELED,
    MARKED_REST,
    DROPPED
}

data class MotionCaptureExerciseCandidate(
    val exerciseId: UUID,
    val exerciseName: String,
    val exerciseType: ExerciseType,
    val supersetId: UUID?,
    val executionOrder: Int,
    val noRepExpected: Boolean = !exerciseType.supportsRepAnnotations()
)

data class MotionCaptureLabel(
    val kind: MotionCaptureLabelKind,
    val stateName: String,
    val exerciseId: UUID? = null,
    val exerciseName: String? = null,
    val setId: UUID? = null,
    val setIndex: UInt? = null,
    val exerciseType: ExerciseType? = null,
    val supersetId: UUID? = null,
    val noRepExpected: Boolean = exerciseType?.supportsRepAnnotations()?.not() ?: false,
    val isWarmupSet: Boolean = false,
    val isCalibrationSet: Boolean = false,
    val isAutoRegulationSet: Boolean = false,
    val isIntraSetRest: Boolean = false
)

data class MotionCaptureSegmentRecord(
    val id: UUID,
    val sessionId: UUID,
    val sequenceIndex: Int,
    val startedAtEpochMs: Long,
    val endedAtEpochMs: Long?,
    val startedAtElapsedRealtimeNanos: Long,
    val endedAtElapsedRealtimeNanos: Long?,
    val stateName: String,
    val autoLabel: MotionCaptureLabel,
    val correctedLabel: MotionCaptureLabel?,
    val reviewStatus: MotionCaptureReviewStatus,
    val chunkFileNames: List<String>
)

data class MotionCaptureSessionRecord(
    val id: UUID,
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val status: MotionCaptureSessionStatus,
    val startedAtEpochMs: Long,
    val endedAtEpochMs: Long?,
    val deviceManufacturer: String,
    val deviceModel: String,
    val deviceName: String,
    val appVersion: String,
    val sessionDirectoryName: String,
    val sensorConfig: MotionCaptureSensorConfig,
    val exerciseCandidates: List<MotionCaptureExerciseCandidate>
)

enum class MotionCaptureEventType {
    ENTERED_SET,
    SET_COMPLETED,
    REST_STARTED,
    NEXT_EXERCISE_ENTERED,
    TIMER_STARTED,
    TIMER_FINISHED,
    SKIPPED,
    SEGMENT_REVIEW_CHANGED,
    CAPTURE_ABORTED_LOW_STORAGE
}

data class MotionCaptureEventRecord(
    val eventType: MotionCaptureEventType,
    val epochTimeMs: Long,
    val elapsedRealtimeNanos: Long,
    val stateName: String? = null,
    val exerciseId: UUID? = null,
    val exerciseName: String? = null,
    val setId: UUID? = null,
    val setIndex: UInt? = null,
    val exerciseType: ExerciseType? = null,
    val noRepExpected: Boolean = false,
    val segmentId: UUID? = null,
    val reviewStatus: MotionCaptureReviewStatus? = null,
    val notes: String? = null,
    /** Reps entered for the completed set; null for timed/no-rep states and older sessions. */
    val actualReps: Int? = null
)

data class MotionCaptureWorkoutContext(
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val orderedExerciseCandidates: List<MotionCaptureExerciseCandidate>
)

data class MotionCaptureRawSensorFileReference(
    val fileName: String
)

data class ExerciseDetectionPrediction(
    val label: MotionCaptureLabel,
    val confidence: Float,
    val startedAtElapsedRealtimeNanos: Long,
    val endedAtElapsedRealtimeNanos: Long
)

interface ExerciseDetectionEngine {
    fun predict(
        sensorWindow: List<MotionSensorSample>,
        candidateExercises: List<MotionCaptureExerciseCandidate>
    ): ExerciseDetectionPrediction?
}

object NoOpExerciseDetectionEngine : ExerciseDetectionEngine {
    override fun predict(
        sensorWindow: List<MotionSensorSample>,
        candidateExercises: List<MotionCaptureExerciseCandidate>
    ): ExerciseDetectionPrediction? = null
}

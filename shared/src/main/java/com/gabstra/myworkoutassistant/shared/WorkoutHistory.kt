package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import com.gabstra.myworkoutassistant.shared.running.RunningResult

@Entity(tableName = "workout_history")
data class WorkoutHistory(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val workoutId: UUID,
    val date: LocalDate,
    val time: LocalTime,
    val startTime: LocalDateTime,
    val duration: Int,
    val heartBeatRecords: List<Int>,
    /** Beat-to-beat intervals per tick, index-aligned with [heartBeatRecords]; empty on pre-IBI records. */
    val ibiRecords: List<List<Int>> = emptyList(),
    /** Mean RMSSD over completed rest windows; null when no rest window had enough IBI data. */
    val restRmssdMs: Double? = null,
    /** Mean SDNN over completed rest windows; null when no rest window had enough IBI data. */
    val restSdnnMs: Double? = null,
    /** Accumulated sweat loss for the session; null when the sensor emitted no samples. */
    val sweatLossMl: Int? = null,
    /** First skin-temperature reading of the session (Celsius); null when unavailable. */
    val skinTempStartC: Float? = null,
    /** Highest skin temperature reached (Celsius); null when unavailable. */
    val skinTempMaxC: Float? = null,
    /** Which device produced heartBeatRecords; see [HeartRateSource]. */
    val heartRateSource: String? = null,
    /** Every source's recorded stream, keyed by [HeartRateSource] name (includes the one above). */
    val heartRateStreams: Map<String, List<Int>> = emptyMap(),
    /**
     * Per-sample offsets in milliseconds from [heartRateStreamsStartEpochMs], index-aligned with
     * [heartRateStreams]. Empty on records captured before timestamps existed.
     */
    val heartRateStreamTimes: Map<String, List<Long>> = emptyMap(),
    /** Wall-clock epoch of offset zero for [heartRateStreamTimes]; null when unknown. */
    val heartRateStreamsStartEpochMs: Long? = null,
    val isDone : Boolean,
    val hasBeenSentToHealth: Boolean,
    val globalId: UUID,
    val version: UInt = 0u,
    val endReason: WorkoutSessionEndReason = WorkoutSessionEndReason.COMPLETED,
    val runningResults: List<RunningResult> = emptyList()
)

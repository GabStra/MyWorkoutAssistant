package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workout.model.ownerDeviceOrDefault
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.UUID

const val DEFAULT_WORKOUT_SESSION_HEARTBEAT_INTERVAL_MS = 30_000L

object WorkoutSessionHeartbeatKeys {
    const val WORKOUT_ID = "workoutId"
    const val WORKOUT_HISTORY_ID = "workoutHistoryId"
    const val EXERCISE_ID = "exerciseId"
    const val SET_INDEX = "setIndex"
    const val SESSION_STATE = "sessionState"
    const val ACTIVE_SESSION_REVISION = "activeSessionRevision"
    const val SENT_AT_EPOCH_MS = "sentAtEpochMs"
}

data class WorkoutSessionHeartbeat(
    val workoutId: UUID,
    val workoutHistoryId: UUID,
    val exerciseId: UUID,
    val setIndex: UInt,
    val sessionState: String,
    val activeSessionRevision: UInt,
    val sentAtEpochMs: Long,
)

enum class WorkoutSessionHeartbeatRejectReason {
    MISSING_RECORD,
    MISSING_HISTORY,
    WORKOUT_MISMATCH,
    WORKOUT_HISTORY_MISMATCH,
    NOT_WEAR_OWNED,
    COMPLETED_HISTORY,
    OLDER_REVISION,
}

data class WorkoutSessionHeartbeatApplyDecision(
    val shouldApply: Boolean,
    val rejectReason: WorkoutSessionHeartbeatRejectReason? = null,
) {
    companion object {
        val Apply = WorkoutSessionHeartbeatApplyDecision(shouldApply = true)
    }
}

fun decideWorkoutSessionHeartbeatApply(
    heartbeat: WorkoutSessionHeartbeat,
    existingRecord: WorkoutRecord?,
    existingHistory: WorkoutHistory?,
): WorkoutSessionHeartbeatApplyDecision {
    if (existingRecord == null) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.MISSING_RECORD
        )
    }
    if (existingHistory == null) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.MISSING_HISTORY
        )
    }
    if (existingRecord.workoutId != heartbeat.workoutId || existingHistory.workoutId != heartbeat.workoutId) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.WORKOUT_MISMATCH
        )
    }
    if (
        existingRecord.workoutHistoryId != heartbeat.workoutHistoryId ||
        existingHistory.id != heartbeat.workoutHistoryId
    ) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.WORKOUT_HISTORY_MISMATCH
        )
    }
    if (existingRecord.ownerDeviceOrDefault() != SessionOwnerDevice.WEAR) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.NOT_WEAR_OWNED
        )
    }
    if (existingHistory.isDone) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.COMPLETED_HISTORY
        )
    }
    if (heartbeat.activeSessionRevision < existingRecord.activeSessionRevision) {
        return WorkoutSessionHeartbeatApplyDecision(
            shouldApply = false,
            rejectReason = WorkoutSessionHeartbeatRejectReason.OLDER_REVISION
        )
    }
    return WorkoutSessionHeartbeatApplyDecision.Apply
}

fun WorkoutSessionHeartbeat.sentAtLocalDateTime(
    zoneId: ZoneId = ZoneId.systemDefault()
): LocalDateTime = LocalDateTime.ofInstant(
    java.time.Instant.ofEpochMilli(sentAtEpochMs),
    zoneId
)

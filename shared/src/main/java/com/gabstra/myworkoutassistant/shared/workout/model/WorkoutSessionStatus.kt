package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import java.time.Duration
import java.time.LocalDateTime

const val ACTIVE_SESSION_STALE_TIMEOUT_MS = 90_000L

enum class SessionOwnerDevice {
    PHONE,
    WEAR,
}

enum class WorkoutSessionStatus {
    COMPLETED,
    IN_PROGRESS_ON_WEAR,
    IN_PROGRESS_ON_PHONE,
    STALE_ON_WEAR,
    INTERRUPTED,
}

fun WorkoutRecord.ownerDeviceOrDefault(): SessionOwnerDevice = runCatching {
    SessionOwnerDevice.valueOf(ownerDevice)
}.getOrDefault(SessionOwnerDevice.PHONE)

fun isWorkoutRecordFresh(
    workoutRecord: WorkoutRecord,
    now: LocalDateTime = LocalDateTime.now(),
    staleTimeoutMs: Long = ACTIVE_SESSION_STALE_TIMEOUT_MS
): Boolean {
    val lastActiveSyncAt = workoutRecord.lastActiveSyncAt ?: return false
    val elapsedMs = Duration.between(lastActiveSyncAt, now).toMillis()
    return elapsedMs <= staleTimeoutMs
}

fun resolveWorkoutSessionStatus(
    workoutHistory: WorkoutHistory,
    workoutRecord: WorkoutRecord?,
    now: LocalDateTime = LocalDateTime.now(),
    staleTimeoutMs: Long = ACTIVE_SESSION_STALE_TIMEOUT_MS
): WorkoutSessionStatus {
    if (workoutHistory.isDone) {
        return WorkoutSessionStatus.COMPLETED
    }

    if (workoutRecord == null || workoutRecord.workoutHistoryId != workoutHistory.id) {
        return WorkoutSessionStatus.INTERRUPTED
    }

    return when (workoutRecord.ownerDeviceOrDefault()) {
        SessionOwnerDevice.PHONE -> WorkoutSessionStatus.IN_PROGRESS_ON_PHONE
        SessionOwnerDevice.WEAR -> {
            if (isWorkoutRecordFresh(workoutRecord, now, staleTimeoutMs)) {
                WorkoutSessionStatus.IN_PROGRESS_ON_WEAR
            } else {
                WorkoutSessionStatus.STALE_ON_WEAR
            }
        }
    }
}

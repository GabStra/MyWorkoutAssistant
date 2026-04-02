package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import java.time.Duration
import java.time.LocalDateTime

const val ACTIVE_SESSION_STALE_TIMEOUT_MS = 90_000L
const val WATCH_SESSION_STATE_RETURNED_HOME = "RETURNED_HOME"

enum class SessionOwnerDevice {
    PHONE,
    WEAR,
}

enum class WorkoutSessionStatus {
    COMPLETED,
    IN_PROGRESS_ON_WEAR,
    IN_PROGRESS_ON_PHONE,
    STOPPED_ON_WEAR,
    STALE_ON_WEAR,
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

fun isWatchWorkoutRecordStopped(workoutRecord: WorkoutRecord): Boolean {
    return workoutRecord.ownerDeviceOrDefault() == SessionOwnerDevice.WEAR &&
        workoutRecord.lastKnownSessionState == WATCH_SESSION_STATE_RETURNED_HOME
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

    val record = workoutRecord
        ?: error("Incomplete workout history ${workoutHistory.id} requires a matching workout record")
    check(record.workoutHistoryId == workoutHistory.id) {
        "Workout record ${record.id} does not match workout history ${workoutHistory.id}"
    }

    return when (record.ownerDeviceOrDefault()) {
        SessionOwnerDevice.PHONE -> WorkoutSessionStatus.IN_PROGRESS_ON_PHONE
        SessionOwnerDevice.WEAR -> {
            if (isWatchWorkoutRecordStopped(record)) {
                WorkoutSessionStatus.STOPPED_ON_WEAR
            } else if (isWorkoutRecordFresh(record, now, staleTimeoutMs)) {
                WorkoutSessionStatus.IN_PROGRESS_ON_WEAR
            } else {
                WorkoutSessionStatus.STALE_ON_WEAR
            }
        }
    }
}

/** User-visible strings for compact session labels (Status tab, history headers). */
object WorkoutSessionDisplayLabels {
    const val IN_PROGRESS = "In progress"
    const val STOPPED_ON_WATCH = "Stopped"
    /** Watch-owned session with no recent sync (e.g. lost connection or watch idle). */
    const val STALE_ON_WATCH = "Stale"
}

/**
 * Short labels for compact UI. [COMPLETED] and null yield no label.
 * Phone and fresh watch sessions share [WorkoutSessionDisplayLabels.IN_PROGRESS];
 * stale watch uses [WorkoutSessionDisplayLabels.STALE_ON_WATCH].
 */
fun workoutSessionDisplayLabel(status: WorkoutSessionStatus?): String? = when (status) {
    null, WorkoutSessionStatus.COMPLETED -> null
    WorkoutSessionStatus.IN_PROGRESS_ON_PHONE, WorkoutSessionStatus.IN_PROGRESS_ON_WEAR ->
        WorkoutSessionDisplayLabels.IN_PROGRESS
    WorkoutSessionStatus.STOPPED_ON_WEAR -> WorkoutSessionDisplayLabels.STOPPED_ON_WATCH
    WorkoutSessionStatus.STALE_ON_WEAR -> WorkoutSessionDisplayLabels.STALE_ON_WATCH
}

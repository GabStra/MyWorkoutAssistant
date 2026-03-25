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

    val record = workoutRecord
        ?: error("Incomplete workout history ${workoutHistory.id} requires a matching workout record")
    check(record.workoutHistoryId == workoutHistory.id) {
        "Workout record ${record.id} does not match workout history ${workoutHistory.id}"
    }

    return when (record.ownerDeviceOrDefault()) {
        SessionOwnerDevice.PHONE -> WorkoutSessionStatus.IN_PROGRESS_ON_PHONE
        SessionOwnerDevice.WEAR -> {
            if (isWorkoutRecordFresh(record, now, staleTimeoutMs)) {
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
    WorkoutSessionStatus.STALE_ON_WEAR -> WorkoutSessionDisplayLabels.STALE_ON_WATCH
}

package com.gabstra.myworkoutassistant.shared.datalayer

import java.util.UUID
import kotlin.math.abs

object WorkoutSessionCommandKeys {
    const val COMMAND = "command"
    const val WORKOUT_ID = "workoutId"
    const val ENABLED = "enabled"
    const val SENT_AT_EPOCH_MS = "sentAtEpochMs"
}

enum class WorkoutSessionCommandType(val wireValue: String) {
    MOTION_CAPTURE("motionCapture");

    companion object {
        fun fromWireValue(value: String?): WorkoutSessionCommandType? =
            entries.firstOrNull { it.wireValue == value }
    }
}

/** Phone and watch clocks are not strictly synced, so accept modest skew in both directions. */
const val WORKOUT_SESSION_COMMAND_MAX_AGE_MS = 5 * 60_000L

/**
 * A phone-side change to live watch session settings. The watch is authoritative: it applies the
 * command only to its current workout and reports the resulting state back in its heartbeat.
 */
data class WorkoutSessionCommand(
    val type: WorkoutSessionCommandType,
    val workoutId: UUID?,
    val enabled: Boolean,
    val sentAtEpochMs: Long,
) {
    fun isFresh(nowEpochMs: Long = System.currentTimeMillis()): Boolean =
        abs(nowEpochMs - sentAtEpochMs) <= WORKOUT_SESSION_COMMAND_MAX_AGE_MS
}

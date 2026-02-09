package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.core.content.edit
import java.util.UUID

internal enum class RecoveryStateType {
    SET,
    REST,
    CALIBRATION_LOAD,
    CALIBRATION_RIR,
    UNKNOWN
}

internal data class WorkoutRecoveryCheckpoint(
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val stateType: RecoveryStateType,
    val exerciseId: UUID?,
    val setId: UUID?,
    val setIndex: UInt?,
    val restOrder: UInt?,
    val setStartEpochMs: Long?,
    val updatedAtEpochMs: Long
)

internal class WorkoutRecoveryCheckpointStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun save(checkpoint: WorkoutRecoveryCheckpoint) {
        prefs.edit {
            putString(KEY_WORKOUT_ID, checkpoint.workoutId.toString())
            putString(KEY_WORKOUT_HISTORY_ID, checkpoint.workoutHistoryId?.toString())
            putString(KEY_STATE_TYPE, checkpoint.stateType.name)
            putString(KEY_EXERCISE_ID, checkpoint.exerciseId?.toString())
            putString(KEY_SET_ID, checkpoint.setId?.toString())
            putInt(KEY_SET_INDEX, checkpoint.setIndex?.toInt() ?: -1)
            putInt(KEY_REST_ORDER, checkpoint.restOrder?.toInt() ?: -1)
            putLong(KEY_SET_START_EPOCH_MS, checkpoint.setStartEpochMs ?: -1L)
            putLong(KEY_UPDATED_AT, checkpoint.updatedAtEpochMs)
        }
    }

    fun load(): WorkoutRecoveryCheckpoint? {
        val workoutId = prefs.getString(KEY_WORKOUT_ID, null)?.toUuidOrNull() ?: return null
        val historyId = prefs.getString(KEY_WORKOUT_HISTORY_ID, null)?.toUuidOrNull()
        val stateType = prefs.getString(KEY_STATE_TYPE, null)
            ?.let { runCatching { RecoveryStateType.valueOf(it) }.getOrNull() }
            ?: RecoveryStateType.UNKNOWN
        val exerciseId = prefs.getString(KEY_EXERCISE_ID, null)?.toUuidOrNull()
        val setId = prefs.getString(KEY_SET_ID, null)?.toUuidOrNull()
        val setIndex = prefs.getInt(KEY_SET_INDEX, -1).takeIf { it >= 0 }?.toUInt()
        val restOrder = prefs.getInt(KEY_REST_ORDER, -1).takeIf { it >= 0 }?.toUInt()
        val setStartEpochMs = prefs.getLong(KEY_SET_START_EPOCH_MS, -1L).takeIf { it >= 0L }
        val updatedAt = prefs.getLong(KEY_UPDATED_AT, 0L)

        return WorkoutRecoveryCheckpoint(
            workoutId = workoutId,
            workoutHistoryId = historyId,
            stateType = stateType,
            exerciseId = exerciseId,
            setId = setId,
            setIndex = setIndex,
            restOrder = restOrder,
            setStartEpochMs = setStartEpochMs,
            updatedAtEpochMs = updatedAt
        )
    }

    fun clear() {
        prefs.edit {
            remove(KEY_WORKOUT_ID)
            remove(KEY_WORKOUT_HISTORY_ID)
            remove(KEY_STATE_TYPE)
            remove(KEY_EXERCISE_ID)
            remove(KEY_SET_ID)
            remove(KEY_SET_INDEX)
            remove(KEY_REST_ORDER)
            remove(KEY_SET_START_EPOCH_MS)
            remove(KEY_UPDATED_AT)
        }
    }

    private fun String.toUuidOrNull(): UUID? = runCatching { UUID.fromString(this) }.getOrNull()

    private companion object {
        const val PREFS_NAME = "workout_recovery_checkpoint"
        const val KEY_WORKOUT_ID = "workoutId"
        const val KEY_WORKOUT_HISTORY_ID = "workoutHistoryId"
        const val KEY_STATE_TYPE = "stateType"
        const val KEY_EXERCISE_ID = "exerciseId"
        const val KEY_SET_ID = "setId"
        const val KEY_SET_INDEX = "setIndex"
        const val KEY_REST_ORDER = "restOrder"
        const val KEY_SET_START_EPOCH_MS = "setStartEpochMs"
        const val KEY_UPDATED_AT = "updatedAt"
    }
}

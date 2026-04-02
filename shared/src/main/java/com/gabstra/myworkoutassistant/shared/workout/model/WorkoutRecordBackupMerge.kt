package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import java.util.LinkedHashMap
import java.util.UUID

fun mergeWorkoutRecordsForBackup(
    existingRecords: List<WorkoutRecord>,
    existingHistoriesById: Map<UUID, WorkoutHistory>,
    incomingRecords: List<WorkoutRecord>,
    incomingHistoriesById: Map<UUID, WorkoutHistory>
): List<WorkoutRecord> {
    val allHistoriesById = existingHistoriesById + incomingHistoriesById
    val mergedByWorkoutId = LinkedHashMap<UUID, WorkoutRecord>()

    existingRecords.forEach { record ->
        choosePreferredWorkoutRecord(
            current = mergedByWorkoutId[record.workoutId],
            candidate = record,
            historiesById = allHistoriesById
        )?.let { preferred ->
            mergedByWorkoutId[record.workoutId] = preferred
        }
    }

    incomingRecords.forEach { record ->
        choosePreferredWorkoutRecord(
            current = mergedByWorkoutId[record.workoutId],
            candidate = record,
            historiesById = allHistoriesById
        )?.let { preferred ->
            mergedByWorkoutId[record.workoutId] = preferred
        }
    }

    return mergedByWorkoutId.values
        .filter { record ->
            val history = allHistoriesById[record.workoutHistoryId]
            history != null && !history.isDone
        }
        .sortedBy { it.workoutId.toString() }
}

private fun choosePreferredWorkoutRecord(
    current: WorkoutRecord?,
    candidate: WorkoutRecord,
    historiesById: Map<UUID, WorkoutHistory>
): WorkoutRecord? {
    val candidateHistory = historiesById[candidate.workoutHistoryId] ?: return current
    if (candidateHistory.isDone) {
        return current
    }

    val currentRecord = current ?: return candidate
    val currentHistory = historiesById[currentRecord.workoutHistoryId]
    if (currentHistory == null || currentHistory.isDone) {
        return candidate
    }

    val decision = decideWorkoutRecordIngest(
        incomingHistory = candidateHistory,
        incomingRecord = candidate,
        existingHistory = currentHistory,
        existingRecord = currentRecord
    )
    return if (decision.shouldApplyIncoming) candidate else currentRecord
}

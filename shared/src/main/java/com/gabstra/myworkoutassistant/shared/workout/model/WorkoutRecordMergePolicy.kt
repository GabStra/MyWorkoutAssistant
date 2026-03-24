package com.gabstra.myworkoutassistant.shared.workout.model

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord

/**
 * Deterministic ingest arbitration for incoming workout records.
 *
 * Precedence:
 * 1) Higher activeSessionRevision wins.
 * 2) If revisions tie, newer workout history version wins.
 * 3) If both tie and history differs, prefer the incoming history context.
 * 4) If all above tie, incoming wins to keep sender as source-of-truth.
 */
data class WorkoutRecordIngestDecision(
    val shouldApplyIncoming: Boolean,
    val shouldPruneExisting: Boolean = false,
)

fun decideWorkoutRecordIngest(
    incomingHistory: WorkoutHistory,
    incomingRecord: WorkoutRecord?,
    existingHistory: WorkoutHistory?,
    existingRecord: WorkoutRecord?,
): WorkoutRecordIngestDecision {
    if (incomingRecord == null) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = false)
    }
    if (existingRecord == null || existingHistory == null) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = true)
    }

    if (incomingRecord.activeSessionRevision > existingRecord.activeSessionRevision) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = true, shouldPruneExisting = true)
    }
    if (incomingRecord.activeSessionRevision < existingRecord.activeSessionRevision) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = false)
    }

    if (incomingHistory.version > existingHistory.version) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = true, shouldPruneExisting = true)
    }
    if (incomingHistory.version < existingHistory.version) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = false)
    }

    val isIncomingDifferentHistory = incomingHistory.id != existingHistory.id
    if (isIncomingDifferentHistory) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = true, shouldPruneExisting = true)
    }

    if (incomingRecord.setIndex < existingRecord.setIndex) {
        return WorkoutRecordIngestDecision(shouldApplyIncoming = false)
    }

    return WorkoutRecordIngestDecision(shouldApplyIncoming = true)
}

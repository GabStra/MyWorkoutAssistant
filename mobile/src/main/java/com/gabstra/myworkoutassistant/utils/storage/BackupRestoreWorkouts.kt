package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStore

/**
 * The store a restore writes back: every workout in the backup is retained.
 *
 * Dependent rows are filtered against these workouts separately. A workout's lack of a
 * [com.gabstra.myworkoutassistant.shared.WorkoutHistory] row is not a reason to drop it: it may
 * still own schedules or records, and a legacy "Unassigned" member must survive until the
 * conversion detaches it. The full-backup shared store is already the union across profiles, so
 * this must not narrow it per profile either.
 */
fun AppBackup.restoredWorkoutStore(): WorkoutStore {
    val backupStore = WorkoutStore
    return backupStore.copy(workouts = backupStore.workouts)
}

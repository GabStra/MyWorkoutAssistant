package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

/**
 * Legacy fallback for older watch clients that send only a full store snapshot.
 *
 * New clients send a [WatchWorkoutDefinitionEditIntent] and are handled by
 * [applyWatchWorkoutDefinitionEdit]; the phone then ignores the snapshot entirely. This function
 * remains only for clients that cannot name their edit. It intentionally drops an edit it cannot
 * prove instead of inferring it from session-hydrated data.
 *
 * The known watch writers are `WorkoutViewModel.persistSelectedWorkoutDefinition` (calibration:
 * work-set weights/subcategories and clearing `requiresLoadCalibration`) and
 * `WorkoutViewModel.updateExerciseEquipmentForCurrentWorkout` (an exercise's `equipmentId`).
 * Everything else in the watch snapshot is a possibly stale copy of an earlier phone snapshot.
 *
 * The phone is therefore authoritative for:
 * - the workout entity set and order (local-only workouts stay, incoming-only ids never appear,
 *   inactive/deleted workouts are never reactivated);
 * - plans, version chains and all workout identity/ownership fields;
 * - personal settings, exercise definitions and the equipment library;
 * - workout definitions other than the narrowly recognized watch edits above.
 *
 * A watch edit is applied only to a local workout that is active and matches the incoming id and
 * `globalId`. It is applied per exercise and only when the incoming exercise differs from the
 * local one solely in an allowed field set. This prevents a stale snapshot from silently
 * overwriting a newer phone edit, while still accepting calibration and equipment changes.
 *
 * Only a genuinely uninitialized profile (no settings and no workouts/plans) adopts the incoming
 * snapshot, so an existing watch can populate a fresh phone. A profiled phone that merely has no
 * workouts keeps its settings and does not resurrect deleted workouts.
 *
 * Known unresolved boundary for this legacy path: the payload carries no edited-component
 * identity or baseline. If the phone changed one of the allowed fields on the same active exercise
 * after the watch snapshot was taken, this merge cannot tell that phone edit from the watch edit.
 */
fun WorkoutStore.mergeWatchWorkoutDefinitionUpdate(incoming: WorkoutStore): WorkoutStore {
    if (workouts.isEmpty() && workoutPlans.isEmpty()) {
        // Only a genuinely uninitialized profile may adopt the snapshot. A profile that already
        // has settings but no workouts/plans must not have those settings replaced or workouts
        // resurrected by an older watch.
        return if (isUninitializedForWatchAdoption()) incoming else this
    }
    val incomingById = incoming.workouts.associateBy { it.id }
    return copy(
        workouts = workouts.map { localWorkout ->
            val incomingWorkout = incomingById[localWorkout.id]
            if (
                !localWorkout.isActive ||
                incomingWorkout == null ||
                !incomingWorkout.isActive ||
                incomingWorkout.globalId != localWorkout.globalId
            ) {
                localWorkout
            } else {
                localWorkout.copy(
                    workoutComponents = mergeWatchEditableComponents(
                        localWorkout.workoutComponents,
                        incomingWorkout.workoutComponents,
                    ),
                )
            }
        },
    )
}

private fun WorkoutStore.isUninitializedForWatchAdoption(): Boolean =
    this == WorkoutStore(
        workouts = emptyList(),
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        birthDateYear = 0,
        weightKg = 0.0,
        progressionPercentageAmount = 0.0,
    )

private fun mergeWatchEditableComponents(
    localComponents: List<WorkoutComponent>,
    incomingComponents: List<WorkoutComponent>,
): List<WorkoutComponent> {
    if (localComponents == incomingComponents) return localComponents
    val incomingById = incomingComponents.associateBy { it.id }
    return localComponents.map { localComponent ->
        when (val incomingComponent = incomingById[localComponent.id]) {
            is Exercise -> {
                if (localComponent is Exercise) {
                    mergeWatchEditableExercise(localComponent, incomingComponent)
                } else {
                    localComponent
                }
            }
            is Superset -> {
                if (localComponent is Superset) {
                    val mergedExercises = mergeWatchEditableExercises(
                        localComponent.exercises,
                        incomingComponent.exercises,
                    )
                    if (mergedExercises == localComponent.exercises) {
                        localComponent
                    } else {
                        localComponent.copy(exercises = mergedExercises)
                    }
                } else {
                    localComponent
                }
            }
            else -> localComponent
        }
    }
}

private fun mergeWatchEditableExercises(
    localExercises: List<Exercise>,
    incomingExercises: List<Exercise>,
): List<Exercise> {
    if (localExercises == incomingExercises) return localExercises
    val incomingById = incomingExercises.associateBy { it.id }
    return localExercises.map { localExercise ->
        incomingById[localExercise.id]?.let { incomingExercise ->
            mergeWatchEditableExercise(localExercise, incomingExercise)
        } ?: localExercise
    }
}

private fun mergeWatchEditableExercise(local: Exercise, incoming: Exercise): Exercise {
    if (local == incoming) return local

    val equipmentChanged = local.equipmentId != incoming.equipmentId
    val calibrationChanged = local.requiresLoadCalibration && !incoming.requiresLoadCalibration
    if (!equipmentChanged && !calibrationChanged) return local

    val expected = local.copy(
        equipmentId = if (equipmentChanged) incoming.equipmentId else local.equipmentId,
        sets = if (calibrationChanged) incoming.sets else local.sets,
        requiresLoadCalibration = if (calibrationChanged) false else local.requiresLoadCalibration,
    )
    // Exercise.equals intentionally ignores a few newer metadata fields, but those fields are
    // never copied below, so an ignored difference cannot leak from the stale snapshot.
    if (incoming != expected) return local
    if (calibrationChanged && !hasOnlyCalibrationSetChanges(local.sets, incoming.sets)) return local
    return expected
}

/**
 * Calibration updates the matching work sets' target load/category. The set ids, order, reps,
 * notes and all other set fields must match the local phone copy exactly.
 */
private fun hasOnlyCalibrationSetChanges(
    localSets: List<Set>,
    incomingSets: List<Set>,
): Boolean {
    if (localSets.size != incomingSets.size) return false
    return localSets.indices.all { index ->
        val localSet = localSets[index]
        val incomingSet = incomingSets[index]
        if (localSet.id != incomingSet.id || localSet::class != incomingSet::class) {
            return@all false
        }
        when {
            localSet is WeightSet && incomingSet is WeightSet ->
                incomingSet == localSet.copy(
                    weight = incomingSet.weight,
                    subCategory = incomingSet.subCategory,
                )
            localSet is BodyWeightSet && incomingSet is BodyWeightSet ->
                incomingSet == localSet.copy(
                    additionalWeight = incomingSet.additionalWeight,
                    subCategory = incomingSet.subCategory,
                )
            else -> incomingSet == localSet
        }
    }
}

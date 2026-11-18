package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.isCompatibleWith
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

sealed class WatchWorkoutDefinitionEditResult {
    data class Applied(val workoutStore: WorkoutStore) : WatchWorkoutDefinitionEditResult()
    data class AlreadyApplied(val workoutStore: WorkoutStore) : WatchWorkoutDefinitionEditResult()
    data class Rejected(val reason: String) : WatchWorkoutDefinitionEditResult()
}

/**
 * Applies one explicit watch edit to the phone-owned store.
 *
 * Only the fields named by [intent] are read from the watch. Every other workout field, every
 * other exercise/set, plan membership, personal settings and the equipment library stay exactly as
 * the phone has them. The store snapshot the watch also sends is intentionally ignored on this
 * path: it is session-hydrated and must never overwrite phone definitions.
 *
 * Conflict rules:
 * - the exact workout version must still exist, active, with the same `globalId`;
 * - equipment edits compare the phone's current equipment with the watch's base equipment;
 * - calibration set edits compare the phone's current set value/subcategory with the watch's base;
 * - if the phone already holds the requested value, the edit is an idempotent success;
 * - any other disagreement is reported as a conflict instead of being applied or silently dropped.
 */
fun WorkoutStore.applyWatchWorkoutDefinitionEdit(
    intent: WatchWorkoutDefinitionEditIntent,
): WatchWorkoutDefinitionEditResult {
    return applyWatchWorkoutDefinitionEditInternal(intent, enforceBaseline = true)
}

/**
 * Applies the same explicit watch edit to the watch-owned store.
 *
 * The watch's `selectedWorkout` is a session-hydrated copy (progression/history may legitimately
 * change set values), so it must not replace the store definition wholesale. Only the fields named
 * by [intent] are written here. Set values are not used as a conflict baseline because the watch's
 * copy may be hydrated; equipment identity is always compared because it is never hydrated.
 */
fun WorkoutStore.applyWatchWorkoutDefinitionEditLocally(
    intent: WatchWorkoutDefinitionEditIntent,
): WatchWorkoutDefinitionEditResult {
    return applyWatchWorkoutDefinitionEditInternal(intent, enforceBaseline = false)
}

private fun WorkoutStore.applyWatchWorkoutDefinitionEditInternal(
    intent: WatchWorkoutDefinitionEditIntent,
    enforceBaseline: Boolean,
): WatchWorkoutDefinitionEditResult {
    val target = findWatchEditTarget(intent)
    if (target is WatchEditTargetResult.Rejected) {
        return WatchWorkoutDefinitionEditResult.Rejected(target.reason)
    }
    val (localWorkout, localExercise) = target as WatchEditTargetResult.Found
    val exerciseResult = when (intent.kind) {
        WatchWorkoutDefinitionEditKind.EXERCISE_EQUIPMENT ->
            // Equipment is never session-hydrated, so both editors must agree on the base.
            applyEquipmentEdit(localExercise, intent)
        WatchWorkoutDefinitionEditKind.LOAD_CALIBRATION ->
            applyCalibrationEdit(localExercise, intent, enforceBaseline)
    }
    return when (exerciseResult) {
        is ExerciseEditResult.Rejected -> WatchWorkoutDefinitionEditResult.Rejected(
            exerciseResult.reason,
        )
        ExerciseEditResult.AlreadyApplied -> WatchWorkoutDefinitionEditResult.AlreadyApplied(this)
        is ExerciseEditResult.Applied -> {
            val updatedWorkout = localWorkout.copy(
                workoutComponents = localWorkout.workoutComponents.replaceExercise(
                    intent.exerciseId,
                    exerciseResult.exercise,
                ),
            )
            WatchWorkoutDefinitionEditResult.Applied(
                copy(
                    workouts = workouts.map { workout ->
                        if (workout.id == updatedWorkout.id) updatedWorkout else workout
                    },
                ),
            )
        }
    }
}

private sealed class WatchEditTargetResult {
    data class Found(val workout: Workout, val exercise: Exercise) : WatchEditTargetResult()
    data class Rejected(val reason: String) : WatchEditTargetResult()
}

private fun WorkoutStore.findWatchEditTarget(
    intent: WatchWorkoutDefinitionEditIntent,
): WatchEditTargetResult {
    val localWorkout = workouts.firstOrNull { it.id == intent.workoutId }
        ?: return WatchEditTargetResult.Rejected(
            if (workouts.any { it.globalId == intent.workoutGlobalId && it.id != intent.workoutId }) {
                "Stale workout version: the phone has a newer version of this workout"
            } else {
                "Workout targeted by the watch edit no longer exists on the phone"
            },
        )
    if (!localWorkout.isActive) {
        return WatchEditTargetResult.Rejected(
            "Stale workout version: the targeted workout is inactive on the phone",
        )
    }
    if (localWorkout.globalId != intent.workoutGlobalId) {
        return WatchEditTargetResult.Rejected(
            "Workout identity mismatch for the watch edit",
        )
    }

    val matchingExercises = localWorkout.workoutComponents.findExercises(intent.exerciseId)
    if (matchingExercises.isEmpty()) {
        return WatchEditTargetResult.Rejected(
            "Exercise targeted by the watch edit no longer exists on the phone",
        )
    }
    if (matchingExercises.size > 1) {
        return WatchEditTargetResult.Rejected(
            "Exercise targeted by the watch edit is ambiguous in the phone workout",
        )
    }
    return WatchEditTargetResult.Found(localWorkout, matchingExercises.single())
}

private sealed class ExerciseEditResult {
    data class Applied(val exercise: Exercise) : ExerciseEditResult()
    object AlreadyApplied : ExerciseEditResult()
    data class Rejected(val reason: String) : ExerciseEditResult()
}

private fun WorkoutStore.applyEquipmentEdit(
    localExercise: Exercise,
    intent: WatchWorkoutDefinitionEditIntent,
): ExerciseEditResult {
    if (intent.setEdits.isNotEmpty()) {
        return ExerciseEditResult.Rejected("Equipment edit unexpectedly carries set changes")
    }
    if (localExercise.exerciseType != com.gabstra.myworkoutassistant.shared.ExerciseType.WEIGHT &&
        localExercise.exerciseType != com.gabstra.myworkoutassistant.shared.ExerciseType.BODY_WEIGHT
    ) {
        return ExerciseEditResult.Rejected("Equipped exercises must be weight or body-weight exercises")
    }
    if (localExercise.exerciseType == com.gabstra.myworkoutassistant.shared.ExerciseType.WEIGHT &&
        intent.newEquipmentId == null
    ) {
        return ExerciseEditResult.Rejected("Weight exercises require an equipment selection")
    }
    intent.newEquipmentId?.let { newEquipmentId ->
        val equipment = equipments.firstOrNull { it.id == newEquipmentId }
            ?: return ExerciseEditResult.Rejected(
                "Equipment selected on the watch no longer exists on the phone",
            )
        if (!equipment.isCompatibleWith(localExercise.exerciseType)) {
            return ExerciseEditResult.Rejected(
                "Equipment selected on the watch is incompatible with the phone exercise",
            )
        }
    }

    return when {
        localExercise.equipmentId == intent.newEquipmentId -> ExerciseEditResult.AlreadyApplied
        localExercise.equipmentId != intent.baseEquipmentId -> ExerciseEditResult.Rejected(
            "Conflicting equipment edit: equipment changed on the phone after the watch snapshot",
        )
        else -> ExerciseEditResult.Applied(localExercise.copy(equipmentId = intent.newEquipmentId))
    }
}

private fun WorkoutStore.applyCalibrationEdit(
    localExercise: Exercise,
    intent: WatchWorkoutDefinitionEditIntent,
    enforceBaseline: Boolean,
): ExerciseEditResult {
    if (!intent.baseRequiresLoadCalibration) {
        return ExerciseEditResult.Rejected("Calibration edit has no load-calibration baseline")
    }
    if (intent.setEdits.map { it.setId }.distinct().size != intent.setEdits.size) {
        return ExerciseEditResult.Rejected("Calibration edit names the same set more than once")
    }
    if (intent.baseEquipmentId != localExercise.equipmentId) {
        return ExerciseEditResult.Rejected(
            "Conflicting equipment edit: equipment changed on the phone after the watch snapshot",
        )
    }

    val localSetsById = localExercise.sets.associateBy { it.id }
    if (!localExercise.requiresLoadCalibration) {
        if (localExercise.hasPendingCalibrationSet()) {
            return ExerciseEditResult.Rejected(
                "Calibration is still pending for a set on the phone",
            )
        }
        val alreadyApplied = intent.setEdits.all { setEdit ->
            val localSet = localSetsById[setEdit.setId] ?: return@all false
            localSet.calibrationValue(setEdit.setKind) == setEdit.newWeight &&
                localSet.subCategory() == setEdit.newSubCategory
        }
        return if (alreadyApplied) {
            ExerciseEditResult.AlreadyApplied
        } else {
            ExerciseEditResult.Rejected(
                "Calibration was already resolved differently on the phone",
            )
        }
    }

    val updatedSetsById = mutableMapOf<java.util.UUID, Set>()

    for (setEdit in intent.setEdits) {
        val localSet = localSetsById[setEdit.setId]
            ?: return ExerciseEditResult.Rejected(
                "Calibration targets a set that no longer exists on the phone",
            )
        if (setEdit.baseSubCategory !in CALIBRATION_WRITABLE_SUBCATEGORIES ||
            setEdit.newSubCategory != SetSubCategory.WorkSet
        ) {
            return ExerciseEditResult.Rejected("Calibration edit targets a non-calibratable set")
        }
        val currentValue = localSet.calibrationValue(setEdit.setKind)
            ?: return ExerciseEditResult.Rejected("Calibration set type no longer matches")
        val requiredValue = setEdit.newWeight
            ?: return ExerciseEditResult.Rejected("Calibration edit is missing its new set value")
        val baseValue = setEdit.baseWeight
            ?: return ExerciseEditResult.Rejected("Calibration edit is missing its baseline value")
        val currentSubCategory = localSet.subCategory()

        if (currentValue == requiredValue && currentSubCategory == setEdit.newSubCategory) {
            continue
        }
        if (
            enforceBaseline &&
            (currentValue != baseValue || currentSubCategory != setEdit.baseSubCategory)
        ) {
            return ExerciseEditResult.Rejected(
                "Conflicting calibration edit: set ${setEdit.setId} changed on the phone after the watch snapshot",
            )
        }
        updatedSetsById[setEdit.setId] = localSet.withCalibrationValue(
            setEdit.setKind,
            requiredValue,
        )
    }

    val updatedExercise = localExercise.copy(
        sets = localExercise.sets.map { set -> updatedSetsById[set.id] ?: set },
        requiresLoadCalibration = false,
    )
    if (updatedExercise.hasPendingCalibrationSet()) {
        return ExerciseEditResult.Rejected(
            "Calibration is still pending for a set after applying the watch edit",
        )
    }
    return ExerciseEditResult.Applied(updatedExercise)
}

private val CALIBRATION_WRITABLE_SUBCATEGORIES = setOf(
    SetSubCategory.WorkSet,
    SetSubCategory.CalibrationPendingSet,
)

private fun Set.calibrationValue(kind: WatchWorkoutSetKind): Double? = when {
    kind == WatchWorkoutSetKind.WEIGHT && this is WeightSet -> weight
    kind == WatchWorkoutSetKind.BODY_WEIGHT && this is BodyWeightSet -> additionalWeight
    else -> null
}

private fun Set.subCategory(): SetSubCategory? = when (this) {
    is WeightSet -> subCategory
    is BodyWeightSet -> subCategory
    else -> null
}

private fun Exercise.hasPendingCalibrationSet(): Boolean =
    sets.any { it.subCategory() == SetSubCategory.CalibrationPendingSet }

private fun Set.withCalibrationValue(kind: WatchWorkoutSetKind, value: Double): Set = when (this) {
    is WeightSet -> {
        check(kind == WatchWorkoutSetKind.WEIGHT)
        copy(weight = value, subCategory = SetSubCategory.WorkSet)
    }
    is BodyWeightSet -> {
        check(kind == WatchWorkoutSetKind.BODY_WEIGHT)
        copy(additionalWeight = value, subCategory = SetSubCategory.WorkSet)
    }
    else -> this
}

private fun List<WorkoutComponent>.findExercises(exerciseId: java.util.UUID): List<Exercise> =
    flatMap { component ->
        when (component) {
            is Exercise -> listOf(component)
            is Superset -> component.exercises
            else -> emptyList()
        }
    }.filter { it.id == exerciseId }

private fun List<WorkoutComponent>.replaceExercise(
    exerciseId: java.util.UUID,
    updatedExercise: Exercise,
): List<WorkoutComponent> = map { component ->
    when (component) {
        is Exercise -> if (component.id == exerciseId) updatedExercise else component
        is Superset -> {
            val updatedExercises = component.exercises.map { exercise ->
                if (exercise.id == exerciseId) updatedExercise else exercise
            }
            if (updatedExercises == component.exercises) {
                component
            } else {
                component.copy(exercises = updatedExercises)
            }
        }
        else -> component
    }
}

package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.util.UUID

data class SetIdRemap(val exerciseId: UUID, val oldSetId: UUID, val newSetId: UUID)

data class SetIdMigrationResult(
    val workoutStore: WorkoutStore,
    val remaps: List<SetIdRemap>
) {
    val hasChanges: Boolean
        get() = remaps.isNotEmpty()
}

suspend fun migrateWorkoutStoreSetIdsIfNeeded(
    workoutStore: WorkoutStore,
    db: AppDatabase,
    workoutStoreRepository: WorkoutStoreRepository
): WorkoutStore {
    val result = dedupeWorkoutStoreSetIds(workoutStore)
    if (!result.hasChanges) {
        return workoutStore
    }

    applySetIdRemaps(db, result.remaps)
    workoutStoreRepository.saveWorkoutStore(result.workoutStore)
    return result.workoutStore
}

private fun dedupeWorkoutStoreSetIds(workoutStore: WorkoutStore): SetIdMigrationResult {
    val seenSetIds = mutableSetOf<UUID>()
    val remaps = mutableListOf<SetIdRemap>()

    val updatedWorkouts = workoutStore.workouts.map { workout ->
        val updatedComponents = workout.workoutComponents.map { component ->
            dedupeComponentSetIds(component, seenSetIds, remaps)
        }
        workout.copy(workoutComponents = updatedComponents)
    }

    return SetIdMigrationResult(
        workoutStore = workoutStore.copy(workouts = updatedWorkouts),
        remaps = remaps
    )
}

private fun dedupeComponentSetIds(
    component: WorkoutComponent,
    seenSetIds: MutableSet<UUID>,
    remaps: MutableList<SetIdRemap>
): WorkoutComponent {
    return when (component) {
        is Exercise -> dedupeExerciseSetIds(component, seenSetIds, remaps)
        is Superset -> component.copy(
            exercises = component.exercises.map { exercise ->
                dedupeExerciseSetIds(exercise, seenSetIds, remaps)
            }
        )
        is Rest -> component
    }
}

private fun dedupeExerciseSetIds(
    exercise: Exercise,
    seenSetIds: MutableSet<UUID>,
    remaps: MutableList<SetIdRemap>
): Exercise {
    var hasUpdates = false
    val updatedSets = exercise.sets.map { set ->
        val setId = set.id
        if (seenSetIds.add(setId)) {
            set
        } else {
            val newId = UUID.randomUUID()
            remaps.add(SetIdRemap(exercise.id, setId, newId))
            hasUpdates = true
            replaceSetId(set, newId)
        }
    }

    return if (hasUpdates) {
        exercise.copy(
            sets = updatedSets,
            requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()
        )
    } else {
        exercise
    }
}

private fun replaceSetId(set: Set, newId: UUID): Set {
    return when (set) {
        is BodyWeightSet -> set.copy(id = newId)
        is EnduranceSet -> set.copy(id = newId)
        is RestSet -> set.copy(id = newId)
        is TimedDurationSet -> set.copy(id = newId)
        is WeightSet -> set.copy(id = newId)
    }
}

private suspend fun applySetIdRemaps(db: AppDatabase, remaps: List<SetIdRemap>) {
    if (remaps.isEmpty()) {
        return
    }

    val remapsByExercise = remaps
        .groupBy { it.exerciseId }
        .mapValues { entry -> entry.value.associate { it.oldSetId to it.newSetId } }

    val setHistoryDao = db.setHistoryDao()
    val exerciseInfoDao = db.exerciseInfoDao()

    val updatedSetHistories = setHistoryDao
        .getAllSetHistories()
        .mapNotNull { setHistory ->
            val exerciseId = setHistory.exerciseId ?: return@mapNotNull null
            val remap = remapsByExercise[exerciseId] ?: return@mapNotNull null
            val newSetId = remap[setHistory.setId] ?: return@mapNotNull null
            setHistory.copy(setId = newSetId, version = setHistory.version.inc())
        }

    if (updatedSetHistories.isNotEmpty()) {
        setHistoryDao.insertAll(*updatedSetHistories.toTypedArray())
    }

    val updatedExerciseInfos = exerciseInfoDao
        .getAllExerciseInfos()
        .mapNotNull { exerciseInfo ->
            val remap = remapsByExercise[exerciseInfo.id] ?: return@mapNotNull null
            val updatedBest = remapSetHistoryList(exerciseInfo.bestSession, remap)
            val updatedLast = remapSetHistoryList(exerciseInfo.lastSuccessfulSession, remap)
            if (!updatedBest.second && !updatedLast.second) {
                return@mapNotNull null
            }
            exerciseInfo.copy(
                bestSession = updatedBest.first,
                lastSuccessfulSession = updatedLast.first,
                version = exerciseInfo.version.inc()
            )
        }

    if (updatedExerciseInfos.isNotEmpty()) {
        exerciseInfoDao.insertAll(*updatedExerciseInfos.toTypedArray())
    }
}

private fun remapSetHistoryList(
    histories: List<SetHistory>,
    remap: Map<UUID, UUID>
): Pair<List<SetHistory>, Boolean> {
    var changed = false
    val updated = histories.map { history ->
        val newSetId = remap[history.setId]
        if (newSetId == null) {
            history
        } else {
            changed = true
            history.copy(setId = newSetId, version = history.version.inc())
        }
    }
    return updated to changed
}

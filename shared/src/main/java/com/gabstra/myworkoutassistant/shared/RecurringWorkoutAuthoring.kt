package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.RunningSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightedEffortSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.time.LocalDate
import java.util.UUID

data class RecurringTrackChoice(
    val trackId: UUID,
    val exerciseName: String,
    val sourceWorkoutId: UUID,
    val sourceWorkoutName: String,
    val prescriptionOrdinal: Int,
    val prescriptionLabel: String?,
    val exercisePosition: Int,
)

/** Copy-only authoring operations. Callers persist edited workouts through [WorkoutManager.updateWorkout]. */
object RecurringWorkoutAuthoring {
    fun startFamily(
        workout: Workout,
        defaultLoadPolicy: LoadHistoryPolicy = LoadHistoryPolicy.NONE,
        label: String? = null,
    ): Workout {
        require(workout.recurringSessionId == null) { "Workout already belongs to a recurring session." }
        return workout.copy(
            recurringSessionId = UUID.randomUUID(),
            prescriptionOrdinal = 1,
            prescriptionLabel = label?.trim()?.takeIf(String::isNotEmpty),
            workoutComponents = mapExercises(workout.workoutComponents) { exercise ->
                exercise.copy(
                    recurringExerciseId = UUID.randomUUID(),
                    loadHistoryPolicy = (defaultLoadPolicy.takeIf { it != LoadHistoryPolicy.NONE }
                        ?: exercise.loadHistoryPolicy.takeIf { it == LoadHistoryPolicy.PRESCRIBED_WEIGHT }
                        ?: LoadHistoryPolicy.NONE).takeIf { isPolicyEligible(exercise, it) } ?: LoadHistoryPolicy.NONE,
                )
            },
        )
    }

    fun attach(workout: Workout, family: List<Workout>): Workout {
        require(workout.recurringSessionId == null) { "Detach this workout before attaching it to another recurring session." }
        val context = familyContext(family)
        return workout.copy(
            name = context.name,
            recurringSessionId = context.sessionId,
            prescriptionOrdinal = context.nextOrdinal,
            prescriptionLabel = null,
            workoutComponents = mapExercises(workout.workoutComponents) { exercise ->
                exercise.copy(
                    recurringExerciseId = UUID.randomUUID(),
                    loadHistoryPolicy = exercise.loadHistoryPolicy.takeIf {
                        it == LoadHistoryPolicy.PRESCRIBED_WEIGHT && isPrescribedLoadEligible(exercise)
                    } ?: LoadHistoryPolicy.NONE,
                )
            },
        )
    }

    fun cloneNext(source: Workout, family: List<Workout>, label: String?): Workout {
        val context = familyContext(family)
        require(source.recurringSessionId == context.sessionId) { "Source workout is not in this recurring session." }
        val components = source.workoutComponents.map(::cloneComponent)
        return source.copy(
            id = UUID.randomUUID(),
            name = context.name,
            workoutComponents = components,
            order = (family.maxOfOrNull { it.order } ?: source.order) + 1,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            globalId = UUID.randomUUID(),
            prescriptionOrdinal = context.nextOrdinal,
            prescriptionLabel = label?.trim()?.takeIf(String::isNotEmpty),
        )
    }

    fun detach(workout: Workout): Workout = workout.copy(
        recurringSessionId = null,
        prescriptionOrdinal = null,
        prescriptionLabel = null,
        workoutComponents = mapExercises(workout.workoutComponents) {
            it.copy(
                recurringExerciseId = null,
                loadHistoryPolicy = it.loadHistoryPolicy.takeIf { policy ->
                    policy == LoadHistoryPolicy.PRESCRIBED_WEIGHT && isPrescribedLoadEligible(it)
                } ?: LoadHistoryPolicy.NONE,
            )
        },
    )

    fun renameFamily(family: List<Workout>, name: String): List<Workout> {
        val familyName = name.trim()
        require(familyName.isNotEmpty()) { "Recurring session name cannot be empty." }
        familyContext(family)
        return family.map { it.copy(name = familyName) }
    }

    fun updatePrescriptionLabel(
        workout: Workout,
        label: String?,
        family: List<Workout>,
    ): Workout {
        val context = familyContext(family)
        require(workout.recurringSessionId == context.sessionId) { "Workout is not in this recurring session." }
        return workout.copy(
            prescriptionLabel = label?.trim()?.takeIf(String::isNotEmpty),
        )
    }

    fun reorderFamily(family: List<Workout>, orderedWorkoutIds: List<UUID>): List<Workout> {
        val context = familyContext(family)
        val active = family.filter { it.isActive && it.recurringSessionId == context.sessionId }
        require(orderedWorkoutIds.size == active.size && orderedWorkoutIds.toSet() == active.map { it.id }.toSet()) {
            "Reordering must include each active prescription exactly once."
        }
        val ordinalById = orderedWorkoutIds.withIndex().associate { it.value to it.index + 1 }
        return family.map { workout ->
            ordinalById[workout.id]?.let { workout.copy(prescriptionOrdinal = it) } ?: workout
        }
    }

    fun createExerciseTrack(workout: Workout, exerciseId: UUID, policy: LoadHistoryPolicy): Workout {
        require(workout.recurringSessionId != null && workout.prescriptionOrdinal != null) {
            "Add this workout to a recurring session before creating a history track."
        }
        return updateExercise(workout, exerciseId) { createExerciseTrack(it, policy, listOf(workout)) }
    }

    fun createExerciseTrack(
        exercise: Exercise,
        policy: LoadHistoryPolicy,
        family: List<Workout>,
    ): Exercise {
        familyContext(family)
        require(isPolicyEligible(exercise, policy)) {
            "Load policies support loaded weight and bodyweight exercises."
        }
        return exercise.copy(recurringExerciseId = UUID.randomUUID(), loadHistoryPolicy = policy)
    }

    fun linkExerciseTrack(
        workout: Workout,
        exerciseId: UUID,
        trackId: UUID,
        policy: LoadHistoryPolicy,
        family: List<Workout>,
    ): Workout {
        val context = familyContext(family)
        require(workout.recurringSessionId == context.sessionId) { "Workout is not in this recurring session." }
        val exercise = workoutExercises(workout).firstOrNull { it.id == exerciseId }
            ?: throw IllegalArgumentException("Exercise is not part of this workout.")
        return updateExercise(workout, exerciseId) { linkExerciseTrack(it, trackId, policy, family) }
    }

    fun linkExerciseTrack(
        exercise: Exercise,
        trackId: UUID,
        policy: LoadHistoryPolicy,
        family: List<Workout>,
    ): Exercise {
        familyContext(family)
        require(compatibleTrackChoices(exercise, family).any { it.trackId == trackId }) {
            "Selected history track is incompatible with this exercise or recurring session."
        }
        require(isPolicyEligible(exercise, policy)) {
            "Load policies support loaded weight and bodyweight exercises."
        }
        return exercise.copy(recurringExerciseId = trackId, loadHistoryPolicy = policy)
    }

    fun unlinkExerciseTrack(workout: Workout, exerciseId: UUID): Workout =
        updateExercise(workout, exerciseId, ::unlinkExerciseTrack)

    fun unlinkExerciseTrack(exercise: Exercise): Exercise =
        exercise.copy(
            recurringExerciseId = null,
            loadHistoryPolicy = exercise.loadHistoryPolicy.takeIf { it == LoadHistoryPolicy.PRESCRIBED_WEIGHT }
                ?: LoadHistoryPolicy.NONE,
        )

    fun compatibleTrackChoices(exercise: Exercise, family: List<Workout>): List<RecurringTrackChoice> {
        val context = familyContext(family)
        val tracks = family.asSequence()
            .filter { it.isActive && it.recurringSessionId == context.sessionId }
            .flatMap { workout ->
                workoutExercisesWithPosition(workout).asSequence().map { (candidate, position) ->
                    Triple(workout, candidate, position)
                }
            }
            .filter { (_, candidate, _) -> candidate.recurringExerciseId != null }
            .groupBy { it.second.recurringExerciseId!! }
        return tracks.mapNotNull { (trackId, occurrences) ->
            if (occurrences.groupBy { it.first.id }.any { it.value.size > 1 } ||
                !occurrences.all { (_, candidate, _) -> isCompatibleTrack(exercise, candidate) }
            ) return@mapNotNull null
            occurrences.minWithOrNull(
                compareBy<Triple<Workout, Exercise, Int>> { it.first.prescriptionOrdinal ?: Int.MAX_VALUE }
                    .thenBy { it.third }
            )
        }
            .sortedWith(compareBy<Triple<Workout, Exercise, Int>> { it.first.prescriptionOrdinal ?: Int.MAX_VALUE }.thenBy { it.third })
            .map { (workout, candidate, position) ->
                RecurringTrackChoice(
                    trackId = candidate.recurringExerciseId!!,
                    exerciseName = candidate.name,
                    sourceWorkoutId = workout.id,
                    sourceWorkoutName = workout.name,
                    prescriptionOrdinal = workout.prescriptionOrdinal ?: 0,
                    prescriptionLabel = workout.prescriptionLabel,
                    exercisePosition = position,
                )
            }
            .toList()
    }

    private data class FamilyContext(val sessionId: UUID, val name: String, val nextOrdinal: Int)

    private fun familyContext(family: List<Workout>): FamilyContext {
        val active = family.filter { it.isActive }
        require(active.isNotEmpty()) { "Recurring session has no active prescriptions." }
        val sessionIds = active.mapNotNull { it.recurringSessionId }.distinct()
        require(sessionIds.size == 1 && active.all { it.recurringSessionId == sessionIds.single() }) {
            "Selected workouts do not belong to one recurring session."
        }
        return FamilyContext(
            sessionId = sessionIds.single(),
            name = active.first().name,
            nextOrdinal = (active.mapNotNull { it.prescriptionOrdinal }.maxOrNull() ?: 0) + 1,
        )
    }

    private fun isLoadEligible(exercise: Exercise): Boolean {
        val workingSets = exercise.sets.filterNot { it is RestSet }
        if (workingSets.isEmpty()) return false
        return when (exercise.exerciseType) {
        ExerciseType.WEIGHT -> workingSets.all { it is WeightSet }
        ExerciseType.BODY_WEIGHT -> workingSets.all { it is BodyWeightSet }
        else -> false
        }
    }

    private fun isPrescribedLoadEligible(exercise: Exercise): Boolean {
        val workingSets = exercise.sets.filterNot { it is RestSet }
        val matchesExerciseType = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> workingSets.all { it is WeightSet }
            ExerciseType.BODY_WEIGHT -> workingSets.all { it is BodyWeightSet }
            else -> false
        }
        return matchesExerciseType && (workingSets.isNotEmpty() || exercise.sets.isEmpty())
    }

    private fun isPolicyEligible(exercise: Exercise, policy: LoadHistoryPolicy): Boolean = when (policy) {
        LoadHistoryPolicy.NONE -> true
        LoadHistoryPolicy.LAST_WORKING_LOAD -> isLoadEligible(exercise)
        LoadHistoryPolicy.PRESCRIBED_WEIGHT -> isPrescribedLoadEligible(exercise)
    }

    private fun isCompatibleTrack(current: Exercise, candidate: Exercise): Boolean =
        candidate.recurringExerciseId != null &&
            current.exerciseDefinitionId == candidate.exerciseDefinitionId &&
            current.exerciseType == candidate.exerciseType &&
            current.equipmentId == candidate.equipmentId

    private fun updateExercise(workout: Workout, exerciseId: UUID, transform: (Exercise) -> Exercise): Workout {
        var found = false
        val updated = mapExercises(workout.workoutComponents) { exercise ->
            if (exercise.id == exerciseId) {
                found = true
                transform(exercise)
            } else exercise
        }
        require(found) { "Exercise is not part of this workout." }
        return workout.copy(workoutComponents = updated)
    }

    private fun mapExercises(components: List<WorkoutComponent>, transform: (Exercise) -> Exercise): List<WorkoutComponent> =
        components.map { component ->
            when (component) {
                is Exercise -> transform(component)
                is Superset -> component.copy(exercises = component.exercises.map(transform))
                else -> component
            }
        }

    private fun workoutExercises(workout: Workout): List<Exercise> = workoutExercisesWithPosition(workout).map { it.first }

    private fun workoutExercisesWithPosition(workout: Workout): List<Pair<Exercise, Int>> = buildList {
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> add(component to size + 1)
                is Superset -> component.exercises.forEach { add(it to size + 1) }
                else -> Unit
            }
        }
    }

    private fun cloneComponent(component: WorkoutComponent): WorkoutComponent = when (component) {
        is Exercise -> component.copy(id = UUID.randomUUID(), sets = component.sets.map(::cloneSet))
        is Rest -> component.copy(id = UUID.randomUUID())
        is Superset -> {
            val exercises = component.exercises.map { it.copy(id = UUID.randomUUID(), sets = it.sets.map(::cloneSet)) }
            val exerciseIds = component.exercises.zip(exercises).associate { (old, copied) -> old.id to copied.id }
            component.copy(
                id = UUID.randomUUID(),
                exercises = exercises,
                restSecondsByExercise = component.restSecondsByExercise.mapNotNull { (id, seconds) ->
                    exerciseIds[id]?.let { it to seconds }
                }.toMap(),
            )
        }
    }

    private fun cloneSet(set: Set): Set = when (set) {
        is BodyWeightSet -> set.copy(id = UUID.randomUUID())
        is WeightSet -> set.copy(id = UUID.randomUUID())
        is EnduranceSet -> set.copy(id = UUID.randomUUID())
        is RunningSet -> set.copy(id = UUID.randomUUID())
        is TimedDurationSet -> set.copy(id = UUID.randomUUID())
        is WeightedEffortSet -> set.copy(id = UUID.randomUUID())
        is RestSet -> set.copy(id = UUID.randomUUID())
    }
}

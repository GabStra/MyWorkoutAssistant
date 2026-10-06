package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.nio.charset.StandardCharsets
import java.util.UUID

data class ResolvedExercise(
    val definition: ExerciseDefinition,
    val prescription: Exercise,
) {
    val displayName: String
        get() = prescription.resolvedName(definition)
}

fun Exercise.resolvedName(definition: ExerciseDefinition): String =
    nameOverride?.trim()?.takeIf { it.isNotEmpty() } ?: definition.name

data class ExerciseVariationResolution(
    val workoutStore: WorkoutStore,
    val definition: ExerciseDefinition,
)

fun ExerciseDefinition.effectiveFamilyId(): UUID =
    exerciseFamilyId ?: deterministicExerciseFamilyId(name)

fun List<ExerciseDefinition>.normalizeExerciseFamilyMovements(): List<ExerciseDefinition> {
    val movementByFamilyId = groupBy(ExerciseDefinition::effectiveFamilyId).mapValues { (_, family) ->
        family.sortedBy { it.id.toString() }.firstNotNullOfOrNull { it.movementRef }
    }
    return map { definition ->
        val familyId = definition.effectiveFamilyId()
        definition.copy(
            exerciseFamilyId = familyId,
            movementRef = movementByFamilyId[familyId],
        )
    }
}

fun WorkoutStore.normalizeExerciseFamilyMovementOwnership(): WorkoutStore {
    val normalizedDefinitions = exerciseDefinitions.normalizeExerciseFamilyMovements()
    val definitionsById = normalizedDefinitions.associateBy { it.id }
    fun materializeMovement(exercise: Exercise): Exercise {
        val definition = exercise.exerciseDefinitionId?.let(definitionsById::get) ?: return exercise
        return exercise.copy(movementRef = definition.movementRef)
    }
    return copy(
        exerciseDefinitions = normalizedDefinitions,
        workouts = workouts.map { workout ->
            workout.copy(
                workoutComponents = workout.workoutComponents.map { component ->
                    when (component) {
                        is Exercise -> materializeMovement(component)
                        is Superset -> component.copy(
                            exercises = component.exercises.map(::materializeMovement),
                        )
                        else -> component
                    }
                },
            )
        },
    )
}

fun WorkoutStore.resolveExercise(prescription: Exercise): ResolvedExercise {
    val definitionId = requireNotNull(prescription.exerciseDefinitionId) {
        "Exercise prescription ${prescription.id} has no definition reference"
    }
    val definition = exerciseDefinitions.firstOrNull { it.id == definitionId }
        ?: throw IllegalArgumentException(
            "Exercise prescription ${prescription.id} references missing definition $definitionId"
        )
    return ResolvedExercise(definition, prescription)
}

fun WorkoutStore.updateExerciseDefinition(updated: ExerciseDefinition): WorkoutStore {
    val current = exerciseDefinitions.firstOrNull { it.id == updated.id }
        ?: throw IllegalArgumentException("Unknown exercise definition ${updated.id}")
    val isReferenced = allExercisePrescriptions().any { it.exerciseDefinitionId == updated.id }
    require(!isReferenced || (
        current.exerciseType == updated.exerciseType && current.equipmentId == updated.equipmentId
    )) { "Exercise type and equipment cannot change while a definition is referenced" }

    val familyId = current.effectiveFamilyId()
    val normalizedUpdated = updated.copy(exerciseFamilyId = familyId)
    val updatedDefinitions = exerciseDefinitions.map { definition ->
        when {
            definition.id == updated.id -> normalizedUpdated
            definition.effectiveFamilyId() == familyId -> definition.copy(
                exerciseFamilyId = familyId,
                name = normalizedUpdated.name,
                movementRef = normalizedUpdated.movementRef,
            )
            else -> definition
        }
    }
    val updatedDefinitionsById = updatedDefinitions.associateBy { it.id }

    fun materialize(exercise: Exercise): Exercise {
        val definition = exercise.exerciseDefinitionId?.let(updatedDefinitionsById::get)
            ?: return exercise
        return exercise.copy(
            name = exercise.resolvedName(definition),
            exerciseType = definition.exerciseType, equipmentId = definition.equipmentId,
            bodyWeightPercentage = definition.bodyWeightPercentage,
            muscleGroups = definition.muscleGroups,
            secondaryMuscleGroups = definition.secondaryMuscleGroups,
            requiredAccessoryEquipmentIds = definition.requiredAccessoryEquipmentIds,
            exerciseCategory = definition.exerciseCategory, movementRef = definition.movementRef,
        )
    }

    return copy(
        exerciseDefinitions = updatedDefinitions,
        workouts = workouts.map { workout ->
            workout.copy(workoutComponents = workout.workoutComponents.map { component ->
                when (component) {
                    is Exercise -> materialize(component)
                    is Superset -> component.copy(exercises = component.exercises.map(::materialize))
                    else -> component
                }
            })
        },
    )
}

fun WorkoutStore.addExerciseDefinition(definition: ExerciseDefinition): WorkoutStore {
    require(exerciseDefinitions.none { it.id == definition.id }) {
        "Exercise definition ${definition.id} already exists"
    }
    val familyId = definition.effectiveFamilyId()
    val existingFamilyMovement = exerciseDefinitions
        .filter { it.effectiveFamilyId() == familyId }
        .firstNotNullOfOrNull { it.movementRef }
    val familyMovement = existingFamilyMovement ?: definition.movementRef
    val updatedDefinitions = exerciseDefinitions.map { existing ->
        if (existing.effectiveFamilyId() == familyId) {
            existing.copy(exerciseFamilyId = familyId, movementRef = familyMovement)
        } else {
            existing
        }
    } + definition.copy(exerciseFamilyId = familyId, movementRef = familyMovement)
    return copy(exerciseDefinitions = updatedDefinitions)
        .normalizeExerciseFamilyMovementOwnership()
}

fun WorkoutStore.deleteExerciseDefinition(definitionId: UUID): WorkoutStore {
    require(allExercisePrescriptions().none { it.exerciseDefinitionId == definitionId }) {
        "Referenced exercise definitions cannot be deleted"
    }
    return copy(exerciseDefinitions = exerciseDefinitions.filterNot { it.id == definitionId })
}

/** Creates an independent workout occurrence while retaining the shared definition link. */
fun Exercise.duplicatePrescription(): Exercise = copy(
    id = UUID.randomUUID(),
    sets = sets.map(Set::withFreshId),
)

fun WorkoutStore.resolveExerciseVariation(
    sourceDefinitionId: UUID,
    candidate: Exercise,
): ExerciseVariationResolution {
    val sourceDefinition = exerciseDefinitions.firstOrNull { it.id == sourceDefinitionId }
        ?: throw IllegalArgumentException("Unknown exercise definition $sourceDefinitionId")
    val familyId = sourceDefinition.effectiveFamilyId()
    val candidateDefinition = ExerciseDefinition(
        id = UUID(0L, 0L),
        exerciseFamilyId = familyId,
        name = sourceDefinition.name,
        exerciseType = candidate.exerciseType,
        equipmentId = candidate.equipmentId,
        bodyWeightPercentage = candidate.bodyWeightPercentage,
        muscleGroups = candidate.muscleGroups,
        secondaryMuscleGroups = candidate.secondaryMuscleGroups,
        requiredAccessoryEquipmentIds = candidate.requiredAccessoryEquipmentIds,
        exerciseCategory = candidate.exerciseCategory,
        movementRef = exerciseDefinitions
            .filter { it.effectiveFamilyId() == familyId }
            .firstNotNullOfOrNull { it.movementRef },
    )
    val matchingDefinition = exerciseDefinitions.firstOrNull { definition ->
        definition.effectiveFamilyId() == familyId &&
            definition.variationFingerprint() == candidateDefinition.variationFingerprint()
    }
    val resolvedDefinition = matchingDefinition ?: candidateDefinition.copy(
        id = deterministicExerciseDefinitionId(candidateDefinition.fingerprint()),
    )
    val normalizedDefinitions = exerciseDefinitions.map { definition ->
        if (definition.exerciseFamilyId == null) {
            definition.copy(exerciseFamilyId = definition.effectiveFamilyId())
        } else {
            definition
        }
    }
    val updatedStore = if (matchingDefinition == null) {
        copy(exerciseDefinitions = normalizedDefinitions + resolvedDefinition)
    } else {
        copy(exerciseDefinitions = normalizedDefinitions)
    }
    return ExerciseVariationResolution(updatedStore, resolvedDefinition)
}

fun Exercise.materializeDefinition(definition: ExerciseDefinition): Exercise {
    val localNotes = placementNotes ?: notes
    val normalizedNameOverride = nameOverride?.trim()?.takeIf {
        it.isNotEmpty() && it != definition.name
    }
    return copy(
        exerciseDefinitionId = definition.id,
        name = normalizedNameOverride ?: definition.name,
        nameOverride = normalizedNameOverride,
        notes = localNotes,
        placementNotes = localNotes,
        exerciseType = definition.exerciseType,
        equipmentId = definition.equipmentId,
        bodyWeightPercentage = definition.bodyWeightPercentage,
        muscleGroups = definition.muscleGroups,
        secondaryMuscleGroups = definition.secondaryMuscleGroups,
        requiredAccessoryEquipmentIds = definition.requiredAccessoryEquipmentIds,
        exerciseCategory = definition.exerciseCategory,
        movementRef = definition.movementRef,
    )
}

private fun Set.withFreshId(): Set = when (this) {
    is BodyWeightSet -> copy(id = UUID.randomUUID())
    is EnduranceSet -> copy(id = UUID.randomUUID())
    is RestSet -> copy(id = UUID.randomUUID())
    is TimedDurationSet -> copy(id = UUID.randomUUID())
    is WeightSet -> copy(id = UUID.randomUUID())
}

fun WorkoutStore.migrateExerciseLibrary(): WorkoutStore {
    if (schemaVersion >= WorkoutStore.CURRENT_SCHEMA_VERSION &&
        allExercisePrescriptions().all {
            it.exerciseDefinitionId != null && it.placementNotes != null &&
                (it.notes.isBlank() || it.notes == it.placementNotes)
        } && exerciseDefinitions.all { it.exerciseFamilyId != null } &&
        exerciseDefinitions.groupBy(ExerciseDefinition::effectiveFamilyId).values.all { family ->
            family.map { it.movementRef }.distinct().size <= 1
        }
    ) return this

    val definitionsByFingerprint = linkedMapOf<String, ExerciseDefinition>()
    exerciseDefinitions.forEach { definition ->
        val normalized = definition.copy(exerciseFamilyId = definition.effectiveFamilyId())
        definitionsByFingerprint.putIfAbsent(normalized.fingerprint(), normalized)
    }

    fun migrate(exercise: Exercise): Exercise {
        val existing = exercise.exerciseDefinitionId?.let { id ->
            definitionsByFingerprint.values.firstOrNull { it.id == id }
        }
        val candidate = existing ?: exercise.toDefinition(
            exerciseFamilyId = deterministicExerciseFamilyId(exercise.name),
        )
        val definition = definitionsByFingerprint.getOrPut(candidate.fingerprint()) {
            candidate.copy(id = deterministicExerciseDefinitionId(candidate.fingerprint()))
        }
        val localNotes = exercise.placementNotes?.takeIf { it.isNotBlank() } ?: exercise.notes
        val normalizedNameOverride = exercise.nameOverride?.trim()?.takeIf {
            it.isNotEmpty() && it != definition.name
        }
        return exercise.copy(
            exerciseDefinitionId = definition.id,
            placementNotes = localNotes,
            name = normalizedNameOverride ?: definition.name,
            nameOverride = normalizedNameOverride,
            notes = localNotes,
            exerciseType = definition.exerciseType,
            equipmentId = definition.equipmentId,
            bodyWeightPercentage = definition.bodyWeightPercentage,
            muscleGroups = definition.muscleGroups,
            secondaryMuscleGroups = definition.secondaryMuscleGroups,
            requiredAccessoryEquipmentIds = definition.requiredAccessoryEquipmentIds,
            exerciseCategory = definition.exerciseCategory,
            movementRef = definition.movementRef,
        )
    }

    val migratedWorkouts = workouts.map { workout ->
            workout.copy(workoutComponents = workout.workoutComponents.map { component ->
                when (component) {
                    is Exercise -> migrate(component)
                    is Superset -> component.copy(exercises = component.exercises.map(::migrate))
                    else -> component
                }
            })
        }
    return copy(
        schemaVersion = WorkoutStore.CURRENT_SCHEMA_VERSION,
        exerciseDefinitions = definitionsByFingerprint.values.toList(),
        workouts = migratedWorkouts,
    ).normalizeExerciseFamilyMovementOwnership()
}

fun WorkoutStore.allExercisePrescriptions(): List<Exercise> = buildList {
    workouts.forEach { workout ->
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> add(component)
                is Superset -> addAll(component.exercises)
                else -> Unit
            }
        }
    }
}

private fun Exercise.toDefinition(exerciseFamilyId: UUID) = ExerciseDefinition(
    id = UUID(0L, 0L),
    exerciseFamilyId = exerciseFamilyId,
    name = name,
    exerciseType = exerciseType,
    equipmentId = equipmentId,
    bodyWeightPercentage = bodyWeightPercentage,
    muscleGroups = muscleGroups,
    secondaryMuscleGroups = secondaryMuscleGroups,
    requiredAccessoryEquipmentIds = requiredAccessoryEquipmentIds,
    exerciseCategory = exerciseCategory,
    movementRef = movementRef,
)

private fun ExerciseDefinition.fingerprint(): String = listOf(
    exerciseFamilyId, name, exerciseType.name, equipmentId, bodyWeightPercentage,
    muscleGroups?.map { it.name }?.sorted(), secondaryMuscleGroups?.map { it.name }?.sorted(),
    requiredAccessoryEquipmentIds?.map(UUID::toString)?.sorted(), exerciseCategory?.name,
).joinToString(separator = "\u001f") { it?.toString() ?: "<null>" }

private fun ExerciseDefinition.variationFingerprint(): String = listOf(
    exerciseType.name, equipmentId, bodyWeightPercentage,
    muscleGroups?.map { it.name }?.sorted(), secondaryMuscleGroups?.map { it.name }?.sorted(),
    requiredAccessoryEquipmentIds?.map(UUID::toString)?.sorted(), exerciseCategory?.name,
).joinToString(separator = "\u001f") { it?.toString() ?: "<null>" }

private fun deterministicExerciseDefinitionId(fingerprint: String): UUID =
    UUID.nameUUIDFromBytes("mwa-exercise-definition-v2\u0000$fingerprint".toByteArray(StandardCharsets.UTF_8))

private fun deterministicExerciseFamilyId(name: String): UUID = UUID.nameUUIDFromBytes(
    "mwa-exercise-family-v3\u0000${name.trim().lowercase()}".toByteArray(StandardCharsets.UTF_8),
)

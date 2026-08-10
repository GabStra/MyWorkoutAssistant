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
)

data class ExerciseVariationResolution(
    val workoutStore: WorkoutStore,
    val definition: ExerciseDefinition,
)

fun ExerciseDefinition.effectiveFamilyId(): UUID =
    exerciseFamilyId ?: deterministicExerciseFamilyId(name)

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
            )
            else -> definition
        }
    }
    val updatedDefinitionsById = updatedDefinitions.associateBy { it.id }

    fun materialize(exercise: Exercise): Exercise {
        val definition = exercise.exerciseDefinitionId?.let(updatedDefinitionsById::get)
            ?: return exercise
        return exercise.copy(
            name = definition.name,
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
        movementRef = candidate.movementRef,
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
    return copy(
        exerciseDefinitionId = definition.id,
        name = definition.name,
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
        } && exerciseDefinitions.all { it.exerciseFamilyId != null }
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
        return exercise.copy(
            exerciseDefinitionId = definition.id,
            placementNotes = localNotes,
            name = definition.name,
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
    )
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
    movementRef,
).joinToString(separator = "\u001f") { it?.toString() ?: "<null>" }

private fun ExerciseDefinition.variationFingerprint(): String = listOf(
    exerciseType.name, equipmentId, bodyWeightPercentage,
    muscleGroups?.map { it.name }?.sorted(), secondaryMuscleGroups?.map { it.name }?.sorted(),
    requiredAccessoryEquipmentIds?.map(UUID::toString)?.sorted(), exerciseCategory?.name,
    movementRef,
).joinToString(separator = "\u001f") { it?.toString() ?: "<null>" }

private fun deterministicExerciseDefinitionId(fingerprint: String): UUID =
    UUID.nameUUIDFromBytes("mwa-exercise-definition-v2\u0000$fingerprint".toByteArray(StandardCharsets.UTF_8))

private fun deterministicExerciseFamilyId(name: String): UUID = UUID.nameUUIDFromBytes(
    "mwa-exercise-family-v3\u0000${name.trim().lowercase()}".toByteArray(StandardCharsets.UTF_8),
)

package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import java.util.UUID

/** Reusable exercise identity shared by workout-specific prescriptions. */
data class ExerciseDefinition(
    val id: UUID,
    val exerciseFamilyId: UUID? = null,
    val name: String,
    val exerciseType: ExerciseType,
    val equipmentId: UUID? = null,
    val bodyWeightPercentage: Double? = null,
    val muscleGroups: Set<MuscleGroup>? = null,
    val secondaryMuscleGroups: Set<MuscleGroup>? = null,
    val requiredAccessoryEquipmentIds: List<UUID>? = null,
    val exerciseCategory: ExerciseCategory? = null,
    val movementRef: ExerciseMovementRef? = null,
)

package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.sets.Set
import java.util.UUID

data class Exercise (
    override val id: UUID,
    override val enabled: Boolean,
    val name: String,
    val notes: String,
    val sets: List<Set>,
    val exerciseType: ExerciseType,
    val minReps : Int,
    val maxReps : Int,

    val lowerBoundMaxHRPercent: Float?,
    val upperBoundMaxHRPercent: Float?,
    val equipmentId: UUID?,
    val bodyWeightPercentage: Double?,
    val generateWarmUpSets: Boolean = false,
    val progressionMode: ProgressionMode = ProgressionMode.OFF,
    val keepScreenOn: Boolean = false,
    val showCountDownTimer: Boolean = false,
    val intraSetRestInSeconds : Int? = null,

    val loadJumpDefaultPct: Double? = null,
    val loadJumpMaxPct: Double? = null,
    val loadJumpOvercapUntil: Int? = null,
    val muscleGroups: kotlin.collections.Set<MuscleGroup>? = null,
    val secondaryMuscleGroups: kotlin.collections.Set<MuscleGroup>? = null,
    val requiredAccessoryEquipmentIds: List<UUID>? = null,
    val requiresLoadCalibration: Boolean = false,
    val exerciseCategory: ExerciseCategory? = null,
    val deloadFailedSessionsThreshold: Int? = null,
    val deloadCompletedSessionsInterval: Int? = null,
    val deloadWeightFactor: Double? = null,
    val deloadRepsDrop: Int? = null,
    val deloadCutSetsTo: Int? = null,
    val movementRef: ExerciseMovementRef? = null,
    /** Canonical schema-v2 definition link. Legacy identity fields above stay materialized. */
    val exerciseDefinitionId: UUID? = null,
    /** Notes specific to this workout occurrence. */
    val placementNotes: String? = null,
    /** Optional workout-specific display name. Null follows the linked definition name. */
    val nameOverride: String? = null,
    ): WorkoutComponent(id,enabled) {
    
    // Custom hashCode and equals to safely handle null requiredAccessoryEquipmentIds
    // (which can occur when Gson sets it to null via reflection)
    override fun hashCode(): Int {
        var result = id.hashCode()
        result = 31 * result + enabled.hashCode()
        result = 31 * result + name.hashCode()
        result = 31 * result + notes.hashCode()
        result = 31 * result + sets.hashCode()
        result = 31 * result + exerciseType.hashCode()
        result = 31 * result + minReps.hashCode()
        result = 31 * result + maxReps.hashCode()
        result = 31 * result + (lowerBoundMaxHRPercent?.hashCode() ?: 0)
        result = 31 * result + (upperBoundMaxHRPercent?.hashCode() ?: 0)
        result = 31 * result + (equipmentId?.hashCode() ?: 0)
        result = 31 * result + (bodyWeightPercentage?.hashCode() ?: 0)
        result = 31 * result + generateWarmUpSets.hashCode()
        result = 31 * result + progressionMode.hashCode()
        result = 31 * result + keepScreenOn.hashCode()
        result = 31 * result + showCountDownTimer.hashCode()
        result = 31 * result + (intraSetRestInSeconds?.hashCode() ?: 0)
        result = 31 * result + (loadJumpDefaultPct?.hashCode() ?: 0)
        result = 31 * result + (loadJumpMaxPct?.hashCode() ?: 0)
        result = 31 * result + (loadJumpOvercapUntil?.hashCode() ?: 0)
        result = 31 * result + (muscleGroups?.hashCode() ?: 0)
        result = 31 * result + (secondaryMuscleGroups?.hashCode() ?: 0)
        result = 31 * result + (requiredAccessoryEquipmentIds?.hashCode() ?: 0)
        result = 31 * result + requiresLoadCalibration.hashCode()
        result = 31 * result + (exerciseCategory?.hashCode() ?: 0)
        result = 31 * result + (deloadFailedSessionsThreshold?.hashCode() ?: 0)
        result = 31 * result + (deloadCompletedSessionsInterval?.hashCode() ?: 0)
        result = 31 * result + (deloadWeightFactor?.hashCode() ?: 0)
        result = 31 * result + (deloadRepsDrop?.hashCode() ?: 0)
        result = 31 * result + (deloadCutSetsTo?.hashCode() ?: 0)
        result = 31 * result + (movementRef?.hashCode() ?: 0)
        return result
    }
    
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Exercise) return false
        
        if (id != other.id) return false
        if (enabled != other.enabled) return false
        if (name != other.name) return false
        if (notes != other.notes) return false
        if (sets != other.sets) return false
        if (exerciseType != other.exerciseType) return false
        if (minReps != other.minReps) return false
        if (maxReps != other.maxReps) return false
        if (lowerBoundMaxHRPercent != other.lowerBoundMaxHRPercent) return false
        if (upperBoundMaxHRPercent != other.upperBoundMaxHRPercent) return false
        if (equipmentId != other.equipmentId) return false
        if (bodyWeightPercentage != other.bodyWeightPercentage) return false
        if (generateWarmUpSets != other.generateWarmUpSets) return false
        if (progressionMode != other.progressionMode) return false
        if (keepScreenOn != other.keepScreenOn) return false
        if (showCountDownTimer != other.showCountDownTimer) return false
        if (intraSetRestInSeconds != other.intraSetRestInSeconds) return false
        if (loadJumpDefaultPct != other.loadJumpDefaultPct) return false
        if (loadJumpMaxPct != other.loadJumpMaxPct) return false
        if (loadJumpOvercapUntil != other.loadJumpOvercapUntil) return false
        if (muscleGroups != other.muscleGroups) return false
        if (secondaryMuscleGroups != other.secondaryMuscleGroups) return false
        if ((requiredAccessoryEquipmentIds ?: emptyList<UUID>()) != (other.requiredAccessoryEquipmentIds ?: emptyList<UUID>())) return false
        if (requiresLoadCalibration != other.requiresLoadCalibration) return false
        if (exerciseCategory != other.exerciseCategory) return false
        if (deloadFailedSessionsThreshold != other.deloadFailedSessionsThreshold) return false
        if (deloadCompletedSessionsInterval != other.deloadCompletedSessionsInterval) return false
        if (deloadWeightFactor != other.deloadWeightFactor) return false
        if (deloadRepsDrop != other.deloadRepsDrop) return false
        if (deloadCutSetsTo != other.deloadCutSetsTo) return false
        if (movementRef != other.movementRef) return false
        
        return true
    }
}

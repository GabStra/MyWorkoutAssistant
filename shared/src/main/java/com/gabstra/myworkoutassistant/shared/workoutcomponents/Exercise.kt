package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.sets.Set
import java.util.UUID

data class Exercise (
    override val id: UUID,
    override val enabled: Boolean,
    val name: String,
    val doNotStoreHistory: Boolean,
    val notes: String,
    val sets: List<Set>,
    val exerciseType: ExerciseType,
    val minLoadPercent : Double,
    val maxLoadPercent : Double,
    val minReps : Int,
    val maxReps : Int,

    val lowerBoundMaxHRPercent: Float?,
    val upperBoundMaxHRPercent: Float?,
    val equipmentId: UUID?,
    val bodyWeightPercentage: Double?,
    val generateWarmUpSets: Boolean = false,
    val enableProgression : Boolean = false,
    val keepScreenOn : Boolean = false,
    val showCountDownTimer: Boolean = false,
    val intraSetRestInSeconds : Int? = null,

    val loadJumpDefaultPct: Double? = null,
    val loadJumpMaxPct: Double? = null,
    val loadJumpOvercapUntil: Int? = null,
    val muscleGroups: kotlin.collections.Set<MuscleGroup>? = null,
    val secondaryMuscleGroups: kotlin.collections.Set<MuscleGroup>? = null,
    val requiredAccessoryEquipmentIds: List<UUID>? = null,
    val requiresLoadCalibration: Boolean = false,
    ): WorkoutComponent(id,enabled) {
    
    // Custom hashCode and equals to safely handle null requiredAccessoryEquipmentIds
    // (which can occur when Gson sets it to null via reflection)
    override fun hashCode(): Int {
        var result = id.hashCode()
        result = 31 * result + enabled.hashCode()
        result = 31 * result + name.hashCode()
        result = 31 * result + doNotStoreHistory.hashCode()
        result = 31 * result + notes.hashCode()
        result = 31 * result + sets.hashCode()
        result = 31 * result + exerciseType.hashCode()
        result = 31 * result + minLoadPercent.hashCode()
        result = 31 * result + maxLoadPercent.hashCode()
        result = 31 * result + minReps.hashCode()
        result = 31 * result + maxReps.hashCode()
        result = 31 * result + (lowerBoundMaxHRPercent?.hashCode() ?: 0)
        result = 31 * result + (upperBoundMaxHRPercent?.hashCode() ?: 0)
        result = 31 * result + (equipmentId?.hashCode() ?: 0)
        result = 31 * result + (bodyWeightPercentage?.hashCode() ?: 0)
        result = 31 * result + generateWarmUpSets.hashCode()
        result = 31 * result + enableProgression.hashCode()
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
        return result
    }
    
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Exercise) return false
        
        if (id != other.id) return false
        if (enabled != other.enabled) return false
        if (name != other.name) return false
        if (doNotStoreHistory != other.doNotStoreHistory) return false
        if (notes != other.notes) return false
        if (sets != other.sets) return false
        if (exerciseType != other.exerciseType) return false
        if (minLoadPercent != other.minLoadPercent) return false
        if (maxLoadPercent != other.maxLoadPercent) return false
        if (minReps != other.minReps) return false
        if (maxReps != other.maxReps) return false
        if (lowerBoundMaxHRPercent != other.lowerBoundMaxHRPercent) return false
        if (upperBoundMaxHRPercent != other.upperBoundMaxHRPercent) return false
        if (equipmentId != other.equipmentId) return false
        if (bodyWeightPercentage != other.bodyWeightPercentage) return false
        if (generateWarmUpSets != other.generateWarmUpSets) return false
        if (enableProgression != other.enableProgression) return false
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
        
        return true
    }
}
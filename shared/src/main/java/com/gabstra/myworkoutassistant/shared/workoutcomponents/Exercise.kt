package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.ExerciseType
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
): WorkoutComponent(id,enabled)
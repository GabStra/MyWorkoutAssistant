package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper
import java.util.UUID

data class Exercise (
    override val id: UUID,
    override val enabled: Boolean,
    val name: String,
    val doNotStoreHistory: Boolean,
    val notes: String,
    val sets: List<Set>,
    val exerciseType: ExerciseType,
    val exerciseCategory: ProgressionHelper.ExerciseCategory?,
    val minLoadPercent : Double,
    val maxLoadPercent : Double,
    val minReps : Int,
    val maxReps : Int,
    val fatigueFactor: Float,
    val volumeIncreasePercent: Float,
): WorkoutComponent(id,enabled)
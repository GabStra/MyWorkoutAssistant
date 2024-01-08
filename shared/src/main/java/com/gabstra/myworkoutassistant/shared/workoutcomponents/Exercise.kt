package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.sets.Set
import java.util.UUID

data class Exercise(
    override val id: UUID,
    override val name: String,
    override val restTimeInSec: Int,
    override val enabled: Boolean,
    override val skipWorkoutRest: Boolean,
    val sets: List<Set>,
) : WorkoutComponent(id, name, restTimeInSec, enabled, skipWorkoutRest)
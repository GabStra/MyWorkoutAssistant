package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.sets.Set

data class Exercise(
    override val name: String,
    override val restTimeInSec: Int,
    override val enabled: Boolean,
    override val skipWorkoutRest: Boolean,
    val sets: List<Set>,
) : WorkoutComponent(name, restTimeInSec, enabled, skipWorkoutRest)
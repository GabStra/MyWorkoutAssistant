package com.gabstra.myworkoutassistant.shared.workoutcomponents

import com.gabstra.myworkoutassistant.shared.sets.Set

data class Exercise(
    override val name: String,
    override val restTimeInSec: Int,
    val sets: List<Set>,
    val enabled: Boolean
) : WorkoutComponent(name, restTimeInSec)
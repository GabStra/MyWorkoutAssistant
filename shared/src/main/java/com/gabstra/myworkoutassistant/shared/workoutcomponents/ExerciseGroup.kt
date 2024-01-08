package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

data class ExerciseGroup(
    override val id: UUID,
    override val name: String,
    override val restTimeInSec: Int,
    override val enabled: Boolean,
    override val skipWorkoutRest: Boolean,
    val workoutComponents: List<WorkoutComponent>,
) : WorkoutComponent(id, name, restTimeInSec, enabled, skipWorkoutRest)
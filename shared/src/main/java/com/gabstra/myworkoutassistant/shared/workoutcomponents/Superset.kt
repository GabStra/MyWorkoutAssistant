package com.gabstra.myworkoutassistant.shared.workoutcomponents

import java.util.UUID

data class Superset(
    override val id: UUID,
    override val enabled: Boolean,
    val exercises: List<Exercise>,
    val restSecondsByExercise: Map<UUID, Int>,
    val timeCapSeconds: Int? = null,
    val roundDurationSeconds: Int? = null,
    // AMRAP mode: the members define ONE round; the runtime repeats it until
    // timeCapSeconds expires (requires timeCapSeconds to be set).
    val amrap: Boolean = false
) : WorkoutComponent(id,enabled)

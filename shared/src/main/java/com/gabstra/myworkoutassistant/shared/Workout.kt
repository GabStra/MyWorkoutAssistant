package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.time.LocalDate
import java.util.UUID

data class Workout(
    val id: UUID,
    val name: String,
    val description: String,
    val workoutComponents: List<WorkoutComponent>,
    val order : Int,
    val enabled: Boolean = true,
    val heartRateSource: HeartRateSource = HeartRateSource.WATCH_SENSOR,
    val creationDate: LocalDate,
    val previousVersionId: UUID? = null,
    val nextVersionId: UUID? = null,
    val isActive: Boolean = true,
    val timesCompletedInAWeek: Int? = null,
    val globalId: UUID,
    val type: Int,
    val workoutPlanId: UUID? = null
) {
    val usePolarDevice: Boolean
        get() = heartRateSource == HeartRateSource.POLAR_BLE

    val usesExternalHeartRateDevice: Boolean
        get() = heartRateSource.isExternal
}

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
    /** Default live/of-record source; always part of [heartRateSources] via [enabledHeartRateSources]. */
    val heartRateSource: HeartRateSource = HeartRateSource.WATCH_SENSOR,
    /** Every source enabled for this workout; all of them connect and record simultaneously. */
    val heartRateSources: Set<HeartRateSource> = emptySet(),
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

    /** Enabled sources, guaranteed to include the default live source. */
    val enabledHeartRateSources: Set<HeartRateSource>
        get() = heartRateSources + heartRateSource

    val usesExternalHeartRateDevice: Boolean
        get() = enabledHeartRateSources.any { it.isExternal }
}

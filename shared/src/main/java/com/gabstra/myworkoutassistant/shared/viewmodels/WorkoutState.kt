package com.gabstra.myworkoutassistant.shared.viewmodels

import java.time.LocalDateTime
import java.util.UUID

sealed class WorkoutState {
    data class Preparing(
        val dataLoaded: Boolean
    ) : WorkoutState()

    data class Set(
        val exerciseId: UUID,
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        val previousSetData: SetData?,
        var currentSetData: SetData,
        val hasNoHistory: Boolean,
        var startTime : LocalDateTime? = null,
        var skipped: Boolean,
        val lowerBoundMaxHRPercent: Float? = null,
        val upperBoundMaxHRPercent: Float? = null,
        val currentBodyWeight: Double,
        val plateChangeResult: PlateCalculator.Companion.PlateChangeResult? = null,
        val streak: Int,
        val isDeloading: Boolean,
        val lastSessionVolume: Double,
        val expectedProgress: Double?
    ) : WorkoutState()

    data class Rest(
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        var currentSetData: SetData,
        val exerciseId: UUID? = null,
        var nextStateSets: List<WorkoutState.Set> = emptyList(),
        var startTime : LocalDateTime? = null,
    ) : WorkoutState()

    data class Finished(val startWorkoutTime: LocalDateTime) : WorkoutState()
}

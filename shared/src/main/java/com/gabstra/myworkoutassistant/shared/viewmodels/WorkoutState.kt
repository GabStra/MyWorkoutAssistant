package com.gabstra.myworkoutassistant.shared.viewmodels

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import java.time.LocalDateTime
import java.util.UUID

enum class ProgressionState {
    DELOAD, RETRY, PROGRESS, FAILED
}

sealed class WorkoutState {
    class Preparing(
        dataLoaded: Boolean
    ) : WorkoutState() {
        var dataLoaded by mutableStateOf(dataLoaded)
    }

    data class Set(
        val exerciseId: UUID,
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val setIndex: UInt,
        val previousSetData: SetData?,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,        // constructor param
        val hasNoHistory: Boolean,
        var startTime : LocalDateTime? = null,
        var skipped: Boolean,
        val lowerBoundMaxHRPercent: Float? = null,
        val upperBoundMaxHRPercent: Float? = null,
        val currentBodyWeight: Double,
        val plateChangeResult: PlateCalculator.Companion.PlateChangeResult? = null,
        val streak: Int,
        val progressionState: ProgressionState?,
        val isWarmupSet: Boolean,
        val equipment: WeightLoadedEquipment?,
        val isUnilateral: Boolean = false,
        val intraSetTotal : UInt? = null,
        var intraSetCounter : UInt = 0u,
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // <-- observe changes
    }

    data class Rest(
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,
        val exerciseId: UUID? = null,
        var nextStateSets: List<WorkoutState.Set> = emptyList(),
        var startTime : LocalDateTime? = null,
        val isIntraSetRest : Boolean = false
    ) : WorkoutState() {
        var currentSetData by currentSetDataState   // <- Compose-observed
    }

    data class Completed(val startWorkoutTime: LocalDateTime) : WorkoutState()
    {
        var endWorkoutTime: LocalDateTime by mutableStateOf(LocalDateTime.now())
    }
}

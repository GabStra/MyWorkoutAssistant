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
    data class Preparing(
        val dataLoaded: Boolean
    ) : WorkoutState()

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
        var plateChangeResult: PlateCalculator.Companion.PlateChangeResult? = null,
        val streak: Int,
        val progressionState: ProgressionState?,
        val isWarmupSet: Boolean,
        val equipment: WeightLoadedEquipment?,
        val isUnilateral: Boolean = false,
        val intraSetTotal : UInt? = null,
        var intraSetCounter : UInt = 0u,
        val isCalibrationSet: Boolean = false, // Identifies if this Set is a calibration set execution
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // <-- observe changes
    }

    data class CalibrationLoadSelection(
        val exerciseId: UUID,
        val calibrationSet: com.gabstra.myworkoutassistant.shared.sets.Set, // The calibration set being configured
        val setIndex: UInt,
        val previousSetData: SetData?,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,
        val equipment: WeightLoadedEquipment?,
        val lowerBoundMaxHRPercent: Float? = null,
        val upperBoundMaxHRPercent: Float? = null,
        val currentBodyWeight: Double,
        val isUnilateral: Boolean = false
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // Observable set data
    }

    data class CalibrationRIRSelection(
        val exerciseId: UUID,
        val calibrationSet: com.gabstra.myworkoutassistant.shared.sets.Set, // The calibration set that was just executed
        val setIndex: UInt,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,
        val equipment: WeightLoadedEquipment?,
        val lowerBoundMaxHRPercent: Float? = null,
        val upperBoundMaxHRPercent: Float? = null,
        val currentBodyWeight: Double
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // Observable set data with RIR
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

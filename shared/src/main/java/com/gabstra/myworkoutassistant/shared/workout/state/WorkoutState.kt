package com.gabstra.myworkoutassistant.shared.workout.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import java.time.LocalDateTime
import java.util.UUID

enum class ProgressionState {
    DELOAD, RETRY, PROGRESS, FAILED
}

/**
 * Phase of the calibration flow for an exercise.
 * Used by [CalibrationContext] so callers can branch without scanning state.
 */
enum class CalibrationPhase {
    /** User is selecting load for the calibration set. */
    LOAD_SELECTION,
    /** User is executing the calibration set. */
    EXECUTING,
    /** User is entering RIR after completing the calibration set. */
    RIR_SELECTION
}

/**
 * Single source of truth for "we are in calibration" and where the calibration set lives.
 * Set when entering any calibration state; cleared when calibration is finished or navigated away.
 */
data class CalibrationContext(
    val exerciseId: UUID,
    val calibrationSetId: UUID,
    val phase: CalibrationPhase,
    /** Index in flattened allStates of the WorkoutState.Set with isCalibrationSet == true. Set when entering RIR_SELECTION. */
    val calibrationSetExecutionStateIndex: Int? = null
)

/**
 * Item under [WorkoutStateContainer.ExerciseState]: either a single state or a calibration block.
 * Only [ExerciseState] uses these; [SupersetState] keeps a flat list of [WorkoutState].
 */
sealed class ExerciseChildItem {
    /** A single workout state (Set, Rest, calibration state, etc.) — not inside a calibration block. */
    data class Normal(val state: WorkoutState) : ExerciseChildItem()

    /**
     * Calibration execution + RIR block. Allowed children: [WorkoutState.Set] with [WorkoutState.Set.isCalibrationSet],
     * [WorkoutState.CalibrationRIRSelection], and [WorkoutState.Rest].
     */
    data class CalibrationExecutionBlock(val childStates: MutableList<WorkoutState>) : ExerciseChildItem()

    /**
     * Load selection block. Allowed children: [WorkoutState.CalibrationLoadSelection], optional warm-up
     * [WorkoutState.Set], and [WorkoutState.Rest].
     */
    data class LoadSelectionBlock(val childStates: MutableList<WorkoutState>) : ExerciseChildItem()

    /**
     * Unilateral set block: same logical set executed twice (left/right), with optional rest in the middle.
     * childStates = [left Set, optional Rest, right Set] (2 or 3 elements). Both Set states share the same set.id.
     */
    data class UnilateralSetBlock(val childStates: MutableList<WorkoutState>) : ExerciseChildItem()
}

/**
 * Containers for organizing workout states by exercise or superset.
 * These are organizational only and NOT states themselves.
 */
sealed class WorkoutStateContainer {
    data class ExerciseState(
        val exerciseId: UUID,
        /** Each item is [ExerciseChildItem.Normal], a calibration/load block, or [ExerciseChildItem.UnilateralSetBlock]. Flatten for linear navigation. */
        val childItems: MutableList<ExerciseChildItem>
    ) : WorkoutStateContainer()

    data class SupersetState(
        val supersetId: UUID,
        val childStates: MutableList<WorkoutState>
    ) : WorkoutStateContainer()
}

/**
 * Items in the state sequence - can be either a container or a Rest state between exercises.
 */
sealed class WorkoutStateSequenceItem {
    data class Container(val container: WorkoutStateContainer) : WorkoutStateSequenceItem()
    data class RestBetweenExercises(val rest: WorkoutState.Rest) : WorkoutStateSequenceItem()
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
        val equipmentId: UUID?,
        val isUnilateral: Boolean = false,
        val intraSetTotal : UInt? = null,
        var intraSetCounter : UInt = 0u,
        val isCalibrationSet: Boolean = false, // Identifies if this Set is a calibration set execution
        val isCalibrationManagedWorkSet: Boolean = false, // Normal work set under an exercise that requires calibration
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // <-- observe changes
    }

    data class CalibrationLoadSelection(
        val exerciseId: UUID,
        val calibrationSet: com.gabstra.myworkoutassistant.shared.sets.Set, // The calibration set being configured
        val setIndex: UInt,
        val previousSetData: SetData?,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,
        val equipmentId: UUID?,
        val lowerBoundMaxHRPercent: Float? = null,
        val upperBoundMaxHRPercent: Float? = null,
        val currentBodyWeight: Double,
        val isUnilateral: Boolean = false,
        val isLoadConfirmed: Boolean = false
    ) : WorkoutState() {
        var currentSetData by currentSetDataState // Observable set data
    }

    data class CalibrationRIRSelection(
        val exerciseId: UUID,
        val calibrationSet: com.gabstra.myworkoutassistant.shared.sets.Set, // The calibration set that was just executed
        val setIndex: UInt,
        val currentSetDataState: androidx.compose.runtime.MutableState<SetData>,
        val equipmentId: UUID?,
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
        var nextState: WorkoutState? = null,
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


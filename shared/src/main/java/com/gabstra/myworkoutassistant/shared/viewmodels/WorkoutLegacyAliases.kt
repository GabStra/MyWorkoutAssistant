package com.gabstra.myworkoutassistant.shared.viewmodels

import com.gabstra.myworkoutassistant.shared.workout.calibration.applyCalibrationRIR as applyCalibrationRIRImpl
import com.gabstra.myworkoutassistant.shared.workout.calibration.confirmCalibrationLoad as confirmCalibrationLoadImpl

typealias ProgressionState = com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
typealias WorkoutState = com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
typealias WorkoutStateMachine = com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
typealias WorkoutStateContainer = com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
typealias WorkoutStateSequenceItem = com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
typealias ExerciseChildItem = com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
typealias WorkoutTimerService = com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
typealias WorkoutScreenState = com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState

fun WorkoutViewModel.applyCalibrationRIR(rir: Double, formBreaks: Boolean = false) {
    with(this) { applyCalibrationRIRImpl(rir, formBreaks) }
}

fun WorkoutViewModel.confirmCalibrationLoad() {
    with(this) { confirmCalibrationLoadImpl() }
}

package com.gabstra.myworkoutassistant.shared.workout.calibration

object CalibrationUiLabels {
    const val Calibration = "Calibration"
    const val Tbd = "TBD"
    const val SelectLoad = "Select Load"
    const val SetRir = "Set RIR"
    const val CompleteCalibrationSet = "Complete Calibration Set"
    const val RateRirAfterSet = "Rate your RIR after completing this set."
    const val ConfirmLoad = "Confirm Load"
    const val ConfirmLoadMessage = "Do you want to proceed with this load?"
    const val ConfirmRir = "Confirm RIR"
    const val ConfirmRirMessage = "Do you want to proceed with this RIR?"
    const val FormBreaksHint = "0 = Form Breaks"

    fun selectLoadInstruction(reps: Int): String = "Select load for $reps reps at 1-2 RIR"
}

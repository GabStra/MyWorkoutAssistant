package com.gabstra.myworkoutassistant.composables

object SetValueSemantics {
    // Value-level semantics used to target specific editable fields
    const val RepsValueDescription = "Reps value"
    const val WeightValueDescription = "Weight value"
    const val TimedDurationValueDescription = "Timed duration value"

    // Screen-level semantics used to detect the current set type from UI tests
    const val WeightSetTypeDescription = "Weight Set screen"
    const val BodyWeightSetTypeDescription = "BodyWeight Set screen"
    const val TimedDurationSetTypeDescription = "TimedDuration Set screen"
    const val EnduranceSetTypeDescription = "Endurance Set screen"
    const val RestSetTypeDescription = "Rest Set screen"
}

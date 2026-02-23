package com.gabstra.myworkoutassistant.shared.workout.rir

import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

/**
 * Returns a copy of this SetData with RIR stored in the appropriate field.
 * @param forAutoRegulation true to write [WeightSetData.autoRegulationRIR], false for [WeightSetData.calibrationRIR]
 */
fun SetData.withRIR(rir: Double, forAutoRegulation: Boolean): SetData = when (this) {
    is WeightSetData -> if (forAutoRegulation) copy(autoRegulationRIR = rir) else copy(calibrationRIR = rir)
    is BodyWeightSetData -> if (forAutoRegulation) copy(autoRegulationRIR = rir) else copy(calibrationRIR = rir)
    else -> this
}

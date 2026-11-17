package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.util.UUID

internal fun SetData.withLastWorkingLoad(set: Set, history: SetHistory): SetData? = when {
    this is WeightSetData && set is WeightSet && history.setData is WeightSetData ->
        copy(actualWeight = history.setData.actualWeight, volume = actualReps * history.setData.actualWeight)
    this is BodyWeightSetData && set is BodyWeightSet && history.setData is BodyWeightSetData ->
        copy(additionalWeight = history.setData.additionalWeight, volume = actualReps * (relativeBodyWeightInKg + history.setData.additionalWeight))
    else -> null
}

internal fun Set.withLastWorkingLoad(history: SetHistory): Set = when {
    this is WeightSet && history.setData is WeightSetData ->
        copy(weight = history.setData.actualWeight)
    this is BodyWeightSet && history.setData is BodyWeightSetData ->
        copy(additionalWeight = history.setData.additionalWeight)
    else -> this
}

internal fun Exercise.withLastWorkingLoads(historyBySetId: Map<UUID, SetHistory>): Exercise = copy(
    sets = sets.map { set -> historyBySetId[set.id]?.let(set::withLastWorkingLoad) ?: set }
)

internal fun Exercise.withHistoryPolicyLoads(historyBySetId: Map<UUID, SetHistory>): Exercise =
    if (loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD && !requiresLoadCalibration) {
        withLastWorkingLoads(historyBySetId)
    } else {
        this
    }

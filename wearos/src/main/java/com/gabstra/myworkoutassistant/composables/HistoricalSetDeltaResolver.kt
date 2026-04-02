package com.gabstra.myworkoutassistant.composables

import android.util.Log
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState

private const val TAG = "HistoricalSetDeltaResolver"

internal fun resolveHistoricalPreviousSetHistory(
    viewModel: AppViewModel,
    state: WorkoutState.Set
): SetHistory? {
    val historicalSetHistories = viewModel.getAllSetHistoriesByExerciseId(state.exerciseId)
    Log.d(
        TAG,
        "Resolving historical delta for exercise=${state.exerciseId}, set=${state.set.id}, " +
            "historicalCount=${historicalSetHistories.size}, historicalSetIds=${historicalSetHistories.map { it.setId }}"
    )
    val directMatch = historicalSetHistories.firstOrNull { it.setId == state.set.id }
    if (directMatch != null) {
        Log.d(
            TAG,
            "Resolved historical delta by direct setId match for exercise=${state.exerciseId}, " +
                "set=${state.set.id}, order=${directMatch.order}, historyId=${directMatch.id}"
        )
        return directMatch
    }

    if (!state.set.isHistoricalDeltaWorkSet()) {
        Log.d(
            TAG,
            "Skipping historical delta resolution for non-work set exercise=${state.exerciseId}, set=${state.set.id}"
        )
        return null
    }

    val currentWorkSetStates = viewModel.getAllExerciseWorkoutStates(state.exerciseId)
        .filter { it.set.isHistoricalDeltaWorkSet() }
        .distinctBy { it.set.id }
    val currentWorkSetIndex = currentWorkSetStates.indexOfFirst { it.set.id == state.set.id }
    if (currentWorkSetIndex < 0) {
        Log.w(
            TAG,
            "Unable to resolve current work-set index for exercise=${state.exerciseId}, set=${state.set.id}"
        )
        return null
    }

    val historicalWorkSets = historicalSetHistories
        .filter { it.setData.isHistoricalDeltaWorkSetData() }
        .sortedBy { it.order.toInt() }
        .distinctBy { it.setId }
    val fallback = historicalWorkSets.getOrNull(currentWorkSetIndex)

    Log.w(
        TAG,
        "Historical delta lookup fell back to work-set order for exercise=${state.exerciseId}, " +
            "currentSet=${state.set.id}, workSetIndex=$currentWorkSetIndex, " +
            "historicalSet=${fallback?.setId}, historicalCount=${historicalWorkSets.size}"
    )

    return fallback
}

private fun com.gabstra.myworkoutassistant.shared.sets.Set.isHistoricalDeltaWorkSet(): Boolean =
    when (this) {
        is WeightSet -> subCategory == SetSubCategory.WorkSet
        is BodyWeightSet -> subCategory == SetSubCategory.WorkSet
        else -> false
    }

private fun com.gabstra.myworkoutassistant.shared.setdata.SetData.isHistoricalDeltaWorkSetData(): Boolean =
    when (this) {
        is WeightSetData -> subCategory == SetSubCategory.WorkSet
        is BodyWeightSetData -> subCategory == SetSubCategory.WorkSet
        else -> false
    }

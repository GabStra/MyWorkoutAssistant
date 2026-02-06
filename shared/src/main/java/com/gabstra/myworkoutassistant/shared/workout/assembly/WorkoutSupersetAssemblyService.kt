package com.gabstra.myworkoutassistant.shared.workout.assembly

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

class WorkoutSupersetAssemblyService {
    fun assembleSupersetChildStates(
        superset: Superset,
        queues: List<MutableList<WorkoutState>>
    ): MutableList<WorkoutState> {
        val out = mutableListOf<WorkoutState>()

        var anyWarmups = true
        while (anyWarmups) {
            anyWarmups = false
            for (q in queues) {
                if (q.isEmpty() || q.first() !is WorkoutState.Set) continue
                val s = q.first() as WorkoutState.Set
                if (!isWarmupSet(s)) continue

                anyWarmups = true
                out.add(q.removeAt(0) as WorkoutState.Set)
                if (q.isNotEmpty() && q.first() is WorkoutState.Rest) {
                    q.removeAt(0)
                }
            }
        }

        for (q in queues) {
            while (q.isNotEmpty() && q.first() is WorkoutState.Rest) q.removeAt(0)
        }

        val rounds = queues.minOfOrNull { workCount(it) } ?: 0

        for (round in 0 until rounds) {
            for (q in queues) {
                while (q.isNotEmpty() && q.first() !is WorkoutState.Set) q.removeAt(0)
                if (q.isEmpty()) continue

                val s = q.first() as WorkoutState.Set
                if (s.isWarmupSet) {
                    q.removeAt(0)
                    continue
                }

                out.add(q.removeAt(0) as WorkoutState.Set)

                val restSec = superset.restSecondsByExercise[s.exerciseId] ?: 0
                if (restSec > 0) {
                    val restSet = RestSet(UUID.randomUUID(), restSec)
                    out.add(
                        WorkoutState.Rest(
                            set = restSet,
                            order = (round + 1).toUInt(),
                            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                            exerciseId = s.exerciseId
                        )
                    )
                }

                while (q.isNotEmpty() && q.first() is WorkoutState.Rest) q.removeAt(0)
            }
        }

        return cleanupRedundantRests(out)
    }

    private fun cleanupRedundantRests(states: List<WorkoutState>): MutableList<WorkoutState> {
        val cleaned = mutableListOf<WorkoutState>()
        for (state in states) {
            if (state is WorkoutState.Rest) {
                if (cleaned.isEmpty() || cleaned.last() is WorkoutState.Rest) continue
            }
            cleaned.add(state)
        }
        while (cleaned.firstOrNull() is WorkoutState.Rest) cleaned.removeAt(0)
        while (cleaned.lastOrNull() is WorkoutState.Rest) cleaned.removeAt(cleaned.lastIndex)
        return cleaned
    }

    private fun workCount(queue: MutableList<WorkoutState>): Int {
        return queue.count {
            if (it !is WorkoutState.Set) {
                false
            } else {
                !isWarmupSet(it)
            }
        }
    }

    private fun isWarmupSet(state: WorkoutState.Set): Boolean {
        return when (val set = state.set) {
            is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
            is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
            else -> false
        }
    }
}



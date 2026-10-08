package com.gabstra.myworkoutassistant.shared.setdata

/**
 * Execution state of a [com.gabstra.myworkoutassistant.shared.sets.RunningSet].
 * Elapsed time, distance, pace and route live in the running tracker and are
 * persisted as a RunningResult on the workout history; the set only records
 * whether the effort was completed.
 */
data class RunningSetData(
    val hasBeenExecuted: Boolean = false
) : SetData()

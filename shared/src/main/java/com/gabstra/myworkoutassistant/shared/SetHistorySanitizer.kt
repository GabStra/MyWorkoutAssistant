package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData

fun sanitizeRestPlacementInSetHistories(setHistories: List<SetHistory>): List<SetHistory> {
    if (setHistories.isEmpty()) return emptyList()

    val adjusted = mutableListOf<SetHistory>()
    for (setHistory in setHistories) {
        val isRest = setHistory.setData is RestSetData
        if (!isRest) {
            adjusted.add(setHistory)
            continue
        }

        if (adjusted.isNotEmpty() && adjusted.last().setData !is RestSetData) {
            adjusted.add(setHistory)
        }
    }

    if (adjusted.lastOrNull()?.setData is RestSetData) {
        adjusted.removeAt(adjusted.lastIndex)
    }

    return adjusted
}

fun sanitizeRestPlacementInSetHistoriesByWorkoutAndExercise(setHistories: List<SetHistory>): List<SetHistory> {
    if (setHistories.isEmpty()) return emptyList()

    val ordering = compareBy<SetHistory>(
        { it.executionSequence == null },
        { it.executionSequence },
        { it.startTime },
        { it.order }
    )

    return setHistories
        .groupBy { it.workoutHistoryId to it.exerciseId }
        .values
        .flatMap { histories ->
            sanitizeRestPlacementInSetHistories(histories.sortedWith(ordering))
        }
}

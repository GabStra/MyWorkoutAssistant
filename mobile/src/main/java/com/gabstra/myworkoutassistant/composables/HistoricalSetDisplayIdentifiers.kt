package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import java.util.UUID

internal class HistoricalSetDisplayIdentifierResolver(
    setHistories: List<SetHistory>,
) {
    private val identifierCounter = SetRowIdentifierCounter()
    private val baseIdentifierBySetId = mutableMapOf<UUID, String>()
    private val totalOccurrenceCountBySetId = setHistories
        .groupingBy(SetHistory::setId)
        .eachCount()
    private val seenOccurrenceCountBySetId = mutableMapOf<UUID, Int>()

    fun resolve(setHistory: SetHistory): String {
        val baseIdentifier = baseIdentifierBySetId.getOrPut(setHistory.setId) {
            identifierCounter.nextIdentifier(resolveSetSubCategory(setHistory.setData))
        }
        val totalOccurrences = totalOccurrenceCountBySetId[setHistory.setId] ?: return baseIdentifier
        if (totalOccurrences != 2) {
            return baseIdentifier
        }

        val sideExecutionIndex = seenOccurrenceCountBySetId
            .getOrDefault(setHistory.setId, 0) + 1
        seenOccurrenceCountBySetId[setHistory.setId] = sideExecutionIndex

        val sideBadge = buildUnilateralSideLabel(
            sideIndex = sideExecutionIndex.toUInt(),
            intraSetTotal = totalOccurrences.toUInt(),
        ) ?: return baseIdentifier

        return "$baseIdentifier$sideBadge"
    }
}

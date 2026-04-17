package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.gabstra.myworkoutassistant.shared.FilterRange

/**
 * Resolves the active date filter: uses [historyFilterRange] when the parent owns state,
 * otherwise keeps an internal [FilterRange.ALL]-based selection.
 */
@Composable
fun rememberHistoryFilterRangeSelection(
    historyFilterRange: FilterRange?,
    onHistoryFilterRangeChange: ((FilterRange) -> Unit)?,
): Pair<FilterRange, (FilterRange) -> Unit> {
    var internalHistoryFilterRange by remember { mutableStateOf(FilterRange.ALL) }
    val selectedRange = historyFilterRange ?: internalHistoryFilterRange
    val onRangeSelected = remember(onHistoryFilterRangeChange) {
        { newRange: FilterRange ->
            if (onHistoryFilterRangeChange != null) {
                onHistoryFilterRangeChange(newRange)
            } else {
                internalHistoryFilterRange = newRange
            }
        }
    }
    return selectedRange to onRangeSelected
}

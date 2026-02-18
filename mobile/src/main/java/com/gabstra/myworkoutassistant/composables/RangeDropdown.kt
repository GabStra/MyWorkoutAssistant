package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier

enum class FilterRange {
    LAST_WEEK,
    LAST_7_DAYS,
    LAST_30_DAYS,
    THIS_MONTH,
    LAST_3_MONTHS,
    ALL
}
@Composable
fun RangeDropdown(
    selectedRange: FilterRange,
    onSelectedRangeChange: (FilterRange) -> Unit
) {
    val items = remember {
        listOf(
            StandardFilterDropdownItem(FilterRange.LAST_WEEK, "Last week"),
            //StandardFilterDropdownItem(FilterRange.LAST_7_DAYS, "Last 7 days"),
            //StandardFilterDropdownItem(FilterRange.LAST_30_DAYS, "Last 30 days"),
            StandardFilterDropdownItem(FilterRange.THIS_MONTH, "This month"),
            StandardFilterDropdownItem(FilterRange.LAST_3_MONTHS, "Last 3 months"),
            StandardFilterDropdownItem(FilterRange.ALL, "All")
        )
    }

    val selectedLabel = remember(selectedRange) {
        items.firstOrNull { it.value == selectedRange }?.label ?: "All"
    }

    StandardFilterDropdown(
        label = "Date range:",
        selectedText = selectedLabel,
        items = items,
        onItemSelected = onSelectedRangeChange,
        modifier = Modifier
            .fillMaxWidth(),
        isItemSelected = { it == selectedRange }
    )
}

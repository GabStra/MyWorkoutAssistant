package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.shared.FilterRange

@Composable
fun FilterRange.historyDisplayLabel(): String = stringResource(
    when (this) {
        FilterRange.LAST_WEEK -> R.string.loc_last_week
        FilterRange.LAST_7_DAYS -> R.string.loc_last_7_days
        FilterRange.LAST_30_DAYS -> R.string.loc_last_30_days
        FilterRange.THIS_MONTH -> R.string.loc_this_month
        FilterRange.LAST_3_MONTHS -> R.string.loc_last_3_months
        FilterRange.ALL -> R.string.common_all
    }
)

@Composable
private fun FilterRange.historyDropdownLabel(): String = stringResource(
    when (this) {
        FilterRange.LAST_WEEK -> R.string.loc_last_week
        FilterRange.LAST_7_DAYS -> R.string.loc_last_7_days
        FilterRange.LAST_30_DAYS -> R.string.loc_last_30_days
        FilterRange.THIS_MONTH -> R.string.loc_this_month
        FilterRange.LAST_3_MONTHS -> R.string.loc_last_3_months
        FilterRange.ALL -> R.string.common_all
    }
)

@Composable
fun RangeDropdown(
    selectedRange: FilterRange,
    onSelectedRangeChange: (FilterRange) -> Unit
) {
    val items = listOf(FilterRange.LAST_WEEK, FilterRange.THIS_MONTH, FilterRange.LAST_3_MONTHS, FilterRange.ALL)
        .map { range -> StandardFilterDropdownItem(range, range.historyDropdownLabel()) }

    val selectedLabel = selectedRange.historyDisplayLabel()

    StandardFilterDropdown(
        label = stringResource(R.string.loc_date_range_label),
        selectedText = selectedLabel,
        items = items,
        onItemSelected = onSelectedRangeChange,
        selectedValue = selectedRange,
        modifier = Modifier
            .fillMaxWidth().padding(horizontal = Spacing.md),
        isItemSelected = { it == selectedRange },
        compact = true
    )
}

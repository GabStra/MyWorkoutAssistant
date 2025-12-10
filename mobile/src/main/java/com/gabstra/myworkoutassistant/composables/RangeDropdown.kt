package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

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
    var expanded by remember { mutableStateOf(false) }
    val label = when (selectedRange) {
        FilterRange.LAST_WEEK     -> "Last week"
        FilterRange.THIS_MONTH    -> "This month"
        FilterRange.LAST_3_MONTHS -> "Last 3 months"
        FilterRange.ALL           -> "All"
        FilterRange.LAST_7_DAYS -> "Last 7 days"
        FilterRange.LAST_30_DAYS -> "Last 30 days"
    }

    Row(
        modifier = Modifier
        .fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    )
    {
        Text("Date range:")
        Spacer(Modifier.width(2.5.dp))
        Box {
            TextButton(onClick = { expanded = true }) { Text(label) }
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                modifier = Modifier.background(MaterialTheme.colorScheme.surface),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
            ) {
                DropdownMenuItem(text = { Text("Last 7 days") }, onClick = {
                    onSelectedRangeChange(FilterRange.LAST_7_DAYS); expanded = false
                })
                DropdownMenuItem(text = { Text("Last 30 days") }, onClick = {
                    onSelectedRangeChange(FilterRange.LAST_30_DAYS); expanded = false
                })
                DropdownMenuItem(text = { Text("Last week") }, onClick = {
                    onSelectedRangeChange(FilterRange.LAST_WEEK); expanded = false
                })
                DropdownMenuItem(text = { Text("Last month") }, onClick = {
                    onSelectedRangeChange(FilterRange.THIS_MONTH); expanded = false
                })
                DropdownMenuItem(text = { Text("Last three months") }, onClick = {
                    onSelectedRangeChange(FilterRange.LAST_3_MONTHS); expanded = false
                })
                DropdownMenuItem(text = { Text("All") }, onClick = {
                    onSelectedRangeChange(FilterRange.ALL); expanded = false
                })
            }
        }
    }


}

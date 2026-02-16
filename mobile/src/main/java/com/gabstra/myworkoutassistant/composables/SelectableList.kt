package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.gabstra.myworkoutassistant.Spacing

@Composable
fun <T, K> SelectableList(
    selectionMode: Boolean,
    modifier: Modifier,
    items: List<T>,
    selectedIds: Set<K>,
    keySelector: (T) -> K,
    itemContent: @Composable (T) -> Unit,
    onItemSelectionToggle: ((T) -> Unit)? = null,
) {
    Column(modifier = modifier) {
        for (item in items) {
            SelectableListRow(
                item = item,
                selectionMode = selectionMode,
                isSelected = selectedIds.contains(keySelector(item)),
                onItemSelectionToggle = onItemSelectionToggle,
                itemContent = itemContent
            )
        }
    }
}

@Composable
private fun <T> SelectableListRow(
    item: T,
    selectionMode: Boolean,
    isSelected: Boolean,
    onItemSelectionToggle: ((T) -> Unit)?,
    itemContent: @Composable (T) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(Spacing.sm),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (selectionMode) {
            Box(
                modifier = Modifier.width(Spacing.xl),
                contentAlignment = Alignment.Center
            ) {
                Checkbox(
                    checked = isSelected,
                    onCheckedChange = { onItemSelectionToggle?.invoke(item) },
                    colors = CheckboxDefaults.colors().copy(
                        checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                    )
                )
            }

            Spacer(modifier = Modifier.width(Spacing.sm))
        }

        Box(modifier = Modifier.fillMaxWidth()) {
            itemContent(item)
        }
    }
}

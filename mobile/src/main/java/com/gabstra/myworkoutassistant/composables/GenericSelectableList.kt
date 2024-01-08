package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun <T> GenericSelectableList(
    it: PaddingValues? = null,
    items: List<T>,
    selectedItems: List<T>,
    isSelectionModeActive: Boolean,
    onItemClick: (T) -> Unit,
    itemContent: @Composable (T) -> Unit,
    onEnableSelection: () -> Unit,
    onDisableSelection: () -> Unit,
    onSelectionChange: (List<T>) -> Unit,
) {
    SelectableList(
        isSelectionModeActive,
        modifier = Modifier
            .fillMaxSize()
            .padding(it ?: PaddingValues(0.dp))
            .clickable {
                if (isSelectionModeActive) {
                    onDisableSelection()
                    onSelectionChange(emptyList())
                }
            },
        items = items,
        selection = selectedItems,
        onSelectionChange = { newSelection ->  onSelectionChange(newSelection) },
        itemContent = { item ->
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .combinedClickable(
                        onClick = {
                            if (isSelectionModeActive) {
                                val newSelection = if (selectedItems.any { it === item }) {
                                    selectedItems.filter{ it !== item }
                                } else {
                                    selectedItems + item
                                }
                                onSelectionChange(newSelection)
                            } else {
                                onItemClick(item)
                            }
                        },
                        onLongClick = { if (!isSelectionModeActive) onEnableSelection() }
                    ),
            ) {
                itemContent(item)
            }
        },
    )
}
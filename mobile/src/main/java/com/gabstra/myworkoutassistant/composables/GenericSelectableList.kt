package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import kotlin.math.abs

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
    onOrderChange: (List<T>) -> Unit
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
            val offsetY = remember { mutableFloatStateOf(0f) }

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
                    )
                    .pointerInput(item) {
                        detectDragGestures(onDrag = { _, dragAmount ->
                            if (!isSelectionModeActive) {
                                val dragAmountY = dragAmount.y
                                offsetY.value += dragAmountY
                            }
                        }, onDragEnd = {
                            if (!isSelectionModeActive) {
                                val oldIndex = items.indexOf(item)
                                val itemHeightPx = with(density) { 70.dp.toPx() }
                                val newIndex = (oldIndex + (offsetY.value / itemHeightPx).toInt()).coerceIn(items.indices)

                                if (newIndex != oldIndex) {
                                    val newList = items.toMutableList().apply {
                                        // Remove the item from its old position and add it to the new position
                                        val movedItem = removeAt(oldIndex)
                                        add(newIndex, movedItem)
                                    }
                                    onOrderChange(newList.toList()) // Invoke the onOrderChange callback
                                }
                                offsetY.value = 0f // Reset the offset when the drag ends
                            }
                        })
                    }
                    .graphicsLayer {
                        translationY = offsetY.value
                    }
            ) {
                itemContent(item)
            }
        },
    )
}
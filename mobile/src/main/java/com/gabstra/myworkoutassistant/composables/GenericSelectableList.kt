package com.gabstra.myworkoutassistant.composables

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Card
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableFloatState
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.abs

fun findNewIndex(newCenterY: Float, currentIndex: Int, centerPointByIndex: MutableMap<Int, Pair<Float, Float>>): Int {
    val minDiff = 60f // Adjust this threshold as needed
    val potentialIndices = centerPointByIndex.keys.filter { it != currentIndex }

    // Find the index with the smallest Y-coordinate difference within the minDiff threshold
    return potentialIndices.minByOrNull { index ->
        abs(centerPointByIndex[index]!!.second - newCenterY)
    }?.takeIf {
        abs(centerPointByIndex[it]!!.second - newCenterY) <= minDiff
    } ?: currentIndex
}


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
    onOrderChange: (List<T>) -> Unit,
    isDragDisabled: Boolean = false
) {
    val centerPointByIndex = remember { mutableMapOf<Int, Pair<Float, Float>>() }
    val itemToRenderByIndex = remember { mutableStateOf(mutableMapOf<Int, @Composable () -> Unit>()) }
    val draggedItem = remember { mutableStateOf<T?>(null) }
    val tempDragChanges = remember { mutableMapOf<Int, T>() }
    val listState = rememberLazyListState() // LazyListState for controlling scrolling

    LaunchedEffect(draggedItem.value) {
        while (draggedItem.value != null) {
            val draggedItemIndex = items.indexOf(draggedItem.value)
            if (draggedItemIndex != -1) {
                val currentCenterY = centerPointByIndex[draggedItemIndex]?.second ?: 0f
                val offsetY = listState.firstVisibleItemScrollOffset
                val visibleAreaStart = listState.layoutInfo.viewportStartOffset
                val visibleAreaEnd = listState.layoutInfo.viewportEndOffset
                val visibleAreaHeight = visibleAreaEnd - visibleAreaStart
                val scrollThreshold = visibleAreaHeight / 10 // Scroll threshold at the edges

                when {
                    currentCenterY < visibleAreaStart + scrollThreshold -> {
                        listState.scrollBy(-20f) // Scroll up when dragging near the top
                    }
                    currentCenterY > visibleAreaEnd - scrollThreshold -> {
                        listState.scrollBy(20f) // Scroll down when dragging near the bottom
                    }
                }
            }
            delay(16) // Control the scroll speed, approx. 60 frames per second
        }
    }


    // Conditional modifier for dragging
    fun Modifier.conditionalPointerInput(item: T,index:Int,offsetY: MutableFloatState): Modifier =
        if (isSelectionModeActive || isDragDisabled) {
            this // If dragging is disabled, return the modifier as-is
        } else {
            this.pointerInput(item) {

                var currentIndex = index

                detectDragGestures(
                    onDragStart = {
                        draggedItem.value = item
                        currentIndex = index

                        for ((i, value) in items.withIndex()) {
                            tempDragChanges[i] = value
                        }
                    },
                    onDrag = { _, dragAmount ->
                        offsetY.floatValue += dragAmount.y

                        val currentCenterY = centerPointByIndex[index]!!.second + offsetY.floatValue
                        val newIndex = findNewIndex(currentCenterY, currentIndex, centerPointByIndex)

                        if(newIndex != currentIndex){
                            val newItemAtIndex = tempDragChanges[newIndex]!!
                            tempDragChanges[currentIndex] = newItemAtIndex

                            itemToRenderByIndex.value =  itemToRenderByIndex.value .toMutableMap().apply {
                                val capturedIndex = currentIndex

                                if(newIndex == index) this.remove(capturedIndex)
                                else {
                                    this[capturedIndex] = {
                                        val itemToDisplay = newItemAtIndex
                                        Card(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(5.dp)
                                        ){
                                            itemContent(itemToDisplay)
                                        }
                                    }
                                }

                                this[newIndex] = {
                                    Box(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(50.dp),
                                    )
                                }
                            }

                            tempDragChanges[newIndex] = item
                            currentIndex = newIndex
                        }
                    }, onDragEnd = {
                        itemToRenderByIndex.value =  itemToRenderByIndex.value .toMutableMap().apply {
                            this.clear()
                        }
                        val newList = items.toMutableList().apply {
                            tempDragChanges.forEach { (oldIndex, newItem) ->
                                val newIndex = items.indexOf(newItem)
                                if (newIndex in indices) {
                                    set(oldIndex, newItem)
                                }
                            }
                        }
                        onOrderChange(newList) // Invoke the onOrderChange callback

                        tempDragChanges.clear() // Clear temporary changes
                        offsetY.floatValue = 0f // Reset the offset
                        draggedItem.value = null
                    },
                    onDragCancel = {
                        // Handle drag cancellation
                        itemToRenderByIndex.value = itemToRenderByIndex.value.toMutableMap().apply {
                            this.clear()
                        }
                        tempDragChanges.clear()
                        offsetY.floatValue = 0f
                        draggedItem.value = null
                    }
                )
            }
        }

    val interactionSource = remember { MutableInteractionSource() }
    SelectableList(
        isSelectionModeActive,
        modifier = Modifier
            .fillMaxSize()
            .padding(it ?: PaddingValues(0.dp))
            .clickable(
                interactionSource = interactionSource,
                indication = null
            ) {
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
            val index = items.indexOf(item)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { coordinates ->
                        if (centerPointByIndex.containsKey(index)) return@onGloballyPositioned

                        val size = coordinates.size
                        val positionInRoot = coordinates.positionInRoot()

                        // Calculate the center based on size and position
                        val centerX = positionInRoot.x + size.width / 2
                        val centerY = positionInRoot.y + size.height / 2

                        centerPointByIndex[index] = centerX to centerY
                    }
                ,
                contentAlignment = Alignment.Center
            ){

                if(itemToRenderByIndex.value.containsKey(index)){
                    itemToRenderByIndex.value[index]!!.invoke()
                }

                if(draggedItem.value === item || !itemToRenderByIndex.value.containsKey(index)) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 5.dp)
                            .combinedClickable(
                                onClick = {
                                    if (isSelectionModeActive) {
                                        val newSelection = if (selectedItems.any { it === item }) {
                                            selectedItems.filter { it !== item }
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
                            .conditionalPointerInput(item, index, offsetY)
                            .graphicsLayer {
                                translationY = offsetY.floatValue
                            }
                    ) {
                        itemContent(item)
                    }
                }
            }
        },
        listState
    )
}
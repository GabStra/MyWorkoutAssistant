package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun <T> DetailScreen(
    title: String,
    items: List<T>,
    isSelected: (T) -> Boolean,
    onGoBack: () -> Unit,
    onSettingsClick: () -> Unit,
    onAddClick: () -> Unit,
    onUpdateItems: ((List<T>) -> Unit)? = null,
    itemContent: @Composable (T) -> Unit,
    onItemEdit: (T) -> Unit,
    onItemLongPress: () -> Unit,
    isAddButtonVisible: Boolean,
    bottomBarActions: @Composable() (RowScope.() -> Unit)
) {
    var selectionMode by remember { mutableStateOf(false) }
    var selectedItems by remember { mutableStateOf(listOf<T>()) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = onSettingsClick ) {
                        Icon(imageVector = Icons.Default.Settings, contentDescription = "Settings")
                    }
                }
            )
        },
        bottomBar = {
            if (selectedItems.isNotEmpty()) BottomAppBar(
                actions = {
                    if(onUpdateItems != null){
                        IconButton(onClick = {
                            onUpdateItems(items.filterNot { it in selectedItems })
                            selectedItems = emptyList()
                            selectionMode = false
                        }) {
                            Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                        }
                    }

                    // Add more actions as necessary
                }
            )
        },
        floatingActionButton = {
            if (isAddButtonVisible && selectedItems.isEmpty())
                FloatingActionButton(onClick =  onAddClick) {
                    Icon(imageVector = Icons.Default.Add, contentDescription = null)
                }
        }
    ) {
        if (items.isEmpty()) {
            Text(modifier = Modifier.fillMaxSize(), text = "No items available", textAlign = TextAlign.Center)
        } else {
            SelectableList(
                selectionMode,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .clickable {
                        if (selectionMode) {
                            selectionMode = false
                            selectedItems= emptyList()
                        }
                    },
                items = items,
                selection = selectedItems,
                onSelectionChange = { newSelection -> selectedItems = newSelection },
                itemContent = { item ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (isSelected(item)) 1f else 0.4f)
                            .combinedClickable(
                                onClick = { if (selectionMode) onItemEdit(item) },
                                onLongClick = onItemLongPress
                            ),
                    ) {
                        itemContent(item)
                    }
                },
            )
        }
    }
}

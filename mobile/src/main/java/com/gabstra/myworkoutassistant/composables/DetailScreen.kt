package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

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
                title = { Text(modifier = Modifier.fillMaxWidth(),text= title, textAlign = TextAlign.Center) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            tint = MaterialTheme.colorScheme.onBackground
                        )
                    }
                },
                actions = {
                    IconButton(onClick = onSettingsClick) {
                        Icon(
                            imageVector = Icons.Default.Settings,
                            contentDescription = "Settings",
                            tint = MaterialTheme.colorScheme.onBackground
                        )
                    }
                }
            )
        },
        bottomBar = {
            if (selectedItems.isNotEmpty()) {
                Column {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    BottomAppBar(
                        contentPadding = PaddingValues(0.dp),
                        containerColor = Color.Transparent,
                        actions = {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier
                                        .width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        selectedItems = emptyList()
                                        selectionMode = false
                                    }) {
                                        Icon(imageVector = Icons.Default.Close, contentDescription = "Cancel selection")
                                    }
                                    Text(
                                        "Cancel selection",
                                        style = MaterialTheme.typography.labelSmall,
                                        textAlign = TextAlign.Center
                                    )
                                }
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier
                                        .width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        selectedItems = items
                                    }) {
                                        Icon(imageVector = Icons.Filled.CheckBox, contentDescription = "Select all")
                                    }
                                    Text(
                                        "Select all",
                                        style = MaterialTheme.typography.labelSmall,
                                        textAlign = TextAlign.Center
                                    )
                                }
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier
                                        .width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        selectedItems = emptyList()
                                    }) {
                                        Icon(imageVector = Icons.Filled.CheckBoxOutlineBlank, contentDescription = "Deselect all")
                                    }
                                    Text(
                                        "Deselect all",
                                        style = MaterialTheme.typography.labelSmall,
                                        textAlign = TextAlign.Center
                                    )
                                }
                                Box(
                                    modifier = Modifier.fillMaxHeight(),
                                    contentAlignment = Alignment.Center
                                ) {
                                    VerticalDivider(
                                        modifier = Modifier.height(48.dp),
                                        color = MaterialTheme.colorScheme.outlineVariant
                                    )
                                }
                                if (onUpdateItems != null) {
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier
                                            .width(56.dp)
                                    ) {
                                        IconButton(onClick = {
                                            onUpdateItems(items.filterNot { it in selectedItems })
                                            selectedItems = emptyList()
                                            selectionMode = false
                                        }) {
                                            Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                                        }
                                        Text(
                                            "Delete",
                                            style = MaterialTheme.typography.labelSmall,
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                }
                            }
                        }
                    )
                }
            }
        },
        floatingActionButton = {
            if (isAddButtonVisible && selectedItems.isEmpty())
                FloatingActionButton(
                    containerColor = MaterialTheme.colorScheme.primary,
                    onClick = onAddClick
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.background
                    )
                }
        }
    ) {
        if (items.isEmpty()) {
            Text(
                modifier = Modifier.fillMaxSize(),
                text = "No items available",
                textAlign = TextAlign.Center
            )
        } else {
            SelectableList(
                selectionMode,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .clickable {
                        if (selectionMode) {
                            selectionMode = false
                            selectedItems = emptyList()
                        }
                    },
                items = items,
                selection = selectedItems,
                onItemSelectionToggle = { item ->
                    selectedItems = if (selectedItems.any { it === item }) {
                        selectedItems.filter { it !== item }
                    } else {
                        selectedItems + item
                    }
                },
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


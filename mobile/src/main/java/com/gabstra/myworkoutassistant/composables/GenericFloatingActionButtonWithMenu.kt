package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

data class MenuItem(
    val label: String,
    val onClick: () -> Unit
)

@Composable
fun GenericFloatingActionButtonWithMenu(
    menuItems: List<MenuItem>,
    fabIcon: @Composable () -> Unit
) {
    var showMenu by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.End
    ) {
        // Dropdown Menu
        DropdownMenu(
            expanded = showMenu,
            onDismissRequest = { showMenu = false },
            modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
        ) {
            menuItems.forEach { menuItem ->
                DropdownMenuItem(
                    onClick = {
                        menuItem.onClick()
                        showMenu = false
                    },
                    text = { Text(menuItem.label) }
                )
            }
        }
        Spacer(modifier = Modifier.height(10.dp))
        // Floating Action Button
        FloatingActionButton(
            containerColor = MaterialTheme.colorScheme.primary,
            onClick = { showMenu = !showMenu }
        ) {
            fabIcon()
        }
    }






}
package com.gabstra.myworkoutassistant.composables

import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue

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

    // Floating Action Button
    FloatingActionButton(onClick = { showMenu = true }) {
        fabIcon()
    }

    // Dropdown Menu
    DropdownMenu(
        expanded = showMenu,
        onDismissRequest = { showMenu = false }
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
}
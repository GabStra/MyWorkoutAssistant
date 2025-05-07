package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.ui.theme.MediumGray

data class MenuItem(
    val label: String,
    val onClick: () -> Unit
)

@Composable
fun GenericButtonWithMenu(
    menuItems: List<MenuItem>,
    content: @Composable () -> Unit,
    enabled: Boolean = true
) {
    var showMenu by remember { mutableStateOf(false) }

    Column{
        DropdownMenu(
            expanded = showMenu,
            onDismissRequest = { showMenu = false },
            modifier = Modifier.background(MaterialTheme.colorScheme.background),
            border = BorderStroke(1.dp, MediumGray)
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
        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = { showMenu = !showMenu },
            enabled = enabled
        ) {
            content()
        }
    }
}
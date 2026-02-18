package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem

@Composable
fun <T> GenericDropdownMenu(
    items: List<T>,
    selectedItem: T,
    onItemSelected: (T) -> Unit,
    itemLabel: (T) -> String
) {
    var showMenu by remember { mutableStateOf(false) }

    Column {
        AppPrimaryButton(
            text = itemLabel(selectedItem),
            onClick = { showMenu = true }
        )

        AppDropdownMenu(
            expanded = showMenu,
            onDismissRequest = { showMenu = false }
        ) {
            items.forEach { item ->
                AppDropdownMenuItem(
                    text = {
                        Text(itemLabel(item))
                    },
                    onClick = {
                        onItemSelected(item)
                        showMenu = false
                    }
                )
            }
        }
    }
}


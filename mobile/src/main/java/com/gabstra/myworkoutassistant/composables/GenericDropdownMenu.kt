package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.font.FontWeight
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
            items.forEachIndexed { index, item ->
                AppDropdownMenuItem(
                    text = {
                        Text(
                            text = itemLabel(item),
                            fontWeight = FontWeight.Normal
                        )
                    },
                    onClick = {
                        onItemSelected(item)
                        showMenu = false
                    }
                )
                if (index < items.lastIndex) {
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)
                    )
                }
            }
        }
    }
}


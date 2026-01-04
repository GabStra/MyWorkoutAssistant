package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing

@Composable
fun <T> SelectableList(
    selectionMode: Boolean ,
    modifier : Modifier,
    items: List<T>,
    selection: List<T>,
    itemContent: @Composable (T) -> Unit,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(if(selectionMode)  5.dp else 0.dp)
    ) {
        for (item in items) {
            val isSelected = selection.any { it === item }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (isSelected) {
                            Modifier
                                .border(1.dp, MaterialTheme.colorScheme.primary)
                                .background(
                                    MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
                                )
                        } else {
                            Modifier
                        }
                    )
                    .padding(Spacing.sm),
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Checkbox container - only allocated when selection mode is active
                if (selectionMode) {
                    Box(
                        modifier = Modifier.width(Spacing.xl),
                        contentAlignment = Alignment.Center
                    ) {
                        Checkbox(
                            checked = isSelected,
                            onCheckedChange = null, // Selection handled by parent click
                            colors = CheckboxDefaults.colors().copy(
                                checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                                uncheckedBorderColor = MaterialTheme.colorScheme.primary
                            )
                        )
                    }

                    Spacer(modifier = Modifier.width(Spacing.sm))
                }

                // Item content
                Box(modifier = Modifier.fillMaxWidth()) {
                    itemContent(item)
                }
            }
        }
    }
}


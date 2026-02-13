package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.gabstra.myworkoutassistant.Spacing
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.font.FontWeight
import java.util.Locale

@Composable
fun WeightPickerDialog(
    combinations: List<Pair<Double, String>>,
    filter: String,
    selectedWeight: Double? = null,
    onFilterChange: (String) -> Unit,
    onDismissRequest: () -> Unit,
    onSelect: (Double) -> Unit
) {
    StandardDialog(
        onDismissRequest = onDismissRequest,
        title = "Available Weights",
        body = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                if (selectedWeight != null) {
                    Text(
                        text = "Current: ${String.format(Locale.US, "%.2f kg", selectedWeight)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                Text(
                    text = "${combinations.size} available options",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                OutlinedTextField(
                    value = filter,
                    onValueChange = onFilterChange,
                    label = { Text("Filter") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                if (combinations.isEmpty()) {
                    StyledCard(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = Spacing.xs)
                    ) {
                        Text(
                            text = "No weights match this filter",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.md)
                        )
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 360.dp),
                        verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                    ) {
                        items(
                            items = combinations,
                            key = { (weight, label) -> weight.hashCode() xor label.hashCode() }
                        ) { (weight, label) ->
                            val isSelected = selectedWeight != null && selectedWeight == weight
                            val weightText = String.format(Locale.US, "%.2f kg", weight)

                            val borderColor = if (isSelected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.outlineVariant
                            }
                            val backgroundColor = if (isSelected) {
                                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.24f)
                            } else {
                                MaterialTheme.colorScheme.surface
                            }

                            StyledCard(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        onSelect(weight)
                                        onDismissRequest()
                                    },
                                borderColor = borderColor,
                                backgroundColor = backgroundColor
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .heightIn(min = 48.dp)
                                        .padding(horizontal = Spacing.md, vertical = Spacing.sm),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(
                                        modifier = Modifier.weight(1f),
                                        verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                                    ) {
                                        Text(
                                            text = label,
                                            style = MaterialTheme.typography.bodyMedium,
                                            fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                                            color = MaterialTheme.colorScheme.onSurface
                                        )
                                        Text(
                                            text = weightText,
                                            style = MaterialTheme.typography.labelMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }

                                    if (isSelected) {
                                        Spacer(modifier = Modifier.width(Spacing.sm))
                                        Icon(
                                            imageVector = Icons.Default.Check,
                                            contentDescription = "Selected weight",
                                            tint = MaterialTheme.colorScheme.primary
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        showConfirm = false,
        showDismiss = false
    )
}

package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R
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
        title = stringResource(R.string.picker_available_weights_title),
        body = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                if (selectedWeight != null) {
                    Text(
                        text = stringResource(
                            R.string.picker_current_weight,
                            String.format(Locale.US, "%.2f", selectedWeight)
                        ),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.tertiaryContent
                    )
                }

                Text(
                    text = stringResource(R.string.picker_available_options, combinations.size),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiaryContent
                )

                OutlinedTextField(
                    value = filter,
                    onValueChange = onFilterChange,
                    label = { Text(stringResource(R.string.picker_filter)) },
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
                            text = stringResource(R.string.picker_no_weights_match),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.md)
                        )
                    }
                } else {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = Spacing.xs),
                        verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                    ) {
                        combinations.forEach { (weight, label) ->
                            val isSelected = selectedWeight != null && selectedWeight == weight
                            val weightText = stringResource(
                                R.string.picker_weight_kg,
                                String.format(Locale.US, "%.2f", weight)
                            )
                            val showsDistinctWeightText = label.trim() != weightText

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
                                        if (showsDistinctWeightText) {
                                            Text(
                                                text = weightText,
                                                style = MaterialTheme.typography.labelMedium,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant
                                            )
                                        }
                                    }

                                    if (isSelected) {
                                        Spacer(modifier = Modifier.width(Spacing.sm))
                                        Icon(
                                            imageVector = Icons.Default.Check,
                                            contentDescription = stringResource(R.string.picker_selected_weight_cd),
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
        showDismiss = true,
        dismissText = stringResource(R.string.common_close),
        onDismissButton = onDismissRequest
    )
}

package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp

data class StandardFilterDropdownItem<T>(
    val value: T,
    val label: String
)

@Composable
fun <T> StandardFilterDropdown(
    label: String,
    selectedText: String,
    items: List<StandardFilterDropdownItem<T>>,
    onItemSelected: (T) -> Unit,
    modifier: Modifier = Modifier,
    isItemSelected: (T) -> Boolean = { false },
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }
    val fieldTextStyle = MaterialTheme.typography.bodyLarge

    Box(modifier = modifier) {
        Box(modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = selectedText,
                onValueChange = { },
                readOnly = true,
                enabled = enabled,
                singleLine = true,
                textStyle = fieldTextStyle.copy(color = Color.Transparent),
                label = {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.labelLarge
                    )
                },
                trailingIcon = {
                    Icon(
                        imageVector = Icons.Default.ExpandMore,
                        contentDescription = null
                    )
                },
                modifier = Modifier.fillMaxWidth()
            )

            Text(
                text = selectedText,
                style = fieldTextStyle,
                maxLines = 1,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 16.dp, top = 6.dp, end = 48.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE)
            )

            Box(
                modifier = Modifier
                    .matchParentSize()
                    .clickable(enabled = enabled) { expanded = true }
            )

            AppDropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
                    .heightIn(max = 320.dp),
                offset = DpOffset(0.dp, 8.dp)
            ) {
                items.forEachIndexed { index, item ->
                    val selected = isItemSelected(item.value)

                    AppDropdownMenuItem(
                        text = {
                            Text(
                                text = item.label,
                                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
                            )
                        },
                        trailingIcon = if (selected) {
                            {
                                Icon(
                                    imageVector = Icons.Default.Check,
                                    contentDescription = null
                                )
                            }
                        } else {
                            null
                        },
                        onClick = {
                            expanded = false
                            onItemSelected(item.value)
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
}

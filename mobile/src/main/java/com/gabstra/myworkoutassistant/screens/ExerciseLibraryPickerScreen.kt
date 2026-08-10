package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.ContentTitle
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition

@Composable
fun ExerciseLibraryPickerScreen(
    definitions: List<ExerciseDefinition>,
    onSelect: (ExerciseDefinition) -> Unit,
    onCreate: () -> Unit,
    onCancel: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val filtered = remember(query, definitions) {
        definitions.filter { it.name.contains(query.trim(), ignoreCase = true) }
            .sortedBy { it.name.lowercase() }
    }
    Column(Modifier.fillMaxSize().padding(Spacing.md)) {
        ContentTitle("Exercise library")
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("Search exercises") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.md),
        )
        LazyColumn(
            modifier = Modifier.fillMaxWidth().weight(1f),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            items(filtered, key = { it.id }) { definition ->
                StyledCard(
                    modifier = Modifier.fillMaxWidth().clickable { onSelect(definition) },
                ) {
                    Column(Modifier.fillMaxWidth().padding(Spacing.md)) {
                        Text(definition.name, style = MaterialTheme.typography.bodyLarge)
                        Text(
                            definition.exerciseType.name.replace('_', ' ').lowercase(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            AppSecondaryButton(
                text = "Cancel",
                onClick = onCancel,
                modifier = Modifier.weight(1f),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
            AppPrimaryButton(
                text = "Create new",
                onClick = onCreate,
                modifier = Modifier.weight(1f),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

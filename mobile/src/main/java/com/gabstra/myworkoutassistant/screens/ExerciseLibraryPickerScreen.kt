package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ExerciseLibraryPickerScreen(
    definitions: List<ExerciseDefinition>,
    equipments: List<com.gabstra.myworkoutassistant.shared.equipments.Equipment>,
    onSelect: (ExerciseDefinition) -> Unit,
    onCreate: () -> Unit,
    onCancel: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val filtered = remember(query, definitions) {
        definitions.filter { it.name.contains(query.trim(), ignoreCase = true) }
            .sortedBy { it.name.lowercase() }
    }
    val equipmentNameById = remember(equipments) {
        equipments.associate { it.id to it.name }
    }
    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = { Text("Exercise library") },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(horizontal = Spacing.md)
        ) {
            Text(
                text = "Pick an exercise from your library to add it to the workout, or create a new one.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.tertiaryContent,
                modifier = Modifier.padding(top = Spacing.md),
            )
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text("Search exercises") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.md),
            )
            if (filtered.isEmpty()) {
                Column(
                    modifier = Modifier.fillMaxSize().weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = "No exercises found",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.tertiaryContent,
                        textAlign = TextAlign.Center,
                    )
                }
            } else {
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
                                val typeLabel = definition.exerciseType.name.replace('_', ' ').lowercase()
                                val equipmentLabel = definition.equipmentId
                                    ?.let { equipmentNameById[it] }
                                    ?.let { " · $it" } ?: " · no equipment"
                                val accessoryLabels = definition.requiredAccessoryEquipmentIds
                                    ?.mapNotNull { accessoryName -> equipmentNameById[accessoryName] }
                                    .orEmpty()
                                val detailLabel = buildString {
                                    append(typeLabel)
                                    append(equipmentLabel)
                                    if (accessoryLabels.isNotEmpty()) {
                                        append(" · with ")
                                        append(accessoryLabels.joinToString(", "))
                                    }
                                }
                                Text(
                                    detailLabel,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.tertiaryContent,
                                )
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(Spacing.md))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f),
                    textAlign = TextAlign.Center,
                )
                AppPrimaryButton(
                    text = "Create new",
                    onClick = onCreate,
                    modifier = Modifier.weight(1f),
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppAddButton
import com.gabstra.myworkoutassistant.composables.ConfirmationDialog
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.effectiveFamilyId
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID
import java.nio.charset.StandardCharsets

private data class ExerciseDefinitionUsage(
    val workout: Workout,
    val planId: UUID?,
    val planName: String?,
    val placementCount: Int,
    val placementNameOverrides: List<String>,
)

private data class ExerciseDefinitionDetail(
    val label: String,
    val value: String,
)

private data class ExerciseFamily(
    val id: UUID,
    val name: String,
    val variations: List<ExerciseDefinition>,
)

private data class ExerciseEquipmentGroup(
    val label: String,
    val families: List<ExerciseFamily>,
)

@Composable
private fun LibraryMovementPreview(
    movementRef: ExerciseMovementRef?,
    contentDescription: String,
    modifier: Modifier = Modifier,
) {
    CompactMovementPreview(movementRef, contentDescription, modifier)
}

private fun String.toDisplayLabel(): String = lowercase()
    .split('_')
    .joinToString(" ") { word -> word.replaceFirstChar { it.titlecase() } }

private fun ExerciseDefinition.variationLabel(): String = exerciseType.name.toDisplayLabel()

private fun ExerciseDefinition.details(
    equipmentNamesById: Map<UUID, String>,
    accessoryNamesById: Map<UUID, String>,
): List<ExerciseDefinitionDetail> = buildList {
    add(ExerciseDefinitionDetail("Type", exerciseType.name.toDisplayLabel()))
    add(
        ExerciseDefinitionDetail(
            "Equipment",
            equipmentId?.let { equipmentNamesById[it] ?: "Unknown equipment" } ?: "None",
        ),
    )
    exerciseCategory?.let { category ->
        add(ExerciseDefinitionDetail("Category", category.name.toDisplayLabel()))
    }
    if (exerciseType == ExerciseType.BODY_WEIGHT) {
        bodyWeightPercentage?.let { percentage ->
            add(ExerciseDefinitionDetail("Body-weight contribution", "$percentage%"))
        }
    }
    muscleGroups.orEmpty().takeIf { it.isNotEmpty() }?.let { muscles ->
        add(
            ExerciseDefinitionDetail(
                "Primary muscles",
                muscles.map { it.name.toDisplayLabel() }.sorted().joinToString(),
            ),
        )
    }
    secondaryMuscleGroups.orEmpty().takeIf { it.isNotEmpty() }?.let { muscles ->
        add(
            ExerciseDefinitionDetail(
                "Secondary muscles",
                muscles.map { it.name.toDisplayLabel() }.sorted().joinToString(),
            ),
        )
    }
    requiredAccessoryEquipmentIds.orEmpty().takeIf { it.isNotEmpty() }?.let { accessoryIds ->
        add(
            ExerciseDefinitionDetail(
                "Accessories",
                accessoryIds.map { id ->
                    accessoryNamesById[id] ?: equipmentNamesById[id] ?: "Unknown accessory"
                }.sorted().joinToString(),
            ),
        )
    }
    if (movementRef != null) {
        add(ExerciseDefinitionDetail("Motion preview", "Available"))
    }
}

private fun buildExerciseDefinitionUsages(
    workouts: List<Workout>,
    plans: List<WorkoutPlan>,
): Map<UUID, List<ExerciseDefinitionUsage>> {
    val planNamesById = plans.associate { it.id to it.name }
    return workouts.flatMap { workout ->
        val prescriptions = workout.workoutComponents.flatMap { component ->
            when (component) {
                is Exercise -> listOf(component)
                is Superset -> component.exercises
                else -> emptyList()
            }
        }
        prescriptions
            .filter { it.exerciseDefinitionId != null }
            .groupBy { requireNotNull(it.exerciseDefinitionId) }
            .map { (definitionId, definitionPrescriptions) ->
                definitionId to ExerciseDefinitionUsage(
                    workout = workout,
                    planId = workout.workoutPlanId,
                    planName = workout.workoutPlanId?.let(planNamesById::get),
                    placementCount = definitionPrescriptions.size,
                    placementNameOverrides = definitionPrescriptions
                        .mapNotNull { it.nameOverride?.trim()?.takeIf(String::isNotEmpty) }
                        .distinct()
                        .sortedBy(String::lowercase),
                )
            }
    }.groupBy(keySelector = { it.first }, valueTransform = { it.second })
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ExerciseLibraryScreen(
    definitions: List<ExerciseDefinition>,
    workouts: List<Workout>,
    plans: List<WorkoutPlan>,
    equipmentNamesById: Map<UUID, String>,
    accessoryNamesById: Map<UUID, String>,
    onAdd: () -> Unit,
    onImport: (String) -> Unit,
    onEdit: (ExerciseDefinition) -> Unit,
    onDelete: (ExerciseDefinition) -> Unit,
    onOpenPlan: (UUID) -> Unit,
    onOpenWorkout: (UUID) -> Unit,
) {
    val context = LocalContext.current
    val importLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching {
            context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                ?: error("The selected file could not be opened.")
        }.onSuccess(onImport).onFailure { error ->
            Toast.makeText(
                context,
                error.message ?: "The exercise library could not be opened.",
                Toast.LENGTH_LONG,
            ).show()
        }
    }
    var query by rememberSaveable { mutableStateOf("") }
    var expandedFamilyIds by remember { mutableStateOf(emptySet<UUID>()) }
    var selectedFamilies by remember { mutableStateOf(emptyList<ExerciseFamily>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }
    var definitionsPendingDelete by remember { mutableStateOf(emptyList<ExerciseDefinition>()) }
    val usagesByDefinitionId = remember(workouts, plans) {
        buildExerciseDefinitionUsages(workouts, plans)
    }
    val equipmentGroups = remember(definitions, equipmentNamesById) {
        definitions
            .groupBy { it.equipmentId }
            .map { (equipmentId, equipmentDefinitions) ->
                val equipmentLabel = equipmentId?.let { id ->
                    equipmentNamesById[id] ?: "Unknown equipment"
                } ?: "No equipment"
                ExerciseEquipmentGroup(
                    label = equipmentLabel,
                    families = equipmentDefinitions
                        .groupBy { it.effectiveFamilyId() }
                        .map { (familyId, familyDefinitions) ->
                            ExerciseFamily(
                                id = UUID.nameUUIDFromBytes(
                                    "$familyId:${equipmentId ?: "none"}"
                                        .toByteArray(StandardCharsets.UTF_8),
                                ),
                                name = familyDefinitions.first().name,
                                variations = familyDefinitions.sortedBy { it.exerciseType.name },
                            )
                        }
                        .sortedBy { it.name.lowercase() },
                )
            }
            .sortedWith(
                compareBy<ExerciseEquipmentGroup> { it.label == "No equipment" }
                    .thenBy { it.label.lowercase() },
            )
    }
    val filteredGroups = remember(query, equipmentGroups) {
        val normalizedQuery = query.trim()
        equipmentGroups.mapNotNull { group ->
            val matchingFamilies = if (group.label.contains(normalizedQuery, ignoreCase = true)) {
                group.families
            } else {
                group.families.filter { family ->
                    family.name.contains(normalizedQuery, ignoreCase = true) ||
                        family.variations.any { variation ->
                            variation.exerciseType.name.toDisplayLabel()
                                .contains(normalizedQuery, ignoreCase = true)
                        }
                }
            }
            group.takeIf { matchingFamilies.isNotEmpty() }?.copy(families = matchingFamilies)
        }
    }
    val filteredFamilies = remember(filteredGroups) { filteredGroups.flatMap { it.families } }

    LaunchedEffect(filteredFamilies.map { it.id }) {
        val visibleIds = filteredFamilies.mapTo(mutableSetOf()) { it.id }
        selectedFamilies = selectedFamilies.filter { it.id in visibleIds }
        if (selectedFamilies.isEmpty()) isSelectionModeActive = false
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = Spacing.md)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text("Search exercise library") },
                singleLine = true,
                modifier = Modifier.weight(1f).padding(vertical = 12.dp),
            )
            IconButton(onClick = { importLauncher.launch(arrayOf("application/json")) }) {
                Icon(Icons.Default.FileOpen, contentDescription = "Import exercise library")
            }
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
        ) {
            if (filteredGroups.isEmpty()) {
                Text(
                    if (definitions.isEmpty()) "No exercise definitions yet." else "No matching exercises.",
                    modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.xl),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                filteredGroups.forEach { group ->
                    Text(
                        text = group.label,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = Spacing.lg, bottom = Spacing.sm),
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    GenericSelectableList(
                items = group.families,
                selectedItems = selectedFamilies,
                isSelectionModeActive = isSelectionModeActive,
                onItemClick = { family ->
                    expandedFamilyIds = if (family.id in expandedFamilyIds) {
                        expandedFamilyIds - family.id
                    } else {
                        expandedFamilyIds + family.id
                    }
                },
                onEnableSelection = { isSelectionModeActive = true },
                onDisableSelection = { isSelectionModeActive = false },
                onSelectionChange = { selectedFamilies = it },
                onOrderChange = {},
                isDragDisabled = true,
                keySelector = { it.id },
                itemContent = { family, onItemClick, onItemLongClick ->
                    val expanded = family.id in expandedFamilyIds
                    val familyMovementRef = remember(family.variations) {
                        family.variations.firstNotNullOfOrNull { it.movementRef }
                    }
                        StyledCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .combinedClickable(
                                    onClick = onItemClick,
                                    onLongClick = onItemLongClick,
                                ),
                        ) {
                        Column(modifier = Modifier.fillMaxWidth().padding(Spacing.md)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                LibraryMovementPreview(
                                    movementRef = familyMovementRef,
                                    contentDescription = if (familyMovementRef == null) {
                                        "No movement available for ${family.name}"
                                    } else {
                                        "Movement preview for ${family.name}"
                                    },
                                    modifier = Modifier.size(72.dp),
                                )
                                Spacer(Modifier.width(Spacing.md))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = family.name,
                                        style = MaterialTheme.typography.bodyLarge,
                                    )
                                    if (family.variations.size > 1) {
                                        Text(
                                            text = "${family.variations.size} variations",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                                Box(
                                    modifier = Modifier
                                        .size(32.dp)
                                        .clickable {
                                            expandedFamilyIds = if (expanded) {
                                                expandedFamilyIds - family.id
                                            } else {
                                                expandedFamilyIds + family.id
                                            }
                                        },
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(
                                        imageVector = if (expanded) {
                                            Icons.Default.ExpandLess
                                        } else {
                                            Icons.Default.ExpandMore
                                        },
                                        contentDescription = if (expanded) {
                                            "Collapse exercise details"
                                        } else {
                                            "Expand exercise details"
                                        },
                                        modifier = Modifier.size(20.dp),
                                    )
                                }
                            }
                            if (expanded) {
                                Column(
                                    modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
                                    verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                                ) {
                                    family.variations.forEach { definition ->
                                        val activeUsages = usagesByDefinitionId[definition.id].orEmpty()
                                            .filter { it.workout.isActive }
                                        Column(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .clip(RoundedCornerShape(10.dp))
                                                .background(MaterialTheme.colorScheme.surface)
                                                .padding(Spacing.md),
                                            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                                        ) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                text = definition.variationLabel(),
                                                modifier = Modifier.weight(1f),
                                                style = MaterialTheme.typography.labelLarge,
                                                color = MaterialTheme.colorScheme.onSurface,
                                            )
                                            Box(
                                                modifier = Modifier
                                                    .size(32.dp)
                                                    .clickable { onEdit(definition) },
                                                contentAlignment = Alignment.Center,
                                            ) {
                                                Icon(
                                                    imageVector = Icons.Default.Edit,
                                                    contentDescription = "Edit ${definition.variationLabel()} variation",
                                                    modifier = Modifier.size(18.dp),
                                                    tint = MaterialTheme.colorScheme.primary,
                                                )
                                            }
                                            Box(
                                                modifier = Modifier
                                                    .size(32.dp)
                                                    .clickable {
                                                        if (usagesByDefinitionId[definition.id].isNullOrEmpty()) {
                                                            definitionsPendingDelete = listOf(definition)
                                                        } else {
                                                            Toast.makeText(
                                                                context,
                                                                "This variation is used by a workout and can't be deleted.",
                                                                Toast.LENGTH_LONG,
                                                            ).show()
                                                        }
                                                    },
                                                contentAlignment = Alignment.Center,
                                            ) {
                                                Icon(
                                                    imageVector = Icons.Default.Delete,
                                                    contentDescription = "Delete ${definition.variationLabel()} variation",
                                                    modifier = Modifier.size(18.dp),
                                                    tint = Red,
                                                )
                                            }
                                        }
                                        ExerciseDefinitionDetailsSection(
                                            definition.details(equipmentNamesById, accessoryNamesById)
                                                .filterNot {
                                                    it.label == "Type" ||
                                                        it.label == "Equipment" ||
                                                        it.label == "Motion preview"
                                                },
                                        )
                                        UsageSection(activeUsages, onOpenPlan, onOpenWorkout)
                                    }
                                }
                            }
                            }
                        }
                    }
                },
                    )
                }
            }
            if (!isSelectionModeActive) {
                Spacer(Modifier.height(Spacing.md))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                ) {
                    AppAddButton(onClick = onAdd)
                }
                Spacer(Modifier.height(Spacing.md))
            }
        }
        if (isSelectionModeActive) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            val selectedDefinitions = selectedFamilies.flatMap { it.variations }
            val unusedSelections = selectedDefinitions.filter {
                usagesByDefinitionId[it.id].isNullOrEmpty()
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.Top,
            ) {
                LibrarySelectionAction(
                    icon = Icons.Default.Close,
                    label = "Close",
                    tint = Red,
                ) {
                    selectedFamilies = emptyList()
                    isSelectionModeActive = false
                }
                LibrarySelectionAction(
                    icon = Icons.Default.CheckBox,
                    label = "Select all",
                ) {
                    selectedFamilies = filteredFamilies
                }
                LibrarySelectionAction(
                    icon = Icons.Default.CheckBoxOutlineBlank,
                    label = "Deselect all",
                ) {
                    selectedFamilies = emptyList()
                }
                LibrarySelectionAction(
                    icon = Icons.Default.Delete,
                    label = "Delete unused",
                    enabled = selectedDefinitions.isNotEmpty(),
                ) {
                    if (unusedSelections.isEmpty()) {
                        Toast.makeText(
                            context,
                            "Selected exercises are used by workouts and can't be deleted.",
                            Toast.LENGTH_LONG,
                        ).show()
                    } else {
                        definitionsPendingDelete = unusedSelections
                    }
                }
            }
        }
    }

    ConfirmationDialog(
        show = definitionsPendingDelete.isNotEmpty(),
        title = "Delete selected exercises?",
        message = if (definitionsPendingDelete.size == 1) {
            "${definitionsPendingDelete.single().name} will be removed from the library."
        } else {
            "${definitionsPendingDelete.size} unused exercises will be removed from the library."
        },
        confirmText = "Delete",
        isDestructive = true,
        onConfirm = {
            definitionsPendingDelete.forEach(onDelete)
            definitionsPendingDelete = emptyList()
            selectedFamilies = emptyList()
            isSelectionModeActive = false
        },
        onDismiss = { definitionsPendingDelete = emptyList() },
    )
}

@Composable
private fun LibrarySelectionAction(
    icon: ImageVector,
    label: String,
    enabled: Boolean = true,
    tint: Color = MaterialTheme.colorScheme.onBackground,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier.width(64.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        IconButton(onClick = onClick, enabled = enabled) {
            Icon(
                imageVector = icon,
                contentDescription = label,
                tint = if (enabled) tint else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f),
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            textAlign = TextAlign.Center,
            maxLines = 2,
        )
    }
}

@Composable
private fun ExerciseDefinitionDetailsSection(
    details: List<ExerciseDefinitionDetail>,
) {
    if (details.isEmpty()) return
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        details.forEach { detail ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                verticalAlignment = Alignment.Top,
            ) {
                Text(
                    text = detail.label,
                    modifier = Modifier.width(96.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = detail.value,
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

@Composable
private fun UsageSection(
    usages: List<ExerciseDefinitionUsage>,
    onOpenPlan: (UUID) -> Unit,
    onOpenWorkout: (UUID) -> Unit,
) {
    Text(
        text = "Used by",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (usages.isEmpty()) {
        Text(
            text = "No active workouts",
            modifier = Modifier.padding(top = 4.dp),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        usages
        .groupBy { it.planId }
        .entries
        .sortedBy { (_, planUsages) -> planUsages.first().planName.orEmpty().lowercase() }
        .forEach { (planId, planUsages) ->
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (planId != null) Modifier.clickable { onOpenPlan(planId) }
                            else Modifier
                        ),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    Text(
                        text = planUsages.first().planName ?: "Without a workout plan",
                        modifier = Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                planUsages
                    .sortedBy { it.workout.name.lowercase() }
                    .forEach { usage ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onOpenWorkout(usage.workout.id) }
                                .padding(start = Spacing.sm, top = Spacing.sm, bottom = Spacing.sm),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                            ) {
                                Text(
                                    text = usage.workout.name,
                                    modifier = Modifier.weight(1f),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                if (usage.placementCount > 1) {
                                    Text(
                                        text = "${usage.placementCount} uses",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Icon(
                                    imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                                    contentDescription = null,
                                    modifier = Modifier.size(16.dp),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            if (usage.placementNameOverrides.isNotEmpty()) {
                                Text(
                                    text = usage.placementNameOverrides.joinToString(
                                        prefix = if (usage.placementNameOverrides.size == 1) {
                                            "Workout name: "
                                        } else {
                                            "Workout names: "
                                        },
                                    ),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                }
            }
        }
    }
}

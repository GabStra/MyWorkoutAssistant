package com.gabstra.myworkoutassistant.screens

import android.content.res.Configuration
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.aspectRatio
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
import androidx.compose.material.icons.outlined.PlayCircle
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
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppAddButton
import com.gabstra.myworkoutassistant.composables.ConfirmationDialog
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.StandardDialog
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
import androidx.compose.ui.tooling.preview.Preview
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import java.time.LocalDate
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
    if (exerciseType == ExerciseType.COUNTUP || exerciseType == ExerciseType.COUNTDOWN) {
        add(ExerciseDefinitionDetail("Type", "Timed"))
    }
    if (exerciseType == ExerciseType.BODY_WEIGHT) {
        bodyWeightPercentage?.let { percentage ->
            add(
                ExerciseDefinitionDetail(
                    "Body weight",
                    "$percentage%",
                ),
            )
        }
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
    var movementPreviewFamily by remember { mutableStateOf<ExerciseFamily?>(null) }
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
                    ExerciseFamilyCard(
                        family = family,
                        expanded = family.id in expandedFamilyIds,
                        usagesByDefinitionId = usagesByDefinitionId,
                        equipmentNamesById = equipmentNamesById,
                        accessoryNamesById = accessoryNamesById,
                        onToggleExpanded = onItemClick,
                        onItemLongClick = onItemLongClick,
                        onEdit = onEdit,
                        onRequestDelete = { definition ->
                            definitionsPendingDelete = listOf(definition)
                        },
                        onOpenWorkout = onOpenWorkout,
                        onPreviewMovement = { movementPreviewFamily = family },
                    )
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

    movementPreviewFamily?.let { family ->
        StandardDialog(
            onDismissRequest = { movementPreviewFamily = null },
            title = family.name,
            body = {
                ExerciseMovementPreviewPage(
                    movementRef = family.variations.firstNotNullOfOrNull { it.movementRef },
                    modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                )
            },
            dismissText = "Close",
            onDismissButton = { movementPreviewFamily = null },
            showConfirm = false,
        )
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

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ExerciseFamilyCard(
    family: ExerciseFamily,
    expanded: Boolean,
    usagesByDefinitionId: Map<UUID, List<ExerciseDefinitionUsage>>,
    equipmentNamesById: Map<UUID, String>,
    accessoryNamesById: Map<UUID, String>,
    onToggleExpanded: () -> Unit,
    onItemLongClick: () -> Unit,
    onEdit: (ExerciseDefinition) -> Unit,
    onRequestDelete: (ExerciseDefinition) -> Unit,
    onOpenWorkout: (UUID) -> Unit,
    onPreviewMovement: () -> Unit,
) {
    val context = LocalContext.current
    val familyMovementRef = remember(family.variations) {
        family.variations.firstNotNullOfOrNull { it.movementRef }
    }
    StyledCard(
        modifier = Modifier
            .fillMaxWidth()
            .clip(MaterialTheme.shapes.medium)
            .combinedClickable(
                onClick = onToggleExpanded,
                onLongClick = onItemLongClick,
            ),
        borderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.md, vertical = Spacing.sm),
        ) {
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
                Spacer(Modifier.width(Spacing.sm))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = family.name,
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    if (family.variations.size > 1) {
                        Text(
                            text = "${family.variations.size} variations",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.tertiaryContent,
                        )
                    }
                }
                Box(
                    modifier = Modifier
                        .size(32.dp)
                        .clickable(onClick = onToggleExpanded),
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
                    modifier = Modifier.fillMaxWidth().padding(top = Spacing.xs),
                ) {
                    if (familyMovementRef != null) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable(onClick = onPreviewMovement)
                                .padding(vertical = Spacing.xs),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                        ) {
                            Icon(
                                imageVector = Icons.Outlined.PlayCircle,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp),
                                tint = MaterialTheme.colorScheme.primary,
                            )
                            Text(
                                text = "View movement",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                    family.variations.forEachIndexed { variationIndex, definition ->
                        if (variationIndex > 0) {
                            HorizontalDivider(
                                modifier = Modifier.padding(vertical = Spacing.sm),
                                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
                            )
                        }
                        val activeUsages = usagesByDefinitionId[definition.id].orEmpty()
                            .filter { it.workout.isActive }
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(MaterialTheme.shapes.small)
                                    .combinedClickable(
                                        onClick = { onEdit(definition) },
                                        onLongClick = {
                                            if (usagesByDefinitionId[definition.id].isNullOrEmpty()) {
                                                onRequestDelete(definition)
                                            } else {
                                                Toast.makeText(
                                                    context,
                                                    "This variation is used by a workout and can't be deleted.",
                                                    Toast.LENGTH_LONG,
                                                ).show()
                                            }
                                        },
                                    ),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = definition.name,
                                    modifier = Modifier.weight(1f),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Icon(
                                    imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                                    contentDescription = "Edit ${definition.variationLabel()} variation",
                                    modifier = Modifier.size(16.dp),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            DetailChipsSection(definition)
                            ExerciseDefinitionDetailsSection(
                                definition.details(equipmentNamesById, accessoryNamesById),
                            )
                            UsageSection(activeUsages, onOpenWorkout)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DetailChip(text: String, emphasized: Boolean) {
    Box(
        modifier = Modifier
            .background(
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = if (emphasized) 0.42f else 0.18f),
                MaterialTheme.shapes.small,
            )
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = if (emphasized) {
                MaterialTheme.colorScheme.onSurface
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DetailChipsSection(definition: ExerciseDefinition) {
    val category = definition.exerciseCategory
    val primaryMuscles = definition.muscleGroups.orEmpty()
    val secondaryMuscles = definition.secondaryMuscleGroups.orEmpty()
    if (category == null && primaryMuscles.isEmpty() && secondaryMuscles.isEmpty()) return
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        category?.let {
            Text(
                text = it.name.toDisplayLabel(),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            primaryMuscles.forEach { muscle ->
                DetailChip(muscle.name.toDisplayLabel(), emphasized = true)
            }
            secondaryMuscles.forEach { muscle ->
                DetailChip(muscle.name.toDisplayLabel(), emphasized = false)
            }
        }
    }
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
                    color = MaterialTheme.colorScheme.tertiaryContent,
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
    onOpenWorkout: (UUID) -> Unit,
) {
    if (usages.isEmpty()) {
        Text(
            text = "This exercise isn't part of any workout yet",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.tertiaryContent,
        )
        return
    }
    val sortedUsages = usages.sortedWith(
        compareBy(
            { it.planName.orEmpty().lowercase() },
            { it.workout.name.lowercase() },
        ),
    )
    val visibleCount = minOf(sortedUsages.size, CollapsedUsageRowCount)
    var showAll by remember { mutableStateOf(false) }
    val visibleUsages = if (showAll) sortedUsages else sortedUsages.take(visibleCount)
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "Used in",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Column(
            modifier = Modifier.fillMaxWidth().padding(top = 2.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            visibleUsages.forEach { usage ->
                Column(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(MaterialTheme.shapes.small)
                            .clickable { onOpenWorkout(usage.workout.id) }
                            .padding(start = Spacing.sm, top = 4.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
                    ) {
                        Text(
                            text = buildString {
                                usage.planName?.let { planName ->
                                    append(planName)
                                    append(" · ")
                                }
                                append(usage.workout.name)
                            },
                            modifier = Modifier.weight(1f),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        if (usage.placementCount > 1) {
                            Text(
                                text = "${usage.placementCount} uses",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.tertiaryContent,
                            )
                        }
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                            contentDescription = "Open workout",
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (usage.placementNameOverrides.isNotEmpty()) {
                        Text(
                            text = usage.placementNameOverrides.joinToString(prefix = "Shown as: "),
                            modifier = Modifier.padding(start = Spacing.md),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.tertiaryContent,
                        )
                    }
                }
            }
        }
        if (sortedUsages.size > visibleCount && !showAll) {
            Text(
                text = "Show all ${sortedUsages.size}",
                modifier = Modifier
                    .clip(MaterialTheme.shapes.small)
                    .clickable { showAll = true }
                    .padding(start = Spacing.sm, top = 4.dp, bottom = 4.dp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

private const val CollapsedUsageRowCount = 3

// region Compose previews (Android Studio)

private const val PreviewBarbellId = "11111111-1111-1111-1111-111111111111"
private const val PreviewBenchId = "22222222-2222-2222-2222-222222222222"
private const val PreviewPullUpBarId = "33333333-3333-3333-3333-333333333333"

private fun PreviewSquatFamily(withMovementRef: Boolean = false): ExerciseFamily {
    val barbellId = UUID.fromString(PreviewBarbellId)
    val rackId = UUID.fromString(PreviewBenchId)
    val definition = ExerciseDefinition(
        id = UUID.nameUUIDFromBytes("squat-weight".toByteArray()),
        name = "Barbell Back Squat",
        exerciseType = ExerciseType.WEIGHT,
        equipmentId = barbellId,
        bodyWeightPercentage = null,
        muscleGroups = setOf(MuscleGroup.FRONT_QUADRICEPS, MuscleGroup.BACK_GLUTEAL),
        secondaryMuscleGroups = setOf(MuscleGroup.BACK_HAMSTRING, MuscleGroup.FRONT_ADDUCTORS),
        requiredAccessoryEquipmentIds = listOf(rackId),
        exerciseCategory = ExerciseCategory.HEAVY_COMPOUND,
        movementRef = if (withMovementRef) {
            ExerciseMovementRef(
                movementId = "exercise-motion:preview-squat",
                contentHash = "0".repeat(64),
            )
        } else {
            null
        },
    )
    return ExerciseFamily(
        id = UUID.nameUUIDFromBytes("squat-family".toByteArray()),
        name = definition.name,
        variations = listOf(definition),
    )
}

private fun PreviewMultiVariationFamily(): ExerciseFamily {
    val pullUpBarId = UUID.fromString(PreviewPullUpBarId)
    val bodyWeight = ExerciseDefinition(
        id = UUID.nameUUIDFromBytes("pullup-bw".toByteArray()),
        name = "Pull-Up",
        exerciseType = ExerciseType.BODY_WEIGHT,
        equipmentId = null,
        bodyWeightPercentage = 100.0,
        muscleGroups = setOf(MuscleGroup.BACK_UPPER_BACK, MuscleGroup.FRONT_BICEPS),
        secondaryMuscleGroups = emptySet(),
        requiredAccessoryEquipmentIds = listOf(pullUpBarId),
        exerciseCategory = ExerciseCategory.HEAVY_COMPOUND,
    )
    val weighted = bodyWeight.copy(
        id = UUID.nameUUIDFromBytes("pullup-weighted".toByteArray()),
        name = "Weighted Pull-Up",
        exerciseType = ExerciseType.WEIGHT,
        bodyWeightPercentage = 40.0,
    )
    return ExerciseFamily(
        id = UUID.nameUUIDFromBytes("pullup-family".toByteArray()),
        name = "Pull-Up",
        variations = listOf(bodyWeight, weighted),
    )
}

private fun PreviewUsage(
    definition: ExerciseDefinition,
    planName: String?,
    workoutName: String,
    placements: Int,
): List<ExerciseDefinitionUsage> {
    val planId = planName?.let { UUID.nameUUIDFromBytes(it.toByteArray()) }
    val workout = Workout(
        id = UUID.nameUUIDFromBytes(workoutName.toByteArray()),
        name = workoutName,
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.nameUUIDFromBytes("global-$workoutName".toByteArray()),
        type = 0,
        workoutPlanId = planId,
    )
    return listOf(
        ExerciseDefinitionUsage(
            workout = workout,
            planId = planId,
            planName = planName,
            placementCount = placements,
            placementNameOverrides = if (placements > 1) listOf("$workoutName 1", "$workoutName 2") else emptyList(),
        ),
    )
}

@Preview(
    name = "Row - collapsed, no movement",
    uiMode = Configuration.UI_MODE_NIGHT_YES,
    showBackground = true,
    backgroundColor = 0xFF000000,
)
@Composable
private fun ExerciseLibraryRowCollapsedPreview() {
    MyWorkoutAssistantTheme {
        Column(
            modifier = Modifier.fillMaxWidth().padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            ExerciseFamilyCard(
                family = PreviewSquatFamily(),
                expanded = false,
                usagesByDefinitionId = emptyMap(),
                equipmentNamesById = mapOf(UUID.fromString(PreviewBarbellId) to "Barbell"),
                accessoryNamesById = mapOf(UUID.fromString(PreviewBenchId) to "Squat Rack"),
                onToggleExpanded = {},
                onItemLongClick = {},
                onEdit = {},
                onRequestDelete = {},
                onOpenWorkout = {},
                onPreviewMovement = {},
            )
        }
    }
}

@Preview(name = "Row – expanded with chips and usage", uiMode = Configuration.UI_MODE_NIGHT_YES, showBackground = true, backgroundColor = 0xFF000000, heightDp = 480)
@Composable
private fun ExerciseLibraryRowExpandedPreview() {
    MyWorkoutAssistantTheme {
        val family = PreviewSquatFamily()
        val definition = family.variations.first()
        ExerciseFamilyCard(
            family = family,
            expanded = true,
            usagesByDefinitionId = mapOf(
                definition.id to PreviewUsage(definition, "Strength Base", "Push Day A", 2),
            ),
            equipmentNamesById = mapOf(UUID.fromString(PreviewBarbellId) to "Barbell"),
            accessoryNamesById = mapOf(UUID.fromString(PreviewBenchId) to "Squat Rack"),
            onToggleExpanded = {},
            onItemLongClick = {},
            onEdit = {},
            onRequestDelete = {},
            onOpenWorkout = {},
            onPreviewMovement = {},
        )
    }
}

@Preview(name = "Row – expanded, two variations, unused", uiMode = Configuration.UI_MODE_NIGHT_YES, showBackground = true, backgroundColor = 0xFF000000, heightDp = 520)
@Composable
private fun ExerciseLibraryRowMultiVariationPreview() {
    MyWorkoutAssistantTheme {
        ExerciseFamilyCard(
            family = PreviewMultiVariationFamily(),
            expanded = true,
            usagesByDefinitionId = emptyMap(),
            equipmentNamesById = emptyMap(),
            accessoryNamesById = mapOf(UUID.fromString(PreviewPullUpBarId) to "Pull-Up Station"),
            onToggleExpanded = {},
            onItemLongClick = {},
            onEdit = {},
            onRequestDelete = {},
            onOpenWorkout = {},
            onPreviewMovement = {},
        )
    }
}

@Preview(name = "Row – expanded, used without plan", uiMode = Configuration.UI_MODE_NIGHT_YES, showBackground = true, backgroundColor = 0xFF000000, heightDp = 480)
@Composable
private fun ExerciseLibraryRowUsageWithoutPlanPreview() {
    MyWorkoutAssistantTheme {
        val family = PreviewMultiVariationFamily()
        val definition = family.variations.first()
        ExerciseFamilyCard(
            family = family,
            expanded = true,
            usagesByDefinitionId = mapOf(
                definition.id to PreviewUsage(definition, null, "Full Body Friday", 1),
            ),
            equipmentNamesById = emptyMap(),
            accessoryNamesById = mapOf(UUID.fromString(PreviewPullUpBarId) to "Pull-Up Station"),
            onToggleExpanded = {},
            onItemLongClick = {},
            onEdit = {},
            onRequestDelete = {},
            onOpenWorkout = {},
            onPreviewMovement = {},
        )
    }
}

// endregion

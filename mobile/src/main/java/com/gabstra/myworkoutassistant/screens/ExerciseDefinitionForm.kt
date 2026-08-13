package com.gabstra.myworkoutassistant.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalMinimumInteractiveComponentSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.tooling.preview.Preview
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.ZoomableMuscleHeatMap
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.isCompatibleWith
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExerciseDefinitionForm(
    definition: ExerciseDefinition?,
    equipments: List<WeightLoadedEquipment>,
    accessories: List<AccessoryEquipment>,
    isReferenced: Boolean,
    onSave: (ExerciseDefinition) -> Unit,
    onCancel: () -> Unit,
    breadcrumbContent: (@Composable () -> Unit)? = null,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var name by rememberSaveable { mutableStateOf(definition?.name.orEmpty()) }
    var exerciseType by rememberSaveable {
        mutableStateOf(definition?.exerciseType ?: ExerciseType.WEIGHT)
    }
    var equipmentId by rememberSaveable { mutableStateOf(definition?.equipmentId) }
    var bodyWeightPercentage by rememberSaveable {
        mutableStateOf(definition?.bodyWeightPercentage?.toString().orEmpty())
    }
    var exerciseCategory by rememberSaveable { mutableStateOf(definition?.exerciseCategory) }
    var selectedAccessoryIds by rememberSaveable {
        mutableStateOf(definition?.requiredAccessoryEquipmentIds.orEmpty())
    }
    var selectedMuscles by rememberSaveable {
        mutableStateOf(definition?.muscleGroups.orEmpty())
    }
    var selectedSecondaryMuscles by rememberSaveable {
        mutableStateOf(definition?.secondaryMuscleGroups.orEmpty())
    }
    var isSelectingSecondary by rememberSaveable { mutableStateOf(false) }
    var resetMuscleMapTrigger by remember { mutableIntStateOf(0) }
    var equipmentExpanded by rememberSaveable { mutableStateOf(false) }
    var musclesExpanded by rememberSaveable { mutableStateOf(false) }
    var movementExpanded by rememberSaveable { mutableStateOf(false) }
    var movementRef by remember(definition?.id) { mutableStateOf(definition?.movementRef) }
    var movementJson by remember(definition?.id) { mutableStateOf<String?>(null) }
    var movementError by remember { mutableStateOf<String?>(null) }
    var isMovementLoading by remember { mutableStateOf(false) }

    val typeItems = remember {
        ExerciseType.entries.map {
            StandardFilterDropdownItem(it, it.name.replace('_', ' ').lowercase())
        }
    }
    val equipmentItems = remember(equipments, exerciseType) {
        listOf(StandardFilterDropdownItem<UUID?>(null, "None")) +
            equipments.filter { it.isCompatibleWith(exerciseType) }
                .map { StandardFilterDropdownItem<UUID?>(it.id, it.name) }
    }
    val categoryItems: List<StandardFilterDropdownItem<ExerciseCategory?>> = remember {
        listOf(
            StandardFilterDropdownItem<ExerciseCategory?>(null, "Not set"),
            StandardFilterDropdownItem<ExerciseCategory?>(ExerciseCategory.HEAVY_COMPOUND, "Heavy compound"),
            StandardFilterDropdownItem<ExerciseCategory?>(ExerciseCategory.MODERATE_COMPOUND, "Moderate compound"),
            StandardFilterDropdownItem<ExerciseCategory?>(ExerciseCategory.ISOLATION, "Isolation"),
        )
    }
    val movementPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        if (isMovementLoading) return@rememberLauncherForActivityResult
        scope.launch {
            isMovementLoading = true
            movementError = null
            runCatching {
                withContext(Dispatchers.IO) {
                    val json = context.contentResolver.openInputStream(uri)
                        ?.bufferedReader()?.use { it.readText() }
                        ?: error("Unable to read selected movement file.")
                    validateWearSkeletonJson(json)
                    val movementId = context.resolveMovementId(uri, json)
                    ExerciseMovementRef.forWearSkeletonJson(movementId, json) to json
                }
            }.onSuccess { (newMovementRef, json) ->
                movementRef = newMovementRef
                movementJson = json
            }.onFailure { error ->
                movementError = error.message ?: "Unable to load selected movement JSON."
            }
            isMovementLoading = false
        }
    }

    LaunchedEffect(definition?.movementRef) {
        movementJson = definition?.movementRef?.let { existingRef ->
            withContext(Dispatchers.IO) {
                ExerciseMovementStorage.readMovementJson(context, existingRef)
            }
        }
    }

    Scaffold(
        topBar = {
            Column {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                    title = {
                        Text(
                            text = if (definition == null) "Create exercise" else "Edit exercise",
                            modifier = Modifier.fillMaxWidth().basicMarquee(iterations = Int.MAX_VALUE),
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onCancel) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                        }
                    },
                    actions = {
                        IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
                        }
                    },
                )
                breadcrumbContent?.invoke()
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(vertical = Spacing.sm)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacing.md),
        ) {
            FormSectionTitle("Essentials")
            StyledCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(Spacing.md),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    OutlinedTextField(
                        value = name,
                        onValueChange = { name = it },
                        label = { Text("Exercise name") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    StandardFilterDropdown<ExerciseType>(
                        label = "Exercise type",
                        selectedText = exerciseType.name.replace('_', ' ').lowercase(),
                        items = typeItems,
                        onItemSelected = {
                            exerciseType = it
                            if (it != ExerciseType.WEIGHT && it != ExerciseType.BODY_WEIGHT) {
                                equipmentId = null
                                selectedAccessoryIds = emptyList()
                            }
                        },
                        selectedValue = exerciseType,
                        isItemSelected = { it == exerciseType },
                        enabled = !isReferenced,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    StandardFilterDropdown<ExerciseCategory?>(
                        label = "Exercise category",
                        selectedText = categoryItems.first { it.value == exerciseCategory }.label,
                        items = categoryItems,
                        onItemSelected = { exerciseCategory = it },
                        selectedValue = exerciseCategory,
                        isItemSelected = { it == exerciseCategory },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (exerciseType == ExerciseType.BODY_WEIGHT) {
                        OutlinedTextField(
                            value = bodyWeightPercentage,
                            onValueChange = { input ->
                                if (input.isEmpty() || input.toDoubleOrNull() != null) {
                                    bodyWeightPercentage = input
                                }
                            },
                            label = { Text("Bodyweight load (%)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    if (isReferenced) {
                        ContentSubtitle(
                            "Type and default equipment cannot change while this exercise is used in a workout.",
                        )
                    }
                }
            }

            if (exerciseType in setOf(
                    ExerciseType.WEIGHT,
                    ExerciseType.BODY_WEIGHT,
                    ExerciseType.COUNTUP,
                    ExerciseType.COUNTDOWN,
                )
            ) {
                Spacer(Modifier.height(Spacing.md))
                val selectedEquipmentName = equipmentItems
                    .firstOrNull { it.value == equipmentId }?.label ?: "None"
                CollapsibleSection(
                    title = "Equipment",
                    summary = "Equipment: $selectedEquipmentName\nAccessories: ${selectedAccessoryIds.size}",
                    expanded = equipmentExpanded,
                    onToggle = { equipmentExpanded = !equipmentExpanded },
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        StandardFilterDropdown(
                            label = "Default equipment",
                            selectedText = selectedEquipmentName,
                            items = equipmentItems,
                            onItemSelected = { equipmentId = it },
                            selectedValue = equipmentId,
                            isItemSelected = { it == equipmentId },
                            enabled = !isReferenced,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Text("Required accessories", style = MaterialTheme.typography.titleMedium)
                        if (accessories.isEmpty()) {
                            ContentSubtitle("No accessories are available in the Gear section.")
                        } else {
                            accessories.forEach { accessory ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides 0.dp) {
                                        Checkbox(
                                            checked = accessory.id in selectedAccessoryIds,
                                            onCheckedChange = { checked ->
                                                selectedAccessoryIds = if (checked) {
                                                    selectedAccessoryIds + accessory.id
                                                } else {
                                                    selectedAccessoryIds - accessory.id
                                                }
                                            },
                                            modifier = Modifier.size(20.dp),
                                            colors = CheckboxDefaults.colors(),
                                        )
                                    }
                                    Text(accessory.name, modifier = Modifier.padding(start = Spacing.sm))
                                }
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(Spacing.md))
            CollapsibleSection(
                title = "Target muscles",
                summary = "Primary: ${selectedMuscles.size}\nSecondary: ${selectedSecondaryMuscles.size}",
                expanded = musclesExpanded,
                onToggle = { musclesExpanded = !musclesExpanded },
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        AppPrimaryOutlinedButton(
                            text = "Reset zoom & center",
                            onClick = { resetMuscleMapTrigger++ },
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                    ZoomableMuscleHeatMap(
                        selectedMuscles = selectedMuscles,
                        selectedSecondaryMuscles = selectedSecondaryMuscles,
                        onMuscleToggled = { muscle ->
                            if (isSelectingSecondary) {
                                selectedMuscles -= muscle
                                selectedSecondaryMuscles = selectedSecondaryMuscles.toggle(muscle)
                            } else {
                                selectedSecondaryMuscles -= muscle
                                selectedMuscles = selectedMuscles.toggle(muscle)
                            }
                        },
                        resetTrigger = resetMuscleMapTrigger,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    ) {
                        if (!isSelectingSecondary) AppPrimaryButton(
                            text = "Primary",
                            onClick = { isSelectingSecondary = false },
                            modifier = Modifier.weight(1f),
                            textAlign = TextAlign.Center,
                        ) else AppSecondaryButton(
                            text = "Primary",
                            onClick = { isSelectingSecondary = false },
                            modifier = Modifier.weight(1f),
                            textAlign = TextAlign.Center,
                        )
                        if (isSelectingSecondary) AppPrimaryButton(
                            text = "Secondary",
                            onClick = { isSelectingSecondary = true },
                            modifier = Modifier.weight(1f),
                            textAlign = TextAlign.Center,
                        ) else AppSecondaryButton(
                            text = "Secondary",
                            onClick = { isSelectingSecondary = true },
                            modifier = Modifier.weight(1f),
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }

            Spacer(Modifier.height(Spacing.md))
            CollapsibleSection(
                title = "Movement",
                summary = movementRef?.movementId?.let { "Movement: $it" } ?: "No movement assigned",
                expanded = movementExpanded,
                onToggle = { movementExpanded = !movementExpanded },
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    ) {
                        AppPrimaryOutlinedButton(
                            text = "Pick JSON",
                            onClick = { movementPicker.launch(arrayOf("application/json", "text/*", "*/*")) },
                            enabled = !isMovementLoading,
                            modifier = Modifier.weight(1f),
                        )
                        AppSecondaryButton(
                            text = "Clear",
                            onClick = { movementRef = null; movementJson = null; movementError = null },
                            enabled = !isMovementLoading && movementRef != null,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    movementError?.let {
                        Text(it, color = MaterialTheme.colorScheme.error)
                    }
                    movementJson?.let { json ->
                        SkeletonMotionPreview(
                            skeletonJson = json,
                            modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                            backgroundColor = MaterialTheme.colorScheme.background,
                            primaryFill = MaterialTheme.colorScheme.primary,
                            animated = true,
                            orbitView = false,
                            dragRotationEnabled = true,
                        )
                    }
                }
            }

            Spacer(Modifier.height(Spacing.xl))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f),
                )
                AppPrimaryButton(
                    text = "Save",
                    enabled = name.isNotBlank(),
                    modifier = Modifier.weight(1f),
                    onClick = {
                        onSave(
                            (definition ?: ExerciseDefinition(
                                id = UUID.randomUUID(),
                                name = "",
                                exerciseType = exerciseType,
                            )).copy(
                                name = name.trim(),
                                exerciseType = exerciseType,
                                equipmentId = equipmentId?.takeIf { selectedId ->
                                    equipments.any {
                                        it.id == selectedId && it.isCompatibleWith(exerciseType)
                                    }
                                },
                                bodyWeightPercentage = bodyWeightPercentage.toDoubleOrNull(),
                                muscleGroups = selectedMuscles,
                                secondaryMuscleGroups = selectedSecondaryMuscles,
                                requiredAccessoryEquipmentIds = selectedAccessoryIds,
                                exerciseCategory = exerciseCategory,
                                movementRef = movementRef,
                            )
                        )
                    },
                )
            }
            Spacer(Modifier.height(Spacing.md))
        }
    }
}

private fun Set<MuscleGroup>.toggle(muscle: MuscleGroup): Set<MuscleGroup> =
    if (muscle in this) this - muscle else this + muscle

@Preview(
    name = "Exercise library editor",
    showBackground = true,
    widthDp = 412,
    heightDp = 892,
)
@Composable
private fun ExerciseDefinitionFormPreview() {
    MyWorkoutAssistantTheme {
        ExerciseDefinitionForm(
            definition = ExerciseDefinition(
                id = UUID.fromString("11111111-1111-1111-1111-111111111111"),
                name = "Barbell bench press",
                exerciseType = ExerciseType.WEIGHT,
                exerciseCategory = ExerciseCategory.HEAVY_COMPOUND,
            ),
            equipments = emptyList(),
            accessories = emptyList(),
            isReferenced = false,
            onSave = {},
            onCancel = {},
            breadcrumbContent = {
                Text(
                    text = "Library  ›  Barbell bench press",
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 7.dp),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            },
        )
    }
}

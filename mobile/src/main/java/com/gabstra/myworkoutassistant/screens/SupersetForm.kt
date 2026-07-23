package com.gabstra.myworkoutassistant.screens // Or your appropriate package

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.AppTextButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.SetTable
import com.gabstra.myworkoutassistant.composables.SetTableRowUiModel
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.assembly.WorkoutSupersetAssemblyService
import com.gabstra.myworkoutassistant.shared.workout.display.SetDisplayCounterKind
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.buildWorkoutRestRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.displayCounterKindForSetState
import com.gabstra.myworkoutassistant.shared.workout.display.formatWorkoutDurationSecondsForDisplay
import com.gabstra.myworkoutassistant.shared.workout.display.toSupersetLetter
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SupersetForm(
    onSupersetUpsert: (Superset) -> Unit,
    onCancel: () -> Unit,
    availableExercises: List<Exercise>,
    superset: Superset? = null,
    isSaving: Boolean = false
) {

    var selectedExercises by remember { mutableStateOf(superset?.exercises ?: emptyList()) }

    var restBetweenExercisesHms by remember(superset) {
        mutableStateOf(
            TimeConverter.secondsToHms(
                superset?.exercises
                    ?.dropLast(1)
                    ?.firstNotNullOfOrNull { superset.restSecondsByExercise[it.id] }
                    ?: 0
            )
        )
    }
    var restBetweenRoundsHms by remember(superset) {
        mutableStateOf(
            TimeConverter.secondsToHms(
                superset?.exercises?.lastOrNull()?.let { superset.restSecondsByExercise[it.id] }
                    ?: 0
            )
        )
    }
    var selectedExerciseId by remember { mutableStateOf<UUID?>(null) }
    var showAddExerciseDialog by remember { mutableStateOf(false) }
    var showExerciseMovements by remember { mutableStateOf(false) }
    var pendingExerciseIds by remember { mutableStateOf<Set<UUID>>(emptySet()) }
    val exercisesToShow = remember(availableExercises, superset) {
        (availableExercises + (superset?.exercises ?: emptyList())).distinctBy { it.id }
    }

    // Check for a mismatch in the number of sets among selected exercises.
    val areSetCountsMismatched = if (selectedExercises.size > 1) {
        selectedExercises.map { it.sets.size }.toSet().size > 1
    } else {
        false
    }

    val outlineVariant = MaterialTheme.colorScheme.outlineVariant
    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                    drawLine(
                        color = outlineVariant,
                        start = Offset(0f, size.height),
                        end = Offset(size.width, size.height),
                        strokeWidth = 1.dp.toPx()
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = if (superset == null) "Add Superset" else "Edit Superset",
                        color = MaterialTheme.colorScheme.onBackground
                    )
                },
                navigationIcon = {
                    IconButton(
                        onClick = {
                            if (selectedExerciseId != null) selectedExerciseId = null else onCancel()
                        },
                        enabled = !isSaving
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    val selectedIndex = selectedExercises.indexOfFirst { it.id == selectedExerciseId }
                    if (selectedIndex >= 0) {
                        IconButton(
                            enabled = selectedIndex > 0,
                            onClick = {
                                selectedExercises = selectedExercises.toMutableList().apply {
                                    val exercise = removeAt(selectedIndex)
                                    add(selectedIndex - 1, exercise)
                                }
                            }
                        ) {
                            Icon(Icons.Filled.ArrowUpward, contentDescription = "Move up")
                        }
                        IconButton(
                            enabled = selectedIndex < selectedExercises.lastIndex,
                            onClick = {
                                selectedExercises = selectedExercises.toMutableList().apply {
                                    val exercise = removeAt(selectedIndex)
                                    add(selectedIndex + 1, exercise)
                                }
                            }
                        ) {
                            Icon(Icons.Filled.ArrowDownward, contentDescription = "Move down")
                        }
                        IconButton(
                            enabled = selectedExercises.size > 2,
                            onClick = {
                                selectedExercises = selectedExercises.filterNot { it.id == selectedExerciseId }
                                selectedExerciseId = null
                            }
                        ) {
                            Icon(Icons.Filled.Delete, contentDescription = "Remove exercise")
                        }
                    } else {
                        // Balance the navigation icon so the normal title remains centered.
                        IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = null
                            )
                        }
                    }
                }
            )
        }
    ) { paddingValues ->
        val scrollState = rememberScrollState()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(vertical = Spacing.sm)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md),
        ) {
            FormSectionTitle(text = "Superset exercises")
            StyledCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(Spacing.md)
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        selectedExercises.forEachIndexed { index, exercise ->
                            val isSelected = selectedExerciseId == exercise.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Box(
                                    modifier = Modifier.width(Spacing.xl),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = ('A'.code + index).toChar().toString(),
                                        style = MaterialTheme.typography.titleMedium,
                                        color = MaterialTheme.colorScheme.primary
                                    )
                                }

                                Spacer(modifier = Modifier.width(Spacing.sm))

                                Box(modifier = Modifier.fillMaxWidth()) {
                                    StyledCard(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .combinedClickable(
                                                onClick = {
                                                    if (selectedExerciseId != null) {
                                                        selectedExerciseId = if (isSelected) null else exercise.id
                                                    }
                                                },
                                                onLongClick = {
                                                    selectedExerciseId = if (isSelected) null else exercise.id
                                                }
                                            ),
                                        borderColor = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant
                                    ) {
                                        Row(
                                            modifier = Modifier.padding(Spacing.md),
                                            horizontalArrangement = Arrangement.Center,
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            Text(
                                                modifier = Modifier.fillMaxWidth(),
                                                text = exercise.name,
                                                style = MaterialTheme.typography.bodyLarge,
                                                color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
                                            )
                                        }
                                    }
                                }
                            }


                        }

                        AppPrimaryOutlinedButton(
                            text = "Add exercise",
                            onClick = {
                                pendingExerciseIds = emptySet()
                                showAddExerciseDialog = true
                            }
                        )
                    }
                }
            }

            if (areSetCountsMismatched) {
                Spacer(modifier = Modifier.height(Spacing.md))
                Text(
                    text = "Selected exercises have different numbers of sets. The superset will use the lowest set count.",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center
                )
            }

            if (selectedExercises.size >= 2) {
                Spacer(Modifier.height(Spacing.md))
                FormSectionTitle(text = "Rest")
                StyledCard(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(Spacing.md),
                        verticalArrangement = Arrangement.spacedBy(Spacing.md)
                    ) {
                        val lastExerciseName = selectedExercises.last().name
                        Text(
                            if (selectedExercises.size == 2) {
                                "After ${selectedExercises.first().name}"
                            } else {
                                "After each exercise except $lastExerciseName"
                            },
                            style = MaterialTheme.typography.titleMedium
                        )
                        CustomTimePicker(
                            initialHour = restBetweenExercisesHms.first,
                            initialMinute = restBetweenExercisesHms.second,
                            initialSecond = restBetweenExercisesHms.third,
                            onTimeChange = { h, m, s -> restBetweenExercisesHms = Triple(h, m, s) }
                        )
                        Text(
                            "After $lastExerciseName, before next round",
                            style = MaterialTheme.typography.titleMedium
                        )
                        CustomTimePicker(
                            initialHour = restBetweenRoundsHms.first,
                            initialMinute = restBetweenRoundsHms.second,
                            initialSecond = restBetweenRoundsHms.third,
                            onTimeChange = { h, m, s -> restBetweenRoundsHms = Triple(h, m, s) }
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.md))
                FormSectionTitle(text = "Execution preview")
                val previewSuperset = remember(
                    selectedExercises,
                    restBetweenExercisesHms,
                    restBetweenRoundsHms,
                    superset
                ) {
                    val betweenExerciseSeconds = TimeConverter.hmsToTotalSeconds(
                        restBetweenExercisesHms.first,
                        restBetweenExercisesHms.second,
                        restBetweenExercisesHms.third
                    )
                    val betweenRoundSeconds = TimeConverter.hmsToTotalSeconds(
                        restBetweenRoundsHms.first,
                        restBetweenRoundsHms.second,
                        restBetweenRoundsHms.third
                    )
                    Superset(
                        id = superset?.id ?: UUID.randomUUID(),
                        exercises = selectedExercises,
                        restSecondsByExercise = selectedExercises.mapIndexed { index, exercise ->
                            exercise.id to if (index == selectedExercises.lastIndex) {
                                betweenRoundSeconds
                            } else {
                                betweenExerciseSeconds
                            }
                        }.toMap(),
                        enabled = true
                    )
                }
                SupersetExecutionPreview(previewSuperset)
            }

            val exercisesWithMovements = selectedExercises.filter { it.movementRef != null }
            if (exercisesWithMovements.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.md))
                CollapsibleSection(
                    title = "Exercise movements",
                    summary = "${exercisesWithMovements.size} available",
                    expanded = showExerciseMovements,
                    onToggle = { showExerciseMovements = !showExerciseMovements }
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        exercisesWithMovements.forEach { exercise ->
                            ExerciseMovementCard(
                                exercise = exercise,
                                title = "${exercise.name} movement",
                            )
                        }
                    }
                }
            }

            Spacer(Modifier.height(Spacing.xl))

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = Spacing.sm),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    onClick = {
                        val betweenExerciseSeconds = TimeConverter.hmsToTotalSeconds(
                            restBetweenExercisesHms.first,
                            restBetweenExercisesHms.second,
                            restBetweenExercisesHms.third
                        )
                        val betweenRoundSeconds = TimeConverter.hmsToTotalSeconds(
                            restBetweenRoundsHms.first,
                            restBetweenRoundsHms.second,
                            restBetweenRoundsHms.third
                        )
                        val restSecondsByExercise = selectedExercises.mapIndexed { index, exercise ->
                            exercise.id to if (index == selectedExercises.lastIndex) {
                                betweenRoundSeconds
                            } else {
                                betweenExerciseSeconds
                            }
                        }.toMap()

                        val newOrUpdatedSuperset = Superset(
                            id = superset?.id ?: UUID.randomUUID(),
                            exercises = selectedExercises,
                            restSecondsByExercise = restSecondsByExercise,
                            enabled = superset?.enabled ?: true
                        )
                        onSupersetUpsert(newOrUpdatedSuperset)
                    },
                    text = "Save",
                    enabled = selectedExercises.size >= 2,
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.height(Spacing.md))
        }
    }
    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
    }

    if (showAddExerciseDialog) {
        val unselectedExercises = exercisesToShow.filter { candidate ->
            selectedExercises.none { it.id == candidate.id }
        }
        AlertDialog(
            onDismissRequest = { showAddExerciseDialog = false },
            title = { Text("Add exercises") },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    if (unselectedExercises.isEmpty()) {
                        Text("All available exercises are already in this superset.")
                    } else {
                        unselectedExercises.forEach { exercise ->
                            val checked = exercise.id in pendingExerciseIds
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        pendingExerciseIds = if (checked) {
                                            pendingExerciseIds - exercise.id
                                        } else {
                                            pendingExerciseIds + exercise.id
                                        }
                                    },
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = {
                                        pendingExerciseIds = if (checked) {
                                            pendingExerciseIds - exercise.id
                                        } else {
                                            pendingExerciseIds + exercise.id
                                        }
                                    },
                                    colors = CheckboxDefaults.colors().copy(
                                        checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                                    )
                                )
                                Spacer(Modifier.width(Spacing.sm))
                                Text(exercise.name)
                            }
                        }
                    }
                }
            },
            confirmButton = {
                AppTextButton(
                    text = "Add",
                    enabled = pendingExerciseIds.isNotEmpty(),
                    onClick = {
                        selectedExercises = selectedExercises + unselectedExercises.filter {
                            it.id in pendingExerciseIds
                        }
                        showAddExerciseDialog = false
                    }
                )
            },
            dismissButton = {
                AppTextButton(text = "Cancel", onClick = { showAddExerciseDialog = false })
            }
        )
    }
}

@Composable
private fun SupersetExecutionPreview(superset: Superset) {
    val previewStates = remember(superset) {
        WorkoutSupersetAssemblyService().assemblePreviewChildStates(superset)
    }
    val exerciseIndexById = remember(superset.exercises) {
        superset.exercises.mapIndexed { index, exercise -> exercise.id to index }.toMap()
    }
    val rows = remember(previewStates, exerciseIndexById) {
        val counters = mutableMapOf<Pair<UUID, SetDisplayCounterKind>, Int>()
        previewStates.mapNotNull { state ->
            when (state) {
                is WorkoutState.Rest -> SetTableRowUiModel.Rest(buildWorkoutRestRowLabel(state))
                is WorkoutState.Set -> {
                    val exerciseIndex = exerciseIndexById[state.exerciseId] ?: return@mapNotNull null
                    val counterKind = displayCounterKindForSetState(state) ?: return@mapNotNull null
                    val counterKey = state.exerciseId to counterKind
                    val shouldAdvanceCounter = !state.isUnilateral || state.intraSetCounter == 1u
                    if (shouldAdvanceCounter) {
                        counters[counterKey] = (counters[counterKey] ?: 0) + 1
                    }
                    val counter = counters[counterKey] ?: 1
                    val prefix = toSupersetLetter(exerciseIndex)
                    val baseIdentifier = when (counterKind) {
                        SetDisplayCounterKind.Warmup -> "W$prefix$counter"
                        SetDisplayCounterKind.Calibration -> "Cal"
                        SetDisplayCounterKind.Work -> "$prefix$counter"
                    }
                    val identifier = baseIdentifier + (buildUnilateralSideLabel(
                        state.intraSetCounter,
                        state.intraSetTotal
                    ) ?: "")
                    when (val set = state.set) {
                        is WeightSet -> SetTableRowUiModel.Data(
                            identifier = identifier,
                            primaryValue = "${set.weight} kg",
                            secondaryValue = set.reps.toString()
                        )
                        is BodyWeightSet -> SetTableRowUiModel.Data(
                            identifier = identifier,
                            primaryValue = if (set.additionalWeight > 0) "${set.additionalWeight} kg" else "-",
                            secondaryValue = set.reps.toString()
                        )
                        is TimedDurationSet -> SetTableRowUiModel.Data(
                            identifier = identifier,
                            primaryValue = formatWorkoutDurationSecondsForDisplay(set.timeInMillis / 1000),
                            monospacePrimary = true
                        )
                        is EnduranceSet -> SetTableRowUiModel.Data(
                            identifier = identifier,
                            primaryValue = formatWorkoutDurationSecondsForDisplay(set.timeInMillis / 1000),
                            monospacePrimary = true
                        )
                        else -> null
                    }
                }
                else -> null
            }
        }
    }

    StyledCard(modifier = Modifier.fillMaxWidth()) {
        if (rows.isEmpty()) {
            Text(
                text = "Add working sets to preview this superset.",
                modifier = Modifier.padding(Spacing.md),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            SetTable(
                rows = rows,
                enabled = true,
                modifier = Modifier.padding(Spacing.md)
            )
        }
    }
}



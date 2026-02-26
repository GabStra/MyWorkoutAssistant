package com.gabstra.myworkoutassistant.screens // Or your appropriate package

import androidx.compose.foundation.basicMarquee
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
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
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import com.gabstra.myworkoutassistant.Spacing
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

    // State for per-exercise rest times, keyed by exercise ID.
    // Handles both creating a new superset and editing an existing one.
    val restsByExerciseHms = remember(superset) {
        val initialRests = mutableStateMapOf<UUID, Triple<Int, Int, Int>>()
        superset?.restSecondsByExercise?.forEach { (id, seconds) ->
            initialRests[id] = TimeConverter.secondsToHms(seconds)
        }
        initialRests
    }

    // Check for a mismatch in the number of sets among selected exercises.
    val areSetCountsMismatched = if (selectedExercises.size > 1) {
        selectedExercises.map { it.sets.size }.toSet().size > 1
    } else {
        false
    }

    var expandedRestTimes by remember { mutableStateOf(false) }

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
                    IconButton(onClick = onCancel, enabled = !isSaving) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    // This is a common trick to center the title when a navigationIcon is present.
                    IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = null
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        val scrollState = rememberScrollState()

        val exercisesToShow = remember(availableExercises, superset) {
            (availableExercises + (superset?.exercises ?: emptyList())).distinctBy { it.id }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(vertical = Spacing.sm, horizontal = Spacing.lg)
                .verticalColumnScrollbarContainer(scrollState),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            FormSectionTitle(text = "Essentials")
            StyledCard(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Select at least two exercises", style = MaterialTheme.typography.titleMedium)
                        if (selectedExercises.isNotEmpty()) {
                            TextButton(onClick = {
                                selectedExercises = emptyList()
                                restsByExerciseHms.clear()
                            }) {
                                Text("Clear")
                            }
                        }
                    }
                    Spacer(modifier = Modifier.height(Spacing.sm))

                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        exercisesToShow.forEach { exercise ->
                            val isSelected = selectedExercises.any { it.id == exercise.id }

                            StyledCard(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = Spacing.sm)
                                    .clickable {
                                        selectedExercises = if (isSelected) {
                                            selectedExercises
                                                .filter { it.id != exercise.id }
                                                .also { restsByExerciseHms.remove(exercise.id) }
                                        } else {
                                            selectedExercises + exercise
                                        }
                                    },
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
                val restSummary = "Rest times for ${selectedExercises.size} exercises"
                CollapsibleSection(
                    title = "Rest after each exercise",
                    summary = restSummary,
                    expanded = expandedRestTimes,
                    onToggle = { expandedRestTimes = !expandedRestTimes }
                ) {
                    selectedExercises.forEach { exercise ->
                        val hms = restsByExerciseHms.getOrPut(exercise.id) { Triple(0, 0, 0) }
                        val (h, m, s) = hms

                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                        ) {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = exercise.name,
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start
                            )
                            CustomTimePicker(
                                initialHour = h,
                                initialMinute = m,
                                initialSecond = s,
                                onTimeChange = { newHour, newMinute, newSecond ->
                                    restsByExerciseHms[exercise.id] = Triple(newHour, newMinute, newSecond)
                                }
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
                        // Convert the H:M:S triples into a map of [UUID, Int] for total seconds
                        val restSecondsByExercise = selectedExercises.associate { ex ->
                            val (h, m, s) = restsByExerciseHms[ex.id] ?: Triple(0, 0, 0)
                            ex.id to TimeConverter.hmsToTotalSeconds(h, m, s)
                        }

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
}



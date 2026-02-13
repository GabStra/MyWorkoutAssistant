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
import com.gabstra.myworkoutassistant.composables.FormPrimaryButton
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.FormSecondaryButton
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
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

    // START of new code
    // Check for a mismatch in the number of sets among selected exercises.
    val areSetCountsMismatched = if (selectedExercises.size > 1) {
        selectedExercises.map { it.sets.size }.toSet().size > 1
    } else {
        false
    }
    // END of new code

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
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(20.dp))

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("Select at least two exercises", style = MaterialTheme.typography.titleMedium)
                // NEW: Show button only if there is a selection to clear
                if (selectedExercises.isNotEmpty()) {
                    TextButton(onClick = {
                        selectedExercises = emptyList()
                        restsByExerciseHms.clear()
                    }) {
                        Text("Clear")
                    }
                }
            }
            Spacer(modifier = Modifier.height(10.dp))

            Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                exercisesToShow.forEach { exercise ->
                    val isSelected = selectedExercises.any { it.id == exercise.id }

                    StyledCard(
                        modifier = Modifier.padding(vertical = 6.dp).clickable {
                            selectedExercises = if (isSelected) {
                                selectedExercises
                                    .filter { it.id != exercise.id }
                                    .also { restsByExerciseHms.remove(exercise.id) } // Remove rest time if deselected
                            } else {
                                selectedExercises + exercise
                            }
                        },
                        borderColor = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant
                    ) {
                        Row(
                            modifier = Modifier.padding(15.dp),
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

            // START of new code
            // Display a warning if the set counts are mismatched.
            if (areSetCountsMismatched) {
                Spacer(modifier = Modifier.height(15.dp))
                Text(
                    text = "WARNING\nSelected exercises have different numbers of sets.\nThe superset will be limited to the lowest set count, extra sets will be pruned.",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = 16.dp),
                    textAlign = TextAlign.Center
                )
            }
            // END of new code

            Spacer(modifier = Modifier.height(25.dp))

            if (selectedExercises.size >= 2) {
                Text("Rest Time After Each Exercise", style = MaterialTheme.typography.titleMedium)
                Spacer(modifier = Modifier.height(15.dp))

                selectedExercises.forEach { exercise ->
                    val hms = restsByExerciseHms.getOrPut(exercise.id) { Triple(0, 0, 0) }
                    val (h, m, s) = hms

                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 6.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = exercise.name,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center
                        )
                        CustomTimePicker(
                            initialHour = h,
                            initialMinute = m,
                            initialSecond = s,
                            onTimeChange = { newHour, newMinute, newSecond ->
                                // Update the map with the new time for this specific exercise
                                restsByExerciseHms[exercise.id] = Triple(newHour, newMinute, newSecond)
                            }
                        )
                    }
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                FormSecondaryButton(
                    text = "Cancel",
                    onClick = onCancel,
                    modifier = Modifier.weight(1f)
                )

                FormPrimaryButton(
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

            Spacer(modifier = Modifier.height(10.dp))
        }
    }
    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
    }
}

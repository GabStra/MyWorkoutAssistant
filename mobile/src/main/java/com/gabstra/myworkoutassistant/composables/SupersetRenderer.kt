package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset

/**
 * Data class representing an execution step in a superset
 */
private data class SupersetExecutionStep(
    val identifier: String, // e.g., "A1", "B1", "REST"
    val exerciseId: java.util.UUID? = null,
    val set: Set? = null,
    val restSeconds: Int? = null,
    val exerciseIndex: Int? = null, // Index in the superset exercises list for identifier (A=0, B=1, etc.)
)

@Composable
fun SupersetRenderer(
    superset: Superset,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
    onExerciseClick: ((java.util.UUID) -> Unit)? = null
) {
    // Generate execution order matching WorkoutViewModel.generateWorkoutStates() logic
    val executionSteps = rememberExecutionOrder(superset, showRest)
    
    // Create title with exercise names
    val exerciseNames = superset.exercises.joinToString(", ") { it.name }
    val titleText = "Superset: $exerciseNames"

    val borderColor = if (superset.enabled) {
        MaterialTheme.colorScheme.outlineVariant
    } else {
        DisabledContentGray.copy(alpha = 0.38f)
    }
    
    ExpandableContainer(
        isOpen = false,
        modifier = modifier
            .fillMaxWidth()
            .border(1.dp, borderColor),
        isExpandable = true,
        titleModifier = titleModifier,
        title = { m ->
            Text(
                modifier = m
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = titleText,
                style = MaterialTheme.typography.bodyLarge,
                color = if (superset.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
            )
        },
        content = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                val textColor = if (superset.enabled) {
                    MaterialTheme.colorScheme.onBackground
                } else {
                    DisabledContentGray
                }

                // Legend section
                Text(
                    text = "Legend:",
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold),
                    color = textColor,
                )
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    superset.exercises.forEachIndexed { index, exercise ->
                        val identifier = ('A'.code + index).toChar().toString()
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Start,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "$identifier:",
                                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                                color = textColor,
                                modifier = Modifier.padding(end = 8.dp)
                            )
                            ScrollableTextColumn(
                                text = exercise.name,
                                modifier = Modifier.weight(1f),
                                maxLines = 2,
                                style = MaterialTheme.typography.bodyMedium,
                                color = textColor,
                            )
                        }
                    }
                }

                // Execution order table
                if (executionSteps.isNotEmpty()) {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        color = MaterialTheme.colorScheme.surface
                    ) {
                        Column {
                            // Table header - determine what columns to show
                            val hasWeightRepsExercises = superset.exercises.any { exercise ->
                                exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT
                            }
                            
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                                    .padding(vertical = 6.dp, horizontal = 12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "SET",
                                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                                    textAlign = TextAlign.Center,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                if (hasWeightRepsExercises) {
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "WEIGHT (KG)",
                                        style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                                        textAlign = TextAlign.Center,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "REPS",
                                        style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                                        textAlign = TextAlign.Center,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                } else {
                                    Text(
                                        modifier = Modifier.weight(2f),
                                        text = "TIME",
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                }
                            }

                            executionSteps.forEachIndexed { stepIndex, step ->
                                if (step.restSeconds != null) {
                                    // Show rest row
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 12.dp, vertical = 8.dp),
                                        horizontalArrangement = Arrangement.Center,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            "REST ${formatTime(step.restSeconds)}",
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = textColor,
                                        )
                                    }
                                } else if (step.set != null && step.exerciseIndex != null) {
                                    // Show set row
                                    val exercise = superset.exercises[step.exerciseIndex]
                                    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
                                    
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 12.dp, vertical = 8.dp)
                                            .then(
                                                if (onExerciseClick != null) {
                                                    Modifier.clickable { onExerciseClick(exercise.id) }
                                                } else {
                                                    Modifier
                                                }
                                            ),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = step.identifier,
                                            style = MaterialTheme.typography.bodyMedium,
                                            textAlign = TextAlign.Center,
                                            color = textColor,
                                        )
                                        when (step.set) {
                                            is WeightSet -> {
                                                val weightText = equipment?.formatWeight(step.set.weight) ?: "${step.set.weight}"
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = weightText,
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = "${step.set.reps}",
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                            }

                                            is BodyWeightSet -> {
                                                val weightText = when {
                                                    step.set.additionalWeight > 0 -> equipment?.formatWeight(step.set.additionalWeight) ?: "${step.set.additionalWeight}"
                                                    else -> "-"
                                                }
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = weightText,
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = "${step.set.reps}",
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                            }

                                            is TimedDurationSet -> {
                                                Text(
                                                    modifier = Modifier.weight(2f),
                                                    text = formatTime(step.set.timeInMillis / 1000),
                                                    style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                                    textAlign = TextAlign.Center,
                                                    color = textColor,
                                                )
                                            }

                                            is EnduranceSet -> {
                                                Text(
                                                    modifier = Modifier.weight(2f),
                                                    text = formatTime(step.set.timeInMillis / 1000),
                                                    style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                                    textAlign = TextAlign.Center,
                                                    color = textColor,
                                                )
                                            }
                                            else -> {
                                                // Fallback for unknown set types
                                                Text(
                                                    modifier = Modifier.weight(2f),
                                                    text = "-",
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                            }
                                        }
                                    }
                                }

                                if (stepIndex < executionSteps.size - 1) {
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant,
                                        modifier = Modifier.padding(horizontal = 12.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    )
}

/**
 * Calculate the execution order of a superset matching WorkoutViewModel.generateWorkoutStates() logic
 * This matches the markdown export logic as well
 */
@Composable
private fun rememberExecutionOrder(superset: Superset, showRest: Boolean): List<SupersetExecutionStep> {
    return androidx.compose.runtime.remember(superset, showRest) {
        // Build lists of work sets (excluding rest sets and warm-up sets) for each exercise
        val exerciseWorkSets = superset.exercises.map { exercise ->
            val allSets = if (showRest) exercise.sets else exercise.sets.filter { it !is RestSet }
            allSets.filter { set ->
                // Filter out RestSets and WarmupSets - only show work sets
                when (set) {
                    is RestSet -> false
                    is BodyWeightSet -> set.subCategory != SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory != SetSubCategory.WarmupSet
                    else -> true // TimedDurationSet, EnduranceSet, etc. don't have warm-up subcategory
                }
            }
        }

        // Determine number of rounds (minimum number of sets across exercises)
        val rounds = exerciseWorkSets.minOfOrNull { it.size } ?: 0

        val executionSteps = mutableListOf<SupersetExecutionStep>()

        // Display alternating sets with rest after each exercise (matching WorkoutViewModel logic)
        for (round in 0 until rounds) {
            val isLastRound = round == rounds - 1
            superset.exercises.forEachIndexed { exerciseIndex, exercise ->
                if (round < exerciseWorkSets[exerciseIndex].size) {
                    val set = exerciseWorkSets[exerciseIndex][round]
                    val identifier = ('A'.code + exerciseIndex).toChar().toString() + (round + 1).toString()
                    
                    executionSteps.add(
                        SupersetExecutionStep(
                            identifier = identifier,
                            exerciseId = exercise.id,
                            set = set,
                            exerciseIndex = exerciseIndex
                        )
                    )

                    // Add rest after each exercise (from restSecondsByExercise, matching WorkoutViewModel)
                    // Skip rest after the last exercise in the last round (last set can't be a rest)
                    val isLastExerciseInLastRound = isLastRound && exerciseIndex == superset.exercises.size - 1
                    
                    if (!isLastExerciseInLastRound) {
                        val restAfter = superset.restSecondsByExercise[exercise.id] ?: 0
                        if (restAfter > 0 && showRest) {
                            executionSteps.add(
                                SupersetExecutionStep(
                                    identifier = "REST",
                                    restSeconds = restAfter
                                )
                            )
                        }
                    }
                }
            }
        }

        executionSteps
    }
}


package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset

private data class SupersetExecutionStep(
    val identifier: String,
    val exerciseId: java.util.UUID? = null,
    val set: Set? = null,
    val restSeconds: Int? = null,
    val exerciseIndex: Int? = null,
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
    val executionSteps = rememberExecutionOrder(superset, showRest)
    val textColor = if (superset.enabled) {
        MaterialTheme.colorScheme.onBackground
    } else {
        DisabledContentGray
    }

    StyledCard(
        modifier = modifier.fillMaxWidth(),
        enabled = superset.enabled
    ) {
        ExpandableContainer(
            isOpen = false,
            modifier = Modifier.fillMaxWidth(),
            isExpandable = true,
            titleModifier = titleModifier,
            title = { m ->
                Text(
                    modifier = m
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp),
                    text = "Superset",
                    style = MaterialTheme.typography.bodyLarge,
                    color = textColor,
                )
            },
            subContent = {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp)
                        .padding(bottom = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp)
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
                                modifier = Modifier.padding(end = 10.dp)
                            )
                            Text(
                                text = exercise.name,
                                modifier = Modifier.weight(1f),
                                style = MaterialTheme.typography.bodyMedium,
                                color = textColor,
                            )
                        }
                    }
                }
            },
            content = {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    val rows = mutableListOf<SetTableRowUiModel>()
                    executionSteps.forEach { step ->
                        if (step.restSeconds != null) {
                            rows += SetTableRowUiModel.Rest(
                                text = "REST ${formatTime(step.restSeconds)}",
                            )
                        } else if (step.set != null && step.exerciseIndex != null) {
                            val exercise = superset.exercises[step.exerciseIndex]
                            val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
                            val onClick = if (onExerciseClick != null) {
                                { onExerciseClick(exercise.id) }
                            } else {
                                null
                            }

                            when (step.set) {
                                is WeightSet -> {
                                    rows += SetTableRowUiModel.Data(
                                        identifier = step.identifier,
                                        primaryValue = equipment?.formatWeight(step.set.weight) ?: "${step.set.weight} kg",
                                        secondaryValue = "${step.set.reps}",
                                        onClick = onClick,
                                    )
                                }

                                is BodyWeightSet -> {
                                    val weightText = if (step.set.additionalWeight > 0) {
                                        equipment?.formatWeight(step.set.additionalWeight)
                                            ?: "${step.set.additionalWeight} kg"
                                    } else {
                                        "-"
                                    }
                                    rows += SetTableRowUiModel.Data(
                                        identifier = step.identifier,
                                        primaryValue = weightText,
                                        secondaryValue = "${step.set.reps}",
                                        onClick = onClick,
                                    )
                                }

                                is TimedDurationSet -> {
                                    rows += SetTableRowUiModel.Data(
                                        identifier = step.identifier,
                                        primaryValue = formatTime(step.set.timeInMillis / 1000),
                                        secondaryValue = null,
                                        monospacePrimary = true,
                                        onClick = onClick,
                                        secondaryText = "Recorded duration",
                                    )
                                }

                                is EnduranceSet -> {
                                    rows += SetTableRowUiModel.Data(
                                        identifier = step.identifier,
                                        primaryValue = formatTime(step.set.timeInMillis / 1000),
                                        secondaryValue = null,
                                        monospacePrimary = true,
                                        onClick = onClick,
                                        secondaryText = "Recorded duration",
                                    )
                                }

                                else -> {
                                    rows += SetTableRowUiModel.Data(
                                        identifier = step.identifier,
                                        primaryValue = "-",
                                        secondaryValue = null,
                                        onClick = onClick,
                                    )
                                }
                            }
                        }
                    }

                    SetTable(
                        rows = rows,
                        enabled = superset.enabled,
                    )
                }
            }
        )
    }
}

@Composable
private fun rememberExecutionOrder(superset: Superset, showRest: Boolean): List<SupersetExecutionStep> {
    return androidx.compose.runtime.remember(superset, showRest) {
        val exerciseWorkSets = superset.exercises.map { exercise ->
            val allSets = if (showRest) exercise.sets else exercise.sets.filter { it !is RestSet }
            allSets.filter { set ->
                when (set) {
                    is RestSet -> false
                    is BodyWeightSet -> set.subCategory != SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory != SetSubCategory.WarmupSet
                    else -> true
                }
            }
        }

        val rounds = exerciseWorkSets.minOfOrNull { it.size } ?: 0
        val executionSteps = mutableListOf<SupersetExecutionStep>()

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

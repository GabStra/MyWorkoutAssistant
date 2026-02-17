package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
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
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun ExerciseRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
    customTitle: (@Composable (Modifier) -> Unit)? = null
) {
    var sets = exercise.sets

    if (!showRest) {
        sets = sets.filter { it !is RestSet }
    }

    if (sets.isEmpty()) {
        Row(
            modifier = modifier.then(titleModifier).padding(15.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                maxLines = 2,
                style = MaterialTheme.typography.bodyLarge,
                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
            )
        }
    } else {
        ExpandableContainer(
            isOpen = false,
            modifier = modifier.fillMaxWidth(),
            isExpandable = true,
            titleModifier = titleModifier,
            title = { m ->
                if (customTitle != null) {
                    customTitle(m)
                } else {
                    Text(
                        modifier = m
                            .padding(horizontal = 10.dp)
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = exercise.name,
                        maxLines = 2,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                    )
                }
            },
            content = {
                Column(
                    modifier = Modifier.padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
                    val accessoryEquipments = (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                        appViewModel.getAccessoryEquipmentById(id)
                    }
                    val textColor = if (exercise.enabled) {
                        MaterialTheme.colorScheme.onBackground
                    } else {
                        DisabledContentGray
                    }

                    ExerciseMetadataStrip(
                        equipmentName = equipment?.name,
                        accessoryNames = accessoryEquipments.joinToString(", ") { it.name }.takeIf { accessoryEquipments.isNotEmpty() },
                        textColor = textColor,
                        modifier = Modifier.fillMaxWidth()
                    )

                    val rows = mutableListOf<SetTableRowUiModel>()
                    var index = 0
                    sets.forEach { set ->
                        when (set) {
                            is RestSet -> {
                                rows += SetTableRowUiModel.Rest(
                                    text = "REST ${formatTime(set.timeInSeconds)}",
                                )
                            }

                            is WeightSet -> {
                                index += 1
                                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                                    exercise = exercise,
                                    set = set
                                )
                                val weightText = if (isCalibrationManagedWorkSet) {
                                    CalibrationUiLabels.Tbd
                                } else {
                                    equipment?.formatWeight(set.weight) ?: "${set.weight} kg"
                                }
                                rows += SetTableRowUiModel.Data(
                                    identifier = index.toString(),
                                    primaryValue = weightText,
                                    secondaryValue = "${set.reps}",
                                )
                            }

                            is BodyWeightSet -> {
                                index += 1
                                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                                    exercise = exercise,
                                    set = set
                                )
                                val weightText = when {
                                    isCalibrationManagedWorkSet -> CalibrationUiLabels.Tbd
                                    set.additionalWeight > 0 -> equipment?.formatWeight(set.additionalWeight)
                                        ?: "${set.additionalWeight} kg"

                                    else -> "-"
                                }
                                rows += SetTableRowUiModel.Data(
                                    identifier = index.toString(),
                                    primaryValue = weightText,
                                    secondaryValue = "${set.reps}",
                                )
                            }

                            is TimedDurationSet -> {
                                index += 1
                                rows += SetTableRowUiModel.Data(
                                    identifier = index.toString(),
                                    primaryValue = formatTime(set.timeInMillis / 1000),
                                    secondaryValue = null,
                                    monospacePrimary = true,
                                    secondaryText = "Recorded duration",
                                )
                            }

                            is EnduranceSet -> {
                                index += 1
                                rows += SetTableRowUiModel.Data(
                                    identifier = index.toString(),
                                    primaryValue = formatTime(set.timeInMillis / 1000),
                                    secondaryValue = null,
                                    monospacePrimary = true,
                                    secondaryText = "Recorded duration",
                                )
                            }
                        }
                    }

                    SetTable(
                        rows = rows,
                        enabled = exercise.enabled,
                    )
                }
            }
        )
    }
}

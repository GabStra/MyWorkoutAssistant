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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun historyExerciseNameTextStyle(): TextStyle =
    MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold)

fun buildExerciseTemplateRows(
    sets: List<Set>,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
): List<SetTableRowUiModel> {
    val rows = mutableListOf<SetTableRowUiModel>()
    val identifierCounter = SetRowIdentifierCounter()
    sets.forEach { set ->
        when (set) {
            is RestSet -> {
                rows += SetTableRowUiModel.Rest(
                    text = "REST ${formatTime(set.timeInSeconds)}",
                )
            }

            is WeightSet -> {
                val subCategory = resolveSetSubCategory(set)
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
                    identifier = identifierCounter.nextIdentifier(subCategory),
                    primaryValue = weightText,
                    secondaryValue = "${set.reps}",
                )
            }

            is BodyWeightSet -> {
                val subCategory = resolveSetSubCategory(set)
                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                    exercise = exercise,
                    set = set
                )
                val weightText = when {
                    isCalibrationManagedWorkSet -> CalibrationUiLabels.Tbd
                    set.additionalWeight > 0 -> equipment?.formatWeight(set.additionalWeight)
                        ?: "${set.additionalWeight} kg"
                    else -> "BW"
                }
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(subCategory),
                    primaryValue = weightText,
                    secondaryValue = "${set.reps}",
                )
            }

            is TimedDurationSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }

            is EnduranceSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }
        }
    }
    return rows
}

private fun buildExerciseHistoryRows(
    sets: List<Set>,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
    setHistories: List<SetHistory>,
    intraExerciseRestHistories: List<RestHistory>,
): List<SetTableRowUiModel> {
    val rows = mutableListOf<SetTableRowUiModel>()
    val identifierCounter = SetRowIdentifierCounter()
    sets.forEach { set ->
        when (set) {
            is RestSet -> {
                val restText = intraExerciseRestHistories
                    .firstOrNull { it.restSetId == set.id }
                    ?.let { formatRestHistoryDisplayLine(it) }
                    ?: setHistories
                        .firstOrNull { it.setId == set.id && it.setData is RestSetData }
                        ?.let { formatHistoricalRestValue(it) }
                    ?: "REST ${formatTime(set.timeInSeconds)}"
                rows += SetTableRowUiModel.Rest(text = restText)
            }

            is WeightSet -> {
                val subCategory = resolveSetSubCategory(set)
                val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(set)
                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                    exercise = exercise,
                    set = set
                )
                val weightText = if (isCalibrationManagedWorkSet) {
                    CalibrationUiLabels.Tbd
                } else {
                    equipment?.formatWeight(set.weight) ?: "${set.weight} kg"
                }
                val rirFromHistory = if (isCalibrationSet) {
                    when (val d = setHistories.firstOrNull { it.setId == set.id }?.setData) {
                        is WeightSetData -> d.calibrationRIR
                        else -> null
                    }
                } else {
                    null
                }
                val secondaryReps = if (rirFromHistory != null) {
                    "${set.reps} (RIR $rirFromHistory)"
                } else {
                    "${set.reps}"
                }
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(subCategory),
                    primaryValue = weightText,
                    secondaryValue = secondaryReps,
                )
            }

            is BodyWeightSet -> {
                val subCategory = resolveSetSubCategory(set)
                val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(set)
                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                    exercise = exercise,
                    set = set
                )
                val weightText = when {
                    isCalibrationManagedWorkSet -> CalibrationUiLabels.Tbd
                    else -> {
                        val historyData = setHistories
                            .firstOrNull { it.setId == set.id }
                            ?.setData as? BodyWeightSetData
                        if (historyData != null) {
                            formatHistoricalBodyWeightSetValue(
                                setData = historyData,
                                equipment = equipment
                            )
                        } else {
                            if (set.additionalWeight > 0) equipment?.formatWeight(set.additionalWeight)
                                ?: "${set.additionalWeight} kg" else "-"
                        }
                    }
                }
                val rirFromHistory = if (isCalibrationSet) {
                    when (val d = setHistories.firstOrNull { it.setId == set.id }?.setData) {
                        is BodyWeightSetData -> d.calibrationRIR
                        else -> null
                    }
                } else {
                    null
                }
                val secondaryReps = if (rirFromHistory != null) {
                    "${set.reps} (RIR $rirFromHistory)"
                } else {
                    "${set.reps}"
                }
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(subCategory),
                    primaryValue = weightText,
                    secondaryValue = secondaryReps,
                )
            }

            is TimedDurationSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }

            is EnduranceSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }
        }
    }
    return rows
}

@Composable
private fun ExerciseTitleOnlyRow(
    exercise: Exercise,
    modifier: Modifier,
    titleModifier: Modifier,
) {
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
            style = historyExerciseNameTextStyle(),
            color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
        )
    }
}

@Composable
private fun ExerciseExpandableSetTableBody(
    exercise: Exercise,
    modifier: Modifier,
    titleModifier: Modifier,
    initiallyExpanded: Boolean,
    equipment: WeightLoadedEquipment?,
    appViewModel: AppViewModel,
    title: @Composable (Modifier) -> Unit,
    rows: List<SetTableRowUiModel>,
) {
    ExpandableContainer(
        isOpen = initiallyExpanded,
        modifier = modifier.fillMaxWidth(),
        isExpandable = true,
        titleModifier = titleModifier,
        title = title,
        content = {
            Column(
                modifier = Modifier.padding(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                val accessoryEquipments = (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                    appViewModel.getAccessoryEquipmentById(id)
                }
                val metadataTextColor = if (exercise.enabled) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    DisabledContentGray
                }

                    ExerciseMetadataStrip(
                        equipmentName = equipment?.name,
                    accessoryNameList = accessoryEquipments.map { it.name },
                    textColor = metadataTextColor,
                    modifier = Modifier.fillMaxWidth(),
                )

                SetTable(
                    rows = rows,
                    enabled = exercise.enabled,
                )
            }
        }
    )
}

@Composable
fun ExerciseTemplateRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
) {
    var sets = exercise.sets
    if (!showRest) {
        sets = sets.filter { it !is RestSet }
    }

    if (sets.isEmpty()) {
        ExerciseTitleOnlyRow(
            exercise = exercise,
            modifier = modifier,
            titleModifier = titleModifier,
        )
        return
    }

    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
    val rows = remember(exercise.id, showRest, sets, equipment?.id) {
        buildExerciseTemplateRows(sets, exercise, equipment)
    }

    ExerciseExpandableSetTableBody(
        exercise = exercise,
        modifier = modifier,
        titleModifier = titleModifier,
        initiallyExpanded = false,
        equipment = equipment,
        appViewModel = appViewModel,
        title = { m ->
            Text(
                modifier = m
                    .padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                maxLines = 2,
                style = historyExerciseNameTextStyle(),
                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
            )
        },
        rows = rows,
    )
}

@Composable
fun ExerciseHistoryRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    intraExerciseRestHistories: List<RestHistory> = emptyList(),
    customTitle: (@Composable (Modifier) -> Unit)? = null,
) {
    var sets = exercise.sets
    if (!showRest) {
        sets = sets.filter { it !is RestSet }
    }

    if (sets.isEmpty()) {
        ExerciseTitleOnlyRow(
            exercise = exercise,
            modifier = modifier,
            titleModifier = titleModifier,
        )
        return
    }

    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
    val rows = remember(
        exercise.id,
        showRest,
        sets,
        equipment?.id,
        setHistories,
        intraExerciseRestHistories,
    ) {
        buildExerciseHistoryRows(
            sets = sets,
            exercise = exercise,
            equipment = equipment,
            setHistories = setHistories,
            intraExerciseRestHistories = intraExerciseRestHistories,
        )
    }

    ExerciseExpandableSetTableBody(
        exercise = exercise,
        modifier = modifier,
        titleModifier = titleModifier,
        initiallyExpanded = true,
        equipment = equipment,
        appViewModel = appViewModel,
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
                    style = historyExerciseNameTextStyle(),
                    color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
            }
        },
        rows = rows,
    )
}

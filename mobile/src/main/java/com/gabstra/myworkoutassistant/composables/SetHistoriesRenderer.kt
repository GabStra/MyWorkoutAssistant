package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun SetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    appViewModel: AppViewModel,
    workout: Workout,
    showMetadata: Boolean = true,
) {
    if (setHistories.isEmpty()) {
        return
    }

    val firstHistory = setHistories[0]
    val exerciseId = firstHistory.exerciseId ?: return
    val exercise = appViewModel.getExerciseById(workout, exerciseId) ?: return

    // Prefer historical equipment snapshot when available so later equipment edits
    // do not change how past sessions are labeled or formatted.
    val historicalEquipmentName = firstHistory.equipmentNameSnapshot
    val historicalEquipmentId = firstHistory.equipmentIdSnapshot

    val equipment = when {
        historicalEquipmentId != null -> appViewModel.getEquipmentById(historicalEquipmentId)
        else -> exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
    }

    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val equipmentName = when {
            !historicalEquipmentName.isNullOrBlank() -> historicalEquipmentName
            equipment != null -> equipment.name
            else -> null
        }
        if (showMetadata) {
            val accessoryNames = (exercise.requiredAccessoryEquipmentIds ?: emptyList())
                .mapNotNull { id -> appViewModel.getAccessoryEquipmentById(id)?.name }
            EquipmentAccessoryMetadata(
                equipmentName = equipmentName,
                accessoryNames = accessoryNames,
            )
        }

        val rows = mutableListOf<SetTableRowUiModel>()
        val identifierCounter = SetRowIdentifierCounter()
        setHistories.forEach { set ->
            val setData = set.setData
            if (setData is RestSetData) {
                rows += SetTableRowUiModel.Rest(
                    text = formatHistoricalRestValue(set)
                )
                return@forEach
            }

            val setSubCategory = resolveSetSubCategory(setData)
            val identifier = identifierCounter.nextIdentifier(setSubCategory)
            when (setData) {
                is WeightSetData -> {
                    val isCal = setData.subCategory == SetSubCategory.CalibrationSet
                    val secondary = if (isCal && setData.calibrationRIR != null) {
                        "${setData.actualReps} (RIR ${setData.calibrationRIR})"
                    } else {
                        "${setData.actualReps}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = identifier,
                        primaryValue = equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg",
                        secondaryValue = secondary,
                    )
                }

                is BodyWeightSetData -> {
                    val isCal = setData.subCategory == SetSubCategory.CalibrationSet
                    val secondary = if (isCal && setData.calibrationRIR != null) {
                        "${setData.actualReps} (RIR ${setData.calibrationRIR})"
                    } else {
                        "${setData.actualReps}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = identifier,
                        primaryValue = formatHistoricalBodyWeightSetValue(
                            setData = setData,
                            equipment = equipment
                        ),
                        secondaryValue = secondary,
                    )
                }

                is TimedDurationSetData -> {
                    val primaryTime = if (setData.endTimer == 0) {
                        formatSecondsToMinutesSeconds(setData.startTimer / 1000)
                    } else {
                        "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = identifier,
                        primaryValue = primaryTime,
                        secondaryValue = null,
                    )
                }

                is EnduranceSetData -> {
                    val primaryTime = if (setData.endTimer == 0) {
                        formatSecondsToMinutesSeconds(setData.startTimer / 1000)
                    } else {
                        "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = identifier,
                        primaryValue = primaryTime,
                        secondaryValue = null,
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

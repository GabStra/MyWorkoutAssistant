package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun SetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    appViewModel: AppViewModel,
    workout: Workout
) {
    if (setHistories.isEmpty()) {
        return
    }

    val exerciseId = setHistories[0].exerciseId ?: return
    val exercise = appViewModel.getExerciseById(workout, exerciseId) ?: return
    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }

    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (equipment != null) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
                text = "Equipment: ${equipment.name}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        val rows = mutableListOf<SetTableRowUiModel>()
        var index = 0
        setHistories.forEach { set ->
            val setData = set.setData
            if (setData is RestSetData) {
                rows += SetTableRowUiModel.Rest(
                    text = "REST ${formatTime(setData.startTimer)}"
                )
                return@forEach
            }

            index += 1
            when (setData) {
                is WeightSetData -> {
                    rows += SetTableRowUiModel.Data(
                        identifier = index.toString(),
                        primaryValue = equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg",
                        secondaryValue = "${setData.actualReps}",
                    )
                }

                is BodyWeightSetData -> {
                    val weightText = if (setData.additionalWeight > 0) {
                        equipment?.formatWeight(setData.additionalWeight) ?: "${setData.additionalWeight} kg"
                    } else {
                        "-"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = index.toString(),
                        primaryValue = weightText,
                        secondaryValue = "${setData.actualReps}",
                    )
                }

                is TimedDurationSetData -> {
                    val primaryTime = if (setData.endTimer == 0) {
                        formatSecondsToMinutesSeconds(setData.startTimer / 1000)
                    } else {
                        "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = index.toString(),
                        primaryValue = primaryTime,
                        secondaryValue = null,
                        monospacePrimary = true,
                    )
                }

                is EnduranceSetData -> {
                    val primaryTime = if (setData.endTimer == 0) {
                        formatSecondsToMinutesSeconds(setData.startTimer / 1000)
                    } else {
                        "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
                    }
                    rows += SetTableRowUiModel.Data(
                        identifier = index.toString(),
                        primaryValue = primaryTime,
                        secondaryValue = null,
                        monospacePrimary = true,
                    )
                }

                else -> throw IllegalArgumentException("Unknown set type")
            }
        }

        SetTable(
            rows = rows,
            enabled = exercise.enabled,
        )
    }
}

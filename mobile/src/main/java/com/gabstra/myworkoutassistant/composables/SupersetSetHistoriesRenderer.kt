package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

@Composable
fun SupersetSetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    restHistories: List<RestHistory> = emptyList(),
    workout: Workout,
    getEquipmentById: (UUID) -> WeightLoadedEquipment? = { null }
) {
    if (setHistories.isEmpty() && restHistories.isEmpty()) return

    val exerciseNameById = workout.workoutComponents
        .filterIsInstance<Superset>()
        .flatMap { it.exercises }
        .associate { it.id to it.name }

    val timeline = mergeSessionTimeline(setHistories, restHistories)

    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        timeline.forEach { item ->
            when (item) {
                is SessionTimelineItem.SetStep -> {
                    val history = item.history
                    val round = (history.supersetRound?.toInt() ?: history.order.toInt()) + 1
                    val exerciseName = history.exerciseId?.let { exerciseNameById[it] } ?: "Exercise"
                    val equipment = history.equipmentIdSnapshot?.let(getEquipmentById)
                    val value = formatSetValue(history, equipment)
                    val calibrationPrefix = history.setData.let { sd ->
                        when (sd) {
                            is WeightSetData -> sd.subCategory == SetSubCategory.CalibrationSet
                            is BodyWeightSetData -> sd.subCategory == SetSubCategory.CalibrationSet
                            else -> false
                        }
                    }.let { if (it) "Calibration • " else "" }
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        text = "R$round • $exerciseName: $calibrationPrefix$value",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                }
                is SessionTimelineItem.RestStep -> {
                    val rh = item.history
                    val exerciseName = rh.exerciseId?.let { exerciseNameById[it] } ?: "Rest"
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        text = "Rest • $exerciseName: ${formatRestHistoryDisplayLine(rh)}",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                }
            }
        }
    }
}

private fun formatSetValue(history: SetHistory, equipment: WeightLoadedEquipment?): String {
    return when (val setData = history.setData) {
        is WeightSetData -> {
            val weightStr = equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg"
            val base = "$weightStr x ${setData.actualReps}"
            if (setData.subCategory == SetSubCategory.CalibrationSet && setData.calibrationRIR != null) {
                "$base, RIR ${setData.calibrationRIR}"
            } else {
                base
            }
        }
        is BodyWeightSetData -> {
            val base =
                "${formatHistoricalBodyWeightSetValue(setData, equipment)} x ${setData.actualReps}"
            if (setData.subCategory == SetSubCategory.CalibrationSet && setData.calibrationRIR != null) {
                "$base, RIR ${setData.calibrationRIR}"
            } else {
                base
            }
        }
        is TimedDurationSetData -> {
            val elapsedSec = (setData.startTimer - setData.endTimer).coerceAtLeast(0) / 1000
            formatTime(elapsedSec)
        }
        is EnduranceSetData -> formatTime((setData.endTimer / 1000).coerceAtLeast(0))
        is RestSetData -> formatRestDurationFromSetHistoryRest(history)
    }
}

private fun formatRestDurationFromSetHistoryRest(history: SetHistory): String {
    val sd = history.setData as? RestSetData ?: return "Rest"
    return "REST ${formatTime(sd.startTimer.coerceAtLeast(0))}"
}

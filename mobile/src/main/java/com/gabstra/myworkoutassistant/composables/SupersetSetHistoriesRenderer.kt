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
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

@Composable
fun SupersetSetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    workout: Workout,
    getEquipmentById: (UUID) -> WeightLoadedEquipment? = { null }
) {
    if (setHistories.isEmpty()) return

    val exerciseNameById = workout.workoutComponents
        .filterIsInstance<Superset>()
        .flatMap { it.exercises }
        .associate { it.id to it.name }

    val orderedHistories = setHistories
        .sortedWith(
            compareBy<SetHistory>(
                { it.executionSequence == null },
                { it.executionSequence ?: UInt.MAX_VALUE },
                { it.startTime },
                { it.order }
            )
        )

    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        orderedHistories.forEach { history ->
            val round = (history.supersetRound?.toInt() ?: history.order.toInt()) + 1
            val exerciseName = history.exerciseId?.let { exerciseNameById[it] } ?: "Exercise"
            val equipment = history.equipmentIdSnapshot?.let(getEquipmentById)
            val value = formatSetValue(history, equipment)
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = "R$round • $exerciseName: $value",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}

private fun formatSetValue(history: SetHistory, equipment: WeightLoadedEquipment?): String {
    return when (val setData = history.setData) {
        is WeightSetData -> {
            val weightStr = equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg"
            "$weightStr x ${setData.actualReps}"
        }
        is BodyWeightSetData -> {
            "${formatHistoricalBodyWeightSetValue(setData, equipment)} x ${setData.actualReps}"
        }
        is TimedDurationSetData -> {
            val elapsedSec = (setData.startTimer - setData.endTimer).coerceAtLeast(0) / 1000
            formatTime(elapsedSec)
        }
        is EnduranceSetData -> formatTime((setData.endTimer / 1000).coerceAtLeast(0))
        is RestSetData -> "REST ${formatTime(setData.startTimer)}"
    }
}

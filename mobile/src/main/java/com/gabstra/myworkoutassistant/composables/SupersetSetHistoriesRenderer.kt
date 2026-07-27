package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.display.buildSupersetAwareRowLabel
import com.gabstra.myworkoutassistant.shared.workout.display.toSupersetLetter
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
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

    val superset = resolveHistoricalSuperset(workout, setHistories) ?: return
    val exerciseById = superset.exercises.associateBy(Exercise::id)
    val prefixByExerciseId = superset.exercises
        .mapIndexed { index, exercise -> exercise.id to toSupersetLetter(index) }
        .toMap()
    val identifierResolverByExerciseId = setHistories
        .filter { it.exerciseId != null && it.setData !is RestSetData }
        .groupBy { requireNotNull(it.exerciseId) }
        .mapValues { (_, histories) -> HistoricalSetDisplayIdentifierResolver(histories) }

    val rows = buildList {
        mergeSessionTimeline(setHistories, restHistories).forEach { item ->
            when (item) {
                is SessionTimelineItem.RestStep -> {
                    add(SetTableRowUiModel.Rest(formatRestHistoryDisplayLine(item.history)))
                }

                is SessionTimelineItem.SetStep -> {
                    val history = item.history
                    if (history.setData is RestSetData) {
                        add(SetTableRowUiModel.Rest(formatHistoricalRestValue(history)))
                        return@forEach
                    }

                    val exerciseId = history.exerciseId ?: return@forEach
                    val exercise = exerciseById[exerciseId] ?: return@forEach
                    val baseIdentifier = identifierResolverByExerciseId[exerciseId]
                        ?.resolve(history)
                        ?: return@forEach
                    val identifier = buildHistoricalSupersetIdentifier(
                        prefix = prefixByExerciseId[exerciseId].orEmpty(),
                        baseIdentifier = baseIdentifier,
                    )
                    val equipment = history.equipmentIdSnapshot
                        ?.let(getEquipmentById)
                        ?: exercise.equipmentId?.let(getEquipmentById)
                    add(createHistoricalSupersetDataRow(history, equipment, identifier))
                }
            }
        }
    }

    Column(
        modifier = modifier.padding(5.dp),
        verticalArrangement = Arrangement.spacedBy(Spacing.md)
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
            superset.exercises.forEachIndexed { index, exercise ->
                Text(
                    text = "${toSupersetLetter(index)} · ${exercise.name}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        SetTable(rows = rows, enabled = superset.enabled)
    }
}

private fun resolveHistoricalSuperset(
    workout: Workout,
    setHistories: List<SetHistory>,
): Superset? {
    val supersets = workout.workoutComponents.filterIsInstance<Superset>()
    val persistedSupersetId = setHistories.firstNotNullOfOrNull(SetHistory::supersetId)
    if (persistedSupersetId != null) {
        supersets.firstOrNull { it.id == persistedSupersetId }?.let { return it }
    }
    val historicalExerciseIds = setHistories.mapNotNull(SetHistory::exerciseId).toSet()
    return supersets.firstOrNull { superset ->
        superset.exercises.any { it.id in historicalExerciseIds }
    }
}

private fun buildHistoricalSupersetIdentifier(
    prefix: String,
    baseIdentifier: String,
): String {
    return if (baseIdentifier.firstOrNull()?.isDigit() == true) {
        "$prefix$baseIdentifier"
    } else {
        buildSupersetAwareRowLabel(
            supersetPrefix = prefix,
            label = if (baseIdentifier.equals("Cal", ignoreCase = true)) "CAL" else baseIdentifier,
        )
    }
}

private fun createHistoricalSupersetDataRow(
    history: SetHistory,
    equipment: WeightLoadedEquipment?,
    identifier: String,
): SetTableRowUiModel.Data {
    return when (val setData = history.setData) {
        is WeightSetData -> SetTableRowUiModel.Data(
            identifier = identifier,
            primaryValue = equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg",
            secondaryValue = buildRepsAndRir(setData.actualReps, setData.calibrationRIR),
        )

        is BodyWeightSetData -> SetTableRowUiModel.Data(
            identifier = identifier,
            primaryValue = formatHistoricalBodyWeightSetValue(setData, equipment),
            secondaryValue = buildRepsAndRir(setData.actualReps, setData.calibrationRIR),
        )

        is TimedDurationSetData -> SetTableRowUiModel.Data(
            identifier = identifier,
            primaryValue = if (setData.endTimer == 0) {
                formatSecondsToMinutesSeconds(setData.startTimer / 1000)
            } else {
                "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
            },
            monospacePrimary = true,
        )

        is EnduranceSetData -> SetTableRowUiModel.Data(
            identifier = identifier,
            primaryValue = if (setData.endTimer == 0) {
                formatSecondsToMinutesSeconds(setData.startTimer / 1000)
            } else {
                "${formatTime(setData.startTimer / 1000)} - ${formatTime(setData.endTimer / 1000)}"
            },
            monospacePrimary = true,
        )

        is RestSetData -> error("Rest histories must be rendered as rest rows")
    }
}

private fun buildRepsAndRir(actualReps: Int, calibrationRir: Double?): String {
    return if (calibrationRir == null) {
        actualReps.toString()
    } else {
        "$actualReps (RIR $calibrationRir)"
    }
}

package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline

@Composable
fun SetHistoriesRenderer(
    modifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    restHistories: List<RestHistory> = emptyList(),
    appViewModel: AppViewModel,
    workout: Workout,
    showMetadata: Boolean = true,
    contentPadding: PaddingValues = PaddingValues(5.dp),
) {
    if (setHistories.isEmpty() && restHistories.isEmpty()) {
        return
    }

    val firstHistory = setHistories.firstOrNull()
        ?: return
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
        modifier = modifier.padding(contentPadding),
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

        val rows = buildExerciseHistoryRows(
            exercise = exercise,
            equipment = equipment,
            setHistories = setHistories,
            intraExerciseRestHistories = restHistories,
            showRest = true,
        )

        SetTable(
            rows = rows,
            enabled = exercise.enabled,
            presentation = SetTablePresentation.REVIEW,
        )
    }
}

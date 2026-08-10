package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Yellow
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.ProgressionLifecycleComparisonConfig
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsForProgressionLifecycle
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext

private data class MobileProgressionInfo(
    val exerciseName: String,
    val versusLastSession: Ternary?
)

private fun SetHistory.isExcludedFromProgressionSummary(): Boolean = when (val data = setData) {
    is BodyWeightSetData -> data.subCategory in setOf(SetSubCategory.RestPauseSet, SetSubCategory.CalibrationSet)
    is WeightSetData -> data.subCategory in setOf(SetSubCategory.RestPauseSet, SetSubCategory.CalibrationSet)
    is RestSetData -> true
    else -> false
}

private fun SetHistory.toSimpleSetOrNull(): SimpleSet? = when (val data = setData) {
    is WeightSetData -> SimpleSet(data.getWeight(), data.actualReps)
    is BodyWeightSetData -> SimpleSet(data.getWeight(), data.actualReps)
    else -> null
}

private fun progressionComparisonConfig(
    exercise: Exercise,
    viewModel: WorkoutViewModel,
    progressionState: ProgressionState
): ProgressionLifecycleComparisonConfig? {
    if (progressionState == ProgressionState.RETRY || progressionState == ProgressionState.DELOAD) return null
    if (exercise.progressionMode == ProgressionMode.OFF) return null

    val availableWeights = when (exercise.exerciseType) {
        ExerciseType.WEIGHT -> exercise.equipmentId
            ?.let(viewModel::getEquipmentById)
            ?.let(viewModel::getWeightByEquipment)
            .orEmpty()
        ExerciseType.BODY_WEIGHT -> {
            val relativeBodyWeight = viewModel.bodyWeight.value * ((exercise.bodyWeightPercentage ?: 0.0) / 100)
            val addedWeights = exercise.equipmentId
                ?.let(viewModel::getEquipmentById)
                ?.let(viewModel::getWeightByEquipment)
                .orEmpty()
            addedWeights.map { relativeBodyWeight + it }.toSet() + relativeBodyWeight
        }
        else -> emptySet()
    }
    if (availableWeights.isEmpty()) return null

    return ProgressionLifecycleComparisonConfig(
        repsRange = exercise.minReps..exercise.maxReps,
        availableWeights = availableWeights,
        jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
            defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
            maxPct = exercise.loadJumpMaxPct ?: 0.5,
            overcapUntil = exercise.loadJumpOvercapUntil ?: 2
        )
    )
}

private fun compareProgression(
    current: List<SimpleSet>,
    baseline: List<SimpleSet>,
    exercise: Exercise,
    progressionState: ProgressionState,
    viewModel: WorkoutViewModel
): Ternary {
    val config = progressionComparisonConfig(exercise, viewModel, progressionState)
        ?: return compareSetListsUnordered(current, baseline)
    return compareSetListsForProgressionLifecycle(current, baseline, config)
}

@Composable
fun WorkoutProgressionSummary(
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
    onCalculated: (Boolean) -> Unit = {}
) {
    var progressionInfo by remember { mutableStateOf<List<MobileProgressionInfo>?>(null) }

    LaunchedEffect(viewModel) {
        viewModel.completionPushCompleted.first { it }
        progressionInfo = withContext(Dispatchers.IO) {
            val executedHistories = viewModel.executedSetsHistory
            val executedExerciseIds = executedHistories.mapNotNull { it.exerciseId }.toSet()
            val exercises = viewModel.selectedWorkout.value.workoutComponents.flatMap { component ->
                when (component) {
                    is Exercise -> listOf(component)
                    is Superset -> component.exercises
                    else -> emptyList()
                }
            }.filter { it.id in executedExerciseIds }

            exercises.mapNotNull { exercise ->
                if (exercise.exerciseType !in setOf(ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT)) {
                    return@mapNotNull null
                }
                val progressionState = viewModel.exerciseProgressionByExerciseId[exercise.id]?.second
                    ?: return@mapNotNull null
                if (progressionState in setOf(ProgressionState.DELOAD, ProgressionState.FAILED)) {
                    return@mapNotNull null
                }
                val currentSets = executedHistories
                    .filter { it.exerciseId == exercise.id }
                    .filterNot { it.isExcludedFromProgressionSummary() }
                    .mapNotNull { it.toSimpleSetOrNull() }
                val baseline = viewModel.getProgressionComparisonBaselineSets(exercise.id)
                MobileProgressionInfo(
                    exerciseName = exercise.name,
                    versusLastSession = baseline?.let {
                        compareProgression(currentSets, it, exercise, progressionState, viewModel)
                    }
                )
            }
        }
        onCalculated(progressionInfo.isNullOrEmpty())
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(text = "Progression", style = MaterialTheme.typography.titleMedium)
        when (val rows = progressionInfo) {
            null -> CircularProgressIndicator(modifier = Modifier.align(Alignment.CenterHorizontally))
            else -> rows.forEach { info -> ProgressionSummaryRow(info) }
        }
    }
}

@Composable
private fun ProgressionSummaryRow(info: MobileProgressionInfo) {
    val status = info.versusLastSession
    val iconAndColor: Pair<androidx.compose.ui.graphics.vector.ImageVector, Color>? = when (status) {
        Ternary.ABOVE -> Icons.AutoMirrored.Filled.TrendingUp to Green
        Ternary.EQUAL -> Icons.Filled.DragHandle to Yellow
        Ternary.BELOW -> Icons.AutoMirrored.Filled.TrendingDown to Red
        Ternary.MIXED -> Icons.Filled.SwapVert to MaterialTheme.colorScheme.tertiary
        null -> null
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text = info.exerciseName, modifier = Modifier.weight(1f))
        if (iconAndColor == null) {
            Text(text = "—", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            Icon(
                imageVector = iconAndColor.first,
                contentDescription = "${info.exerciseName}: $status",
                tint = iconAndColor.second
            )
        }
    }
}

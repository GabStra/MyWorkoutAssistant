package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class ProgressionInfo(val exerciseName: String, val initialVolume: Double, val finalVolume: Double)

@SuppressLint("DefaultLocale")
@Composable
private fun ProgressionRow(
    info: ProgressionInfo,
    modifier: Modifier = Modifier
) {
    val progression = if (info.initialVolume != 0.0) {
        ((info.finalVolume - info.initialVolume) / info.initialVolume) * 100
    } else if (info.finalVolume > 0) {
        100.0 // Consider it 100% progress if initial was 0
    } else {
        0.0
    }

    val progressionText = when {
        progression.isNaN() || progression == 0.0 -> "-"
        progression > 0 -> "+${String.format("%.1f", progression)}%"
        else -> "${String.format("%.1f", progression)}%"
    }

    val progressionColor = when {
        progression > 0 -> Green
        progression < 0 -> Red
        else -> MaterialTheme.colorScheme.onBackground
    }

    Row(
        modifier = modifier.height(20.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        ScalableText(
            modifier = Modifier.weight(2f).basicMarquee(iterations = Int.MAX_VALUE),
            text = info.exerciseName,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground
        )
        ScalableText(
            modifier = Modifier.weight(1f),
            text = progressionText.replace(',','.'),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = progressionColor
        )
    }
}


@Composable
fun ProgressionSection(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel
) {
    var progressionData by remember { mutableStateOf<List<ProgressionInfo>?>(null) }

    LaunchedEffect(viewModel) {
        progressionData = withContext(Dispatchers.Default) {
            val exerciseIds = viewModel.executedSetsHistory
                .mapNotNull { it.exerciseId }
                .distinct()

            exerciseIds.mapNotNull { exerciseId ->
                val exercise = viewModel.exercisesById[exerciseId] ?: return@mapNotNull null
                if (exercise.exerciseType != ExerciseType.WEIGHT && exercise.exerciseType != ExerciseType.BODY_WEIGHT) return@mapNotNull null

                val finalVolume = viewModel.executedSetsHistory
                    .filter { it.exerciseId == exerciseId }
                    .sumOf {
                        when (val setData = it.setData) {
                            is WeightSetData -> {
                                setData.volume
                            }
                            is BodyWeightSetData -> {
                                setData.volume
                            }
                            else -> 0.0
                        }
                    }

                val initialVolume = viewModel.originalWorkout?.let { originalWorkout ->
                    val originalExercise = (originalWorkout.workoutComponents.filterIsInstance<Exercise>() +
                            originalWorkout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises })
                        .find { it.id == exerciseId } ?: return@let 0.0

                    originalExercise.sets
                        .filter { it !is RestSet &&
                                (it is WeightSet && !it.isWarmupSet) ||
                                (it is BodyWeightSet && !it.isWarmupSet)
                        }
                        .sumOf { set ->
                            when (set) {
                                is WeightSet -> {
                                    set.weight * set.reps
                                }
                                is BodyWeightSet -> {
                                    val bodyWeight = viewModel.bodyWeight.value
                                    val bodyWeightPercentage = originalExercise.bodyWeightPercentage ?: 100.0
                                    val relativeBodyWeight = bodyWeight * (bodyWeightPercentage / 100.0)
                                    set.getWeight(relativeBodyWeight) * set.reps
                                }
                                else -> 0.0
                            }
                        }
                } ?: 0.0



                if (initialVolume > 0 || finalVolume > 0) {
                    ProgressionInfo(exercise.name, initialVolume, finalVolume)
                } else {
                    null
                }
            }
        }
    }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()

    // A sample item for DynamicHeightColumn to measure.
    val prototypeItem = @Composable {
        ProgressionRow(
            info = ProgressionInfo("Sample Exercise", 100.0, 110.0)
        )
    }

    if (!progressionData.isNullOrEmpty()) {
        Column(
            modifier = modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(2.5.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    modifier = Modifier.weight(2f),
                    text = "EXERCISE",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "PROGRESS",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
            }

            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f) // Fills remaining vertical space
                    .fillMaxWidth(), // Still need to fill width
                prototypeItem = { prototypeItem() }
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalColumnScrollbar(
                            scrollState = scrollState,
                            scrollBarColor = MaterialTheme.colorScheme.onBackground,
                            enableTopFade = false,
                            enableBottomFade = false
                        )
                        .verticalScroll(scrollState),
                ) {
                    progressionData?.forEachIndexed { index, info ->
                        val backgroundColor = if (index % 2 == 0) {
                            MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f)
                        } else {
                            Color.Transparent
                        }
                        ProgressionRow(
                            info = info,
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(backgroundColor)
                        )
                    }
                }
            }
        }
    }
}
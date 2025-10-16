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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingFlat
import androidx.compose.material.icons.automirrored.filled.TrendingUp
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
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

enum class ProgressStatus { PROGRESSED, EQUAL, WORSE }

data class ProgressionInfo(val exerciseName: String, val progressStatus: ProgressStatus)

@SuppressLint("DefaultLocale")
@Composable
private fun ProgressionRow(
    info: ProgressionInfo,
    modifier: Modifier = Modifier
) {

    val progressionColor = when(info.progressStatus) {
        ProgressStatus.PROGRESSED -> Green
        ProgressStatus.EQUAL -> MaterialTheme.colorScheme.onBackground
        ProgressStatus.WORSE -> Red
    }

    Row(
        modifier = modifier.height(20.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        ScalableText(
            modifier = Modifier
                .weight(2f)
                .basicMarquee(iterations = Int.MAX_VALUE),
            text = info.exerciseName,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = progressionColor
        )
        when(info.progressStatus){
            ProgressStatus.PROGRESSED -> {
                Icon(
                    modifier = Modifier.weight(1f),
                    imageVector =Icons.AutoMirrored.Filled.TrendingUp,
                    contentDescription = "Trending Up",
                    tint = progressionColor
                )
            }
            ProgressStatus.EQUAL -> {
                Icon(
                    modifier = Modifier.weight(1f),
                    imageVector = Icons.AutoMirrored.Filled.TrendingFlat,
                    contentDescription = "Trending Flat",
                    tint = progressionColor
                )
            }
            ProgressStatus.WORSE -> {
                Icon(
                    modifier = Modifier.weight(1f),
                    imageVector =Icons.AutoMirrored.Filled.TrendingDown,
                    contentDescription = "Trending Down",
                    tint = progressionColor
                )
            }
        }
    }
}


@Composable
fun ProgressionSection(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel
) {
    var progressionData by remember { mutableStateOf<List<ProgressionInfo>?>(null) }

    LaunchedEffect(viewModel) {
        progressionData = withContext(Dispatchers.IO) {
            val exerciseIds = viewModel.executedSetsHistory
                .mapNotNull { it.exerciseId }
                .distinct()

            exerciseIds.mapNotNull { exerciseId ->
                val exercise = viewModel.exercisesById[exerciseId] ?: return@mapNotNull null
                if (exercise.exerciseType != ExerciseType.WEIGHT && exercise.exerciseType != ExerciseType.BODY_WEIGHT) return@mapNotNull null

                val executedSets = viewModel.executedSetsHistory
                    .filter { it.exerciseId == exerciseId }
                    .filter { it ->
                        when(val setData = it.setData){
                            is BodyWeightSetData -> !setData.isRestPause
                            is WeightSetData -> !setData.isRestPause
                            is RestSetData -> !setData.isRestPause
                            else -> true
                        }
                    }
                    .mapNotNull { when(val setData = it.setData){
                        is WeightSetData -> {
                            val weight = setData.getWeight()
                            val reps = setData.actualReps

                            SimpleSet(weight,reps)
                        }
                        is BodyWeightSetData -> {
                            val weight = setData.getWeight()
                            val reps = setData.actualReps

                            SimpleSet(weight,reps)
                        }
                        else -> null
                    } }

                val progressionData =
                    if (viewModel.exerciseProgressionByExerciseId.containsKey(exerciseId)) viewModel.exerciseProgressionByExerciseId[exerciseId] else null

                if(progressionData == null) return@mapNotNull null

                val expectedSets = progressionData.first.sets
                val progressionState = progressionData.second

                if(progressionState == ProgressionState.DELOAD || progressionState == ProgressionState.FAILED) return@mapNotNull null

                val originalExercise = (viewModel.originalWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                        viewModel.originalWorkout!!.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises })
                    .find { it.id == exerciseId }

                val originalSets = originalExercise!!.sets
                    .filter { it !is RestSet &&
                            (it is WeightSet && !it.isWarmupSet && !it.isRestPause) ||
                            (it is BodyWeightSet && !it.isWarmupSet&& !it.isRestPause)
                    }
                    .mapNotNull { set ->
                        when (set) {
                            is WeightSet -> {
                                SimpleSet( set.weight, set.reps)
                            }
                            is BodyWeightSet -> {
                                val bodyWeight = viewModel.bodyWeight.value
                                val bodyWeightPercentage = originalExercise.bodyWeightPercentage ?: 100.0
                                val relativeBodyWeight = bodyWeight * (bodyWeightPercentage / 100.0)
                                set.getWeight(relativeBodyWeight) * set.reps
                                SimpleSet(  set.getWeight(relativeBodyWeight),set.reps)
                            }
                            else -> null
                        }
                    }

                val hasProgressed = executedSets.indices.all { i ->
                    val executedSet = executedSets[i]
                    val expectedSet = expectedSets[i]

                    executedSet.weight >= expectedSet.weight && executedSet.reps >= expectedSet.reps
                }

                val isEqualToOriginal = executedSets.indices.all { i ->
                    val originalSet = originalSets[i]
                    val executedSet = executedSets[i]
                    executedSet == originalSet
                }

                val progressStatus = when {
                    hasProgressed -> ProgressStatus.PROGRESSED
                    isEqualToOriginal -> ProgressStatus.EQUAL
                    else -> ProgressStatus.WORSE
                }

                ProgressionInfo(exercise.name, progressStatus)
            }
        }
    }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()

    // A sample item for DynamicHeightColumn to measure.
    val prototypeItem = @Composable {
        ProgressionRow(
            info = ProgressionInfo("Sample Exercise", ProgressStatus.PROGRESSED)
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
                            MaterialTheme.colorScheme.surfaceContainer
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
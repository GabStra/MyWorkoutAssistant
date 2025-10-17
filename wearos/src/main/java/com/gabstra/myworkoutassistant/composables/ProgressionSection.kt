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
import androidx.compose.material.icons.filled.SwapVert
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
import com.gabstra.myworkoutassistant.shared.round
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

enum class Ternary { BELOW, EQUAL, ABOVE, MIXED }
data class ProgressionInfo(
    val exerciseName: String,
    val vsExpected: Ternary,
    val vsLast: Ternary
)

private val simpleSetComparator =
    compareBy<SimpleSet>({ it.weight.round(2) }, { it.reps })

private fun normalizeSets(list: List<SimpleSet>): List<SimpleSet> =
    list.sortedWith(simpleSetComparator)

// ---- 2) Order-insensitive equality (for "same as original") ----
private fun listsEqualUnordered(a: List<SimpleSet>, b: List<SimpleSet>): Boolean =
    a.size == b.size && normalizeSets(a) == normalizeSets(b)

// ---- 3) Order-insensitive ternary compare (for vs expected / vs last) ----
private fun compareSets(a: SimpleSet, b: SimpleSet): Int = when {
    a.weight.round(2) > b.weight.round(2) ||
            (a.weight.round(2) == b.weight.round(2) && a.reps > b.reps) -> 1
    a.weight.round(2) == b.weight.round(2) && a.reps == b.reps -> 0
    else -> -1
}

private fun compareSetListsUnordered(a: List<SimpleSet>, b: List<SimpleSet>): Ternary {
    if (a.size != b.size) return Ternary.MIXED
    val A = normalizeSets(a)
    val B = normalizeSets(b)

    var pos = 0
    var neg = 0
    for (i in A.indices) {
        when (compareSets(A[i], B[i])) {
            1  -> pos++
            -1 -> neg++
            // 0 (equal) is ignored
        }
    }

    return when {
        pos > 0 && neg == 0 -> Ternary.ABOVE   // some improved, rest equal
        neg > 0 && pos == 0 -> Ternary.BELOW   // some worse, rest equal
        pos == 0 && neg == 0 -> Ternary.EQUAL  // all equal
        else -> Ternary.MIXED                  // both improved and worse present
    }
}

@Composable
private fun StatusIcon(label: String, status: Ternary, modifier: Modifier = Modifier) {
    val (icon, tint) = when (status) {
        Ternary.ABOVE -> Icons.AutoMirrored.Filled.TrendingUp to Green
        Ternary.EQUAL -> Icons.AutoMirrored.Filled.TrendingFlat to MaterialTheme.colorScheme.onBackground
        Ternary.BELOW -> Icons.AutoMirrored.Filled.TrendingDown to Red
        Ternary.MIXED -> Icons.Filled.SwapVert to MaterialTheme.colorScheme.tertiary
    }
    Icon(imageVector = icon, contentDescription = label, tint = tint)
}

@SuppressLint("DefaultLocale")
@Composable
private fun ProgressionRow(
    info: ProgressionInfo,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.height(20.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        ScalableText(
            modifier = Modifier.weight(2f).basicMarquee(iterations = Int.MAX_VALUE),
            text = info.exerciseName,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center
        )
        StatusIcon(label = "EXP", status = info.vsExpected, modifier = Modifier.weight(1f))
        StatusIcon(label = "LAST", status = info.vsLast, modifier = Modifier.weight(1f))
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

                val lastSessionExercise = (viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                        viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises })
                    .find { it.id == exerciseId }

                val lastSessionSets = lastSessionExercise!!.sets
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
                                val bodyWeightPercentage = lastSessionExercise.bodyWeightPercentage ?: 100.0
                                val relativeBodyWeight = bodyWeight * (bodyWeightPercentage / 100.0)
                                set.getWeight(relativeBodyWeight) * set.reps
                                SimpleSet(  set.getWeight(relativeBodyWeight),set.reps)
                            }
                            else -> null
                        }
                    }

                val vsExpected = compareSetListsUnordered(executedSets, expectedSets)
                val vsLast     = compareSetListsUnordered(executedSets, lastSessionSets)

                ProgressionInfo(exercise.name, vsExpected, vsLast)
            }
        }
    }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()

    // A sample item for DynamicHeightColumn to measure.
    val prototypeItem = @Composable {
        ProgressionRow(
            info = ProgressionInfo("Sample Exercise", Ternary.EQUAL, Ternary.EQUAL)
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
                Text(modifier = Modifier.weight(2f), text = "EXERCISE", style = headerStyle, textAlign = TextAlign.Center)
                Text(modifier =Modifier.weight(1f), text = "VS EXP", style = headerStyle, textAlign = TextAlign.Center)
                Text(modifier =Modifier.weight(1f), text = "VS LAST", style = headerStyle, textAlign = TextAlign.Center)
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
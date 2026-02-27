package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.filled.DragHandle
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
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
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class ProgressionInfo(
    val exerciseName: String,
    val vsExpected: Ternary,
    val vsLast: Ternary
)

private fun SetHistory.isExcludedFromProgressionComparison(): Boolean {
    return when (val setData = setData) {
        is BodyWeightSetData ->
            setData.subCategory == SetSubCategory.RestPauseSet ||
                setData.subCategory == SetSubCategory.CalibrationSet
        is WeightSetData ->
            setData.subCategory == SetSubCategory.RestPauseSet ||
                setData.subCategory == SetSubCategory.CalibrationSet
        is RestSetData ->
            setData.subCategory == SetSubCategory.RestPauseSet ||
                setData.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }
}

private fun SetHistory.toSimpleSetOrNull(): SimpleSet? {
    return when (val setData = setData) {
        is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
        is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
        else -> null
    }
}

@Composable
private fun StatusIcon(label: String, status: Ternary, modifier: Modifier = Modifier) {
    val (icon, tint) = when (status) {
        Ternary.ABOVE -> Icons.AutoMirrored.Filled.TrendingUp to Green
        Ternary.EQUAL -> Icons.Filled.DragHandle to MaterialTheme.colorScheme.onBackground
        Ternary.BELOW -> Icons.AutoMirrored.Filled.TrendingDown to Red
        Ternary.MIXED -> Icons.Filled.SwapVert to MaterialTheme.colorScheme.tertiary
    }
    Icon(modifier = modifier, imageVector = icon, contentDescription = label, tint = tint)
}

@SuppressLint("DefaultLocale")
@Composable
private fun ProgressionRow(
    info: ProgressionInfo
) {
    val shape = RoundedCornerShape(25)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(30.dp)
            .padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Row(
            modifier = Modifier
                .height(27.5.dp)
                .padding(bottom = 2.5.dp)
                .border(BorderStroke(1.dp,  MaterialTheme.colorScheme.onBackground), shape)
                .clip(shape), // keep if you want content clipped to the rounded shape
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = Modifier.fillMaxSize().padding(2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                ScalableText(
                    modifier = Modifier.weight(2f).basicMarquee(iterations = Int.MAX_VALUE),
                    text = info.exerciseName,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                    textAlign = TextAlign.Center
                )
                StatusIcon(label = "LAST", status = info.vsLast, modifier = Modifier.weight(1f))
                StatusIcon(label = "EXP", status = info.vsExpected, modifier = Modifier.weight(1f))
            }
        }
    }
}


@Composable
fun ProgressionSection(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
    onProgressionDataCalculated: ((isEmpty: Boolean) -> Unit)? = null
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
                    .filterNot { it.isExcludedFromProgressionComparison() }
                    .mapNotNull { it.toSimpleSetOrNull() }

                val progressionData =
                    if (viewModel.exerciseProgressionByExerciseId.containsKey(exerciseId)) viewModel.exerciseProgressionByExerciseId[exerciseId] else null

                if(progressionData == null) return@mapNotNull null

                val expectedSets = progressionData.first.sets
                val progressionState = progressionData.second

                if(progressionState == ProgressionState.DELOAD || progressionState == ProgressionState.FAILED) return@mapNotNull null

                // Compare against the pre-session snapshot to avoid including the current session.
                val lastSessionSets = viewModel.latestSetHistoriesByExerciseId[exerciseId]
                    ?.filterNot { it.isExcludedFromProgressionComparison() }
                    ?.mapNotNull { it.toSimpleSetOrNull() }
                    ?.takeIf { it.isNotEmpty() }

                val vsExpected = compareSetListsUnordered(executedSets, expectedSets)
                val vsLast = if (lastSessionSets != null) {
                    compareSetListsUnordered(executedSets, lastSessionSets)
                } else {
                    Ternary.EQUAL
                }

                ProgressionInfo(exercise.name, vsExpected, vsLast)
            }
        }
        
        // Notify callback when calculation completes
        onProgressionDataCalculated?.invoke(progressionData.isNullOrEmpty())
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
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(modifier = Modifier.weight(2f), text = "EXERCISE", style = headerStyle, textAlign = TextAlign.Center)
                Text(modifier =Modifier.weight(1f), text = "VS LAST", style = headerStyle, textAlign = TextAlign.Center)
                Text(modifier =Modifier.weight(1f), text = "VS EXP", style = headerStyle, textAlign = TextAlign.Center)

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
                        .verticalColumnScrollbar(scrollState = scrollState)
                        .verticalScroll(scrollState),
                ) {
                    progressionData?.forEachIndexed { index, info ->
                       ProgressionRow(info = info)
                    }
                }
            }
        }
    }
}

package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
    set: WorkoutState.Set,
){
    val parentIndex = viewModel.setsByExercise.keys.indexOf(set.parentExercise)
    val totalGroups = viewModel.setsByExercise.keys.count()
    val maxCount = 1

    // Determine the range of elements to display based on parentIndex and total available elements
    val elementsToSkip = (parentIndex ).coerceAtLeast(0).coerceAtMost((totalGroups - maxCount).coerceAtLeast(0))
    val areMoreElementsAvailable = totalGroups > elementsToSkip + maxCount

    val exerciseSelection = viewModel.setsByExercise.keys.drop(elementsToSkip).take(maxCount)

    val numberOfElementsLeft = totalGroups - (elementsToSkip + exerciseSelection.size)

    // Calculate gaps and angles
    val baseGapAngle = 2f
    val size= 20f

    val availableAngle = 140f - (if (elementsToSkip >0) size + baseGapAngle else 0f) - (if (areMoreElementsAvailable) size + baseGapAngle else 0f)
    var angleForCurrentExercise = availableAngle / exerciseSelection.size.coerceAtLeast(1)


    Box(modifier = modifier.fillMaxSize()) {
        var accumulatedAngle = -70f // Starting angle

        // Indicate skipped elements at the start
        if (elementsToSkip > 0) {
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, MaterialTheme.colors.primary)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + size,
                trackColor = Color.White,
            )

            if(elementsToSkip > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+size/2, circleRadius = 15f, circleColor = MaterialTheme.colors.primary, number = elementsToSkip, margin = -10f, transparency = 1f)
            }
            accumulatedAngle += size + baseGapAngle
        }

        SetIndicator(accumulatedAngle+ baseGapAngle,angleForCurrentExercise -  (baseGapAngle*2), set, viewModel.setsByExercise[set.parentExercise] ?: listOf(), Modifier.fillMaxSize())
        accumulatedAngle += angleForCurrentExercise + baseGapAngle
        // Indicate more elements available at the end
        if (areMoreElementsAvailable) {

            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, Color.DarkGray)),
                progress = 1f,
                modifier = Modifier.fillMaxSize().alpha(1f),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + size,
                trackColor = Color.White,
            )

            CircleWithNumber(baseAngleInDegrees = accumulatedAngle+size/2, circleRadius = 15f, circleColor =  Color.DarkGray, number = numberOfElementsLeft, margin = -10f, transparency = 1f)
        }
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun SetIndicator(
    startingAngle: Float,
    maxAngle: Float,
    currentSet: WorkoutState.Set,
    sets: List<WorkoutState.Set>,
    modifier: Modifier = Modifier
) {
    val parentIndex = sets.indexOfFirst { it === currentSet }
    val totalGroups = sets.count()
    val maxCount = 1

    // Determine the range of elements to display based on parentIndex and total available elements
    val elementsToSkip = (parentIndex).coerceAtLeast(0).coerceAtMost((totalGroups - maxCount).coerceAtLeast(0))
    val setsSelection = sets.drop(elementsToSkip).take(maxCount)

    val numberOfElementsLeft = totalGroups - (elementsToSkip + setsSelection.size)

    // Calculate gaps and angles
    val baseGapAngle = 2f
    val parentGapAngle = 2f

    val indicatorSize = 20f

    val availableAngle = maxAngle - (if (elementsToSkip > 1) indicatorSize + baseGapAngle else 0f) - (if (numberOfElementsLeft > 1) indicatorSize + baseGapAngle else 0f)

    var angleForSet = availableAngle / setsSelection.size.coerceAtLeast(1)

    if(elementsToSkip ==1 || numberOfElementsLeft == 1){
        angleForSet= (availableAngle-baseGapAngle) / (1f+setsSelection.size.coerceAtLeast(1))
    }

    if(elementsToSkip ==1 && numberOfElementsLeft == 1){
        angleForSet= (availableAngle-baseGapAngle*2) / (2f+setsSelection.size.coerceAtLeast(1))
    }


    Box(modifier = modifier.fillMaxSize()) {
        var accumulatedAngle = startingAngle // Starting angle

        // Indicator for skipped elements
        if (elementsToSkip > 0) {
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f,if(setsSelection.isEmpty()) Color.White else MyColors.Green)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(elementsToSkip == 1) angleForSet else indicatorSize,
                trackColor = Color.White,
            )

            if(elementsToSkip > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 15f, circleColor = MyColors.Green, number = elementsToSkip, margin = -10f, transparency = 1f)
            }

            accumulatedAngle += (if(elementsToSkip == 1) angleForSet else indicatorSize) + baseGapAngle
        }

        var markAsCompleted = true

        setsSelection.forEachIndexed { index, set ->
            val isCurrentSet = set === currentSet
            if(isCurrentSet){
                markAsCompleted = false
            }
            // Draw group segment
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, if (isCurrentSet) Color.White else (if(markAsCompleted)  MyColors.Green else Color.DarkGray))),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + angleForSet,
                trackColor = Color.White,
            )

            accumulatedAngle += angleForSet // Move to next segment start

            // Add gaps appropriately
            if (index < setsSelection.size - 1 || isCurrentSet) {
                accumulatedAngle += if (isCurrentSet) parentGapAngle else baseGapAngle
            }
        }

        // Indicator for more elements available
        if (numberOfElementsLeft > 0) {
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, Color.DarkGray)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(numberOfElementsLeft == 1) angleForSet else indicatorSize,
                trackColor = Color.White,
            )

            if(numberOfElementsLeft > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 15f, circleColor = Color.DarkGray, number = numberOfElementsLeft, margin = -10f)
            }
        }
    }
}
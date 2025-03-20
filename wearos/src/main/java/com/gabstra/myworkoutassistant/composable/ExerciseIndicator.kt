package com.gabstra.myworkoutassistant.composable

import CircleWithNumber
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.getValueInRange
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
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

    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseCount = exerciseOrSupersetIds.count()

    val exerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(set.exerciseId)) viewModel.supersetIdByExerciseId[set.exerciseId] else set.exerciseId
    val currentExerciseIndex = exerciseOrSupersetIds.indexOf(exerciseOrSupersetId)

    val step = (1f / exerciseCount)

    val halfStep = (step / 2)

    val progress = (currentExerciseIndex + 1).toFloat() / exerciseCount

    Box(modifier = modifier.fillMaxSize()) {
        // Create n SegmentedProgressIndicator
        for (index in 0 until exerciseCount) {
            // Calculate whether this indicator should be filled (1.0) or empty (0.0)
            val indicatorProgress = if (index <= currentExerciseIndex) 1.0f else 0.0f

            // Create a single segment for each indicator
            val trackSegment = ProgressIndicatorSegment(
                weight = 1f,
                indicatorColor = if (index != currentExerciseIndex) MyColors.Orange else Color.White
            )

            // Calculate angle for each indicator to space them evenly
            // Total arc: 65f - (-60f) = 125f
            val totalArcAngle = 125f
            val segmentArcAngle = (totalArcAngle - (exerciseCount - 1) * 2f) / exerciseCount
            val startAngle = -60f + index * (segmentArcAngle + 2f)
            val endAngle = startAngle + segmentArcAngle

            SegmentedProgressIndicator(
                trackSegments = listOf(trackSegment),
                progress = indicatorProgress,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 0f,
                startAngle = startAngle,
                endAngle = endAngle,
                trackColor = Color.DarkGray,
            )
        }
    }

    val totalArcAngle = 125f
    val segmentArcAngle = (totalArcAngle - (exerciseCount - 1) * 2f) / exerciseCount
    val startAngle = -60f + currentExerciseIndex * (segmentArcAngle + 2f)
    val middleAngle = startAngle + (segmentArcAngle / 2f)

    // Place the indicator exactly at the middle of the current segment
    RotatingIndicator(middleAngle, Color.White)

    /*val parentIndex = viewModel.setsByExerciseId.keys.indexOf(set.exerciseId)
    val totalGroups = viewModel.setsByExerciseId.keys.count()
    val maxCount = 1

    // Determine the range of elements to display based on parentIndex and total available elements
    val elementsToSkip = (parentIndex ).coerceAtLeast(0).coerceAtMost((totalGroups - maxCount).coerceAtLeast(0))
    val areMoreElementsAvailable = totalGroups > elementsToSkip + maxCount

    val exerciseSelection = viewModel.setsByExerciseId.keys.drop(elementsToSkip).take(maxCount)

    val numberOfElementsLeft = totalGroups - (elementsToSkip + exerciseSelection.size)

    // Calculate gaps and angles
    val baseGapAngle = 1f
    val size= 25f

    val availableAngle = 125f - (if (elementsToSkip >0) size + baseGapAngle else 0f) - (if (areMoreElementsAvailable) size + baseGapAngle else 0f)
    var angleForCurrentExercise = availableAngle / exerciseSelection.size.coerceAtLeast(1)


    Box(modifier = modifier.fillMaxSize()) {
        var accumulatedAngle = -60f // Starting angle

        // Indicate skipped elements at the start
        if (elementsToSkip > 0) {
            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, MyColors.Orange)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + size,
                trackColor =  MyColors.Orange,
            )

            if(elementsToSkip > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+size/2, circleRadius = 20f, circleColor = MyColors.Orange, number = elementsToSkip, transparency = 1f)
            }
            accumulatedAngle += size + baseGapAngle
        }

        val allSets = viewModel.setsByExerciseId[set.exerciseId] ?: listOf()
        val filteredSets = allSets.filter { it.set !is RestSet }
        SetIndicator(accumulatedAngle + baseGapAngle,angleForCurrentExercise -  (baseGapAngle*2), set, filteredSets, Modifier.fillMaxSize())
        accumulatedAngle += angleForCurrentExercise + baseGapAngle
        // Indicate more elements available at the end
        if (areMoreElementsAvailable) {

            SegmentedProgressIndicator(
                trackSegments = listOf(ProgressIndicatorSegment(1f, Color.White)),
                progress = 1f,
                modifier = Modifier.fillMaxSize().alpha(1f),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + size,
                trackColor = Color.White,
            )

            if(numberOfElementsLeft > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+size/2, circleRadius = 20f, circleColor = Color.White, number = numberOfElementsLeft, transparency = 1f)
            }
        }
    }*/
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
    val baseGapAngle = 1f
    val parentGapAngle = 1f

    val indicatorSize = 25f

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
                trackSegments = listOf(ProgressIndicatorSegment(1f, MyColors.Orange)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(elementsToSkip == 1) angleForSet else indicatorSize,
                trackColor = Color.White,
            )

            if(elementsToSkip > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 20f, circleColor = MyColors.Orange, number = elementsToSkip, transparency = 1f)
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
                trackSegments = listOf(ProgressIndicatorSegment(1f, if (isCurrentSet) Color.White  else (if(markAsCompleted) MyColors.Orange else Color.White))),
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
                trackSegments = listOf(ProgressIndicatorSegment(1f, Color.White)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(numberOfElementsLeft == 1) angleForSet else indicatorSize,
                trackColor = Color.White,
            )

            if(numberOfElementsLeft > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 20f, circleColor = Color.White, number = numberOfElementsLeft)
            }
        }
    }
}
package com.gabstra.myworkoutassistant.composables

import CircleWithNumber
import android.util.Log
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import java.util.UUID

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    viewModel: AppViewModel,
    set: WorkoutState.Set,
    selectedExerciseId : UUID? = null
){

    val exerciseIds = remember { viewModel.setsByExerciseId.keys.toList() }
    val exerciseOrSupersetIds = remember { exerciseIds.map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseCount = exerciseOrSupersetIds.count()

    val exerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(set.exerciseId)) viewModel.supersetIdByExerciseId[set.exerciseId] else set.exerciseId
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(exerciseOrSupersetId)

    val startingAngle = -50f
    val totalArcAngle = 100f
    val segmentArcAngle = (totalArcAngle - (exerciseCount - 1) * 2f) / exerciseCount

    Box(modifier = Modifier.fillMaxSize()) {
        exerciseOrSupersetIds.forEachIndexed { index, exerciseOrSupersetId ->
            val isSuperset = remember(exerciseOrSupersetId) { viewModel.supersetIdByExerciseId.containsValue(exerciseOrSupersetId)  }

            if(isSuperset){
                val supersetExerciseIds =
                    exerciseIds
                        .filter { viewModel.supersetIdByExerciseId.containsKey(it) && viewModel.supersetIdByExerciseId[it] == exerciseOrSupersetId }
                
                val supersetExercisesCount = supersetExerciseIds.count()

                val subSegmentArcAngle = (segmentArcAngle - (supersetExercisesCount - 1) * 1f) / supersetExercisesCount

                for (subIndex in 0 until supersetExercisesCount) {
                    val indicatorProgress = when{
                        index <= currentExerciseOrSupersetIndex -> 1.0f
/*                        index == currentExerciseOrSupersetIndex -> {
                            val supersetExerciseId = supersetExerciseIds[subIndex]
                            val sets = viewModel.setsByExerciseId[supersetExerciseId]
                            val executedSetsCount = viewModel.getAllExecutedSetsByExerciseId(supersetExerciseId).size
                            val totalSets = sets!!.size
                            (executedSetsCount + 1).toFloat() / totalSets.toFloat()
                        }*/
                        else -> 0.0f
                    }

                    // Create a single segment for each indicator
                    val trackSegment = ProgressIndicatorSegment(
                        weight = 1f,
                        indicatorColor = if (index != currentExerciseOrSupersetIndex) Orange else LightGray
                    )

                    val startAngle = startingAngle + index * (segmentArcAngle + 2f) + subIndex * (subSegmentArcAngle + 1f)
                    val endAngle = startAngle + subSegmentArcAngle

                    SegmentedProgressIndicator(
                        trackSegments = listOf(trackSegment),
                        progress = indicatorProgress,
                        modifier = Modifier.fillMaxSize(),
                        strokeWidth = 4.dp,
                        paddingAngle = 0f,
                        startAngle = startAngle,
                        endAngle = endAngle,
                        trackColor = MediumDarkGray,
                    )
                }
            }else{
                val indicatorProgress = when {
                    index <= currentExerciseOrSupersetIndex -> 1.0f // Previous exercises are fully completed
/*                    index == currentExerciseOrSupersetIndex -> {
                        val sets = viewModel.setsByExerciseId[set.exerciseId]
                        val currentSetIndex = sets!!.indexOfFirst { it === set }
                        val totalSets = sets.size
                        (currentSetIndex + 1).toFloat() / totalSets.toFloat()
                    }*/
                    else -> 0.0f // Future exercises are not started
                }

                // Create a single segment for each indicator
                val trackSegment = ProgressIndicatorSegment(
                    weight = 1f,
                    indicatorColor = if (index != currentExerciseOrSupersetIndex) Orange else LightGray
                )

                // Calculate angle for each indicator to space them evenly
                // Total arc: 65f - (-60f) = 125f

                val startAngle = startingAngle + index * (segmentArcAngle + 2f)
                val endAngle = startAngle + segmentArcAngle

                SegmentedProgressIndicator(
                    trackSegments = listOf(trackSegment),
                    progress = indicatorProgress,
                    modifier = Modifier.fillMaxSize(),
                    strokeWidth = 4.dp,
                    paddingAngle = 0f,
                    startAngle = startAngle,
                    endAngle = endAngle,
                    trackColor = MediumDarkGray,
                )
            }
        }
    }

    if(selectedExerciseId != null && exerciseIds.contains(selectedExerciseId)){
        val isSuperset = remember(selectedExerciseId) { viewModel.supersetIdByExerciseId.containsKey(selectedExerciseId)  }

        if(isSuperset){
            val supersetId = viewModel.supersetIdByExerciseId[selectedExerciseId]
            val customExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(supersetId)

            val supersetExerciseIds = exerciseIds.filter { viewModel.supersetIdByExerciseId.containsKey(it) && viewModel.supersetIdByExerciseId[it] == supersetId }
            val supersetExercisesCount = supersetExerciseIds.count()

            val subSegmentArcAngle = (segmentArcAngle - (supersetExercisesCount - 1) * 1f) / supersetExercisesCount

            val subIndex = supersetExerciseIds.indexOf(selectedExerciseId)

            val startAngle = startingAngle + customExerciseOrSupersetIndex * (segmentArcAngle + 2f) + subIndex * (subSegmentArcAngle + 1f)
            val middleAngle = startAngle + (subSegmentArcAngle / 2f)

            RotatingIndicator(middleAngle, LightGray)

        }else{
            val customExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(selectedExerciseId)
            val startAngle = startingAngle + customExerciseOrSupersetIndex * (segmentArcAngle + 2f)
            val middleAngle = startAngle + (segmentArcAngle / 2f)

            RotatingIndicator(middleAngle, LightGray)
        }
    }else{
        val startAngle = startingAngle + currentExerciseOrSupersetIndex * (segmentArcAngle + 2f)
        val middleAngle = startAngle + (segmentArcAngle / 2f)

        RotatingIndicator(middleAngle, LightGray)
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
                trackSegments = listOf(ProgressIndicatorSegment(1f, Orange)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(elementsToSkip == 1) angleForSet else indicatorSize,
                trackColor = LightGray,
            )

            if(elementsToSkip > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 20f, circleColor = Orange, number = elementsToSkip, transparency = 1f)
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
                trackSegments = listOf(ProgressIndicatorSegment(1f, if (isCurrentSet) LightGray  else (if(markAsCompleted) Orange else LightGray))),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + angleForSet,
                trackColor = LightGray,
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
                trackSegments = listOf(ProgressIndicatorSegment(1f, LightGray)),
                progress = 1f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = accumulatedAngle,
                endAngle = accumulatedAngle + if(numberOfElementsLeft == 1) angleForSet else indicatorSize,
                trackColor = LightGray,
            )

            if(numberOfElementsLeft > 1){
                CircleWithNumber(baseAngleInDegrees = accumulatedAngle+indicatorSize/2, circleRadius = 20f, circleColor = LightGray, number = numberOfElementsLeft)
            }
        }
    }
}
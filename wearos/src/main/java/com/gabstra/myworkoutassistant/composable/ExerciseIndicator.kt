package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import kotlin.math.min

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    modifier: Modifier = Modifier.fillMaxSize(),
    viewModel: AppViewModel,
    set: WorkoutState.Set,
){
    val parentIndex = viewModel.groupedSetsByWorkoutComponent.keys.indexOf(set.parentExercise)

    val maxCount = 5

    var workoutComponentSelection = viewModel.groupedSetsByWorkoutComponent.keys.toList()
    var areMoreElementsAvailable = false
    var elementsToSkip = 0

    val maxElementToSkip = viewModel.groupedSetsByWorkoutComponent.keys.count() - maxCount
    if(maxElementToSkip > 0){
        elementsToSkip = min(parentIndex-2, maxElementToSkip)
        if(elementsToSkip <0){
            elementsToSkip = 0
        }

        workoutComponentSelection = viewModel.groupedSetsByWorkoutComponent.keys.drop(elementsToSkip).take(maxCount)
        areMoreElementsAvailable = viewModel.groupedSetsByWorkoutComponent.keys.count() > (elementsToSkip + workoutComponentSelection.size)
    }

    val totalGroups = workoutComponentSelection.count()
    val baseGapAngle = 2f
    val parentGapAngle = 2f // Larger gap for the parent segment
    val totalGap = if (totalGroups <= 1) 0f else baseGapAngle * (totalGroups - 2) + parentGapAngle * 2

    var availableAngle = 140f

    if(elementsToSkip > 0){
        availableAngle -= 12f
    }

    if(areMoreElementsAvailable){
        availableAngle -= 12f
    }

    var angleForParent = if (totalGroups == 1) availableAngle else availableAngle / 2
    var angleForOthers = if (totalGroups == 1) 0f else (availableAngle - angleForParent - totalGap) / (totalGroups - 1)

    // Ensure angleForOthers is not less than 10 degrees
    if (angleForOthers < 10f) {
        angleForOthers = 10f
        angleForParent = availableAngle - (angleForOthers * (totalGroups - 1)) - totalGap
    }

    Box(modifier = modifier) {
        var accumulatedAngle = -70f

        if(elementsToSkip > 0) {
            RotatedCircles(
                baseAngleInDegrees = accumulatedAngle,
                circleRadius = 3f, // Size of each circle
                color = MaterialTheme.colors.primary,
                offsetDegrees = 4f
            )
            accumulatedAngle += 12f
        }

        for ((index,workoutComponent) in workoutComponentSelection.withIndex()) {
            val groupIndex = viewModel.groupedSetsByWorkoutComponent.keys.indexOf(workoutComponent)

            val isParent = groupIndex == parentIndex
            val anglePerGroup = if (isParent) angleForParent else angleForOthers

            var startAngleForGroup = accumulatedAngle
            accumulatedAngle += anglePerGroup

            // Add the gap after calculating the start angle
            if (isParent || groupIndex == parentIndex - 1) {
                accumulatedAngle += parentGapAngle // Larger gap for parent segment
            } else if (index < totalGroups - 1) {
                accumulatedAngle += baseGapAngle // Regular gap for other segments
            }

            var endAngleForGroup = startAngleForGroup + anglePerGroup

            val sets = viewModel.groupedSetsByWorkoutComponent[workoutComponent] ?: listOf()

            // Find the index of the current setHistoryId
            val currentSetIndex = sets.indexOfFirst { it === set }
            val exerciseSegments = listOf(ProgressIndicatorSegment(1f / sets.count(),if(isParent) Color.White else MaterialTheme.colors.primary))

            if(totalGroups == 1 && sets.isNotEmpty() && currentSetIndex == 0){
                endAngleForGroup-=13
            }

            if(isParent && currentSetIndex >0){
                RotatedCircles(
                    baseAngleInDegrees = 2f + startAngleForGroup,
                    circleRadius = 3f, // Size of each circle
                    color = MaterialTheme.colors.primary,
                    offsetDegrees = 4f
                )

                startAngleForGroup+=13f
                endAngleForGroup = startAngleForGroup + (anglePerGroup-13f)
            }

            if(isParent && currentSetIndex < sets.count()-1 && currentSetIndex>0){
                endAngleForGroup-=13f
            }

            SegmentedProgressIndicator(
                trackSegments = exerciseSegments,
                progress = if (groupIndex <= parentIndex) 1f else 0f,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = startAngleForGroup,
                endAngle = endAngleForGroup,
                trackColor = Color.DarkGray,
            )
            if(isParent && currentSetIndex < sets.count()-1) {


                RotatedCircles(
                    baseAngleInDegrees = 4f + endAngleForGroup,
                    circleRadius = 3f, // Size of each circle
                    color = Color.DarkGray,
                    offsetDegrees = 4f
                )
            }
        }

        if(areMoreElementsAvailable) {

            RotatedCircles(
                baseAngleInDegrees = baseGapAngle*2 + accumulatedAngle,
                circleRadius = 3f, // Size of each circle
                color =  Color.DarkGray,
                offsetDegrees = 4f
            )
            accumulatedAngle += 12f
        }
    }
}
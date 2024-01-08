package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    modifier: Modifier = Modifier.fillMaxSize(),
    viewModel: AppViewModel,
    state: WorkoutState.Set,
){
    val workout by viewModel.selectedWorkout
    val parentIndex = viewModel.groupedSets.keys.indexOf(state.parents.first())

    val totalGroups = workout.workoutComponents.count()
    val baseGapAngle = 2f
    val parentGapAngle = 2f // Larger gap for the parent segment
    val totalGap = baseGapAngle * (totalGroups - 2) + parentGapAngle * 2 // Include parent gap both before and after the parent

    val availableAngle = 140f
    var angleForParent = availableAngle / 2
    var angleForOthers = (availableAngle - angleForParent - totalGap) / (totalGroups - 1)

    // Ensure angleForOthers is not less than 10 degrees
    if (angleForOthers < 10f) {
        angleForOthers = 10f
        angleForParent = availableAngle - (angleForOthers * (totalGroups - 1)) - totalGap
    }

    Box(modifier = modifier) {
        var accumulatedAngle = -70f

        for ((groupIndex, workoutComponent) in viewModel.groupedSets.keys.withIndex()) {
            val isParent = groupIndex == parentIndex
            val anglePerGroup = if (isParent) angleForParent else angleForOthers

            var startAngleForGroup = accumulatedAngle
            accumulatedAngle += anglePerGroup

            // Add the gap after calculating the start angle
            if (isParent || groupIndex == parentIndex - 1) {
                accumulatedAngle += parentGapAngle // Larger gap for parent segment
            } else if (groupIndex < totalGroups - 1) {
                accumulatedAngle += baseGapAngle // Regular gap for other segments
            }

            var endAngleForGroup = startAngleForGroup + anglePerGroup

            var setIds = viewModel.groupedSets[workoutComponent]?.map{ state -> state.setHistoryId} ?: listOf()

            // Find the index of the current setHistoryId
            var currentSetIndex = setIds.indexOf(state.setHistoryId)
            val exerciseSegments = listOf(ProgressIndicatorSegment(1f / setIds.count(),if(isParent) Color.White else MaterialTheme.colors.primary))

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

            if(isParent && currentSetIndex < setIds.count()-1) {
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
            if(isParent && currentSetIndex < setIds.count()-1) {
                RotatedCircles(
                    baseAngleInDegrees =4f + endAngleForGroup,
                    circleRadius = 3f, // Size of each circle
                    color = Color.DarkGray,
                    offsetDegrees = 4f
                )
            }
        }
    }
}
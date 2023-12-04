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
    val parentGapAngle = 6f // Larger gap for the parent segment
    val totalGap = baseGapAngle * (totalGroups - 2) + parentGapAngle * 2 // Include parent gap both before and after the parent

    val availableAngle = 140f
    val angleForParent = availableAngle / 3
    val angleForOthers = (availableAngle - angleForParent - totalGap) / (totalGroups - 1)

    Box(modifier = modifier) {
        var accumulatedAngle = -70f

        for ((groupIndex, workoutComponent) in viewModel.groupedSets.keys.withIndex()) {
            val isParent = groupIndex == parentIndex
            val anglePerGroup = if (isParent) angleForParent else angleForOthers

            val startAngleForGroup = accumulatedAngle
            accumulatedAngle += anglePerGroup

            // Add the gap after calculating the start angle
            if (isParent || groupIndex == parentIndex - 1) {
                accumulatedAngle += parentGapAngle // Larger gap for parent segment
            } else if (groupIndex < totalGroups - 1) {
                accumulatedAngle += baseGapAngle // Regular gap for other segments
            }

            val endAngleForGroup = startAngleForGroup + anglePerGroup

            val setIds = viewModel.groupedSets[workoutComponent]?.map{ state -> state.setHistoryId} ?: listOf()

            val currentSetIndex = setIds.indexOf(state.setHistoryId)+1

            val exerciseSegments = if(isParent){
                setIds.map{ setId ->
                    val color = if(setId ==  state.setHistoryId) Color.White else MaterialTheme.colors.primary
                    ProgressIndicatorSegment(1f / setIds.count(),  color)
                }
            }else{
                listOf(ProgressIndicatorSegment(1f / setIds.count(),  MaterialTheme.colors.primary))
            }
            SegmentedProgressIndicator(
                trackSegments = exerciseSegments,
                progress =  if(isParent) ((currentSetIndex/(setIds.count().toFloat())-0.001f)) else (if(parentIndex>groupIndex) 1f else 0f),
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 2f,
                startAngle = startAngleForGroup,
                endAngle = endAngleForGroup,
                trackColor = Color.DarkGray,
            )
        }
    }
}
package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myhomeworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.Workout
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    modifier: Modifier = Modifier.fillMaxSize(),
    viewModel: AppViewModel,
    state: WorkoutState.Exercise,
){
    val workout by viewModel.selectedWorkout
    val totalGroups = workout.exerciseGroups.count()
    val gapAngle = 2f // Define the size of the gap between segments
    val totalGap = gapAngle * (totalGroups - 1)
    val anglePerGroup = (140f - totalGap) / totalGroups

    val currentExerciseGroup = workout.exerciseGroups.indexOf(state.exerciseGroup)

    Box(
        modifier = modifier,
    ) {
        for ((groupIndex, exerciseGroup) in workout.exerciseGroups.withIndex()) {
            val startAngleForGroup = -70f + anglePerGroup * groupIndex + gapAngle * groupIndex
            val endAngleForGroup = startAngleForGroup + anglePerGroup

            val exerciseSegments = remember(exerciseGroup.sets) {
                List(exerciseGroup.sets) { index ->
                    val color = if((currentExerciseGroup == groupIndex) and (index +1 == state.currentSet)) Color.White else Color(0xFF02A61D)
                    ProgressIndicatorSegment(1f / exerciseGroup.sets,  color)
                }
            }
            Log.d("VALUE","GROUP "+(groupIndex).toString()+" CURRENT GROUP "+(currentExerciseGroup).toString()+"CURRENT SET "+(state.currentSet).toString())
            SegmentedProgressIndicator(
                trackSegments = exerciseSegments,
                progress =  if(currentExerciseGroup == groupIndex) ((state.currentSet)/exerciseGroup.sets.toFloat()-0.001f) else (if(currentExerciseGroup>groupIndex) 1f else 0f),
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
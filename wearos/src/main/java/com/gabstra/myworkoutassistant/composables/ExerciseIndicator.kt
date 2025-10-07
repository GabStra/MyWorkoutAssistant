package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
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
                        indicatorColor = if (index != currentExerciseOrSupersetIndex) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.primary
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
                        trackColor = MediumDarkGray
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
                    indicatorColor = if (index != currentExerciseOrSupersetIndex) MaterialTheme.colorScheme.primary else LightGray
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
                    trackColor = MediumDarkGray
                )
            }
        }
    }

    @Composable
    fun ShowRotatingIndicator(exerciseId : UUID){
        val isSuperset = remember(exerciseId) { viewModel.supersetIdByExerciseId.containsKey(exerciseId)  }

        if(isSuperset){
            val supersetId = viewModel.supersetIdByExerciseId[exerciseId]
            val customExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(supersetId)

            val supersetExerciseIds = exerciseIds.filter { viewModel.supersetIdByExerciseId.containsKey(it) && viewModel.supersetIdByExerciseId[it] == supersetId }
            val supersetExercisesCount = supersetExerciseIds.count()

            val subSegmentArcAngle = (segmentArcAngle - (supersetExercisesCount - 1) * 1f) / supersetExercisesCount

            val subIndex = supersetExerciseIds.indexOf(exerciseId)

            val startAngle = startingAngle + customExerciseOrSupersetIndex * (segmentArcAngle + 2f) + subIndex * (subSegmentArcAngle + 1f)
            val middleAngle = startAngle + (subSegmentArcAngle / 2f)

            RotatingIndicator(middleAngle, LightGray)

        }else{
            val customExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(exerciseId)
            val startAngle = startingAngle + customExerciseOrSupersetIndex * (segmentArcAngle + 2f)
            val middleAngle = startAngle + (segmentArcAngle / 2f)

            RotatingIndicator(middleAngle, LightGray)
        }
    }

    if(selectedExerciseId != null && exerciseIds.contains(selectedExerciseId)){
        ShowRotatingIndicator(selectedExerciseId)
    }else{
        ShowRotatingIndicator(set.exerciseId)
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun SetIndicator(
    viewModel: AppViewModel,
    set: WorkoutState.Set
){
    val exerciseIds = remember { viewModel.setsByExerciseId.keys.toList() }
    val exerciseOrSupersetIds = remember { exerciseIds.map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseCount = exerciseOrSupersetIds.count()

    val exerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(set.exerciseId)) viewModel.supersetIdByExerciseId[set.exerciseId]!! else set.exerciseId
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(exerciseOrSupersetId)

    val isSuperset = remember(exerciseOrSupersetId) { viewModel.supersetIdByExerciseId.containsValue(exerciseOrSupersetId)  }

    val sets: List<WorkoutState.Set> = remember(
        isSuperset,
        viewModel.allWorkoutStates,
        exerciseOrSupersetId
    ) {
        val targetExerciseIds: Set<UUID> =
            if (isSuperset) {
                viewModel.exercisesBySupersetId[exerciseOrSupersetId]
                    ?.map { it.id }
                    ?.toSet()
                    ?: emptySet()
            } else {
                setOf(exerciseOrSupersetId)   // here exerciseOrSupersetId is the exercise id
            }

        viewModel.allWorkoutStates
            .asSequence()
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId in targetExerciseIds }
            .toList()
    }

    val currentSetIndex = sets.indexOfFirst { it === set }

    val startingAngle = -50f
    val totalArcAngle = 100f
    val segmentArcAngle = (totalArcAngle - (exerciseCount - 1) * 2f) / exerciseCount

    Box(modifier = Modifier.fillMaxSize()) {
        sets.forEachIndexed { index, set ->
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
                indicatorColor = if (index != currentExerciseOrSupersetIndex) MaterialTheme.colorScheme.primary else LightGray
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
                trackColor = MediumDarkGray
            )
        }
    }

    val startAngle = startingAngle + currentSetIndex * (segmentArcAngle + 2f)
    val middleAngle = startAngle + (segmentArcAngle / 2f)

    RotatingIndicator(middleAngle, LightGray)
}

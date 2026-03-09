package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

private fun resolveExerciseOrSupersetId(viewModel: AppViewModel, exerciseId: UUID): UUID =
    viewModel.supersetIdByExerciseId[exerciseId] ?: exerciseId

private fun getRepresentativeExercise(viewModel: AppViewModel, exerciseOrSupersetId: UUID): Exercise {
    val supersetExercises = viewModel.exercisesBySupersetId[exerciseOrSupersetId]
    return if (supersetExercises != null) {
        supersetExercises.first()
    } else {
        viewModel.exercisesById[exerciseOrSupersetId]!!
    }
}

internal fun resolvePageExercisesActiveState(
    workoutState: WorkoutState?,
    fallbackSetState: WorkoutState.Set? = null,
): WorkoutState? {
    if (workoutState !is WorkoutState.Rest) return workoutState

    return when (val nextExecutableState = workoutState.nextState ?: fallbackSetState) {
        is WorkoutState.Set ->
            if (nextExecutableState.exerciseId == workoutState.exerciseId) workoutState else nextExecutableState
        is WorkoutState.CalibrationLoadSelection ->
            if (nextExecutableState.exerciseId == workoutState.exerciseId) workoutState else nextExecutableState
        is WorkoutState.CalibrationRIRSelection ->
            if (nextExecutableState.exerciseId == workoutState.exerciseId) workoutState else nextExecutableState
        is WorkoutState.AutoRegulationRIRSelection ->
            if (nextExecutableState.exerciseId == workoutState.exerciseId) workoutState else nextExecutableState
        else -> workoutState
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PageExercises(
    selectedExercise: Exercise,
    workoutState: WorkoutState?,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    onExerciseSelected: (Exercise) -> Unit
) {
    val activeWorkoutState = remember(workoutState, viewModel.allWorkoutStates.size) {
        resolvePageExercisesActiveState(
            workoutState = workoutState,
            fallbackSetState = viewModel.getFirstSetStateAfterCurrent()
        )
    }

    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .map { resolveExerciseOrSupersetId(viewModel, it) }
            .distinct()
    }

    val currentExerciseOrSupersetId = remember(currentExercise.id) {
        resolveExerciseOrSupersetId(viewModel, currentExercise.id)
    }
    val currentExerciseOrSupersetIndex = remember(currentExerciseOrSupersetId, exerciseOrSupersetIds) {
        derivedStateOf { exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId) }
    }

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val currentSet = remember(activeWorkoutState, selectedExercise.id) {
        when (activeWorkoutState) {
            is WorkoutState.Set -> activeWorkoutState.set
            is WorkoutState.CalibrationLoadSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.CalibrationRIRSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.AutoRegulationRIRSelection -> activeWorkoutState.workSet
            else -> selectedExercise.sets.firstOrNull()
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val selectedExerciseOrSupersetId = remember(selectedExercise) {
            resolveExerciseOrSupersetId(viewModel, selectedExercise.id)
        }
        val selectedExerciseOrSupersetIndex = remember(selectedExerciseOrSupersetId, exerciseOrSupersetIds) {
            derivedStateOf { exerciseOrSupersetIds.indexOf(selectedExerciseOrSupersetId) }
        }

        val isSuperset = remember(selectedExerciseOrSupersetId) {
            viewModel.exercisesBySupersetId.containsKey(selectedExerciseOrSupersetId)
        }

        val containerIndex = selectedExerciseOrSupersetIndex
        val containerCount = exerciseOrSupersetIds.size

        val supersetExercises = remember(selectedExerciseOrSupersetId, isSuperset) {
            if (isSuperset) {
                viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!!
            } else null
        }
        val titleStyle = workoutPagerTitleTextStyle()
        val displayName = remember(isSuperset, supersetExercises, selectedExercise, titleStyle) {
            if (isSuperset && supersetExercises != null && supersetExercises.size > 1) {
                buildAnnotatedString {
                    supersetExercises.forEachIndexed { i, exercise ->
                        if (i > 0) {
                            append(" ↔ ")
                        }
                        append(exercise.name)
                        append(" ")
                        append("(")
                        append(('A' + i).toString())
                        append(")")
                    }
                }
            } else {
                AnnotatedString(selectedExercise.name)
            }
        }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Top),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(WorkoutPagerLayoutTokens.WorkoutHeaderHeight),
                contentAlignment = Alignment.Center
            ) {
                ExerciseNameText(
                    text = displayName,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 22.5.dp),
                    style = titleStyle,
                    textAlign = TextAlign.Center
                )
            }

            val selectedExerciseEquipment = remember(selectedExercise) {
                selectedExercise.equipmentId?.let { viewModel.getEquipmentById(it) }
            }
            val selectedExerciseAccessories = remember(selectedExercise) {
                (selectedExercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                    viewModel.getAccessoryEquipmentById(id)
                }
            }

            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                // Metadata strip: superset-specific when viewing superset, else exercise metadata
                if (isSuperset && supersetExercises != null) {
                    SupersetMetadataStrip(
                        containerLabel = if (containerCount > 1) "${containerIndex.value + 1}/${containerCount}" else null
                    )
                } else {
                    ExerciseMetadataStrip(
                        exerciseLabel = if (containerCount > 1) "${containerIndex.value + 1}/${containerCount}" else null,
                        supersetExerciseIndex = null,
                        supersetExerciseTotal = null,
                        sideIndicator = null,
                        currentSideIndex = null,
                        isUnilateral = currentExercise == selectedExercise && (workoutState as? WorkoutState.Set)?.exerciseId == selectedExercise.id && workoutState.isUnilateral
                    )
                }
            }

            if (currentSet != null) {
                val progressState = when {
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> ProgressState.PAST
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> ProgressState.FUTURE
                    else -> ProgressState.CURRENT
                }
                val isSelectedCurrentContainer = progressState == ProgressState.CURRENT
                ExerciseSetsViewer(
                    modifier = Modifier.padding(horizontal = 22.5.dp),
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    exercise = selectedExercise,
                    currentSet = currentSet,
                    progressState = progressState,
                    currentWorkoutStateOverride = if (isSelectedCurrentContainer) activeWorkoutState else null
                )
            }
        }

        Box(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxSize(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                        .clickable(
                            enabled = containerIndex.value > 0
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val prevId = exerciseOrSupersetIds[containerIndex.value - 1]
                            onExerciseSelected(getRepresentativeExercise(viewModel, prevId))
                        }
                        .then(if (containerCount > 1) Modifier else Modifier.alpha(0f)),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
/*                    Icon(
                        modifier = backArrowModifier,
                        imageVector = Icons.Filled.ArrowBack,
                        contentDescription = "Previous",
                        tint = LightGray
                    )*/
                }
                Spacer(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                )
                Row(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                        .clickable(
                            enabled = containerIndex.value < containerCount - 1
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val nextId = exerciseOrSupersetIds[containerIndex.value + 1]
                            onExerciseSelected(getRepresentativeExercise(viewModel, nextId))
                        }
                        .then(if (containerCount > 1) Modifier else Modifier.alpha(0f)),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
/*                    Icon(
                        modifier = forwardArrowModifier,
                        imageVector = Icons.Filled.ArrowForward,
                        contentDescription = "Next",
                        tint = LightGray
                    )*/
                }
            }
        }
    }
}

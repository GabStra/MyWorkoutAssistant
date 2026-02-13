package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.basicMarquee
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
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.ScrollableTextColumn
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PageExercises(
    workoutState: WorkoutState?,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    onExerciseSelected: (UUID) -> Unit
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .map { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseOrSupersetId =
        if (viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    var selectedExercise by remember { mutableStateOf(currentExercise) }

    val captionStyle = MaterialTheme.typography.bodySmall

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val currentSet = remember(workoutState, selectedExercise) {
        when (workoutState) {
            is WorkoutState.Set -> workoutState.set
            is WorkoutState.CalibrationLoadSelection -> workoutState.calibrationSet
            is WorkoutState.CalibrationRIRSelection -> workoutState.calibrationSet
            else -> selectedExercise.sets.firstOrNull()
        }
    }

    val setState = workoutState as? WorkoutState.Set

    val overrideSetIndex = remember(isSuperset, currentExercise, workoutState, viewModel.allWorkoutStates.size) {
        if (isSuperset && setState != null) {
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }
                .indexOf(setState.set.id)
        } else null
    }

    val currentExerciseSetIds = remember(currentExercise, viewModel.allWorkoutStates.size) {
        viewModel.allWorkoutStates
            .asSequence()
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == currentExercise.id }
            .map { it.set.id }
            .toList()
            .distinct()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val selectedExerciseOrSupersetId = remember(selectedExercise) {
            if (viewModel.supersetIdByExerciseId.containsKey(selectedExercise.id)) viewModel.supersetIdByExerciseId[selectedExercise.id]!! else selectedExercise.id
        }
        val selectedExerciseOrSupersetIndex = remember(selectedExerciseOrSupersetId) {
            exerciseOrSupersetIds.indexOf(selectedExerciseOrSupersetId)
        }

        LaunchedEffect(selectedExercise) {
            onExerciseSelected(selectedExercise.id)
        }

        val isSuperset = remember(selectedExerciseOrSupersetId) {
            viewModel.exercisesBySupersetId.containsKey(selectedExerciseOrSupersetId)
        }
        
        val currentIndex = remember(selectedExercise) { exerciseIds.indexOf(selectedExercise.id) }

        Row(
            modifier = Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(2.5.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxHeight()
                    .weight(1f),
                verticalArrangement = Arrangement.spacedBy(5.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                ScrollableTextColumn(
                    text = selectedExercise.name,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            marqueeEnabled = !marqueeEnabled
                            hapticsViewModel.doGentleVibration()
                        },
                    maxLines = 2,
                    style = MaterialTheme.typography.titleLarge,
                    textAlign = TextAlign.Center
                )

                val selectedExerciseEquipment = remember(selectedExercise) {
                    selectedExercise.equipmentId?.let { viewModel.getEquipmentById(it) }
                }
                val selectedExerciseAccessories = remember(selectedExercise) {
                    (selectedExercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                        viewModel.getAccessoryEquipmentById(id)
                    }
                }
                
                val isWarmupSet = remember(currentSet, selectedExercise, currentExercise) {
                    currentExercise == selectedExercise && currentSet != null && when(val set = currentSet) {
                        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                        else -> false
                    }
                }
                
                val isCalibrationSet = remember(setState, selectedExercise, currentExercise) {
                    currentExercise == selectedExercise && (setState?.isCalibrationSet == true)
                }
                
                val supersetExercises = remember(selectedExerciseOrSupersetId, isSuperset) {
                    if (isSuperset) {
                        viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!!
                    } else null
                }
                val supersetIndex = remember(supersetExercises, selectedExercise) {
                    supersetExercises?.indexOf(selectedExercise)
                }
                
                val setBelongsToSelected = setState?.exerciseId == selectedExercise.id
                val sideIndicator = remember(setState, selectedExercise, currentExercise, setBelongsToSelected) {
                    if (currentExercise == selectedExercise && setBelongsToSelected && setState?.intraSetTotal != null) {
                        "① ↔ ②"
                    } else null
                }
                
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    // Status badges row
                    if (isWarmupSet || isCalibrationSet) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            if (isWarmupSet) {
                                Chip(backgroundColor = MaterialTheme.colorScheme.primary) {
                                    Text(
                                        text = "Warm-up",
                                        style = captionStyle,
                                        color = MaterialTheme.colorScheme.primary,
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }
                            if (isCalibrationSet) {
                                Text(
                                    text = "This exercise is waiting to be calibrated.",
                                    style = captionStyle,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    textAlign = TextAlign.Center
                                )
                            }
                        }
                    }
                    
                    // Metadata strip
                    ExerciseMetadataStrip(
                        exerciseLabel = if (isSuperset) {
                            "Superset: ${selectedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}"
                        } else {
                            "Exercise: ${selectedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}"
                        },
                        supersetExerciseLabel = if (isSuperset && supersetIndex != null) {
                            "Exercise: ${supersetIndex + 1}/${supersetExercises!!.size}"
                        } else null,
                        supersetExerciseIndex = if (isSuperset && supersetIndex != null) supersetIndex else null,
                        supersetExerciseTotal = if (isSuperset && supersetExercises != null) supersetExercises!!.size else null,
                        setLabel = null, // Not showing set info in PageExercises
                        sideIndicator = sideIndicator,
                        currentSideIndex = if (currentExercise == selectedExercise && setBelongsToSelected) {
                            setState?.intraSetCounter?.takeIf { setState?.intraSetTotal != null }
                        } else null,
                        isUnilateral = currentExercise == selectedExercise && setBelongsToSelected && (setState?.isUnilateral == true),
                        equipmentName = selectedExerciseEquipment?.name,
                        accessoryNames = selectedExerciseAccessories.joinToString(", ") { it.name }.takeIf { selectedExerciseAccessories.isNotEmpty() },
                        textColor = MaterialTheme.colorScheme.onBackground,
                        onTap = {
                            hapticsViewModel.doGentleVibration()
                        }
                    )
                }

                if (currentSet != null) {
                    ExerciseSetsViewer(
                        modifier = Modifier
                            .fillMaxSize().padding(horizontal = 10.dp),
                        viewModel = viewModel,
                        hapticsViewModel = hapticsViewModel,
                        exercise = selectedExercise,
                        currentSet = currentSet,
                        customMarkAsDone = when {
                            selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> true
                            selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> false
                            else -> null
                        },
                        customBorderColor = when {
                            selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> null
                            selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> null
                            else -> null
                        },
                        customTextColor = when {
                            selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.onBackground
                            selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.onBackground
                            else -> null
                        },
                        overrideSetIndex = if (selectedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                            overrideSetIndex
                        } else null,
                        isFutureExercise = selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex
                    )
                }
            }
        }

        Box(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier.fillMaxSize(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                        .clickable(
                            enabled = currentIndex > 0
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex - 1
                            selectedExercise =
                                viewModel.exercisesById[exerciseIds[newIndex]]!!
                        }
                        .then(if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
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
                            enabled = currentIndex < exerciseIds.size - 1
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex + 1
                            selectedExercise =
                                viewModel.exercisesById[exerciseIds[newIndex]]!!
                        }
                        .then(if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
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



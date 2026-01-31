package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.FadingText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PageExercises(
    selectedExercise : Exercise,
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    exerciseOrSupersetIds: List<java.util.UUID>,
    onExerciseSelected: (Exercise) -> Unit
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()

    val currentExerciseOrSupersetId =
        remember(currentExercise.id) {
            if (viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
        }
    val currentExerciseOrSupersetIndex = remember(currentExerciseOrSupersetId, exerciseOrSupersetIds) {
        derivedStateOf { exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId) }
    }

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val overrideSetIndex = remember(isSuperset, currentExercise) {
        if (isSuperset) {
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }
                .indexOf(currentStateSet.set.id)
        } else null
    }

    // Optimize: Use setsByExerciseId which is already cached in viewModel instead of filtering allWorkoutStates
    val currentExerciseSetIds = remember(currentExercise.id) {
        viewModel.setsByExerciseId[currentExercise.id]?.map { it.set.id } ?: emptyList()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val selectedExerciseOrSupersetId = remember(selectedExercise) {
            if (viewModel.supersetIdByExerciseId.containsKey(selectedExercise.id)) viewModel.supersetIdByExerciseId[selectedExercise.id]!! else selectedExercise.id
        }
        val selectedExerciseOrSupersetIndex = remember(selectedExerciseOrSupersetId, exerciseOrSupersetIds) {
            derivedStateOf { exerciseOrSupersetIds.indexOf(selectedExerciseOrSupersetId) }
        }

        val isSuperset = remember(selectedExerciseOrSupersetId) {
            viewModel.exercisesBySupersetId.containsKey(selectedExerciseOrSupersetId)
        }

        val currentIndex = remember(selectedExercise.id, exerciseIds) {
            derivedStateOf { exerciseIds.indexOf(selectedExercise.id) }
        }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp,Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            FadingText(
                text = selectedExercise.name,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(20.dp)
                    .padding(horizontal = 22.5.dp),
                style = MaterialTheme.typography.titleMedium.copy(
                    fontWeight = FontWeight.SemiBold
                ),
                textAlign = TextAlign.Center,
                onClick = {
                    hapticsViewModel.doGentleVibration()
                }
            )

            val selectedExerciseEquipment = remember(selectedExercise) {
                selectedExercise.equipmentId?.let { viewModel.getEquipmentById(it) }
            }
            val selectedExerciseAccessories = remember(selectedExercise) {
                (selectedExercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                    viewModel.getAccessoryEquipmentById(id)
                }
            }
            
            val supersetExercises = remember(selectedExerciseOrSupersetId, isSuperset) {
                if (isSuperset) {
                    viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!!
                } else null
            }
            val supersetIndex = remember(supersetExercises, selectedExercise) {
                supersetExercises?.indexOf(selectedExercise)
            }
            
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                // Metadata strip
                ExerciseMetadataStrip(
                    exerciseLabel = "${selectedExerciseOrSupersetIndex.value + 1}/${exerciseOrSupersetIds.size}",
                    supersetExerciseIndex = if (isSuperset && supersetIndex != null) supersetIndex else null,
                    supersetExerciseTotal = if (isSuperset && supersetExercises != null) supersetExercises!!.size else null,
                    setLabel = if (currentExercise == selectedExercise && currentExerciseSetIds.size > 1) {
                        val setIndex = remember(currentStateSet.set.id) { currentExerciseSetIds.indexOf(currentStateSet.set.id) }
                        "${setIndex + 1}/${currentExerciseSetIds.size}"
                    } else null,
                    sideIndicator = if (currentExercise == selectedExercise && currentStateSet.intraSetTotal != null) "① ↔ ②" else null,
                    currentSideIndex = if (currentExercise == selectedExercise) {
                        currentStateSet.intraSetCounter.takeIf { currentStateSet.intraSetTotal != null }
                    } else null,
                    isUnilateral = currentExercise == selectedExercise && currentStateSet.isUnilateral,
                    equipmentName = selectedExerciseEquipment?.name,
                    accessoryNames = selectedExerciseAccessories.joinToString(", ") { it.name }.takeIf { selectedExerciseAccessories.isNotEmpty() },
                    textColor = MaterialTheme.colorScheme.onBackground,
                    onTap = {
                        hapticsViewModel.doGentleVibration()
                    }
                )
            }

            ExerciseSetsViewer(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                exercise = selectedExercise,
                currentSet = currentStateSet.set,
                customMarkAsDone = when {
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> true
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> false
                    else -> null
                },
                customBorderColor = when {
                    // Previous exercise: enforce previous set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.onBackground
                    // Future exercise: enforce future set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.surfaceContainerHigh
                    // Current exercise: use default logic (null = distinguish between previous/current/future sets)
                    else -> null
                },
                customTextColor = when {
                    // Previous exercise: enforce previous set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.onBackground
                    // Future exercise: enforce future set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.surfaceContainerHigh
                    // Current exercise: use default logic (null = distinguish between previous/current/future sets)
                    else -> null
                },
                overrideSetIndex = if (selectedExerciseOrSupersetIndex.value == currentExerciseOrSupersetIndex.value) {
                    overrideSetIndex
                } else null,
                isFutureExercise = selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value
            )
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
                            enabled = currentIndex.value > 0
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex.value - 1
                            onExerciseSelected(viewModel.exercisesById[exerciseIds[newIndex]]!!)
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
                            enabled = currentIndex.value < exerciseIds.size - 1
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex.value + 1
                            onExerciseSelected(viewModel.exercisesById[exerciseIds[newIndex]]!!)
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
package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun PageExercises(
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    onSelectionChange: (Int) -> Unit
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember {
        viewModel.setsByExerciseId.keys.toList()
            .map { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseOrSupersetId =
        if (viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    var selectedExercise by remember { mutableStateOf(currentExercise) }

    val typography = MaterialTheme.typography
    val captionStyle =
        remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val overrideSetIndex = remember(isSuperset, currentExercise) {
        if (isSuperset) {
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }
                .indexOf(currentStateSet.set.id)
        } else null
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val selectedExerciseOrSupersetId = remember(selectedExercise) {
            if (viewModel.supersetIdByExerciseId.containsKey(selectedExercise.id)) viewModel.supersetIdByExerciseId[selectedExercise.id] else selectedExercise.id
        }
        val selectedExerciseOrSupersetIndex = remember(selectedExerciseOrSupersetId) {
            exerciseOrSupersetIds.indexOf(selectedExerciseOrSupersetId)
        }

        LaunchedEffect(selectedExerciseOrSupersetIndex) {
            onSelectionChange(selectedExerciseOrSupersetIndex)
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
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            marqueeEnabled = !marqueeEnabled
                            hapticsViewModel.doGentleVibration()
                        }
                        .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = selectedExercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3.copy(fontWeight = FontWeight.Bold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(
                            textAlign = TextAlign.Center,
                            text = "${selectedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                            style = captionStyle
                        )
                        if (isSuperset) {
                            val supersetExercises =
                                remember(selectedExerciseOrSupersetId) { viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!! }
                            val supersetIndex =
                                remember(
                                    supersetExercises,
                                    selectedExercise
                                ) { supersetExercises.indexOf(selectedExercise) }

                            Text(
                                textAlign = TextAlign.Center,
                                text = "${supersetIndex + 1}/${supersetExercises.size}",
                                style = captionStyle
                            )
                        }
                    }
                }

                ExerciseSetsViewer(
                    modifier = Modifier
                        .fillMaxSize(),
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    exercise = selectedExercise,
                    currentSet = currentStateSet.set,
                    customColor = when {
                        selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> Orange
                        selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MediumLightGray
                        else -> null
                    },
                    overrideSetIndex = if (selectedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                        overrideSetIndex
                    } else null
                )
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
package com.gabstra.myworkoutassistant.composables

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
import androidx.compose.runtime.Composable
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
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
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
    onExerciseSelected: (Exercise) -> Unit
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember {
        viewModel.setsByExerciseId.keys.toList()
            .map { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }

    var marqueeEnabled by remember { mutableStateOf(false) }
    var headerMarqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseOrSupersetId =
        if (viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val overrideSetIndex = remember(isSuperset, currentExercise) {
        if (isSuperset) {
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }
                .indexOf(currentStateSet.set.id)
        } else null
    }

    val currentExerciseSetIds = remember(
        currentExercise
    ) {
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

        val isSuperset = remember(selectedExerciseOrSupersetId) {
            viewModel.exercisesBySupersetId.containsKey(selectedExerciseOrSupersetId)
        }

        val currentIndex = remember(selectedExercise) { exerciseIds.indexOf(selectedExercise.id) }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp,Alignment.Bottom),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
                    .clickable {
                        marqueeEnabled = !marqueeEnabled
                        hapticsViewModel.doGentleVibration()
                    }
                    .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                text = selectedExercise.name,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontWeight = FontWeight.SemiBold
                ),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )

            val topLine = buildAnnotatedString {
                @Composable
                fun pipe() {
                    withStyle(
                        SpanStyle(
                            //color = MaterialTheme.colorScheme.surfaceContainerHigh,
                            fontWeight = FontWeight.Bold
                        )
                    ) {
                        append(" • ")
                    }
                }
                fun separator() {
                    withStyle(SpanStyle(baselineShift = BaselineShift(0.18f))) { // tweak 0.12–0.25f as needed

                    }
                }

                append("Ex: ${selectedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}")

                if(currentExercise == selectedExercise) {
                    if (currentExerciseSetIds.size > 1) {
                        pipe()
                        val setIndex = remember (currentStateSet.set.id){ currentExerciseSetIds.indexOf(currentStateSet.set.id) }
                        append("Set: ${setIndex + 1}/${currentExerciseSetIds.size}")
                    }


                    if (currentStateSet.intraSetTotal != null){
                        pipe()

                        withStyle(
                            SpanStyle(
                                color = if (currentStateSet.intraSetCounter == 1u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append("①")
                        }
                        separator()
                        withStyle(
                            SpanStyle(
                                color = if (currentStateSet.intraSetCounter == 2u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append("②")
                        }
                    }
                }

                if (isSuperset) {
                    pipe()
                    val supersetExercises =
                        remember(selectedExerciseOrSupersetId) { viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!! }

                    val currentIdx = remember(supersetExercises, selectedExercise) {
                        supersetExercises.indexOf(selectedExercise)
                    }

                    supersetExercises.indices.forEach { i ->
                        if (i > 0) { separator() }
                        withStyle(
                            SpanStyle(
                                color = if (i == currentIdx) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append(('A' + i).toString())
                        }
                    }
                }


            }

            Text(
                text = topLine,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.clickable {
                    headerMarqueeEnabled = !headerMarqueeEnabled
                    hapticsViewModel.doGentleVibration()
                }
                .then(if (headerMarqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
            )

            ExerciseSetsViewer(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                exercise = selectedExercise,
                currentSet = currentStateSet.set,
                customMarkAsDone = when {
                    selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> true
                    selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> false
                    else -> null
                },
                customBackgroundColor = when {
                    selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.primary
                    selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.surfaceContainerHigh
                    else -> null
                },
                customTextColor = when {
                    selectedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.primary //background.copy(0.75f)
                    selectedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MaterialTheme.colorScheme.surfaceContainerHigh
                    else -> null
                },
                overrideSetIndex = if (selectedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                    overrideSetIndex
                } else null
            )
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
                            enabled = currentIndex < exerciseIds.size - 1
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex + 1
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